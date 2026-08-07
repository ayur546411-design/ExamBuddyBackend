"""
audit_semester_mapping.py — Investigate semester/subject corruption in DB
"""
import asyncio
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.document import Document, DocumentTypeEnum
from app.models.subject import Subject
from app.models.semester import Semester
from app.models.department import Department

SEP = "=" * 65

async def main():
    async with AsyncSessionLocal() as db:

        # ── 1. Show all semesters and their subjects ─────────────────────
        print(f"\n{SEP}")
        print("  ALL SEMESTERS → SUBJECTS (checking for mis-assignments)")
        print(SEP)

        depts = (await db.execute(select(Department))).scalars().all()
        for dept in depts:
            sems = (await db.execute(
                select(Semester)
                .where(Semester.department_id == dept.id, Semester.is_active == True)
                .order_by(Semester.semester_number)
            )).scalars().all()

            if not sems:
                continue

            print(f"\n  Dept: {dept.name}")
            for sem in sems:
                subjects = (await db.execute(
                    select(Subject)
                    .where(Subject.semester_id == sem.id, Subject.is_active == True)
                )).scalars().all()

                print(f"    Semester {sem.semester_number} (id={sem.id[:8]}) — {len(subjects)} subjects")
                for s in subjects:
                    docs = (await db.execute(
                        select(Document)
                        .where(Document.subject_id == s.id, Document.status == "active")
                    )).scalars().all()
                    
                    # Check if any doc has a structured_json with a different semester
                    for doc in docs:
                        sj = doc.structured_json or {}
                        doc_sem = sj.get("Semester", "?")
                        flag = ""
                        if doc_sem and doc_sem != "?" and str(doc_sem).strip():
                            try:
                                doc_sem_num = int(str(doc_sem).strip())
                                if doc_sem_num != sem.semester_number:
                                    flag = f"  ⚠️  MISMATCH: doc says Sem {doc_sem_num}, stored in Sem {sem.semester_number}"
                            except:
                                pass
                    
                    print(f"      [{s.code or 'NO-CODE'}] {s.name[:50]:50s} | docs={len(docs)}{flag}")

        # ── 2. Cross-check: doc structured_json semester vs stored semester ───
        print(f"\n{SEP}")
        print("  DOCUMENTS WITH SEMESTER MISMATCH (doc JSON vs DB semester)")
        print(SEP)

        all_docs = (await db.execute(
            select(Document)
            .where(Document.document_type == DocumentTypeEnum.syllabus, Document.status == "active")
        )).scalars().all()

        mismatches = []
        for doc in all_docs:
            if not doc.subject_id or not doc.semester_id:
                continue
            
            sj = doc.structured_json or {}
            json_sem_str = str(sj.get("Semester", "")).strip()
            if not json_sem_str or json_sem_str.lower() in ("null", "none", ""):
                continue
            
            try:
                json_sem_num = int(json_sem_str)
            except ValueError:
                continue
            
            # Get stored semester
            stored_sem = await db.get(Semester, doc.semester_id)
            if stored_sem and stored_sem.semester_number != json_sem_num:
                mismatches.append({
                    "doc_title": doc.title,
                    "json_says": json_sem_num,
                    "stored_as": stored_sem.semester_number,
                    "semester_id": doc.semester_id,
                    "subject_id": doc.subject_id,
                    "doc_id": doc.id,
                })

        if mismatches:
            print(f"\n  Found {len(mismatches)} MISMATCHED documents:")
            for m in mismatches:
                print(f"    '{m['doc_title'][:45]:45s}'")
                print(f"      JSON says Semester {m['json_says']} | Stored in Semester {m['stored_as']}")
                print(f"      doc_id={m['doc_id'][:8]} sem_id={m['semester_id'][:8]}")
        else:
            print("  No mismatches found (structured_json semester matches DB semester)")

        # ── 3. Check subjects for duplicate names in different semesters ──
        print(f"\n{SEP}")
        print("  SUBJECTS WITH SAME NAME IN MULTIPLE SEMESTERS")
        print(SEP)
        
        all_subjects = (await db.execute(select(Subject))).scalars().all()
        name_to_sems = {}
        for s in all_subjects:
            name_lower = s.name.strip().lower()
            if name_lower not in name_to_sems:
                name_to_sems[name_lower] = []
            name_to_sems[name_lower].append(s)
        
        duplicates_found = 0
        for name, subjects in name_to_sems.items():
            if len(subjects) > 1:
                sem_ids = set(s.semester_id for s in subjects)
                if len(sem_ids) > 1:
                    duplicates_found += 1
                    print(f"\n  '{subjects[0].name[:50]}'")
                    for s in subjects:
                        sem = await db.get(Semester, s.semester_id) if s.semester_id else None
                        sem_num = sem.semester_number if sem else "?"
                        docs = (await db.execute(select(Document).where(Document.subject_id == s.id))).scalars().all()
                        print(f"    id={s.id[:8]} Semester {sem_num} | docs={len(docs)}")
        
        if duplicates_found == 0:
            print("  No duplicate subject names across different semesters found.")

        print(f"\n{SEP}")
        print("  AUDIT COMPLETE")
        print(SEP)

asyncio.run(main())
