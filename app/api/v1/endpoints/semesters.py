from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional

from app.db.session import get_db
from app.models.department import Department
from app.models.semester import Semester
from app.schemas.semester import Semester as SemesterSchema, SemesterCreate
from app.models.user import User, UserRoleEnum
from app.api.v1.endpoints.users import get_current_user

import logging

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

@router.get("/", response_model=List[SemesterSchema])
async def get_semesters(
    department_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieve active semesters. Admins can fetch all semesters; regular users only see their own department.
    """
    logger.info("[Semesters] ---- REQUEST START ----")
    logger.info(f"[Semesters] user={current_user.full_name} dept_id={current_user.department_id} requested_department={department_id}")

    if not current_user.department_id and not is_admin_user(current_user):
        logger.warning(f"[Semesters] REJECTED: user {current_user.full_name} has no department_id")
        raise HTTPException(status_code=400, detail="User is not assigned to a department")

    query = select(Semester).where(Semester.is_active == True)

    if department_id:
        if not is_admin_user(current_user) and current_user.department_id != department_id:
            raise HTTPException(status_code=403, detail="Not allowed to access this department")
        query = query.where(Semester.department_id == department_id)
    elif not is_admin_user(current_user):
        query = query.where(Semester.department_id == current_user.department_id)

    result = await db.execute(query.order_by(Semester.semester_number.asc()))
    semesters = result.scalars().all()
    logger.info(f"[Semesters] RESULT: {len(semesters)} semesters")
    if not semesters:
        logger.warning("[Semesters] EMPTY RESULT - no semesters found for the requested scope")
    logger.info("[Semesters] ---- REQUEST END ----")
    return semesters

@router.post("/", response_model=SemesterSchema, status_code=status.HTTP_201_CREATED)
async def create_semester(
    semester_in: SemesterCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new semester for a department."""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Only admins can create semesters")

    if not semester_in.department_id:
        raise HTTPException(status_code=400, detail="Department is required")

    department = await db.get(Department, semester_in.department_id)
    if not department or not department.is_active:
        raise HTTPException(status_code=404, detail="Department not found")

    existing = await db.execute(
        select(Semester).where(
            Semester.department_id == semester_in.department_id,
            Semester.semester_number == semester_in.semester_number,
            Semester.is_active == True,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Semester already exists for this department")

    semester = Semester(
        department_id=semester_in.department_id,
        semester_number=semester_in.semester_number,
        academic_year=semester_in.academic_year,
        description=semester_in.description,
        is_active=semester_in.is_active,
    )
    db.add(semester)
    await db.commit()
    await db.refresh(semester)
    return semester
