from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class CalendarEventBase(BaseModel):
    event_title: str
    event_date: datetime
    description: Optional[str] = None

class CalendarEvent(CalendarEventBase):
    id: str
    school_id: str
    department_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
