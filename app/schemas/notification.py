from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class NotificationBase(BaseModel):
    title: str
    body: str
    user_id: Optional[str] = None
    is_read: bool = False


class NotificationCreate(NotificationBase):
    pass


class Notification(NotificationBase):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True
