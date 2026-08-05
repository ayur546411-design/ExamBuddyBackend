import asyncio
from app.db.session import AsyncSessionLocal
from sqlalchemy import select
from app.models.document import Document
from app.models.subject import Subject
from app.models.department import Department

async def check():
    async with AsyncSessionLocal() as db:
        # Find AVFX department
        dept_query = await db.execute(select(Department).where(Department.name.ilike('%AVFX%')))
        dept = dept_query.scalars().first()
        if not dept:
            print("AVFX department not found")
            return
            
        print(f"Found Department: {dept.name}")
        
        # Check subjects
        subj_query = await db.execute(select(Subject).where(Subject.department_id == dept.id))
        subjects = subj_query.scalars().all()
        print(f"Total AVFX Subjects in DB: {len(subjects)}")
        
        # Check documents
        doc_query = await db.execute(select(Document).where(Document.department_id == dept.id))
        docs = doc_query.scalars().all()
        print(f"Total AVFX Documents in DB: {len(docs)}")
        for doc in docs:
            print(f"- {doc.title} (Sem: {doc.semester_id})")

if __name__ == "__main__":
    asyncio.run(check())
