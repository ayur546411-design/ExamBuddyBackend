"""Add admin_users table and seed initial admin

Revision ID: 011_add_admin_users_table
Revises: 010_public_api_indexes
Create Date: 2026-10-29
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column


# revision identifiers
revision: str = "011_add_admin_users_table"
down_revision: Union[str, Sequence[str], None] = "010_public_api_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create admin_users table
    op.create_table(
        "admin_users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("password", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now(), nullable=True),
    )
    op.create_index("ix_admin_users_user_id", "admin_users", ["user_id"], unique=True)

    # 2. Also create view "adminUser" for case-insensitive alias compatibility
    op.execute('CREATE OR REPLACE VIEW "adminUser" AS SELECT * FROM admin_users')

    # 3. Seed default admin users (AYU07 with password 5464, and AY07FU with admin123)
    admin_users_table = table(
        "admin_users",
        column("id", sa.String),
        column("user_id", sa.String),
        column("password", sa.String),
        column("full_name", sa.String),
        column("is_active", sa.Boolean),
    )

    op.bulk_insert(
        admin_users_table,
        [
            {
                "id": "admin-ayu07-001",
                "user_id": "AYU07",
                "password": "5464",
                "full_name": "Admin AYU07",
                "is_active": True,
            },
            {
                "id": "admin-ay07fu-002",
                "user_id": "AY07FU",
                "password": "admin123",
                "full_name": "Admin AY07FU",
                "is_active": True,
            },
        ],
    )


def downgrade() -> None:
    op.execute('DROP VIEW IF EXISTS "adminUser"')
    op.drop_index("ix_admin_users_user_id", table_name="admin_users")
    op.drop_table("admin_users")

