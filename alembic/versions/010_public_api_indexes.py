"""Add composite indexes for public API performance

Revision ID: 010_public_api_indexes
Revises: 3bb92709766e
Create Date: 2026-10-03

Adds composite indexes that directly serve the three new public endpoints:
  GET /api/v1/public/syllabus
  GET /api/v1/public/pyqs
  GET /api/v1/public/subjects

Most single-column indexes (department_id, semester_id, subject_id, status)
already exist from migration 004a54a7b6d0.  We only add what is missing.

Composite indexes speed up the WHERE clauses that filter on multiple columns
simultaneously — the query planner can satisfy the entire filter from the index
without touching table rows for non-matching departments.

DO NOT duplicate existing indexes.  Existing single-column indexes confirmed:
  documents: ix_documents_department_id, ix_documents_semester_id,
             ix_documents_subject_id, ix_documents_title,
             ix_documents_youtube_url, ix_documents_youtube_video_id
  subjects:  ix_subjects_department_id, ix_subjects_semester_id,
             ix_subjects_name, ix_subjects_code, ix_subjects_school_id
  departments: ix_departments_school_id, ix_departments_code, ix_departments_name
"""
from typing import Sequence, Union
from alembic import op


# revision identifiers
revision: str = "010_public_api_indexes"
down_revision: Union[str, Sequence[str], None] = "3bb92709766e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── documents table ────────────────────────────────────────────────────────
    # Public syllabus query:
    #   WHERE document_type = 'syllabus'
    #     AND department_id = ?
    #     AND status IN ('active', 'published')
    #   ORDER BY updated_at DESC, created_at DESC
    op.create_index(
        "ix_documents_public_syllabus",
        "documents",
        ["document_type", "department_id", "status", "updated_at"],
        unique=False,
        postgresql_ops={"updated_at": "DESC NULLS LAST"},
    )

    # Public PYQ query:
    #   WHERE document_type = 'pyq'
    #     AND department_id = ?
    #     AND status IN ('active', 'published')
    #   ORDER BY academic_year DESC, created_at DESC
    op.create_index(
        "ix_documents_public_pyq",
        "documents",
        ["document_type", "department_id", "status", "academic_year"],
        unique=False,
        postgresql_ops={"academic_year": "DESC NULLS LAST"},
    )

    # Optional additional index for semester-scoped PYQ/syllabus queries
    # (covers the very common subject_id filter path)
    op.create_index(
        "ix_documents_dept_sem_type_status",
        "documents",
        ["department_id", "semester_id", "document_type", "status"],
        unique=False,
    )

    # ── subjects table ─────────────────────────────────────────────────────────
    # Public subjects query:
    #   WHERE department_id = ? AND is_active = true
    #   ORDER BY name ASC
    # department_id index already exists; add composite with is_active for
    # index-only scan on (department_id, is_active).
    op.create_index(
        "ix_subjects_dept_active",
        "subjects",
        ["department_id", "is_active"],
        unique=False,
    )

    # Subject lookup for the batch enrichment step (subjects_by_id)
    # is via primary key — no additional index needed.


def downgrade() -> None:
    op.drop_index("ix_documents_public_syllabus", table_name="documents")
    op.drop_index("ix_documents_public_pyq", table_name="documents")
    op.drop_index("ix_documents_dept_sem_type_status", table_name="documents")
    op.drop_index("ix_subjects_dept_active", table_name="subjects")
