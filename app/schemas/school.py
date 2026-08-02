from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# Shared Properties
class DepartmentBase(BaseModel):
    name: str
    code: str
    description: Optional[str] = None
    duration_years: Optional[int] = None
    total_semesters: Optional[int] = None
    is_active: bool = True

class SchoolBase(BaseModel):
    name: str
    code: str
    description: Optional[str] = None
    logo_url: Optional[str] = None
    is_active: bool = True

class Department(DepartmentBase):
    id: str
    school_id: str
    created_at: datetime

    class Config:
        from_attributes = True

class School(SchoolBase):
    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    # We don't always need to load departments when fetching schools
    # departments: List[Department] = []

    class Config:
        from_attributes = True
