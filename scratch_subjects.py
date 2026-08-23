import asyncio
from app.db.session import AsyncSessionLocal
from sqlalchemy import select
from app.models.document import Document

async def main():
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Document).where(Document.subject_id == None))
        null_docs = r.scalars().all()
        print(f"Documents with NULL subject_id remaining: {len(null_docs)}")

        r2 = await db.execute(select(Document))
        all_docs = r2.scalars().all()
        print(f"Total documents remaining: {len(all_docs)}")

asyncio.run(main())
