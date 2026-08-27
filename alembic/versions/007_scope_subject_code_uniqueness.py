"""Allow subject codes to be reused across departments.

Revision ID: 007_scope_subject_code_uniqueness
Revises: 006_add_notifications_table
"""
from typing import Sequence, Union

from alembic import op

revision: str = '007_subject_code_scope'
down_revision: Union[str, Sequence[str], None] = ('006_add_notifications_table', '3bb92709766e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_subjects_code', table_name='subjects')
    op.create_index('ix_subjects_code', 'subjects', ['code'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_subjects_code', table_name='subjects')
    op.create_index('ix_subjects_code', 'subjects', ['code'], unique=True)
