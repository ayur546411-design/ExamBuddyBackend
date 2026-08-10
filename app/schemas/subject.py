from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.models.subject import SubjectTypeEnum

class SubjectBase(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    credits: Optional[int] = None
    faculty_name: Optional[str] = None
    subject_type: SubjectTypeEnum = SubjectTypeEnum.theory
    is_active: bool = True

class Subject(SubjectBase):
    id: str
    school_id: str
    department_id: str
    semester_id: str
    created_at: datetime

    class Config:
        from_attributes = True

class SubjectCreate(SubjectBase):
    school_id: Optional[str] = None
    department_id: Optional[str] = None
    semester_id: Optional[str] = None

class SubjectUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    credits: Optional[int] = None
    faculty_name: Optional[str] = None
    subject_type: Optional[SubjectTypeEnum] = None
    is_active: Optional[bool] = None
    school_id: Optional[str] = None
    department_id: Optional[str] = None
    semester_id: Optional[str] = None
