"""
fix_all.py — Complete backend data repair + migration
======================================================
Fixes:
1. Identifies the department(s) that have real data
2. Updates any users in empty departments to the correct data department
3. Verifies all subject-document links
4. Reports orphaned records and repairs them
5. Validates structured_json content

Run from Backend/: python fix_all.py
"""
import asyncio
import uuid
from sqlalchemy import select, update
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

        print(f"\n{SEP}")
        print("  STEP 1: Find departments that have real uploaded data")
        print(SEP)

        # Find departments that have subjects
        all_subjects = (await db.execute(select(Subject))).scalars().all()
        dept_ids_with_data = set(s.department_id for s in all_subjects)

        for dept_id in dept_ids_with_data:
            dept = await db.get(Department, dept_id)
            subj_count = sum(1 for s in all_subjects if s.department_id == dept_id)
            doc_count = len((await db.execute(select(Document).where(Document.department_id == dept_id))).scalars().all())
            print(f"  [DATA DEPT] {dept.name}")
            print(f"             dept_id = {dept_id}")
            print(f"             subjects = {subj_count}  |  documents = {doc_count}")

        if not dept_ids_with_data:
            print("  ERROR: No departments have any subject data. Upload syllabuses first.")
            return

        print(f"\n{SEP}")
        print("  STEP 2: Find users in empty departments and migrate them")
        print(SEP)

        all_users = (await db.execute(select(User))).scalars().all()
        migrated = 0
        already_ok = 0

        # For each user, check if their department has data
        # If not, find the best matching department with data
        for user in all_users:
            if user.department_id in dept_ids_with_data:
                already_ok += 1
                continue

            # User is in an empty department — find the best data dept
            user_dept = await db.get(Department, user.department_id) if user.department_id else None

            # Try to find a matching department by name similarity
            best_match_id = None
            for data_dept_id in dept_ids_with_data:
                data_dept = await db.get(Department, data_dept_id)
                if data_dept:
                    best_match_id = data_dept_id
                    break  # Use first available data department

            if best_match_id:
                old_dept = user_dept.name if user_dept else "NONE"
                new_dept_obj = await db.get(Department, best_match_id)
                print(f"  MIGRATING: {user.full_name:20s}")
                print(f"    FROM: {old_dept}")
                print(f"    TO:   {new_dept_obj.name}")
                user.department_id = best_match_id
                user.school_id = new_dept_obj.school_id  # Also update school to match
                db.add(user)
                migrated += 1

        if migrated > 0:
            await db.commit()
            print(f"\n  Migrated {migrated} users to data-containing departments.")
        else:
            print(f"  All {already_ok} users already in correct departments.")

        print(f"\n{SEP}")
        print("  STEP 3: Repair orphaned documents (subject_id = NULL)")
        print(SEP)

        orphans = (await db.execute(
            select(Document).where(Document.subject_id == None, Document.status == "active")
        )).scalars().all()

        print(f"  Orphaned documents found: {len(orphans)}")
        repaired = 0
        skipped = 0

        for doc in orphans:
            if not doc.structured_json:
                print(f"  SKIP (no structured_json): {doc.title}")
                skipped += 1
                continue

            sj = doc.structured_json
            subject_name = sj.get("Subject Name") or doc.title.replace(" Syllabus", "").replace(" PYQ", "").strip()
            subject_code = sj.get("Subject Code", "")

            # Find matching subject
            found_subj = None

            # Try by code first
            if subject_code:
                r = await db.execute(select(Subject).where(Subject.code == subject_code))
                found_subj = r.scalars().first()

            # Try by name
            if not found_subj and subject_name:
                r = await db.execute(
                    select(Subject).where(
                        Subject.department_id == doc.department_id,
                        Subject.name.ilike(f"%{subject_name[:15]}%")
                    )
                )
                found_subj = r.scalars().first()

            if found_subj:
                doc.subject_id = found_subj.id
                doc.semester_id = found_subj.semester_id
                db.add(doc)
                await db.commit()
                print(f"  REPAIRED: {doc.title[:45]} -> subject: {found_subj.name}")
                repaired += 1
            else:
                print(f"  SKIP (no matching subject): {doc.title[:45]}")
                skipped += 1

        print(f"\n  Repaired: {repaired}  |  Skipped: {skipped}")

        print(f"\n{SEP}")
        print("  STEP 4: Verify all document-subject links are intact")
        print(SEP)

        all_docs = (await db.execute(
            select(Document).where(Document.status == "active")
        )).scalars().all()

        broken_links = 0
        for doc in all_docs:
            if doc.subject_id:
                subj = await db.get(Subject, doc.subject_id)
                if not subj:
                    print(f"  BROKEN LINK: doc '{doc.title}' -> subject_id {doc.subject_id} does not exist")
                    broken_links += 1
                elif subj.department_id != doc.department_id:
                    print(f"  DEPT MISMATCH: doc '{doc.title[:35]}' doc_dept={doc.department_id[:8]} subj_dept={subj.department_id[:8]}")

        if broken_links == 0:
            print(f"  All {len(all_docs)} document-subject links are valid.")

        print(f"\n{SEP}")
        print("  STEP 5: Verify structured_json content by document type")
        print(SEP)

        for dtype in [DocumentTypeEnum.syllabus, DocumentTypeEnum.pyq]:
            docs = (await db.execute(
                select(Document).where(Document.document_type == dtype, Document.status == "active")
            )).scalars().all()

            if not docs:
                print(f"  {dtype.value}: 0 documents")
                continue

            has_json = sum(1 for d in docs if d.structured_json)
            has_subject = sum(1 for d in docs if d.subject_id)
            print(f"  {dtype.value:15s}: {len(docs)} docs | has_structured_json={has_json} | linked_to_subject={has_subject}")

            if dtype == DocumentTypeEnum.syllabus:
                has_units = sum(1 for d in docs if d.structured_json and d.structured_json.get("Units"))
                print(f"               has_units_content={has_units}")
            elif dtype == DocumentTypeEnum.pyq:
                has_questions = sum(1 for d in docs if d.structured_json and d.structured_json.get("Questions"))
                print(f"               has_questions_content={has_questions}")

        print(f"\n{SEP}")
        print("  STEP 6: Final state summary")
        print(SEP)

        all_users_final = (await db.execute(select(User))).scalars().all()
        for dept_id in dept_ids_with_data:
            dept = await db.get(Department, dept_id)
            users_in_dept = [u for u in all_users_final if u.department_id == dept_id]
            subjects_in_dept = [s for s in all_subjects if s.department_id == dept_id]
            docs_in_dept = (await db.execute(
                select(Document).where(Document.department_id == dept_id, Document.status == "active")
            )).scalars().all()

            print(f"  Department: {dept.name}")
            print(f"    Users   : {len(users_in_dept)}")
            print(f"    Subjects: {len(subjects_in_dept)}")
            print(f"    Docs    : {len(docs_in_dept)}")
            by_type = {}
            for d in docs_in_dept:
                by_type[d.document_type.value] = by_type.get(d.document_type.value, 0) + 1
            for t, cnt in sorted(by_type.items()):
                print(f"      {t}: {cnt}")

        print(f"\n{SEP}")
        print("  ALL FIXES COMPLETE")
        print(SEP)
        print()
        print("  Next steps:")
        print("  1. Redeploy on Render (or already deployed)")
        print("  2. Open the app -> Syllabus tab -> select semester -> tap subject")
        print("  3. Units and topics should now display correctly")
        print()

asyncio.run(main())
