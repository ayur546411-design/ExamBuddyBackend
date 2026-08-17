import asyncio
from sqlalchemy import inspect
from app.db.session import engine

async def check_constraints():
    async with engine.begin() as conn:
        inspector = inspect(conn.sync_engine)
        
        print('Users table constraints:')
        constraints = inspector.get_unique_constraints('users')
        print(f'  Unique constraints: {constraints}')
        
        print('\nUsers table indexes:')
        indexes = inspector.get_indexes('users')
        for idx in indexes:
            name = idx.get('name')
            cols = idx.get('column_names')
            unique = idx.get('unique')
            print(f'  {name}: columns={cols}, unique={unique}')
        
        print('\nUsers table columns:')
        columns = inspector.get_columns('users')
        for col in columns:
            col_name = col.get('name')
            col_type = col.get('type')
            nullable = col.get('nullable')
            print(f'  {col_name}: type={col_type}, nullable={nullable}')

asyncio.run(check_constraints())
