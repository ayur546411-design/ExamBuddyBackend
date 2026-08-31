from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class UserFeedbackBase(BaseModel):
    full_name: str
    feedback_type: str = "Suggestion"
    message: str
    school_id: Optional[str] = None
    department_id: Optional[str] = None
    user_id: Optional[str] = None


class UserFeedbackCreate(UserFeedbackBase):
    pass


class UserFeedback(UserFeedbackBase):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True
