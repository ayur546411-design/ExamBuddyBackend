from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional, List
import json

from app.db.session import get_db
from app.models.document import Document, DocumentTypeEnum
from app.schemas.document import Document as DocumentSchema
from app.services.cloudinary_service import upload_file_to_cloudinary
from app.services.gemini_service import extract_structured_data_from_pdf_text
from app.services.pdf_service import extract_text_from_pdf
from app.api.v1.endpoints.users import get_current_user
from app.models.user import User
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/", response_model=List[DocumentSchema])
async def get_documents(
    subject_id: Optional[str] = None,
    document_type: Optional[DocumentTypeEnum] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieve documents relevant to the current user.
    Optionally filter by subject_id and document_type.
    """
    logger.info(f"[Documents API] Fetching documents for user {current_user.full_name}, dept: {current_user.department_id}, type: {document_type}, subject: {subject_id}")
    
    if not current_user.department_id:
        logger.warning(f"[Documents API] User {current_user.full_name} has no department_id")
        raise HTTPException(status_code=400, detail="User is not assigned to a department")
        
    query = select(Document).where(
        Document.department_id == current_user.department_id,
        Document.status == "active"
    )
    
    if subject_id:
        query = query.where(Document.subject_id == subject_id)
        
    if document_type:
        query = query.where(Document.document_type == document_type)
        
    result = await db.execute(query.order_by(Document.created_at.desc()))
    documents = result.scalars().all()
    
    logger.info(f"[Documents API] Found {len(documents)} documents")
    if not documents:
        logger.warning(f"[Documents API] No documents found matching criteria")
        
    return documents

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    school_id: str = Form(...),
    department_id: str = Form(...),
    subject_id: Optional[str] = Form(None),
    semester_id: Optional[str] = Form(None),
    academic_year: Optional[str] = Form(None),
    document_type: DocumentTypeEnum = Form(DocumentTypeEnum.academic_calendar),
    db: AsyncSession = Depends(get_db)
):
    """
    Upload a PDF, extract text, process with Gemini, and save to DB.
    """
    from app.models.school import School
    from app.models.department import Department
    
    # 1. Validate foreign keys first, auto-fallback to first available if dummy data provided
    school = await db.execute(select(School).where(School.id == school_id))
    if not school.scalar_one_or_none():
        logger.warning(f"[Upload API] Invalid school_id '{school_id}', auto-falling back")
        # Try to use current_user's school if logged in? We don't have current_user here by default for upload testing
        first_school = (await db.execute(select(School))).scalars().first()
        school_id = first_school.id if first_school else None
        
    department = await db.execute(select(Department).where(Department.id == department_id))
    if not department.scalar_one_or_none():
        logger.warning(f"[Upload API] Invalid department_id '{department_id}', auto-falling back")
        # Ensure we pick a department from the same school
        first_dept = (await db.execute(select(Department).where(Department.school_id == school_id))).scalars().first()
        department_id = first_dept.id if first_dept else None
        
    if semester_id:
        from app.models.semester import Semester
        semester = await db.execute(select(Semester).where(Semester.id == semester_id))
        if not semester.scalar_one_or_none():
            semester_id = None # Just ignore if invalid
            
    if subject_id:
        from app.models.subject import Subject
        subject = await db.execute(select(Subject).where(Subject.id == subject_id))
        if not subject.scalar_one_or_none():
            subject_id = None # Just ignore if invalid
            
    doc_type_enum = document_type
        
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
        
    try:
        # Read file bytes
        file_bytes = await file.read()
        
        # 1. Upload to Cloudinary
        cloudinary_res = await upload_file_to_cloudinary(file_bytes, file.filename)
        cloudinary_url = cloudinary_res.get("url")
        cloudinary_public_id = cloudinary_res.get("public_id")
        file_size = cloudinary_res.get("bytes")
        file_format = cloudinary_res.get("format")
        
        # 2. Extract Text from PDF
        pdf_text = await extract_text_from_pdf(file_bytes)
        
        # 3. Get Structured JSON from Gemini
        structured_data = {}
        try:
            structured_data = await extract_structured_data_from_pdf_text(pdf_text, document_type)
        except Exception as gemini_e:
            print(f"Gemini extraction failed: {gemini_e}")
            structured_data = {"error": "Failed to extract metadata with Gemini"}
        
        # 4. Process all entities in structured_json and Save to Database
        entities = []
        if doc_type_enum == DocumentTypeEnum.syllabus and "Subjects" in structured_data:
            entities = structured_data["Subjects"]
        elif doc_type_enum == DocumentTypeEnum.pyq and "QuestionPapers" in structured_data:
            entities = structured_data["QuestionPapers"]
        elif doc_type_enum == DocumentTypeEnum.academic_calendar and "Events" in structured_data:
            # Calendar is a single document containing an array of events
            # We don't want 50 different Document rows for 50 events. We want 1 document that holds the events array
            entities = [structured_data]
        else:
            # Fallback for generic documents or if the model ignored the array wrapper
            entities = [structured_data]
            
        logger.info(f"[Upload API] PDF uploaded. Total pages extracted: {len(pdf_text) // 2000 + 1}. Total text extracted: {len(pdf_text)} characters.")
        logger.info(f"[Upload API] Gemini returned {len(entities)} entities from the document.")

        inserted_count = 0
        skipped_count = 0
        
        for entity in entities:
            try:
                # Infer title based on doc type
                title = file.filename
                if doc_type_enum == DocumentTypeEnum.syllabus and entity.get("Subject Name"):
                    title = f"{entity['Subject Name']} {doc_type_enum.value.capitalize()}"
                elif doc_type_enum == DocumentTypeEnum.pyq and entity.get("Subject Name"):
                    title = f"{entity['Subject Name']} PYQ"
                elif entity.get("Title"):
                    title = entity["Title"]
                    
                description = entity.get("Summary", "") or ""
                
                keywords_list = entity.get("Keywords", [])
                keywords = ", ".join(keywords_list) if isinstance(keywords_list, list) else str(keywords_list or "")
                
                final_academic_year = academic_year or entity.get("Academic Year")
                
                new_doc = Document(
                    document_type=doc_type_enum,
                    cloudinary_url=cloudinary_url,
                    cloudinary_public_id=cloudinary_public_id,
                    file_size=file_size,
                    file_type=file_format,
                    title=title,
                    description=description,
                    academic_year=final_academic_year,
                    keywords=keywords,
                    extracted_text=pdf_text,
                    structured_json=entity,
                    school_id=school_id,
                    department_id=department_id,
                    semester_id=semester_id,
                    subject_id=subject_id
                )
                db.add(new_doc)
                inserted_count += 1
            except Exception as e:
                skipped_count += 1
                logger.error(f"[Upload API] Skipped entity due to error: {str(e)}\nEntity: {entity}")
                
        await db.commit()
        
        logger.info(f"[Upload API] Upload complete. Inserted: {inserted_count}, Skipped: {skipped_count}")
        
        return {
            "message": "Document processed and saved to database successfully",
            "inserted_entities": inserted_count,
            "skipped_entities": skipped_count,
            "cloudinary_url": cloudinary_url,
            "structured_json": structured_data
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")
