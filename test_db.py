import asyncio
from app.db.session import AsyncSessionLocal
from sqlalchemy import select
from app.models.document import Document

async def main():
    async with AsyncSessionLocal() as db:
        docs = (await db.execute(select(Document).where(Document.subject_id == None))).scalars().all()
        print(f"Found {len(docs)} documents with NULL subject_id")
        for d in docs[:5]:
            print(f"ID: {d.id}, Title: {d.title}, Type: {d.document_type}")
            print(f"Structured JSON: {str(d.structured_json)[:500]}")
            print("-" * 50)

if __name__ == "__main__":
    asyncio.run(main())
