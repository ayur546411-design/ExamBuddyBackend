"""
full_audit.py — Complete end-to-end data audit
Run from Backend/: python full_audit.py
"""
import asyncio
from sqlalchemy import select, func
from app.db.session import AsyncSessionLocal
from app.models.document import Document, DocumentTypeEnum
from app.models.subject import Subject
from app.models.semester import Semester
from app.models.department import Department
from app.models.school import School
from app.models.user import User

SEP = "=" * 65

async def main():
    async with AsyncSessionLocal() as db:

        # ── 1. SCHOOLS ────────────────────────────────────────────────
        schools = (await db.execute(select(School))).scalars().all()
        print(f"\n{SEP}\n  SCHOOLS ({len(schools)})\n{SEP}")
        for s in schools:
            print(f"  [{s.id[:8]}] {s.name} | active={s.is_active}")

        # ── 2. DEPARTMENTS ────────────────────────────────────────────
        depts = (await db.execute(select(Department))).scalars().all()
        print(f"\n{SEP}\n  DEPARTMENTS ({len(depts)})\n{SEP}")
        for d in depts:
            subj_n = len((await db.execute(select(Subject).where(Subject.department_id == d.id))).scalars().all())
            doc_n  = len((await db.execute(select(Document).where(Document.department_id == d.id))).scalars().all())
            if subj_n > 0 or doc_n > 0:
                print(f"  [{d.id[:8]}] {d.name[:50]:50s} subjects={subj_n:3d} docs={doc_n:3d}  *** HAS DATA ***")
            else:
                print(f"  [{d.id[:8]}] {d.name[:50]:50s} subjects={subj_n:3d} docs={doc_n:3d}")

        # ── 3. USERS ──────────────────────────────────────────────────
        users = (await db.execute(select(User).limit(20))).scalars().all()
        print(f"\n{SEP}\n  USERS (first 20)\n{SEP}")
        for u in users:
            dept = await db.get(Department, u.department_id) if u.department_id else None
            subj_n = 0
            if u.department_id:
                subj_n = len((await db.execute(select(Subject).where(Subject.department_id == u.department_id))).scalars().all())
            match = "OK" if subj_n > 0 else "NO DATA IN THIS DEPT"
            print(f"  {u.full_name:20s} dept={dept.name[:35] if dept else 'NONE':35s} [{match}]")

        # ── 4. DOCUMENTS BY TYPE ──────────────────────────────────────
        print(f"\n{SEP}\n  DOCUMENTS BY TYPE\n{SEP}")
        for dtype in DocumentTypeEnum:
            docs = (await db.execute(
                select(Document).where(Document.document_type == dtype, Document.status == "active")
            )).scalars().all()
            if docs:
                null_subj = sum(1 for d in docs if d.subject_id is None)
                null_dept = sum(1 for d in docs if d.department_id is None)
                has_json  = sum(1 for d in docs if d.structured_json)
                print(f"  {dtype.value:20s} total={len(docs):3d} | null_subject={null_subj} | null_dept={null_dept} | has_structured_json={has_json}")

        # ── 5. ORPHANED DOCUMENTS ─────────────────────────────────────
        print(f"\n{SEP}\n  ORPHANED DOCUMENTS (subject_id = NULL)\n{SEP}")
        orphans = (await db.execute(
            select(Document).where(Document.subject_id == None, Document.status == "active")
        )).scalars().all()
        print(f"  Total orphaned: {len(orphans)}")
        for d in orphans[:15]:
            print(f"  [{d.document_type.value:15s}] {d.title[:50]:50s} dept=[{d.department_id[:8] if d.department_id else 'NONE'}]")

        # ── 6. STRUCTURED_JSON CHECK ──────────────────────────────────
        print(f"\n{SEP}\n  STRUCTURED JSON CONTENT CHECK (syllabus docs)\n{SEP}")
        syl_docs = (await db.execute(
            select(Document).where(Document.document_type == DocumentTypeEnum.syllabus, Document.status == "active")
        )).scalars().all()
        for d in syl_docs[:5]:
            sj = d.structured_json or {}
            has_units    = bool(sj.get("Units"))
            has_subj     = bool(sj.get("Subject Name"))
            has_sem      = bool(sj.get("Semester"))
            print(f"  Doc: {d.title[:45]:45s}")
            print(f"       has_subject_name={has_subj} has_semester={has_sem} has_units={has_units} subject_id={'OK' if d.subject_id else 'NULL'}")
            if has_units:
                print(f"       units[0]: {str(sj['Units'][0])[:80]}")
            print()

        # ── 7. USER vs DATA DEPT MISMATCH SUMMARY ─────────────────────
        print(f"\n{SEP}\n  USER ↔ DATA MISMATCH SUMMARY\n{SEP}")
        data_dept_ids = set()
        for s in (await db.execute(select(Subject))).scalars().all():
            data_dept_ids.add(s.department_id)

        mismatch_users = []
        for u in users:
            if u.department_id not in data_dept_ids:
                dept = await db.get(Department, u.department_id) if u.department_id else None
                mismatch_users.append((u.full_name, dept.name if dept else "NONE", u.id, u.department_id))

        if mismatch_users:
            print(f"  *** {len(mismatch_users)} users in departments that have NO data uploaded: ***")
            for name, dept_name, uid, dept_id in mismatch_users:
                print(f"    {name:20s} -> {dept_name}")
            print()
            data_depts = []
            for dept_id in data_dept_ids:
                dept = await db.get(Department, dept_id)
                if dept:
                    data_depts.append(dept.name)
            print(f"  Departments WITH data: {data_depts}")
        else:
            print("  All users are in departments that have data. OK!")

        print(f"\n{SEP}\n  AUDIT COMPLETE\n{SEP}\n")

asyncio.run(main())
