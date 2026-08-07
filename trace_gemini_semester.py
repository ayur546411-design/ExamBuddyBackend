"""
trace_gemini_semester.py — Show exactly what Gemini returned for each stored document
"""
import asyncio
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.document import Document, DocumentTypeEnum
from app.models.subject import Subject
from app.models.semester import Semester

async def main():
    async with AsyncSessionLocal() as db:
        # Get all syllabus documents with their full structured_json
        docs = (await db.execute(
            select(Document)
            .where(Document.document_type == DocumentTypeEnum.syllabus, Document.status == "active")
            .order_by(Document.created_at)
        )).scalars().all()

        print(f"Total syllabus documents: {len(docs)}\n")
        print("=" * 65)

        for doc in docs:
            sj = doc.structured_json or {}
            subject = await db.get(Subject, doc.subject_id) if doc.subject_id else None
            sem = await db.get(Semester, doc.semester_id) if doc.semester_id else None

            json_sem = sj.get("Semester", "NOT IN JSON")
            db_sem = sem.semester_number if sem else "NO SEM IN DB"
            subject_name = subject.name if subject else "NO SUBJECT"

            mismatch = ""
            if json_sem and str(json_sem) != str(db_sem):
                mismatch = "  <<< MISMATCH"

            print(f"  Doc   : {doc.title[:55]}")
            print(f"  Subject: {subject_name[:55]}")
            print(f"  JSON semester : '{json_sem}'")
            print(f"  DB semester   : {db_sem}{mismatch}")
            print(f"  created_at    : {doc.created_at}")
            
            # Show what other JSON fields are present
            keys = list(sj.keys())
            print(f"  JSON keys     : {keys}")
            if sj.get("Subject Code"):
                print(f"  Subject Code  : {sj['Subject Code']}")
            print()

asyncio.run(main())
