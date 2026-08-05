import asyncio
from app.db.session import AsyncSessionLocal
from sqlalchemy import select
from app.models.document import Document

async def main():
    async with AsyncSessionLocal() as db:
        docs = (await db.execute(select(Document))).scalars().all()
        print(f"Total documents: {len(docs)}")

if __name__ == "__main__":
    asyncio.run(main())
