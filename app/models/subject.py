from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, DateTime, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
import uuid
import enum

class SubjectTypeEnum(str, enum.Enum):
    theory = "theory"
    lab = "lab"

class Subject(Base):
    __tablename__ = "subjects"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    school_id = Column(String, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    department_id = Column(String, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True)
    semester_id = Column(String, ForeignKey("semesters.id", ondelete="CASCADE"), nullable=False, index=True)
    
    name = Column(String, index=True, nullable=False)
    code = Column(String, unique=True, index=True, nullable=True) # E.g., CS401
    description = Column(String, nullable=True)
    credits = Column(Integer, nullable=True)
    faculty_name = Column(String, nullable=True)
    subject_type = Column(Enum(SubjectTypeEnum), default=SubjectTypeEnum.theory)
    
    is_active = Column(Boolean(), default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    semester = relationship("Semester", back_populates="subjects")
    documents = relationship("Document", back_populates="subject", cascade="all, delete-orphan")
