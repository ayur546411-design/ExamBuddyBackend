"""
Public academic read-only endpoints — designed for Cloudflare CDN caching.

Rules enforced by this router:
  - NO JWT / authentication required (no Depends(get_current_user)).
  - Only returns status IN ('active', 'published') documents.
  - Only returns is_active=True subjects and departments.
  - Never returns user-specific, admin, credential, or internal data.
  - All query parameters are validated before hitting the DB.
  - Cross-department leakage is prevented by always filtering on department_id.
  - All responses carry Cache-Control headers suitable for Cloudflare edge caching.
  - PDFs are NOT proxied — the Cloudinary URL is returned and the app fetches direct.

Cache-Control strategy:
  public, max-age=300, s-maxage=21600, stale-while-revalidate=86400
    → browser/mobile: 5 min
    → Cloudflare edge: 6 hours
    → stale-while-revalidate: 24 hours (serve stale while fetching fresh in background)
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.db.session import get_db
from app.models.department import Department
from app.models.document import Document, DocumentTypeEnum
from app.models.semester import Semester
from app.models.subject import Subject
from app.schemas.public import (
    PublicPYQItem,
    PublicPYQResponse,
    PublicSubjectItem,
    PublicSubjectResponse,
    PublicSyllabusItem,
    PublicSyllabusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Cache-Control header value ────────────────────────────────────────────────
# browser/app: 5 min | Cloudflare edge: 6 h | stale-while-revalidate: 24 h
_CACHE_CONTROL = "public, max-age=300, s-maxage=21600, stale-while-revalidate=86400"

# Statuses the public API considers "published"
_PUBLIC_STATUSES = ("active", "published")

# Maximum page size allowed to prevent abuse
_MAX_PAGE_SIZE = 100


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _assert_department_exists(department_id: str, db: AsyncSession) -> None:
    """Raise 404 if the department_id doesn't exist or is inactive."""
    dept = await db.get(Department, department_id)
    if not dept or not dept.is_active:
        raise HTTPException(status_code=404, detail=f"Department '{department_id}' not found.")


async def _assert_semester_in_department(semester_id: str, department_id: str, db: AsyncSession) -> None:
    """Raise 404 if semester_id doesn't belong to department_id."""
    sem = await db.get(Semester, semester_id)
    if not sem or not sem.is_active or sem.department_id != department_id:
        raise HTTPException(
            status_code=404,
            detail=f"Semester '{semester_id}' not found in department '{department_id}'.",
        )


async def _assert_subject_in_department(subject_id: str, department_id: str, db: AsyncSession) -> None:
    """Raise 404 if subject_id doesn't belong to department_id — prevents cross-dept leakage."""
    subj = await db.get(Subject, subject_id)
    if not subj or not subj.is_active or subj.department_id != department_id:
        raise HTTPException(
            status_code=404,
            detail=f"Subject '{subject_id}' not found in department '{department_id}'.",
        )


def _cache_response(data: dict) -> JSONResponse:
    """Wrap a dict payload in a JSONResponse with CDN-safe Cache-Control headers."""
    return JSONResponse(
        content=data,
        headers={"Cache-Control": _CACHE_CONTROL},
    )


# ── Syllabus endpoint ─────────────────────────────────────────────────────────

