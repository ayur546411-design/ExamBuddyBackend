"""
Public API Schemas — read-only, CDN-safe, no private/user data.

These schemas define exactly what the public endpoints return.
They deliberately exclude:
  - extracted_text (can be large / internal)
  - uploaded_by_admin (user ID)
  - metadata_json (internal admin data)
  - cloudinary_public_id (only needed if app calls Cloudinary Management API)
  - any JWT / auth / credential fields
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel


# ── Nested lightweight references ─────────────────────────────────────────────

class PublicDepartmentRef(BaseModel):
    id: str
    name: str
    code: str

    class Config:
        from_attributes = True


class PublicSemesterRef(BaseModel):
    id: str
    semester_number: int
    academic_year: Optional[str] = None

    class Config:
        from_attributes = True


class PublicSubjectRef(BaseModel):
    id: str
    name: str
    code: Optional[str] = None
    credits: Optional[float] = None
    subject_type: Optional[str] = None

    class Config:
        from_attributes = True


# ── Syllabus response ──────────────────────────────────────────────────────────

class PublicSyllabusItem(BaseModel):
    """One syllabus document for a subject, returned by GET /api/v1/public/syllabus."""

    # Document identity
    id: str
    title: str
    description: Optional[str] = None
    academic_year: Optional[str] = None
    status: str

    # Subject / academic context
    subject_id: Optional[str] = None
    subject_name: Optional[str] = None
    subject_code: Optional[str] = None
    subject_credits: Optional[float] = None

    # Relational IDs — needed so the app can filter/join client-side
    department_id: str
    semester_id: Optional[str] = None
    semester_number: Optional[int] = None

    # Syllabus content — the structured JSON that the app renders
    structured_json: Optional[Any] = None  # {"Units": [...]}

    # Version / cache-busting signal
    updated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PublicSyllabusResponse(BaseModel):
    """Paginated wrapper for syllabus list."""
    total: int
    items: List[PublicSyllabusItem]


# ── PYQ response ───────────────────────────────────────────────────────────────

class PublicPYQItem(BaseModel):
    """One PYQ document, returned by GET /api/v1/public/pyqs."""

    # Document identity
    id: str
    title: str
    description: Optional[str] = None
    academic_year: Optional[str] = None
    status: str

    # Content delivery — app downloads PDF directly from Cloudinary
    cloudinary_url: str                       # Primary delivery URL
    cloudinary_public_id: Optional[str] = None  # Needed by app to construct transforms
    thumbnail_url: Optional[str] = None
    file_size: Optional[int] = None           # bytes — for progress bars
    file_type: Optional[str] = None           # "pdf" / "jpg" etc.

    # YouTube video reference (for video-based PYQs)
    youtube_url: Optional[str] = None
    youtube_video_id: Optional[str] = None
    video_title: Optional[str] = None

    # Exam metadata
    exam_type: Optional[str] = None           # extracted from metadata_json

    # Subject / academic context
    subject_id: Optional[str] = None
    subject_name: Optional[str] = None
    subject_code: Optional[str] = None

    # Relational IDs
    department_id: str
    semester_id: Optional[str] = None
    semester_number: Optional[int] = None

    # Version signal
    updated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PublicPYQResponse(BaseModel):
    """Paginated wrapper for PYQ list."""
    total: int
    page: int
    page_size: int
    items: List[PublicPYQItem]


# ── Subjects response (optional public listing) ────────────────────────────────

class PublicSubjectItem(BaseModel):
    """One subject, returned by GET /api/v1/public/subjects."""

    id: str
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    credits: Optional[float] = None
    subject_type: Optional[str] = None

    department_id: str
    semester_id: str
    semester_number: Optional[int] = None

    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PublicSubjectResponse(BaseModel):
    """List wrapper for subjects."""
    total: int
    items: List[PublicSubjectItem]
