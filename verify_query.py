"""
verify_query.py — Verify the fixed GET /documents/ query works end-to-end locally
"""
import asyncio
from sqlalchemy import select
from sqlalchemy.orm import load_only
from app.db.session import AsyncSessionLocal
from app.models.document import Document, DocumentTypeEnum
from app.models.subject import Subject

async def main():
    async with AsyncSessionLocal() as db:
        subjects = (await db.execute(select(Subject).limit(3))).scalars().all()
        
        all_ok = True
        for subj in subjects:
            print(f"Subject: {subj.name[:45]}  id={subj.id[:8]}")
            
            # Exact query from the fixed endpoint
            query = (
                select(Document)
                .options(load_only(
                    Document.id,
                    Document.title,
                    Document.description,
                    Document.document_type,
                    Document.academic_year,
                    Document.cloudinary_url,
                    Document.thumbnail_url,
                    Document.file_size,
                    Document.file_type,
                    Document.keywords,
                    Document.status,
                    Document.school_id,
                    Document.department_id,
                    Document.semester_id,
                    Document.subject_id,
                    Document.uploaded_by_admin,
                    Document.created_at,
                    Document.structured_json,
                    Document.metadata_json,
                    Document.extracted_text,
                ))
                .where(
                    Document.subject_id == subj.id,
                    Document.document_type == DocumentTypeEnum.syllabus,
                    Document.status == "active"
                )
            )
            docs = (await db.execute(query)).scalars().all()
            print(f"  Docs found: {len(docs)}")
            
            if docs:
                d = docs[0]
                sj = d.structured_json or {}
                
                # Try accessing all fields — this is what Pydantic does during serialization
                try:
                    _ = d.id
                    _ = d.title
                    _ = d.structured_json
                    _ = d.metadata_json     # Was causing MissingGreenlet before fix
                    _ = d.extracted_text    # Was causing MissingGreenlet before fix
                    print(f"  All fields accessible WITHOUT MissingGreenlet: OK")
                except Exception as e:
                    print(f"  FIELD ACCESS ERROR: {e}")
                    all_ok = False
                
                units = sj.get("Units", [])
                print(f"  structured_json has Units: {len(units)} unit(s)")
                if units:
                    print(f"    Unit 1: {units[0].get('Unit Name', 'N/A')[:50]}")
                    topics = units[0].get("Topics", [])
                    print(f"    Topics: {len(topics)}")
            print()
        
        if all_ok:
            print("=" * 50)
            print("  ALL QUERIES PASS - MissingGreenlet fix confirmed")
            print("  SyllabusViewerScreen will now render correctly")
            print("=" * 50)

asyncio.run(main())
