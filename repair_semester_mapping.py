"""
repair_semester_mapping.py — Fix subjects/documents assigned to wrong semester.

Based on audit:
- Subjects with codes ITUETK3/4/5/6 and Machine Learning Lab (ITUELT1)
  were assigned Semester 3 but belong to Semester 5/7 elective scheme.

This script:
1. Shows the current state
2. Prompts for confirmation
3. Moves affected subjects + documents to the correct semester
"""
import asyncio
import sys
from sqlalchemy import select, update
from app.db.session import AsyncSessionLocal
from app.models.document import Document, DocumentTypeEnum
from app.models.subject import Subject
from app.models.semester import Semester
from app.models.department import Department

# ─── These subjects with their codes were wrongly assigned to Semester 3 ────
# They have structured_json["Semester"] = "3" but subject codes suggest
# they are elective subjects (ITUETK = IT Elective).
# Based on GGU IT curriculum, ITUETK3-6 are Department Electives from Sem 7.
# Machine Learning Lab (ITUELT1) is Semester 5.
#
# The repair strategy:
# 1. Look at the structured_json["Semester"] field in each document
# 2. Compare against the DB semester the subject is stored in
# 3. If user uploaded a "Semester 5" PDF but doc says "3" → that's wrong
#
# Since the structured_json semester = "3" and DB semester = 3 (they match),
# the root cause is Gemini returning "3" incorrectly from subject codes.
# The only way to repair is to ask the user: what semester does each subject ACTUALLY belong to?
#
# For now, we'll show the problem and ask the user to specify the correct semester.

async def main():
    async with AsyncSessionLocal() as db:
        dept = (await db.execute(
            select(Department).where(Department.name.ilike("%Information Technology%"))
        )).scalars().first()

        if not dept:
            print("Department not found")
            return

        print(f"Department: {dept.name} (id={dept.id[:8]})")
        print()

        # Get all semesters for this department
        sems = {
            s.semester_number: s
            for s in (await db.execute(
                select(Semester).where(Semester.department_id == dept.id)
            )).scalars().all()
        }
        print(f"Existing semesters: {sorted(sems.keys())}")
        print()

        # Get all subjects in Semester 3
        sem3 = sems.get(3)
        if not sem3:
            print("Semester 3 not found")
            return

        sem3_subjects = (await db.execute(
            select(Subject).where(Subject.semester_id == sem3.id)
        )).scalars().all()

        print(f"=== Semester 3 subjects that may be incorrectly placed ===")
        print()
        for subj in sem3_subjects:
            docs = (await db.execute(
                select(Document).where(Document.subject_id == subj.id)
            )).scalars().all()

            # Get what the structured_json says about semester
            json_sems = set()
            for doc in docs:
                sj = doc.structured_json or {}
                json_sems.add(str(sj.get("Semester", "?")))

            print(f"  [{subj.code or 'NO-CODE'}] {subj.name}")
            print(f"    Docs: {len(docs)} | JSON semesters: {json_sems}")

        print()
        print("=" * 60)
        print("REPAIR PLAN:")
        print("All above subjects were placed in Semester 3 because Gemini")
        print("incorrectly read subject codes (ITUETK3 = 3rd elective != Semester 3).")
        print()
        print("Enter the correct semester for each subject below.")
        print("Press Enter to SKIP a subject (leave in current semester).")
        print("Enter 0 to CANCEL repair.")
        print("=" * 60)
        print()

        repairs = []  # [(subject, new_sem_num), ...]

        for subj in sem3_subjects:
            answer = input(f"  Correct semester for '{subj.name[:50]}' (code={subj.code or '?'}): ").strip()
            if answer == "0":
                print("Cancelled.")
                return
            if answer == "":
                print(f"  -> Skipped (stays in Semester 3)")
                continue
            try:
                new_sem_num = int(answer)
                if not 1 <= new_sem_num <= 8:
                    raise ValueError
                repairs.append((subj, new_sem_num))
            except ValueError:
                print(f"  -> Invalid input '{answer}', skipped")

        if not repairs:
            print("No repairs to make.")
            return

        print()
        print("PREVIEW of changes:")
        for subj, new_num in repairs:
            print(f"  '{subj.name}' -> Semester {new_num}")

        confirm = input("\nApply these changes? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("Cancelled.")
            return

        # Apply repairs
        print()
        for subj, new_num in repairs:
            # Find or create target semester
            target_sem = sems.get(new_num)
            if not target_sem:
                import uuid
                target_sem = Semester(
                    id=str(uuid.uuid4()),
                    department_id=dept.id,
                    semester_number=new_num,
                    is_active=True
                )
                db.add(target_sem)
                await db.commit()
                await db.refresh(target_sem)
                sems[new_num] = target_sem
                print(f"  Created Semester {new_num} (id={target_sem.id[:8]})")

            # Move subject to new semester
            old_sem_id = subj.semester_id
            subj.semester_id = target_sem.id
            db.add(subj)

            # Update all docs linked to this subject
            docs = (await db.execute(
                select(Document).where(Document.subject_id == subj.id)
            )).scalars().all()

            for doc in docs:
                doc.semester_id = target_sem.id
                # Also fix structured_json semester
                sj = dict(doc.structured_json or {})
                sj["Semester"] = str(new_num)
                doc.structured_json = sj
                db.add(doc)

            await db.commit()
            print(f"  Moved '{subj.name}' + {len(docs)} doc(s) -> Semester {new_num}")

        print()
        print("REPAIR COMPLETE.")
        print()
        print("Verify by running: python audit_semester_mapping.py")

asyncio.run(main())
