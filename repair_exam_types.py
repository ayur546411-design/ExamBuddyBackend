import asyncio
from app.db.session import AsyncSessionLocal
from sqlalchemy import select
from app.models.document import Document
from sqlalchemy.orm import attributes

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Document).where(Document.document_type == "pyq"))
        pyqs = result.scalars().all()
        
        print(f"Auditing {len(pyqs)} PYQ database records...")
        updated_count = 0
        
        for doc in pyqs:
            title_lower = (doc.title or "").lower()
            desc_lower = (doc.description or "").lower()
            text = f"{title_lower} {desc_lower}"
            
            meta = doc.metadata_json or {}
            struct = doc.structured_json or {}
            
            current_exam_type = meta.get("exam_type")
            inferred_type = None
            
            # Check title for End Sem indications
            is_end_sem_title = any(term in text for term in ["end sem", "endsem", "end semester", "semester end", "final exam", "semester final"])
            is_ct1_title = any(term in text for term in ["ct1", "ct 1", "ct-1", "class test 1"])
            is_ct2_title = any(term in text for term in ["ct2", "ct 2", "ct-2", "class test 2"])
            
            # Determine correct classification
            if is_end_sem_title and current_exam_type in ["ct1", "ct2"]:
                inferred_type = "end_semester"
            elif (is_ct1_title or is_ct2_title) and current_exam_type == "end_semester":
                inferred_type = "ct2" if is_ct2_title else "ct1"
                
            if inferred_type:
                print(f"CORRECTING ID={doc.id} | Title='{doc.title}' | '{current_exam_type}' -> '{inferred_type}'")
                
                # Update metadata_json
                new_meta = dict(meta)
                new_meta["exam_type"] = inferred_type
                doc.metadata_json = new_meta
                
                # Update structured_json
                new_struct = dict(struct)
                new_struct["exam_type"] = inferred_type
                doc.structured_json = new_struct
                
                # SQLAlchemy JSON mutation tracking flag
                attributes.flag_modified(doc, "metadata_json")
                attributes.flag_modified(doc, "structured_json")
                
                updated_count += 1

        if updated_count > 0:
            await db.commit()
            print(f"\nSuccessfully corrected {updated_count} records in the database.")
        else:
            print("\nAudit completed. No mismatched records found.")

if __name__ == "__main__":
    asyncio.run(main())
