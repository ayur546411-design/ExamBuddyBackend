import asyncio
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from app.core.config import settings
from app.models.school import School
from app.models.department import Department

# The raw data provided by the user
data = {
    "School of Studies of Engineering and Technology": [
        "Department of Chemical Engineering",
        "Department of Civil Engineering",
        "Department of Computer Science & Engineering",
        "Department of Electronics and Communication Engineering",
        "Electronics & Communication Engineering Branch",
        "Electrical Engineering Branch",
        "Department of Industrial & Production Engineering",
        "Department of Information Technology",
        "B.Tech. Information Technology",
        "B.Tech. Artificial Intelligence & Data Science",
        "B.Tech. VFX & Animation",
        "Department of Mechanical Engineering"
    ],
    "School of Studies of Arts": [
        "Department of English and Foreign Language",
        "Department of Hindi",
        "Department of Journalism & Mass Communication",
        "Department of Library & Information Science"
    ],
    "School of Studies of Life Science": [
        "Department of Anthropology & Tribal Development",
        "Department of Botany",
        "Department of Zoology"
    ],
    "School of Studies of Social Science": [
        "Department of Economics",
        "Department of History",
        "Department of Political Science & Public Administration",
        "Department of Social Work"
    ],
    "School of Studies of Mathematical and Computational Science": [
        "Department of Computer Science & Information Technology",
        "Department of Mathematics"
    ],
    "School of Studies of Natural Resources": [
        "Department of Forestry, Wildlife & Environmental Science",
        "Department of Pharmacy"
    ],
    "School of Studies of Physical Science": [
        "Department of Chemistry",
        "Department of Pure & Applied Physics"
    ],
    "School of Studies of Commerce and Management": [
        "Department of Commerce",
        "Department of Management Studies"
    ],
    "School of Studies of Law": [
        "Department of Law"
    ],
    "School of Studies of Education": [
        "Department of Education",
        "Department of Physical Education, Yoga and Sports Science"
    ],
    "School of Studies of Interdisciplinary Education and Research": [
        "Department of Biotechnology",
        "Department of Forensic Science",
        "Department of Rural Technology"
    ]
}

async def seed_data():
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session() as session:
        # Clear existing data for a clean slate
        await session.execute(text("TRUNCATE TABLE schools CASCADE;"))
        
        for school_name, departments in data.items():
            school_id = str(uuid.uuid4())
            # Generate a code from initials
            school_code = "".join([word[0] for word in school_name.replace("&", "").split() if word.lower() not in ("of", "and", "studies")]).upper()
            
            school = School(
                id=school_id,
                name=school_name,
                code=school_code,
                is_active=True
            )
            session.add(school)
            
            for index, dept_name in enumerate(departments):
                dept_id = str(uuid.uuid4())
                dept_code = f"{school_code}-D{index+1}"
                
                dept = Department(
                    id=dept_id,
                    school_id=school_id,
                    name=dept_name,
                    code=dept_code,
                    is_active=True
                )
                session.add(dept)
                
        await session.commit()
        print("Successfully seeded all Schools and Departments into Supabase!")

if __name__ == "__main__":
    asyncio.run(seed_data())
