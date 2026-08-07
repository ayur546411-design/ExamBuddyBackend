"""
query_tables_async.py — Run async queries to see what tables and data exist
"""
import asyncio
from dotenv import load_dotenv
load_dotenv()
from app.db.session import AsyncSessionLocal
from sqlalchemy import text

async def main():
    async with AsyncSessionLocal() as db:
        # Search path
        sp = (await db.execute(text("SHOW search_path"))).fetchone()
        print("Search path:", sp)
        
        # User tables
        res = (await db.execute(text("""
            SELECT schemaname, tablename 
            FROM pg_tables 
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        """))).fetchall()
        print("\nTables found:")
        for row in res:
            print(f"  {row[0]}.{row[1]}")
            
        # Count public.semesters if it exists
        try:
            count = (await db.execute(text("SELECT COUNT(*) FROM public.semesters"))).scalar()
            print("\nRow count public.semesters:", count)
        except Exception as e:
            print("\nError counting public.semesters:", e)

asyncio.run(main())
