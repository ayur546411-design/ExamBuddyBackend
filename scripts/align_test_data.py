import asyncio
import sys
import os

# Add the Backend directory to path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal
from sqlalchemy.future import select
from app.models.semester import Semester
from app.models.subject import Subject
from app.models.document import Document
from app.models.department import Department
from app.models.user import User

async def align_data():
    async with AsyncSessionLocal() as db:
        # Get the latest user (the one testing)
        user = (await db.execute(select(User).order_by(User.created_at.desc()).limit(1))).scalars().first()
        if not user or not user.department_id:
            print("No valid user with department found")
            return

        target_dept_id = user.department_id
        target_school_id = user.school_id
        
        print(f"Target Dept ID: {target_dept_id}")
        
        # Move all semesters to this department
        sems = (await db.execute(select(Semester))).scalars().all()
        for sem in sems:
            sem.department_id = target_dept_id
            db.add(sem)
            print(f"Aligned Semester {sem.semester_number} to target dept")
            
        # Move all subjects to this department
        subs = (await db.execute(select(Subject))).scalars().all()
        for sub in subs:
            sub.department_id = target_dept_id
            sub.school_id = target_school_id
            db.add(sub)
            print(f"Aligned Subject {sub.name} to target dept")
            
        # Move all documents to this department
        docs = (await db.execute(select(Document))).scalars().all()
        for doc in docs:
            doc.department_id = target_dept_id
            doc.school_id = target_school_id
            db.add(doc)
            print(f"Aligned Document {doc.title} to target dept")
            
        await db.commit()
        print("Successfully aligned all test data to user's department!")

if __name__ == "__main__":
    asyncio.run(align_data())
