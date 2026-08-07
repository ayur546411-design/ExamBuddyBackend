"""
run_test_local.py — Test local database query using the environment variables
"""
import asyncio
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.semester import Semester
from app.models.subject import Subject

async def test():
    async with AsyncSessionLocal() as db:
        sems = (await db.execute(select(Semester))).scalars().all()
        print(f"Semesters found in local settings DB: {[s.semester_number for s in sems]}")
        subjs = (await db.execute(select(Subject))).scalars().all()
        print(f"Subjects found: {len(subjs)}")
        for s in subjs:
            sem = await db.get(Semester, s.semester_id) if s.semester_id else None
            sem_num = sem.semester_number if sem else "?"
            print(f"  Sem{sem_num} | [{s.code}] {s.name[:50]}")

asyncio.run(test())
