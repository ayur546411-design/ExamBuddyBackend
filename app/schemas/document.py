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
