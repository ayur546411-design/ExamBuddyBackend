import asyncio
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.subject import Subject
from app.models.document import Document, DocumentTypeEnum
from app.models.department import Department
from app.models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        depts = (await db.execute(select(Department))).scalars().all()
        print("All departments + subject/syllabus counts:")
        for dept in depts:
            subj_count = len((await db.execute(select(Subject).where(Subject.department_id == dept.id))).scalars().all())
            doc_count = len((await db.execute(select(Document).where(
                Document.department_id == dept.id,
                Document.document_type == DocumentTypeEnum.syllabus,
                Document.status == "active"
            ))).scalars().all())
            print(f"  [{dept.id[:8]}] {dept.name[:45]:45s} subjects={subj_count} syllabus_docs_by_dept={doc_count}")

        print()
        users = (await db.execute(select(User).limit(10))).scalars().all()
        print("Users -> department mapping:")
        for u in users:
            dept = await db.get(Department, u.department_id) if u.department_id else None
            dept_name = dept.name if dept else "NO DEPT"
            print(f"  {u.full_name:20s} -> {dept_name}")
            
        print()
        # Where are the 34 subjects actually living?
        subjects = (await db.execute(select(Subject).where(Subject.is_active == True))).scalars().all()
        dept_subject_map = {}
        for s in subjects:
            dept_subject_map.setdefault(s.department_id, []).append(s.name)
        print("Subjects grouped by department_id:")
        for dept_id, names in dept_subject_map.items():
            dept = await db.get(Department, dept_id)
            dept_name = dept.name if dept else "UNKNOWN"
            print(f"  dept [{dept_id[:8]}] {dept_name}: {len(names)} subjects")

asyncio.run(main())
