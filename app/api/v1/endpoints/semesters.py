from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List

from app.db.session import get_db
from app.models.semester import Semester
from app.schemas.semester import Semester as SemesterSchema
from app.models.user import User
from app.api.v1.endpoints.users import get_current_user

router = APIRouter()

@router.get("/", response_model=List[SemesterSchema])
async def get_semesters(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieve all active semesters for the current user's department.
    """
    if not current_user.department_id:
        raise HTTPException(status_code=400, detail="User is not assigned to a department")
        
    result = await db.execute(
        select(Semester)
        .where(Semester.department_id == current_user.department_id, Semester.is_active == True)
        .order_by(Semester.semester_number.asc())
    )
    return result.scalars().all()
