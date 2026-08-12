from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class SemesterBase(BaseModel):
    semester_number: int
    academic_year: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True

class Semester(SemesterBase):
    id: str
    department_id: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class SemesterCreate(SemesterBase):
    department_id: Optional[str] = None

class SemesterUpdate(BaseModel):
    semester_number: Optional[int] = None
    academic_year: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    department_id: Optional[str] = None
