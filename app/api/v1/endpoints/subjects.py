from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
import json
import base64

from app.db.session import get_db
from app.models.department import Department
from app.models.semester import Semester
from app.models.subject import Subject
from app.schemas.subject import Subject as SubjectSchema, SubjectCreate, SubjectUpdate, SubjectBulkCopy
from app.models.user import User, UserRoleEnum
from app.models.document import Document, DocumentTypeEnum
from app.schemas.document import QuestionSchema
from app.api.v1.endpoints.users import get_current_user
from app.services.gemini_service import extract_structured_data_from_pdf_text, extract_subject_list_from_text, _normalize_syllabus_payload
from app.services.pdf_service import extract_text_from_pdf, extract_text_from_pdf_by_pages
import logging
import uuid

logger = logging.getLogger(__name__)

router = APIRouter()


def _normalize_subject_label(value: Optional[str]) -> str:
    return (value or '').strip().lower().replace(' ', '')


def _subject_identity_matches(existing: Subject, name: Optional[str], code: Optional[str]) -> bool:
    normalized_name = _normalize_subject_label(name)
    normalized_code = _normalize_subject_label(code)

    if not normalized_name and not normalized_code:
        return False

    if normalized_code and existing.code:
        if _normalize_subject_label(existing.code) == normalized_code:
            return True

    if normalized_name and existing.name:
        if _normalize_subject_label(existing.name) == normalized_name:
            return True

    return False


def is_admin_user(user: User) -> bool:
    role_value = getattr(user, 'role', None)
    if isinstance(role_value, str):
        if role_value.lower() == UserRoleEnum.admin.value:
            return True
    if role_value == UserRoleEnum.admin:
        return True
    return bool(user.is_admin)

