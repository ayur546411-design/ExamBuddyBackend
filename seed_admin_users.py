"""
Seed script: Creates the admin_users table and inserts example admin users.

Usage:
    cd Backend
    python seed_admin_users.py
"""
import asyncio
import sys
import os

# Ensure the Backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.config import settings
from app.db.base import Base
from app.models.admin_user import AdminUser
from app.utils.security import get_password_hash


EXAMPLE_ADMINS = [
    {"user_id": "AYU07",  "password": "5464",     "full_name": "Admin AYU07"},
    {"user_id": "AY07FU", "password": "admin123",  "full_name": "Admin AY07FU"},
]


async def seed():
    engine = create_async_engine(settings.DATABASE_URL, echo=True)

    # 1. Create the admin_users table if it doesn't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text('CREATE OR REPLACE VIEW "adminUser" AS SELECT * FROM admin_users'))
    print("\n✅ Table 'admin_users' and view 'adminUser' ensured in database.\n")

    # 2. Insert example admin users
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        for admin in EXAMPLE_ADMINS:
            result = await session.execute(
                text("SELECT id FROM admin_users WHERE UPPER(user_id) = :uid"),
                {"uid": admin["user_id"].upper()}
            )
            existing = result.scalars().first()

            if existing:
                print(f"⏭️  Admin '{admin['user_id']}' already exists, skipping.")
                continue

            new_admin = AdminUser(
                user_id=admin["user_id"],
                password=admin["password"],
                full_name=admin["full_name"],
                is_active=True,
            )
            session.add(new_admin)
            await session.commit()
            print(f"✅  Created admin: user_id='{admin['user_id']}', password='{admin['password']}'")

    await engine.dispose()
    print("\n🎉 Seeding complete!")


if __name__ == "__main__":
    asyncio.run(seed())