@router.get(
    "/syllabus",
    summary="Public syllabus — CDN cacheable",
    response_model=PublicSyllabusResponse,
)
async def get_public_syllabus(
    department_id: str = Query(..., description="Required. Filters to this department only."),
    semester_id: Optional[str] = Query(None, description="Filter by semester (must belong to department_id)."),
    subject_id: Optional[str] = Query(None, description="Filter by subject (must belong to department_id)."),
    academic_year: Optional[str] = Query(None, description="Filter by academic year e.g. '2025-2026'."),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns published syllabus documents for the given department.

    - No authentication required.
    - Always scoped to department_id (cross-department leakage impossible).
    - Returns structured_json (units/topics) so the app can render offline.
    - PDFs are not included — syllabus content is in structured_json only.
    - Safe to cache at Cloudflare for 6 hours.
    """
    logger.info(
        "[Public/Syllabus] dept=%s sem=%s subj=%s year=%s",
        department_id, semester_id, subject_id, academic_year,
    )

    # ── Validate all IDs before touching documents ────────────────────────────
    await _assert_department_exists(department_id, db)

    if semester_id:
        await _assert_semester_in_department(semester_id, department_id, db)

    if subject_id:
        await _assert_subject_in_department(subject_id, department_id, db)

    # ── Build query — load only needed columns (no extracted_text, no metadata_json) ──
    query = (
        select(Document)
        .options(load_only(
            Document.id,
            Document.title,
            Document.description,
            Document.academic_year,
            Document.status,
            Document.document_type,
            Document.department_id,
            Document.semester_id,
            Document.subject_id,
            Document.structured_json,
            Document.created_at,
            Document.updated_at,
        ))
        .where(
            Document.document_type == DocumentTypeEnum.syllabus,
            Document.department_id == department_id,  # hard scope — no cross-dept
            Document.status.in_(_PUBLIC_STATUSES),
        )
    )

    if semester_id:
        query = query.where(Document.semester_id == semester_id)

    if subject_id:
        query = query.where(Document.subject_id == subject_id)

    if academic_year:
        query = query.where(Document.academic_year == academic_year)

    query = query.order_by(Document.updated_at.desc().nulls_last(), Document.created_at.desc())

    result = await db.execute(query)
    documents = result.scalars().all()

    # ── Enrich with subject / semester data ───────────────────────────────────
    # Collect IDs to batch-fetch; avoids N+1 queries.
    subject_ids = {d.subject_id for d in documents if d.subject_id}
    semester_ids = {d.semester_id for d in documents if d.semester_id}

    subjects_by_id: dict = {}
    if subject_ids:
        subj_result = await db.execute(
            select(Subject)
            .options(load_only(Subject.id, Subject.name, Subject.code, Subject.credits, Subject.subject_type))
            .where(Subject.id.in_(subject_ids))
        )
        subjects_by_id = {s.id: s for s in subj_result.scalars().all()}

    semesters_by_id: dict = {}
    if semester_ids:
        sem_result = await db.execute(
            select(Semester)
            .options(load_only(Semester.id, Semester.semester_number, Semester.academic_year))
            .where(Semester.id.in_(semester_ids))
        )
        semesters_by_id = {s.id: s for s in sem_result.scalars().all()}

    # ── Assemble response items ───────────────────────────────────────────────
    items: list[PublicSyllabusItem] = []
    for doc in documents:
        subj = subjects_by_id.get(doc.subject_id) if doc.subject_id else None
        sem = semesters_by_id.get(doc.semester_id) if doc.semester_id else None

        items.append(PublicSyllabusItem(
            id=doc.id,
            title=doc.title,
            description=doc.description,
            academic_year=doc.academic_year,
            status=doc.status,
            subject_id=doc.subject_id,
            subject_name=subj.name if subj else None,
            subject_code=subj.code if subj else None,
            subject_credits=subj.credits if subj else None,
            department_id=doc.department_id,
            semester_id=doc.semester_id,
            semester_number=sem.semester_number if sem else None,
            structured_json=doc.structured_json,
            updated_at=doc.updated_at,
            created_at=doc.created_at,
        ))

    logger.info("[Public/Syllabus] Returning %d items for dept=%s", len(items), department_id)

    payload = PublicSyllabusResponse(total=len(items), items=items)
    return _cache_response(payload.model_dump(mode="json"))


# ── PYQ endpoint ──────────────────────────────────────────────────────────────

@router.get(
    "/pyqs",
    summary="Public PYQs — CDN cacheable",
    response_model=PublicPYQResponse,
)
async def get_public_pyqs(
    department_id: str = Query(..., description="Required. Filters to this department only."),
    semester_id: Optional[str] = Query(None, description="Filter by semester (must belong to department_id)."),
    subject_id: Optional[str] = Query(None, description="Filter by subject (must belong to department_id)."),
    academic_year: Optional[str] = Query(None, description="Filter by academic year e.g. '2025-2026'."),
    page: int = Query(1, ge=1, description="Page number (1-indexed)."),
    page_size: int = Query(20, ge=1, le=_MAX_PAGE_SIZE, description="Items per page (max 100)."),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns published PYQ documents for the given department.

    - No authentication required.
    - Always scoped to department_id (cross-department leakage impossible).
    - Returns Cloudinary delivery URLs — app downloads PDFs directly from Cloudinary CDN.
    - FastAPI does NOT proxy or stream PDF bytes.
    - Paginated. Default page_size=20, max=100.
    - Safe to cache at Cloudflare for 6 hours.
    """
    logger.info(
        "[Public/PYQs] dept=%s sem=%s subj=%s year=%s page=%d size=%d",
        department_id, semester_id, subject_id, academic_year, page, page_size,
    )

    # ── Validate IDs ──────────────────────────────────────────────────────────
    await _assert_department_exists(department_id, db)

    if semester_id:
        await _assert_semester_in_department(semester_id, department_id, db)

    if subject_id:
        await _assert_subject_in_department(subject_id, department_id, db)

    # ── Base filter — always hard-scoped to department_id ─────────────────────
    base_filter = [
        Document.document_type == DocumentTypeEnum.pyq,
        Document.department_id == department_id,
        Document.status.in_(_PUBLIC_STATUSES),
    ]

    if semester_id:
        base_filter.append(Document.semester_id == semester_id)

    if subject_id:
        base_filter.append(Document.subject_id == subject_id)

    if academic_year:
        base_filter.append(Document.academic_year == academic_year)

    # ── Count total (for pagination metadata) ─────────────────────────────────
    count_result = await db.execute(
        select(func.count(Document.id)).where(*base_filter)
    )
    total = count_result.scalar_one()

    # ── Fetch page — only needed columns, no extracted_text or metadata_json body ──
    query = (
        select(Document)
        .options(load_only(
            Document.id,
            Document.title,
            Document.description,
            Document.academic_year,
            Document.status,
            Document.document_type,
            Document.cloudinary_url,
            Document.cloudinary_public_id,
            Document.thumbnail_url,
            Document.file_size,
            Document.file_type,
            Document.youtube_url,
            Document.youtube_video_id,
            Document.video_title,
            Document.metadata_json,   # needed to extract exam_type
            Document.department_id,
            Document.semester_id,
            Document.subject_id,
            Document.created_at,
            Document.updated_at,
        ))
        .where(*base_filter)
        .order_by(Document.academic_year.desc().nulls_last(), Document.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await db.execute(query)
    documents = result.scalars().all()

    # ── Batch-fetch subjects and semesters ────────────────────────────────────
    subject_ids = {d.subject_id for d in documents if d.subject_id}
    semester_ids = {d.semester_id for d in documents if d.semester_id}

    subjects_by_id: dict = {}
    if subject_ids:
        subj_result = await db.execute(
            select(Subject)
            .options(load_only(Subject.id, Subject.name, Subject.code))
            .where(Subject.id.in_(subject_ids))
        )
        subjects_by_id = {s.id: s for s in subj_result.scalars().all()}

    semesters_by_id: dict = {}
    if semester_ids:
        sem_result = await db.execute(
            select(Semester)
            .options(load_only(Semester.id, Semester.semester_number))
            .where(Semester.id.in_(semester_ids))
        )
        semesters_by_id = {s.id: s for s in sem_result.scalars().all()}

    # ── Assemble response items ───────────────────────────────────────────────
    items: list[PublicPYQItem] = []
    for doc in documents:
        subj = subjects_by_id.get(doc.subject_id) if doc.subject_id else None
        sem = semesters_by_id.get(doc.semester_id) if doc.semester_id else None

        # Extract exam_type from metadata_json without exposing the full metadata_json blob
        exam_type: Optional[str] = None
        if isinstance(doc.metadata_json, dict):
            exam_type = doc.metadata_json.get("exam_type")

        items.append(PublicPYQItem(
            id=doc.id,
            title=doc.title,
            description=doc.description,
            academic_year=doc.academic_year,
            status=doc.status,
            cloudinary_url=doc.cloudinary_url,
            cloudinary_public_id=doc.cloudinary_public_id,
            thumbnail_url=doc.thumbnail_url,
            file_size=doc.file_size,
            file_type=doc.file_type,
            youtube_url=doc.youtube_url,
            youtube_video_id=doc.youtube_video_id,
            video_title=doc.video_title,
            exam_type=exam_type,
            subject_id=doc.subject_id,
            subject_name=subj.name if subj else None,
            subject_code=subj.code if subj else None,
            department_id=doc.department_id,
            semester_id=doc.semester_id,
            semester_number=sem.semester_number if sem else None,
            updated_at=doc.updated_at,
            created_at=doc.created_at,
        ))

    logger.info("[Public/PYQs] Returning %d/%d items page=%d dept=%s", len(items), total, page, department_id)

    payload = PublicPYQResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )
    return _cache_response(payload.model_dump(mode="json"))


# ── Public subjects endpoint ──────────────────────────────────────────────────

@router.get(
    "/subjects",
    summary="Public subjects — CDN cacheable",
    response_model=PublicSubjectResponse,
)
async def get_public_subjects(
    department_id: str = Query(..., description="Required. Filters to this department only."),
    semester_id: Optional[str] = Query(None, description="Filter by semester (must belong to department_id)."),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns active subjects for the given department/semester.

    - No authentication required.
    - Always scoped to department_id.
    - Used by the app to build navigation before fetching syllabus/PYQs.
    - Safe to cache at Cloudflare for 6 hours.
    """
    logger.info("[Public/Subjects] dept=%s sem=%s", department_id, semester_id)

    await _assert_department_exists(department_id, db)

    if semester_id:
        await _assert_semester_in_department(semester_id, department_id, db)

    query = (
        select(Subject)
        .options(load_only(
            Subject.id,
            Subject.name,
            Subject.code,
            Subject.description,
            Subject.credits,
            Subject.subject_type,
            Subject.department_id,
            Subject.semester_id,
            Subject.created_at,
        ))
        .where(
            Subject.department_id == department_id,
            Subject.is_active == True,
        )
    )

    if semester_id:
        query = query.where(Subject.semester_id == semester_id)

    query = query.order_by(Subject.name.asc())

    result = await db.execute(query)
    subjects = result.scalars().all()

    # Batch-fetch semester numbers
    semester_ids = {s.semester_id for s in subjects if s.semester_id}
    semesters_by_id: dict = {}
    if semester_ids:
        sem_result = await db.execute(
            select(Semester)
            .options(load_only(Semester.id, Semester.semester_number))
            .where(Semester.id.in_(semester_ids))
        )
        semesters_by_id = {s.id: s for s in sem_result.scalars().all()}

    items = [
        PublicSubjectItem(
            id=s.id,
            name=s.name,
            code=s.code,
            description=s.description,
            credits=s.credits,
            subject_type=s.subject_type.value if s.subject_type else None,
            department_id=s.department_id,
            semester_id=s.semester_id,
            semester_number=semesters_by_id[s.semester_id].semester_number
            if s.semester_id and s.semester_id in semesters_by_id
            else None,
            created_at=s.created_at,
        )
        for s in subjects
    ]

    logger.info("[Public/Subjects] Returning %d subjects for dept=%s", len(items), department_id)

    payload = PublicSubjectResponse(total=len(items), items=items)
    return _cache_response(payload.model_dump(mode="json"))
