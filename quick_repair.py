"""quick_repair.py — Direct repair using known IDs from audit"""
import asyncio
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.document import Document, DocumentTypeEnum
from app.models.subject import Subject
from app.models.semester import Semester

# From audit output:
# Semester 3 id=bf59ac41  — has incorrectly placed subjects
# Semester 5 id=df9dd92e  — correct semester for Semester 5 subjects

# Subjects wrongly in Semester 3 that should be in Semester 5 or 7:
# Based on GGU IT curriculum:
#   ITUETK3 = Soft Computing         -> Sem 7 elective (but was in uploaded "Sem 5" PDF)
#   ITUETK4 = Wireless Sensor Network -> Sem 7 elective
#   ITUETK5 = Human Computer Interface -> Sem 7 elective
#   ITUETK6 = Network Security        -> Sem 7 elective
#   ITUELT1 = Machine Learning Lab    -> Sem 5
#   ITUETT2 = DBMS                    -> Sem 3 (correct — from the earlier upload)
#   ITUETT3 = Formal Language         -> Sem 3 (correct)
#   ITUELT2 = DBMS Lab (linked to DBMS subject) -> Sem 3 (correct)
#   AUTO-35c6 = Cryptography          -> Sem 3 (correct — was in wrong section)
#
# The user said: "uploaded ONLY a Semester 5 PDF" -> those Elective subjects
# with ITUETK codes are Semester 5 electives in GGU scheme, not 7.
# So: ITUETK3/4/5/6 should be Semester 5, and ITUELT1 should be Semester 5.

async def main():
    async with AsyncSessionLocal() as db:
        # Show all subjects in sem 3 with their codes
        sems_result = (await db.execute(select(Semester))).scalars().all()
        print("All semesters in DB:")
        for s in sems_result:
            print(f"  id={s.id[:8]} num={s.semester_number} dept={s.department_id[:8]}")
        
        sem3 = next((s for s in sems_result if s.semester_number == 3), None)
        sem5 = next((s for s in sems_result if s.semester_number == 5), None)
        
        if not sem3 or not sem5:
            print(f"sem3={sem3}, sem5={sem5}")
            return
        
        print(f"\nSem3 id={sem3.id[:8]}, Sem5 id={sem5.id[:8]}")
        print(f"Sem3 dept={sem3.department_id[:8]}, Sem5 dept={sem5.department_id[:8]}")
        
        # Subjects in sem3 that need to move to sem5
        # (elective codes ITUETK3-6 and ITUELT1 = Machine Learning Lab)
        subjects_to_move_codes = ['ITUETK3', 'ITUETK4', 'ITUETK5', 'ITUETK6', 'ITUELT1']
        
        sem3_subjects = (await db.execute(
            select(Subject).where(Subject.semester_id == sem3.id)
        )).scalars().all()
        
        print(f"\nSubjects in Semester 3: {len(sem3_subjects)}")
        for s in sem3_subjects:
            tag = "  <-- WILL MOVE to Sem5" if s.code in subjects_to_move_codes else "  (stays in Sem3)"
            print(f"  [{s.code}] {s.name[:50]}{tag}")
        
        print()
        confirm = input("Move ITUETK3/4/5/6 and ITUELT1 from Semester 3 -> Semester 5? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("Cancelled.")
            return
        
        moved = 0
        for subj in sem3_subjects:
            if subj.code not in subjects_to_move_codes:
                continue
            
            old_sem = subj.semester_id
            subj.semester_id = sem5.id
            db.add(subj)
            
            # Move all docs linked to this subject
            docs = (await db.execute(
                select(Document).where(Document.subject_id == subj.id)
            )).scalars().all()
            
            for doc in docs:
                doc.semester_id = sem5.id
                # Fix the semester in structured_json
                sj = dict(doc.structured_json or {})
                sj["Semester"] = "5"
                doc.structured_json = sj
                db.add(doc)
            
            await db.commit()
            print(f"  Moved '{subj.name}' ({subj.code}) + {len(docs)} doc(s) -> Semester 5")
            moved += 1
        
        print(f"\nRepair complete. Moved {moved} subjects to Semester 5.")
        print("Running post-repair verification...")
        
        # Verify
        sem3_after = (await db.execute(
            select(Subject).where(Subject.semester_id == sem3.id)
        )).scalars().all()
        sem5_after = (await db.execute(
            select(Subject).where(Subject.semester_id == sem5.id)
        )).scalars().all()
        
        print(f"\nSemester 3 subjects after repair: {len(sem3_after)}")
        for s in sem3_after:
            print(f"  [{s.code}] {s.name[:50]}")
        
        print(f"\nSemester 5 subjects after repair: {len(sem5_after)}")
        for s in sem5_after:
            print(f"  [{s.code}] {s.name[:50]}")

asyncio.run(main())
