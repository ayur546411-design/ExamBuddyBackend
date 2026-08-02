from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.models.user import UserRoleEnum

class UserBase(BaseModel):
    full_name: str

    mobile_number: Optional[str] = None
    school_id: Optional[str] = None
    department_id: Optional[str] = None
    role: Optional[UserRoleEnum] = UserRoleEnum.student
    is_active: Optional[bool] = True

class UserCreate(UserBase):
    password: Optional[str] = None

class UserUpdate(UserBase):
    password: Optional[str] = None

class UserInDBBase(UserBase):
    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class User(UserInDBBase):
    pass
