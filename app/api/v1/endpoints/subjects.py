from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional

from app.db.session import get_db
from app.models.department import Department
from app.models.semester import Semester
from app.models.subject import Subject
from app.schemas.subject import Subject as SubjectSchema, SubjectCreate, SubjectUpdate
from app.models.user import User, UserRoleEnum
from app.models.document import Document, DocumentTypeEnum
from app.schemas.document import QuestionSchema
from app.api.v1.endpoints.users import get_current_user
import logging
import uuid

logger = logging.getLogger(__name__)

router = APIRouter()

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

    if not current_user.department_id and not is_admin_user(current_user):
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

    department = await db.get(Department, subject_in.department_id)
    if not department or not department.is_active:
        raise HTTPException(status_code=404, detail="Department not found")

    semester = await db.get(Semester, subject_in.semester_id)
    if not semester or not semester.is_active or semester.department_id != subject_in.department_id:
        raise HTTPException(status_code=404, detail="Semester not found for this department")

    school_id = subject_in.school_id or department.school_id
    if school_id != department.school_id:
        raise HTTPException(status_code=400, detail="School does not match the selected department")

    existing = await db.execute(
        select(Subject).where(
            Subject.department_id == subject_in.department_id,
            Subject.semester_id == subject_in.semester_id,
            Subject.name == subject_in.name,
            Subject.is_active == True,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Subject already exists for this semester")

    subject = Subject(
        school_id=school_id,
        department_id=subject_in.department_id,
        semester_id=subject_in.semester_id,
        name=subject_in.name,
        code=subject_in.code,
        description=subject_in.description,
        credits=subject_in.credits,
        faculty_name=subject_in.faculty_name,
        subject_type=subject_in.subject_type,
        is_active=subject_in.is_active,
    )
    db.add(subject)
    await db.commit()
    await db.refresh(subject)
    return subject

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
