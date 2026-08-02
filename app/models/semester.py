from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
import uuid

class Semester(Base):
    __tablename__ = "semesters"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    department_id = Column(String, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True)
    semester_number = Column(Integer, nullable=False)
    academic_year = Column(String, nullable=True) # E.g., "2026-2027"
    description = Column(String, nullable=True)
    is_active = Column(Boolean(), default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    department = relationship("Department", back_populates="semesters")
    subjects = relationship("Subject", back_populates="semester", cascade="all, delete-orphan")
