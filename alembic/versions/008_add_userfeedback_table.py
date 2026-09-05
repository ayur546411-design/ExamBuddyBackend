"""Add userfeedback table for app feedback submissions.

Revision ID: 008_add_userfeedback_table
Revises: 007_subject_code_scope
Create Date: 2026-08-31 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '008_add_userfeedback_table'
down_revision: Union[str, Sequence[str], None] = '007_subject_code_scope'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table('userfeedback'):
        op.create_table(
            'userfeedback',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('user_id', sa.String(), nullable=True),
            sa.Column('full_name', sa.String(), nullable=False),
            sa.Column('feedback_type', sa.String(), nullable=False, server_default='Suggestion'),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('school_id', sa.String(), nullable=True),
            sa.Column('department_id', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )

    existing_indexes = {index['name'] for index in inspector.get_indexes('userfeedback')}
    for index_name, column_name in (
        ('ix_userfeedback_user_id', 'user_id'),
        ('ix_userfeedback_full_name', 'full_name'),
        ('ix_userfeedback_school_id', 'school_id'),
        ('ix_userfeedback_department_id', 'department_id'),
    ):
        if index_name not in existing_indexes:
            op.create_index(index_name, 'userfeedback', [column_name])


def downgrade() -> None:
    op.drop_index('ix_userfeedback_department_id', table_name='userfeedback')
    op.drop_index('ix_userfeedback_school_id', table_name='userfeedback')
    op.drop_index('ix_userfeedback_full_name', table_name='userfeedback')
    op.drop_index('ix_userfeedback_user_id', table_name='userfeedback')
    op.drop_table('userfeedback')
