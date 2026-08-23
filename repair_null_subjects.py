"""
repair_null_subjects.py
=======================
Safely removes the 8 orphaned syllabus documents that have subject_id = NULL
because they were scanned image PDFs that could not be text-extracted.

These documents have:
  - structured_json = {"error": "Gemini extraction returned no structured data..."}
  - extracted_text  = all pages "(empty)" — scanned image PDF, no text
  - subject_id      = NULL — no subject was created for them
  - Their associated semesters have 0 subjects

These records are genuinely unusable in the mobile app and cannot be repaired
without a proper text-selectable PDF being re-uploaded via the admin panel.

This script will:
  1. DRY-RUN mode (default): Print what would be deleted without touching DB.
  2. LIVE mode: Delete only documents that match ALL safety criteria:
       a. subject_id IS NULL
       b. document_type = 'syllabus'
       c. structured_json contains ONLY {"error": "..."} — no real subject data
       d. extracted_text is all-empty pages (no real text was extracted)

Usage:
  python repair_null_subjects.py          # DRY RUN (safe, read-only)
  python repair_null_subjects.py --live   # LIVE deletion
"""
import asyncio
import sys
from app.db.session import AsyncSessionLocal
from sqlalchemy import select
from app.models.document import Document

DRY_RUN = "--live" not in sys.argv

async def is_genuinely_broken(doc: Document) -> bool:
    """Return True only if the document is a failed scanned-image upload with no useful data."""
    # Must have null subject_id
    if doc.subject_id is not None:
        return False
    
    # Must be a syllabus
    if str(doc.document_type) not in ("syllabus", "DocumentTypeEnum.syllabus"):
        return False
    
    # structured_json must only contain an error key (not real subject data)
    sj = doc.structured_json or {}
    has_real_subject_data = bool(
        sj.get("Subject Name") or
        sj.get("Subject Code") or
        sj.get("Units") or
        sj.get("Subjects")
    )
    if has_real_subject_data:
        return False
    
    has_error_key = "error" in sj
    
    # extracted_text must be all-empty pages
    et = doc.extracted_text or ""
    real_text_lines = [
        line for line in et.splitlines()
        if line.strip() and not line.startswith("--- PAGE") and "(empty)" not in line
    ]
    no_real_text = len(real_text_lines) == 0
    
    return has_error_key and no_real_text


async def main():
    async with AsyncSessionLocal() as db:
        doc_result = await db.execute(
            select(Document).where(Document.subject_id == None)
        )
        null_docs = doc_result.scalars().all()
        
        print(f"[Repair] Found {len(null_docs)} documents with subject_id = NULL")
        print(f"[Repair] Mode: {'DRY RUN (pass --live to actually delete)' if DRY_RUN else '*** LIVE DELETION ***'}")
        print()
        
        to_delete = []
        skipped = []
        
        for doc in null_docs:
            broken = await is_genuinely_broken(doc)
            if broken:
                to_delete.append(doc)
                print(f"  [WILL DELETE] ID={doc.id}")
                print(f"    Title:       {doc.title}")
                print(f"    Type:        {doc.document_type}")
                print(f"    Semester ID: {doc.semester_id}")
                print(f"    Dept ID:     {doc.department_id}")
                print(f"    Reason:      scanned PDF, Gemini extraction failed, no subjects created")
                print()
            else:
                skipped.append(doc)
                print(f"  [SAFE - SKIPPING] ID={doc.id} | Title={doc.title} | Has real data, not deleting.")
                print()
        
        print(f"\n[Summary] Would delete: {len(to_delete)} | Would skip (safe): {len(skipped)}")
        
        if not DRY_RUN and to_delete:
            print(f"\n[LIVE] Deleting {len(to_delete)} broken syllabus documents...")
            for doc in to_delete:
                await db.delete(doc)
            await db.commit()
            print(f"[LIVE] Done. Deleted {len(to_delete)} documents.")
            print("[LIVE] Note: The associated semesters (EE sem 3,4,5,6,7 and IPE sem 5,6,7)")
            print("       now have 0 subjects. Please re-upload these syllabi using text-based PDFs")
            print("       via the admin panel, or add subjects manually.")
        elif DRY_RUN:
            print("\n[DRY RUN] No changes made. Run with --live to apply deletions.")

if __name__ == "__main__":
    asyncio.run(main())
