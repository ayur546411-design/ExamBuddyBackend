from sqlalchemy import Column, String, ForeignKey, DateTime, JSON, Enum, Integer, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
import uuid
import enum

class DocumentTypeEnum(str, enum.Enum):
    pyq = "pyq"
    syllabus = "syllabus"
    note = "note"
    notice = "notice"
    circular = "circular"
    assignment = "assignment"
    lab_manual = "lab_manual"
    time_table = "time_table"
    academic_calendar = "academic_calendar"
    result = "result"
    question_bank = "question_bank"
    practical_file = "practical_file"
    form = "form"
    other = "other"

class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    school_id = Column(String, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    department_id = Column(String, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True)
    semester_id = Column(String, ForeignKey("semesters.id", ondelete="CASCADE"), nullable=True, index=True)
    subject_id = Column(String, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=True, index=True)
    
    document_type = Column(Enum(DocumentTypeEnum), nullable=False)
    academic_year = Column(String, nullable=True) # E.g., "2026-2027"
    
    cloudinary_url = Column(String, nullable=False)
    cloudinary_public_id = Column(String, nullable=True)
    thumbnail_url = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True) # in bytes
    file_type = Column(String, nullable=True) # mime type
    
    title = Column(String, nullable=False, index=True) # indexed for text search
    description = Column(String, nullable=True)
    keywords = Column(String, nullable=True) # stored as comma separated or text
    metadata_json = Column(JSON, nullable=True)
    extracted_text = Column(String, nullable=True)
    structured_json = Column(JSON, nullable=True)
    
    uploaded_by_admin = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String, default="active")
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    subject = relationship("Subject", back_populates="documents")
