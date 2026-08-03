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
    logger.info(f"[Documents API] Fetching documents for user {current_user.email}, dept: {current_user.department_id}, type: {document_type}, subject: {subject_id}")
    
    if not current_user.department_id:
        logger.warning(f"[Documents API] User {current_user.email} has no department_id")
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
        
        # 4. Save to Database
        # Try to infer title from JSON, otherwise fallback to filename
        title = file.filename
        if structured_data.get("Subject Name"):
            title = f"{structured_data['Subject Name']} {doc_type_enum.value.capitalize()}"
        elif structured_data.get("Title"):
            title = structured_data["Title"]
            
        if not title:
            title = file.filename
            
        description = structured_data.get("Summary", "")
        if description is None:
            description = ""
            
        keywords_list = structured_data.get("Keywords", [])
        if keywords_list is None:
            keywords = ""
        else:
            keywords = ", ".join(keywords_list) if isinstance(keywords_list, list) else str(keywords_list)
        
        # If academic year isn't provided, see if Gemini found it
        final_academic_year = academic_year or structured_data.get("Academic Year")

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
            structured_json=structured_data,
            school_id=school_id,
            department_id=department_id,
            semester_id=semester_id,
            subject_id=subject_id
        )
        
        db.add(new_doc)
        await db.commit()
        await db.refresh(new_doc)
        
        return {
            "message": "Document processed and saved to database successfully",
            "document_id": new_doc.id,
            "cloudinary_url": cloudinary_url,
            "structured_json": structured_data
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")
