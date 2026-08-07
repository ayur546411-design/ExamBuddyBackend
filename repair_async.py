"""
repair_async.py — Fix semester mis-assignment using the same SQLAlchemy session
that already confirmed the data exists (audit scripts used this and worked).
"""
import asyncio
import json
from sqlalchemy import select, update
from app.db.session import AsyncSessionLocal
from app.models.document import Document, DocumentTypeEnum
from app.models.subject import Subject
from app.models.semester import Semester

# Codes confirmed in Semester 3 by audit, but uploaded as part of Semester 5 PDF
# ITUETK3-6 = elective slot numbers (K3 = 3rd elective), NOT semester 3
# ITUELT1   = Machine Learning Lab, belongs to Semester 5
CODES_TO_FIX = {'ITUETK3', 'ITUETK4', 'ITUETK5', 'ITUETK6', 'ITUELT1'}

async def main():
    async with AsyncSessionLocal() as db:

        # ── Get all semesters ──────────────────────────────────────────────
        sems_result = (await db.execute(select(Semester))).scalars().all()
        sems_by_num = {s.semester_number: s for s in sems_result}

        print("Semesters in DB:")
        for num in sorted(sems_by_num):
            s = sems_by_num[num]
            print(f"  Semester {num}  id={s.id[:8]}  dept={s.department_id[:8]}")

        sem3 = sems_by_num.get(3)
        sem5 = sems_by_num.get(5)

        if not sem3:
            print("Semester 3 not found.")
            return
        if not sem5:
            print("Semester 5 not found.")
            return

        # ── Find subjects in Semester 3 with elective codes ───────────────
        sem3_subjects = (await db.execute(
            select(Subject).where(Subject.semester_id == sem3.id)
        )).scalars().all()

        print(f"\nAll subjects in Semester 3 ({len(sem3_subjects)}):")
        for s in sem3_subjects:
            tag = "  <<< WILL MOVE to Sem5" if s.code in CODES_TO_FIX else ""
            print(f"  [{s.code or 'NO-CODE'}] {s.name[:55]}{tag}")

        to_fix = [s for s in sem3_subjects if s.code in CODES_TO_FIX]

        if not to_fix:
            print("\nNo subjects with those codes found in Semester 3. Nothing to repair.")
            return

        print(f"\nSubjects to move from Semester 3 -> Semester 5: {len(to_fix)}")
        for s in to_fix:
            print(f"  [{s.code}] {s.name}")

        confirm = input("\nApply repair? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("Cancelled.")
            return

        # ── Move each subject and its documents ───────────────────────────
        fixed_subjects = 0
        fixed_docs = 0

        for subj in to_fix:
            old_sem_id = subj.semester_id
            subj.semester_id = sem5.id
            db.add(subj)

            # Fix all documents linked to this subject
            docs = (await db.execute(
                select(Document).where(Document.subject_id == subj.id)
            )).scalars().all()

            for doc in docs:
                doc.semester_id = sem5.id
                # Fix structured_json semester field
                sj = dict(doc.structured_json or {})
                old_val = sj.get("Semester", "?")
                sj["Semester"] = "5"
                doc.structured_json = sj
                db.add(doc)
                fixed_docs += 1
                print(f"  Doc: '{doc.title[:45]}' | JSON Semester: '{old_val}' -> '5'")

            await db.commit()
            print(f"  [OK] [{subj.code}] '{subj.name}' + {len(docs)} doc(s) -> Semester 5")
            fixed_subjects += 1

        print(f"\n[SUCCESS] Moved {fixed_subjects} subjects and {fixed_docs} documents to Semester 5.")

        # ── Post-repair verification ───────────────────────────────────────
        print("\n=== POST-REPAIR STATE ===")

        for num in sorted(sems_by_num):
            sem = sems_by_num[num]
            subjects_after = (await db.execute(
                select(Subject).where(Subject.semester_id == sem.id, Subject.is_active == True)
            )).scalars().all()

            print(f"\nSemester {num} ({len(subjects_after)} subjects):")
            for s in subjects_after:
                docs_after = (await db.execute(
                    select(Document).where(Document.subject_id == s.id, Document.status == "active")
                )).scalars().all()

                sem_vals = set()
                for d in docs_after:
                    sj = d.structured_json or {}
                    sem_vals.add(str(sj.get("Semester", "?")))

                mismatch = ""
                if sem_vals and sem_vals != {str(num)}:
                    mismatch = f"  *** JSON says {sem_vals} != Sem{num} ***"

                print(f"  [{s.code or 'NO-CODE'}] {s.name[:50]:50s} | docs={len(docs_after)}{mismatch}")

asyncio.run(main())
