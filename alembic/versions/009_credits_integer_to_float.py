"""Change subjects.credits from INTEGER to FLOAT to support decimal values.

Revision ID: 009_credits_integer_to_float
Revises: 008_add_userfeedback_table
Create Date: 2026-09-12 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '009_credits_integer_to_float'
down_revision: Union[str, Sequence[str], None] = '008_add_userfeedback_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Change credits column from INTEGER to DOUBLE PRECISION (Float) so values
    # like 1.5, 0.5 etc. are stored without truncation.
    op.alter_column(
        'subjects',
        'credits',
        type_=sa.Float(),
        existing_type=sa.Integer(),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Revert back to INTEGER (decimal values will be truncated on downgrade)
    op.alter_column(
        'subjects',
        'credits',
        type_=sa.Integer(),
        existing_type=sa.Float(),
        existing_nullable=True,
    )
