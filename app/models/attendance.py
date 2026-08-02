from sqlalchemy import Column, String, ForeignKey, DateTime, Enum, Date
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
import uuid
import enum

class AttendanceStatusEnum(str, enum.Enum):
    present = "present"
    absent = "absent"
    holiday = "holiday"
    no_class = "no_class"

class Attendance(Base):
    __tablename__ = "attendance"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = Column(String, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True)
    
    date = Column(Date, nullable=False, index=True)
    status = Column(Enum(AttendanceStatusEnum), nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
