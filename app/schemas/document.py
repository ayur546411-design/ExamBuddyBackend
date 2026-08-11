from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime
from app.models.document import DocumentTypeEnum

class DocumentBase(BaseModel):
    title: str
    description: Optional[str] = None
    document_type: DocumentTypeEnum
    academic_year: Optional[str] = None
    cloudinary_url: str
    thumbnail_url: Optional[str] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    keywords: Optional[str] = None
    metadata_json: Optional[Any] = None
    structured_json: Optional[Any] = None
    extracted_text: Optional[str] = None
    status: Optional[str] = "active"
    exam_type: Optional[str] = None
    pdf_url: Optional[str] = None
    youtube_url: Optional[str] = None
    video_title: Optional[str] = None

class Document(DocumentBase):
    id: str
    school_id: str
    department_id: str
    semester_id: Optional[str] = None
    subject_id: Optional[str] = None
    uploaded_by_admin: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class DocumentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    academic_year: Optional[str] = None
    keywords: Optional[str] = None
    metadata_json: Optional[Any] = None
    structured_json: Optional[Any] = None
    status: Optional[str] = None
    semester_id: Optional[str] = None
    subject_id: Optional[str] = None
    exam_type: Optional[str] = None
    pdf_url: Optional[str] = None
    youtube_url: Optional[str] = None
    video_title: Optional[str] = None

class QuestionSchema(BaseModel):
    id: str
    question_number: str
    question_text: str
    marks: Optional[float] = None
    unit: Optional[str] = None
    academic_year: Optional[str] = None
    exam_type: Optional[str] = None
    frequently_asked: bool = False
    source_document_id: str