@router.get("/", response_model=List[SubjectSchema])
async def get_subjects(
    semester_id: Optional[str] = None,
    department_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieve active subjects. Admins can fetch all subjects; regular users only see their own department.
    """
    logger.info("[Subjects] ---- REQUEST START ----")
    logger.info(f"[Subjects] user={current_user.full_name} dept_id={current_user.department_id} semester_id={semester_id} department_id={department_id}")

    if not department_id and not current_user.department_id and not is_admin_user(current_user):
        logger.warning(f"[Subjects] REJECTED: user {current_user.full_name} has no department_id")
        raise HTTPException(status_code=400, detail="User is not assigned to a department")

    query = select(Subject).where(Subject.is_active == True)
    if department_id:
        if not is_admin_user(current_user) and current_user.department_id != department_id:
            raise HTTPException(status_code=403, detail="Not allowed to access this department")
        query = query.where(Subject.department_id == department_id)
    elif not is_admin_user(current_user):
        query = query.where(Subject.department_id == current_user.department_id)

    if semester_id:
        query = query.where(Subject.semester_id == semester_id)
        logger.info(f"[Subjects] filter: semester_id = {semester_id}")

    result = await db.execute(query)
    subjects = result.scalars().all()

    logger.info(f"[Subjects] RESULT: {len(subjects)} subjects")
    if not subjects:
        logger.warning("[Subjects] EMPTY RESULT - no subjects found for the requested scope")
    logger.info("[Subjects] ---- REQUEST END ----")
    return subjects

@router.post("/ai/extract-syllabus", status_code=200)
async def ai_extract_syllabus(
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    department_id: Optional[str] = Form(None),
    semester_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Extract syllabus JSON from source text, a PDF, or an image and return it for review."""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Only admins can use AI syllabus extraction")

    source_text = (text or '').strip()

    if file is not None:
        payload = await file.read()
        mime_type = file.content_type or "application/octet-stream"
        filename = (file.filename or '').lower()
        is_pdf = mime_type.startswith("application/pdf") or filename.endswith(".pdf")
        is_image = mime_type.startswith("image/") or filename.endswith((".png", ".jpg", ".jpeg", ".webp"))

        if is_pdf:
            extracted_text = await extract_text_from_pdf(payload)
            if not extracted_text.strip():
                raise HTTPException(status_code=422, detail="No readable text could be extracted from the PDF")
            structured = await extract_structured_data_from_pdf_text(extracted_text, "syllabus")
            return {"structured_json": _normalize_syllabus_payload(structured), "source_text": extracted_text}

        if is_image:
            try:
                from app.services.gemini_service import extract_syllabus_from_image
                result = await extract_syllabus_from_image(payload, mime_type)
                structured_json = _normalize_syllabus_payload(result)
                return {"structured_json": structured_json, "source_text": source_text or "Image upload"}
            except Exception as exc:
                logger.warning(f"[AI Syllabus] image extraction failed: {exc}")
                raise HTTPException(status_code=422, detail="No syllabus content could be read from the uploaded image. Please paste text instead.")

        raise HTTPException(status_code=400, detail="Unsupported file type. Please upload a PDF or image.")

    if not source_text:
        raise HTTPException(status_code=400, detail="Paste syllabus text or upload a PDF/image before extracting")

    result = await extract_structured_data_from_pdf_text(source_text, "syllabus")
    normalized = _normalize_syllabus_payload(result)
    return {"structured_json": normalized, "source_text": source_text}


@router.post("/ai/bulk-create", status_code=201)
async def ai_bulk_create_subjects(
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    department_id: str = Form(...),
    semester_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create many subjects from extracted data under the selected department and semester."""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Only admins can create subjects in bulk")

    department = await db.get(Department, department_id)
    if not department or not department.is_active:
        raise HTTPException(status_code=404, detail="Department not found")

    semester = await db.get(Semester, semester_id)
    if not semester or not semester.is_active or semester.department_id != department_id:
        raise HTTPException(status_code=404, detail="Semester not found for this department")

    source_text = (text or "").strip()
    if file is not None:
        source_bytes = await file.read()
        source_text = await extract_text_from_pdf(source_bytes) if file.filename.lower().endswith(".pdf") else source_text
    if not source_text:
        raise HTTPException(status_code=400, detail="Provide subject text or upload a PDF")

    parsed = await extract_subject_list_from_text(source_text)
    subjects = parsed.get("Subjects") or []
    if not subjects:
        raise HTTPException(status_code=400, detail="Gemini could not detect any valid subjects from the provided text")

    created = []
    for item in subjects:
        name = str(item.get("Subject Name") or "").strip()
        code = str(item.get("Subject Code") or "").strip()
        credits = item.get("Credits") or 0
        if not name:
            continue
        subject_payload = SubjectCreate(
            school_id=department.school_id,
            department_id=department.id,
            semester_id=semester.id,
            name=name,
            code=code or None,
            description="",
            credits=int(credits) if isinstance(credits, (int, float)) else 0,
            faculty_name="",
            subject_type="theory",
            is_active=True,
        )
        created_subject = await create_subject(subject_payload, db=db, current_user=current_user)
        created.append(created_subject)
    return created


@router.get("/{subject_id}", response_model=SubjectSchema)
async def get_subject(
    subject_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieve details for a single subject by ID."""
    subject = await db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    return subject

@router.put("/{subject_id}", response_model=SubjectSchema)
async def update_subject(
    subject_id: str,
    subject_in: SubjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not is_admin_user(current_user) and not current_user.department_id:
        raise HTTPException(status_code=400, detail="User is not assigned to a department")

    subject_query = select(Subject).where(Subject.id == subject_id)
    if not is_admin_user(current_user):
        subject_query = subject_query.where(Subject.department_id == current_user.department_id)

    result = await db.execute(subject_query)
    subject = result.scalars().first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    if subject_in.department_id is not None:
        department = await db.get(Department, subject_in.department_id)
        if not department or not department.is_active:
            raise HTTPException(status_code=404, detail="Department not found")
        subject.department_id = subject_in.department_id
        if subject_in.school_id is None:
            subject.school_id = department.school_id

    if subject_in.semester_id is not None:
        semester = await db.get(Semester, subject_in.semester_id)
        if not semester or not semester.is_active:
            raise HTTPException(status_code=404, detail="Semester not found")
        if subject_in.department_id is not None and semester.department_id != subject_in.department_id:
            raise HTTPException(status_code=400, detail="Semester does not belong to the selected department")
        if subject_in.department_id is None and semester.department_id != subject.department_id:
            raise HTTPException(status_code=400, detail="Semester does not belong to the subject's department")
        subject.semester_id = subject_in.semester_id

    if subject_in.school_id is not None:
        subject.school_id = subject_in.school_id

    updatable_fields = [
        "name",
        "code",
        "description",
        "credits",
        "faculty_name",
        "subject_type",
        "is_active"
    ]

    for field in updatable_fields:
        value = getattr(subject_in, field)
        if value is not None:
            setattr(subject, field, value)

    db.add(subject)
    await db.commit()
    await db.refresh(subject)
    return subject

@router.post("/", response_model=SubjectSchema, status_code=status.HTTP_201_CREATED)
async def create_subject(
    subject_in: SubjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new subject under a department and semester."""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Only admins can create subjects")

    if not subject_in.department_id or not subject_in.semester_id:
        raise HTTPException(status_code=400, detail="Department and semester are required")

    name = (subject_in.name or '').strip()
    code = (subject_in.code or '').strip()
    if not name:
        raise HTTPException(status_code=400, detail="Subject name is required")
    if not code:
        raise HTTPException(status_code=400, detail="Subject code is required")

    department = await db.get(Department, subject_in.department_id)
    if not department or not department.is_active:
        raise HTTPException(status_code=404, detail="Department not found")

    semester = await db.get(Semester, subject_in.semester_id)
    if not semester or not semester.is_active or semester.department_id != subject_in.department_id:
        raise HTTPException(status_code=404, detail="Semester not found for this department")

    school_id = subject_in.school_id or department.school_id
    if school_id != department.school_id:
        raise HTTPException(status_code=400, detail="School does not match the selected department")

    existing_query = await db.execute(
        select(Subject).where(
            Subject.is_active == True,
            Subject.school_id == school_id,
            Subject.department_id == subject_in.department_id,
            Subject.semester_id == subject_in.semester_id,
        )
    )
    existing_subjects = existing_query.scalars().all()

    for existing in existing_subjects:
        if _subject_identity_matches(existing, name, code):
            existing.name = name
            existing.code = code
            existing.description = existing.description or (subject_in.description or '')
            existing.credits = subject_in.credits if subject_in.credits is not None else existing.credits
            existing.faculty_name = subject_in.faculty_name or existing.faculty_name
            existing.subject_type = subject_in.subject_type or existing.subject_type
            existing.school_id = school_id
            existing.department_id = subject_in.department_id
            existing.semester_id = subject_in.semester_id
            db.add(existing)
            await db.commit()
            await db.refresh(existing)
            return existing

    destination_code_match = await db.execute(
        select(Subject).where(
            Subject.is_active == True,
            Subject.school_id == school_id,
            Subject.department_id == subject_in.department_id,
            Subject.semester_id == subject_in.semester_id,
            Subject.code == code,
        )
    )
    destination_code_subject = destination_code_match.scalars().first()
    if destination_code_subject:
        raise HTTPException(
            status_code=400,
            detail=f"Subject code '{code}' already exists in the selected department and semester."
        )

    try:
        subject = Subject(
            school_id=school_id,
            department_id=subject_in.department_id,
            semester_id=subject_in.semester_id,
            name=name,
            code=code,
            description=subject_in.description,
            credits=subject_in.credits,
            faculty_name=subject_in.faculty_name,
            subject_type=subject_in.subject_type,
            is_active=subject_in.is_active,
        )
        db.add(subject)
        await db.commit()
        await db.refresh(subject)

        # Keep the document workspace in sync with the subject directory.
        syllabus_document = Document(
            document_type=DocumentTypeEnum.syllabus,
            cloudinary_url="",
            title=f"{subject.name} Syllabus",
            description=subject.description or "",
            structured_json={"Units": []},
            school_id=subject.school_id,
            department_id=subject.department_id,
            semester_id=subject.semester_id,
            subject_id=subject.id,
            status="draft",
        )
        db.add(syllabus_document)
        await db.commit()
        return subject
    except Exception as exc:
        await db.rollback()
        if 'duplicate key' in str(exc).lower() or 'unique' in str(exc).lower():
            raise HTTPException(
                status_code=400,
                detail=f"This subject already exists in the selected department and semester. Check the subject name and code before saving."
            ) from exc
        raise HTTPException(
            status_code=400,
            detail=f"Unable to save subject '{name}'. The selected department/semester may already contain this subject or the submitted data is invalid."
        ) from exc

@router.post("/bulk-copy", response_model=List[SubjectSchema], status_code=status.HTTP_201_CREATED)
async def bulk_copy_subjects(
    copy_in: SubjectBulkCopy,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Copy subject metadata to one or more department/semester destinations atomically."""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Only admins can copy subjects")
    if not copy_in.source_subject_ids or not copy_in.destinations:
        raise HTTPException(status_code=400, detail="Select at least one subject and destination")

    source_ids = list(dict.fromkeys(copy_in.source_subject_ids))
    destinations = list({(item.department_id, item.semester_id): item for item in copy_in.destinations}.values())
    source_result = await db.execute(select(Subject).where(Subject.id.in_(source_ids), Subject.is_active == True))
    sources = source_result.scalars().all()
    source_by_id = {subject.id: subject for subject in sources}
    if len(source_by_id) != len(source_ids):
        raise HTTPException(status_code=404, detail="One or more source subjects were not found")

    destination_rows = []
    for destination in destinations:
        department = await db.get(Department, destination.department_id)
        semester = await db.get(Semester, destination.semester_id)
        if not department or not department.is_active:
            raise HTTPException(status_code=404, detail=f"Department not found: {destination.department_id}")
        if not semester or not semester.is_active or semester.department_id != department.id:
            raise HTTPException(status_code=400, detail=f"Semester does not belong to department '{department.name}'")
        destination_rows.append((department, semester))

    planned = []
    planned_documents = []
    for source_id in source_ids:
        source = source_by_id[source_id]
        for department, semester in destination_rows:
            if source.department_id == department.id and source.semester_id == semester.id:
                raise HTTPException(status_code=400, detail=f"'{source.name}' is already in the selected destination")
            existing_result = await db.execute(select(Subject).where(
                Subject.is_active == True,
                Subject.school_id == department.school_id,
                Subject.department_id == department.id,
                Subject.semester_id == semester.id,
                (Subject.name == source.name) | (Subject.code == source.code),
            ))
            if existing_result.scalars().first():
                raise HTTPException(status_code=409, detail=f"'{source.name}' or code '{source.code}' already exists in {department.name}, Semester {semester.semester_number}")
            planned.append(Subject(
                id=str(uuid.uuid4()),
                school_id=department.school_id,
                department_id=department.id,
                semester_id=semester.id,
                name=source.name,
                code=source.code,
                description=source.description if copy_in.copy_description else None,
                credits=source.credits if copy_in.copy_credits else None,
                faculty_name=source.faculty_name,
                subject_type=source.subject_type,
                is_active=True,
            ))

            document_result = await db.execute(select(Document).where(Document.subject_id == source.id))
            for document in document_result.scalars().all():
                should_copy = (
                    (document.document_type == DocumentTypeEnum.syllabus and (copy_in.copy_topics or copy_in.copy_pdf))
                    or (document.document_type == DocumentTypeEnum.note and copy_in.copy_notes)
                    or (document.document_type == DocumentTypeEnum.pyq and copy_in.copy_pyqs)
                )
                if not should_copy:
                    continue
                planned_documents.append((document, planned[-1], department, semester))

    try:
        db.add_all(planned)
        for source_document, target_subject, department, semester in planned_documents:
            copied_document = Document(
                id=str(uuid.uuid4()),
                school_id=department.school_id,
                department_id=department.id,
                semester_id=semester.id,
                subject_id=target_subject.id,
                document_type=source_document.document_type,
                academic_year=source_document.academic_year,
                cloudinary_url=source_document.cloudinary_url,
                cloudinary_public_id=source_document.cloudinary_public_id,
                thumbnail_url=source_document.thumbnail_url,
                file_size=source_document.file_size,
                file_type=source_document.file_type,
                title=source_document.title,
                description=source_document.description,
                keywords=source_document.keywords,
                metadata_json=source_document.metadata_json if copy_in.copy_topics else None,
                extracted_text=source_document.extracted_text if copy_in.copy_topics else None,
                structured_json=source_document.structured_json if copy_in.copy_topics else None,
                uploaded_by_admin=current_user.id,
                status='draft',
                youtube_url=source_document.youtube_url if copy_in.copy_youtube else None,
                youtube_video_id=source_document.youtube_video_id if copy_in.copy_youtube else None,
                video_title=source_document.video_title if copy_in.copy_youtube else None,
            )
            db.add(copied_document)
        await db.commit()
        for subject in planned:
            await db.refresh(subject)
        return planned
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Unable to copy subjects. No subjects were created.") from exc

@router.get("/{subject_id}/questions", response_model=List[QuestionSchema])
async def get_subject_questions(
    subject_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieve all structured PYQ questions for a specific subject.
    Extracts them dynamically from the Document.structured_json field.
    """
    logger.info(f"[Subjects API] Fetching questions for subject {subject_id}")
    
    query = select(Document).where(
        Document.subject_id == subject_id,
        Document.document_type == DocumentTypeEnum.pyq,
        Document.status == "active"
    )
    result = await db.execute(query)
    documents = result.scalars().all()
    
    all_questions = []
    question_texts = set()
    frequent_texts = set()
    
    # First pass: collect all questions and find duplicates
    for doc in documents:
        if not doc.structured_json:
            continue
            
        sj = doc.structured_json
        academic_year = doc.academic_year
        
        # Collect a flat list of (paper_dict, year, exam_type) tuples to process
        papers_to_process = []
        
        if isinstance(sj, dict):
            if "QuestionPapers" in sj:
                # Legacy/alternative format: wrapper with array
                for paper in sj["QuestionPapers"]:
                    papers_to_process.append(paper)
            elif "Questions" in sj:
                # ✅ Standard format: each document IS one QuestionPaper entity
                papers_to_process.append(sj)
            else:
                # Unknown dict structure – skip
                continue
        elif isinstance(sj, list):
            # In case it's a raw list of question paper objects
            papers_to_process.extend(sj)
        
        for paper in papers_to_process:
            year = paper.get("Academic Year") or academic_year
            type_ = paper.get("Exam Type")
            questions_raw = paper.get("Questions", [])
            
            if not isinstance(questions_raw, list):
                continue
                
            for q in questions_raw:
                if not isinstance(q, dict):
                    continue
                    
                text = q.get("Question Text", "") or ""
                text = text.strip()
                if not text:
                    continue
                    
                normalized = text.lower()
                if normalized in question_texts:
                    frequent_texts.add(normalized)
                else:
                    question_texts.add(normalized)
                    
                marks = q.get("Marks")
                try:
                    marks = float(marks)
                except (ValueError, TypeError):
                    marks = None
                    
                all_questions.append({
                    "id": str(uuid.uuid4()),
                    "question_number": str(q.get("Question Number", "") or ""),
                    "question_text": text,
                    "marks": marks,
                    "unit": str(q.get("Unit") or "").strip() or None,
                    "academic_year": str(year).strip() if year else None,
                    "exam_type": str(type_).strip() if type_ else None,
                    "source_document_id": doc.id,
                    "_normalized_text": normalized
                })
                        
    # Second pass: tag frequent questions
    final_questions = []
    for q in all_questions:
        q["frequently_asked"] = q["_normalized_text"] in frequent_texts
        del q["_normalized_text"]
        final_questions.append(q)
    
    logger.info(f"[Subjects API] Returning {len(final_questions)} questions for subject {subject_id} from {len(documents)} documents")
    return final_questions

@router.delete("/{subject_id}")
async def delete_subject(
    subject_id: str,
    confirm: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a subject.
    If confirm is False and there are associated documents, returns a warning and list of documents.
    If confirm is True, deletes the subject (cascade delete will automatically delete documents).
    """
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Only admins can delete subjects")

    subject = await db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    # Get associated documents
    doc_query = await db.execute(
        select(Document).where(Document.subject_id == subject_id)
    )
    documents = doc_query.scalars().all()
    doc_count = len(documents)

    if doc_count > 0 and not confirm:
        return {
            "status": "warning",
            "message": f"Subject '{subject.name}' has {doc_count} associated document(s) (syllabus, notes, or PYQs).",
            "doc_count": doc_count,
            "documents": [{"id": d.id, "title": d.title, "type": d.document_type} for d in documents]
        }

    try:
        await db.delete(subject)
        await db.commit()
        return {"status": "success", "message": f"Subject '{subject.name}' and its {doc_count} associated documents deleted successfully."}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete subject: {str(e)}")

