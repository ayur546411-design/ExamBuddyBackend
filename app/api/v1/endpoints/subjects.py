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
    logger.info(f"[Subjects API] Fetching subjects for user {current_user.full_name}, dept: {current_user.department_id}, semester: {semester_id}")
    
    if not current_user.department_id:
        logger.warning(f"[Subjects API] User {current_user.full_name} has no department_id")
        raise HTTPException(status_code=400, detail="User is not assigned to a department")
        
    query = select(Subject).where(
        Subject.department_id == current_user.department_id, 
        Subject.is_active == True
    )
    
    if semester_id:
        query = query.where(Subject.semester_id == semester_id)
        
    result = await db.execute(query)
    subjects = result.scalars().all()
    
    logger.info(f"[Subjects API] Found {len(subjects)} subjects")
    if not subjects:
        logger.warning(f"[Subjects API] No subjects found for department {current_user.department_id}, semester {semester_id}")
        
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
            
        academic_year = doc.academic_year
        exam_type = None
        questions_array = []
        
        # Determine how QuestionPapers are structured
        if isinstance(doc.structured_json, dict) and "QuestionPapers" in doc.structured_json:
            for paper in doc.structured_json["QuestionPapers"]:
                year = paper.get("Academic Year") or academic_year
                type_ = paper.get("Exam Type")
                for q in paper.get("Questions", []):
                    # Clean the question text
                    text = q.get("Question Text", "")
                    if text:
                        normalized = text.lower().strip()
                        if normalized in question_texts:
                            frequent_texts.add(normalized)
                        else:
                            question_texts.add(normalized)
                            
                        # Try parsing marks to float
                        marks = q.get("Marks")
                        try:
                            marks = float(marks)
                        except (ValueError, TypeError):
                            marks = None
                            
                        all_questions.append({
                            "id": str(uuid.uuid4()),
                            "question_number": str(q.get("Question Number", "")),
                            "question_text": text,
                            "marks": marks,
                            "unit": str(q.get("Unit", "")) if q.get("Unit") else None,
                            "academic_year": str(year) if year else None,
                            "exam_type": str(type_) if type_ else None,
                            "source_document_id": doc.id,
                            "_normalized_text": normalized # Internal field for 2nd pass
                        })
                        
    # Second pass: tag frequent questions
    final_questions = []
    for q in all_questions:
        q["frequently_asked"] = q["_normalized_text"] in frequent_texts
        del q["_normalized_text"]
        final_questions.append(q)
        
    return final_questions
