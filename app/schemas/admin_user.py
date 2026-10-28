from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class AdminUserLogin(BaseModel):
    user_id: str
    password: str


class AdminUserCreate(BaseModel):
    user_id: str
    password: str
    full_name: Optional[str] = None


class AdminUserOut(BaseModel):
    id: str
    user_id: str
    full_name: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

