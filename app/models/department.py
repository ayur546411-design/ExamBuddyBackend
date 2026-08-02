from sqlalchemy import Column, String, Boolean, DateTime, Integer, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
import uuid

class Department(Base):
    __tablename__ = "departments"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    school_id = Column(String, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, index=True, nullable=False)
    code = Column(String, unique=True, index=True, nullable=False)
    description = Column(String, nullable=True)
    duration_years = Column(Integer, nullable=True)
    total_semesters = Column(Integer, nullable=True)
    is_active = Column(Boolean(), default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    school = relationship("School", back_populates="departments")
    semesters = relationship("Semester", back_populates="department", cascade="all, delete-orphan")
    users = relationship("User", back_populates="department", cascade="all, delete-orphan")
