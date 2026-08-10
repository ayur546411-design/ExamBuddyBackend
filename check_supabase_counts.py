import asyncio
from app.core.config import settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    engine = create_async_engine(settings.DATABASE_URL, future=True)
    try:
        async with engine.begin() as conn:
            for table in ['documents','subjects','semesters','schools','departments']:
                res = await conn.execute(text(f'SELECT COUNT(*) FROM {table}'))
                print(table, res.scalar_one())
    finally:
        await engine.dispose()

asyncio.run(main())
