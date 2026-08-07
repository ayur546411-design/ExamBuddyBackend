"""
check_all_data.py — Print all semesters, subjects, and documents in detail.
"""
import asyncio
from dotenv import load_dotenv
load_dotenv()
from app.db.session import AsyncSessionLocal
from sqlalchemy import text

async def main():
    async with AsyncSessionLocal() as db:
        # Semesters
        sems = (await db.execute(text("SELECT id, department_id, semester_number, is_active FROM public.semesters"))).fetchall()
        print(f"Semesters ({len(sems)}):")
        for s in sems:
            print(f"  id={s[0]} dept={s[1][:8]} sem_num={s[2]} active={s[3]}")
            
        # Subjects
        subjs = (await db.execute(text("SELECT id, semester_id, name, code FROM public.subjects"))).fetchall()
        print(f"\nSubjects ({len(subjs)}):")
        for s in subjs:
            print(f"  id={s[0]} sem_id={s[1][:8] if s[1] else 'None'} name={s[2]} code={s[3]}")
            
        # Documents
        docs = (await db.execute(text("SELECT id, subject_id, semester_id, title FROM public.documents"))).fetchall()
        print(f"\nDocuments ({len(docs)}):")
        for d in docs:
            print(f"  id={d[0]} subj_id={d[1][:8] if d[1] else 'None'} sem_id={d[2][:8] if d[2] else 'None'} title={d[3]}")

asyncio.run(main())
