from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List

from app.db.session import get_db
from app.models.school import School
from app.models.department import Department
from app.models.user import User, UserRoleEnum
from app.schemas.school import School as SchoolSchema, Department as DepartmentSchema, DepartmentCreate, DepartmentUpdate
from app.api.v1.endpoints.users import get_current_user

router = APIRouter()

def is_admin_user(user: User) -> bool:
    role_value = getattr(user, 'role', None)
    if isinstance(role_value, str):
        return role_value.lower() == UserRoleEnum.admin.value
    return role_value == UserRoleEnum.admin or bool(user.is_admin)

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

@router.post("/{school_id}/departments", response_model=DepartmentSchema, status_code=status.HTTP_201_CREATED)
async def create_department(
    school_id: str,
    department_in: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an active department under a school."""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Only admins can create departments")
    if department_in.school_id != school_id:
        raise HTTPException(status_code=400, detail="School in the request does not match the route")

    name = department_in.name.strip()
    code = department_in.code.strip().upper()
    if not name:
        raise HTTPException(status_code=400, detail="Department name is required")
    if not code:
        raise HTTPException(status_code=400, detail="Department code is required")

    school = await db.get(School, school_id)
    if not school or not school.is_active:
        raise HTTPException(status_code=404, detail="School not found")

    existing = await db.execute(select(Department).where(Department.code == code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Department code already exists")

    department = Department(
        school_id=school_id,
        name=name,
        code=code,
        description=department_in.description,
        duration_years=department_in.duration_years,
        total_semesters=department_in.total_semesters,
        is_active=department_in.is_active,
    )
    db.add(department)
    await db.commit()
    await db.refresh(department)
    return department

@router.put("/{school_id}/departments/{department_id}", response_model=DepartmentSchema)
async def update_department(
    school_id: str,
    department_id: str,
    department_in: DepartmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update department details."""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Only admins can update departments")

    department = await db.get(Department, department_id)
    if not department or department.school_id != school_id or not department.is_active:
        raise HTTPException(status_code=404, detail="Department not found")

    updates = department_in.model_dump(exclude_unset=True)
    if "name" in updates:
        updates["name"] = updates["name"].strip()
        if not updates["name"]:
            raise HTTPException(status_code=400, detail="Department name is required")
    if "code" in updates:
        updates["code"] = updates["code"].strip().upper()
        if not updates["code"]:
            raise HTTPException(status_code=400, detail="Department code is required")
        existing = await db.execute(select(Department).where(Department.code == updates["code"], Department.id != department_id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Department code already exists")

    for field, value in updates.items():
        setattr(department, field, value)
    await db.commit()
    await db.refresh(department)
    return department
