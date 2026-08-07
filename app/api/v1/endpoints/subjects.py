from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional

from app.db.session import get_db
from app.models.subject import Subject
from app.schemas.subject import Subject as SubjectSchema
from app.models.user import User
from app.models.document import Document, DocumentTypeEnum
from app.schemas.document import QuestionSchema
from app.api.v1.endpoints.users import get_current_user
import logging
import uuid

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/", response_model=List[SubjectSchema])
async def get_subjects(
    semester_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieve all active subjects for the current user's department.
    Optionally filter by semester_id.
    """
    logger.info("[Subjects] ---- REQUEST START ----")
    logger.info(f"[Subjects] user={current_user.full_name} dept_id={current_user.department_id} semester_id={semester_id}")
    
    if not current_user.department_id:
        logger.warning(f"[Subjects] REJECTED: user {current_user.full_name} has no department_id")
        raise HTTPException(status_code=400, detail="User is not assigned to a department")
        
    query = select(Subject).where(
        Subject.department_id == current_user.department_id, 
        Subject.is_active == True
    )
    
    if semester_id:
        query = query.where(Subject.semester_id == semester_id)
        logger.info(f"[Subjects] filter: semester_id = {semester_id}")
        
    result = await db.execute(query)
    subjects = result.scalars().all()
    
    logger.info(f"[Subjects] RESULT: {len(subjects)} subjects for dept={current_user.department_id}")
    if not subjects:
        logger.warning(f"[Subjects] EMPTY RESULT - dept_id={current_user.department_id} semester_id={semester_id}. No subjects uploaded for this dept yet.")
    logger.info("[Subjects] ---- REQUEST END ----")
    return subjects

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
