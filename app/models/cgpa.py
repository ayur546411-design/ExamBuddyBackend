from sqlalchemy import Column, String, ForeignKey, DateTime, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
import uuid

class CGPA(Base):
    __tablename__ = "cgpa"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    semester_id = Column(String, ForeignKey("semesters.id", ondelete="CASCADE"), nullable=False, index=True)
    
    semester_gpa = Column(Float, nullable=True)
    credits_earned = Column(Float, nullable=True)
    total_credits = Column(Float, nullable=True)
    overall_cgpa = Column(Float, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
