import asyncio
from app.db.session import AsyncSessionLocal
from sqlalchemy import select
from app.models.document import Document

async def main():
    async with AsyncSessionLocal() as db:
        docs = (await db.execute(select(Document))).scalars().all()
        print(f"Checking all {len(docs)} documents for classification issues...")
        
        for d in docs:
            title_lower = (d.title or "").lower()
            meta = d.metadata_json or {}
            struct = d.structured_json or {}
            et_meta = meta.get("exam_type")
            et_struct = struct.get("exam_type")
            
            # If title indicates End Sem but type is ct
            if ("end" in title_lower or "sem" in title_lower) and (et_meta in ["ct1", "ct2"] or et_struct in ["ct1", "ct2"]):
                print(f"POTENTIAL MISMATCH: ID={d.id} | Title='{d.title}' | Type={d.document_type} | MetaExamType={et_meta} | StructExamType={et_struct}")

if __name__ == "__main__":
    asyncio.run(main())
