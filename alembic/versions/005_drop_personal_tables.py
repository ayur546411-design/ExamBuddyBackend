"""Drop personal tables and update document

Revision ID: 005_drop_personal_tables
Revises: 004a54a7b6d0
Create Date: 2026-08-02 18:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '005_drop_personal_tables'
down_revision: Union[str, Sequence[str], None] = '004a54a7b6d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Drop tables if they exist
    op.drop_table('attendance', if_exists=True)
    op.drop_table('cgpa', if_exists=True)
    op.drop_table('results', if_exists=True)
    op.drop_table('notices', if_exists=True)
    op.drop_table('notifications', if_exists=True)
    op.drop_table('academic_calendar', if_exists=True)

    # Add new columns to documents
    op.add_column('documents', sa.Column('extracted_text', sa.String(), nullable=True))
    op.add_column('documents', sa.Column('structured_json', sa.JSON(), nullable=True))

def downgrade() -> None:
    # Remove columns from documents
    op.drop_column('documents', 'extracted_text')
    op.drop_column('documents', 'structured_json')

    # We won't reconstruct the dropped personal tables in downgrade for brevity,
    # as they are permanently removed from the application architecture.
    pass
