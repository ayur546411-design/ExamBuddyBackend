from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional

from app.db.session import get_db
from app.models.subject import Subject
from app.schemas.subject import Subject as SubjectSchema
from app.models.user import User
from app.api.v1.endpoints.users import get_current_user

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
    if not current_user.department_id:
        raise HTTPException(status_code=400, detail="User is not assigned to a department")
        
    query = select(Subject).where(
        Subject.department_id == current_user.department_id, 
        Subject.is_active == True
    )
    
    if semester_id:
        query = query.where(Subject.semester_id == semester_id)
        
    result = await db.execute(query)
    return result.scalars().all()
