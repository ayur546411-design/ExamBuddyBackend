"""
check_syllabus_links.py
-----------------------
Diagnostic: shows all syllabus documents and how they are linked to subjects.
Helps identify why "No Syllabus Found" appears for a subject that has uploads.

Run from Backend/:
    python check_syllabus_links.py
"""
import asyncio
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.document import Document, DocumentTypeEnum
from app.models.subject import Subject
from app.models.semester import Semester


async def main():
    async with AsyncSessionLocal() as db:
        # 1. All syllabus documents
        docs = (
            await db.execute(
                select(Document).where(Document.document_type == DocumentTypeEnum.syllabus)
            )
        ).scalars().all()

        print(f"\n{'='*60}")
        print(f"  SYLLABUS DOCUMENTS IN DB: {len(docs)}")
        print(f"{'='*60}\n")

        for doc in docs:
            subject = None
            if doc.subject_id:
                subject = await db.get(Subject, doc.subject_id)

            print(f"Document: {doc.title}")
            print(f"   ID         : {doc.id}")
            print(f"   Status     : {doc.status}")
            print(f"   dept_id    : {doc.department_id}")
            print(f"   subject_id : {doc.subject_id}")
            if subject:
                print(f"   OK Subject  : {subject.name}  (id={subject.id})")
                print(f"      sem_id   : {subject.semester_id}")
            else:
                print(f"   PROBLEM: Subject NOT LINKED (subject_id is NULL or invalid)")
            print()

        # 2. All subjects and whether they have a syllabus
        print(f"\n{'='*60}")
        print(f"  SUBJECTS vs SYLLABUS COVERAGE")
        print(f"{'='*60}\n")

        subjects = (await db.execute(select(Subject))).scalars().all()
        for subj in subjects:
            sem = await db.get(Semester, subj.semester_id) if subj.semester_id else None
            linked_docs = (
                await db.execute(
                    select(Document).where(
                        Document.subject_id == subj.id,
                        Document.document_type == DocumentTypeEnum.syllabus,
                        Document.status == "active"
                    )
                )
            ).scalars().all()

            sem_num = sem.semester_number if sem else "?"
            status = f"OK - {len(linked_docs)} syllabus doc(s)" if linked_docs else "MISSING - No syllabus"
            print(f"  Sem {sem_num} | {subj.name:40s} | {status}")

        print()


if __name__ == "__main__":
    asyncio.run(main())
