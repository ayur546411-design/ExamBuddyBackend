from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import load_only
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
    Returns only essential fields (no extracted_text) for fast list loading.
    structured_json is included so viewers (e.g. SyllabusViewerScreen) can render content.
    """
    import time
    t0 = time.perf_counter()
    logger.info(f"[Documents API] Fetching documents dept={current_user.department_id} type={document_type} subject={subject_id}")

    if not current_user.department_id:
        raise HTTPException(status_code=400, detail="User is not assigned to a department")

    # Only fetch lightweight columns — skip extracted_text but KEEP structured_json
    # (SyllabusViewerScreen needs structured_json to render units/topics)
    query = (
        select(Document)
        .options(load_only(
            Document.id,
            Document.title,
            Document.description,
            Document.document_type,
            Document.academic_year,
            Document.cloudinary_url,
            Document.thumbnail_url,
            Document.file_size,
            Document.file_type,
            Document.keywords,
            Document.status,
            Document.school_id,
            Document.department_id,
            Document.semester_id,
            Document.subject_id,
            Document.uploaded_by_admin,
            Document.created_at,
            Document.structured_json,  # Needed by SyllabusViewerScreen for unit/topic rendering
        ))
        .where(Document.status == "active")
    )

    if subject_id:
        # When filtering by subject_id, trust the subject scope — don't restrict by
        # department_id. This fixes syllabus docs uploaded with a different dept_id
        # still appearing correctly for users of that subject.
        query = query.where(Document.subject_id == subject_id)
    else:
        # Without a specific subject, scope to the user's department for safety
        query = query.where(Document.department_id == current_user.department_id)

    if document_type:
        query = query.where(Document.document_type == document_type)

    result = await db.execute(query.order_by(Document.created_at.desc()))
    documents = result.scalars().all()

    elapsed = round((time.perf_counter() - t0) * 1000, 2)
    logger.info(f"[Documents API] Returned {len(documents)} docs in {elapsed}ms")
    return documents

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    school_id: str = Form(...),
    department_id: str = Form(...),
    subject_id: Optional[str] = Form(None),
    semester_id: Optional[str] = Form(None),
    academic_year: Optional[str] = Form(None),
    document_type: DocumentTypeEnum = Form(DocumentTypeEnum.syllabus),  # default = syllabus (most common upload)
    db: AsyncSession = Depends(get_db)
):
    """
    Upload a PDF, extract text, process with Gemini, and save to DB.
    """
    from app.models.school import School
    from app.models.department import Department
    from app.models.semester import Semester
    from app.models.subject import Subject
    
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
                # Helper to convert roman numeral to int
                def parse_semester(sem_str):
                    if not sem_str or str(sem_str).strip().lower() == "null":
                        return None
                    sem_str = str(sem_str).upper()
                    import re
                    # Check for digits first
                    digit_match = re.search(r'\d+', sem_str)
                    if digit_match:
                        return int(digit_match.group())
                    
                    # Check for roman numerals
                    roman_map = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10}
                    # Extract standalone roman numeral words
                    roman_match = re.search(r'\b(I|II|III|IV|V|VI|VII|VIII|IX|X)\b', sem_str)
                    if roman_match:
                        return roman_map.get(roman_match.group())
                    return None

                # 1. Dynamic Semester Parsing & Creation
                entity_semester_id = semester_id
                extracted_semester = entity.get("Semester")
                
                sem_num = parse_semester(extracted_semester)
                if not sem_num:
                    sem_num = 1 # Fallback to Semester 1 if missing or unparseable to avoid data loss
                
                if sem_num:
                    try:
                            
                            # Find or Create Semester
                            sem_query = await db.execute(
                                select(Semester).where(
                                    Semester.department_id == department_id,
                                    Semester.semester_number == sem_num
                                )
                            )
                            found_sem = sem_query.scalars().first()
                            
                            if found_sem:
                                entity_semester_id = found_sem.id
                            else:
                                import uuid
                                new_sem = Semester(
                                    id=str(uuid.uuid4()),
                                    department_id=department_id,
                                    semester_number=sem_num,
                                    is_active=True
                                )
                                db.add(new_sem)
                                await db.commit()
                                await db.refresh(new_sem)
                                entity_semester_id = new_sem.id
                                logger.info(f"[Upload API] Auto-created Semester {sem_num} for dept {department_id}")
                    except Exception as e:
                        logger.warning(f"[Upload API] Failed to auto-create semester from '{extracted_semester}': {e}")
                
                # 2. Dynamic Subject Parsing & Creation
                entity_subject_id = subject_id
                subject_name = entity.get("Subject Name")
                subject_code = entity.get("Subject Code", "")
                
                if subject_name and entity_semester_id:
                    # Find or Create Subject
                    # Use bidirectional ilike: DB name contains Gemini name OR Gemini name contains DB name.
                    # This prevents duplicate subjects when Gemini returns a slightly different
                    # abbreviation (e.g. "ML Lab" vs "Machine Learning Lab").
                    from sqlalchemy import or_
                    subj_query = await db.execute(
                        select(Subject).where(
                            Subject.semester_id == entity_semester_id,
                            or_(
                                Subject.name.ilike(f"%{subject_name}%"),
                                Subject.name.ilike(f"{subject_name[:10]}%")  # prefix match as fallback
                            )
                        )
                    )
                    found_subj = subj_query.scalars().first()
                    
                    if found_subj:
                        entity_subject_id = found_subj.id
                    else:
                        import uuid
                        new_subj = Subject(
                            id=str(uuid.uuid4()),
                            school_id=school_id,
                            department_id=department_id,
                            semester_id=entity_semester_id,
                            name=subject_name,
                            code=subject_code if subject_code else f"AUTO-{str(uuid.uuid4())[:4]}",
                            credits=entity.get("Credits", 0) or 0
                        )
                        db.add(new_subj)
                        await db.commit()
                        await db.refresh(new_subj)
                        entity_subject_id = new_subj.id
                        logger.info(f"[Upload API] Auto-created Subject '{subject_name}' for semester {entity_semester_id}")
                
                # 3. Document Creation
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
                    semester_id=entity_semester_id,
                    subject_id=entity_subject_id
                )
                db.add(new_doc)
                await db.commit() # Commit individually to ensure foreign keys are saved
                inserted_count += 1
            except Exception as e:
                # If an entity fails, rollback the transaction state so the loop can continue
                await db.rollback()
                skipped_count += 1
                logger.error(f"[Upload API] Skipped entity due to error: {str(e)}\nEntity: {entity}")
                
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
