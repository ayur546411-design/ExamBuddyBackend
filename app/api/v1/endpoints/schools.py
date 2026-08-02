from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List

from app.db.session import get_db
from app.models.school import School
from app.models.department import Department
from app.schemas.school import School as SchoolSchema, Department as DepartmentSchema

router = APIRouter()

@router.get("/", response_model=List[SchoolSchema])
async def get_schools(db: AsyncSession = Depends(get_db)):
    """
    Retrieve all active schools.
    """
    result = await db.execute(select(School).where(School.is_active == True))
    return result.scalars().all()

@router.get("/{school_id}/departments", response_model=List[DepartmentSchema])
async def get_departments_by_school(school_id: str, db: AsyncSession = Depends(get_db)):
    """
    Retrieve all active departments for a specific school.
    """
    result = await db.execute(
        select(Department).where(Department.school_id == school_id, Department.is_active == True)
    )
    departments = result.scalars().all()
    if not departments:
        # Check if school exists
        school = await db.get(School, school_id)
        if not school:
            raise HTTPException(status_code=404, detail="School not found")
            
    return departments
