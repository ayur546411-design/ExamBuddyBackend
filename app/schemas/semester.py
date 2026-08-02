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
    created_at: datetime

    class Config:
        from_attributes = True
