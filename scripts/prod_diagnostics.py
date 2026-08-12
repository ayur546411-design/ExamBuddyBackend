import asyncio
import sys
import os
import requests
from jose import jwt
from datetime import datetime, timedelta

# Add the Backend directory to path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal
from sqlalchemy.future import select
from app.models.user import User

API_URL = 'https://projectb-p0tv.onrender.com/api/v1'
# If local testing is needed: API_URL = 'http://localhost:8000/api/v1'

# We use the same secret key from .env to sign the token 
# assuming Render uses the same secret key.
from app.core.config import settings

async def run_diagnostics():
    print(f"--- Starting Production API Diagnostics against {API_URL} ---")
    
    # 1. Get a valid user from the database
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).order_by(User.created_at.desc()).limit(1))).scalars().first()
        if not user:
            print("ERROR: No user found in database.")
            return
            
        user_id = user.id
        dept_id = user.department_id
        school_id = user.school_id
        print(f"User identified: {user.full_name} (Dept: {dept_id})")
        
    # 2. Generate a valid JWT token exactly like the backend would
    expire = datetime.utcnow() + timedelta(minutes=1440)
    to_encode = {'exp': expire, 'sub': str(user_id)}
    token = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    headers = {'Authorization': f'Bearer {token}'}
    print(f"Generated JWT token successfully.")
    
    # 3. Test /semesters API
    print(f"\n[Test 1] Fetching semesters...")
    res = requests.get(f'{API_URL}/semesters/', headers=headers)
    print(f"Status Code: {res.status_code}")
    if res.status_code != 200:
        print(f"ERROR fetching semesters: {res.text}")
        return
        
    sems = res.json()
    print(f"Result: Found {len(sems)} semesters.")
    if not sems:
        print("STOPPING: No semesters returned. The chain is broken here.")
        return
        
    for s in sems:
        print(f"  - Semester {s.get('semester_number')} (ID: {s.get('id')})")
        
    sem_id = sems[0].get('id')
    
    # 4. Test /subjects API
    print(f"\n[Test 2] Fetching subjects for semester {sem_id}...")
    res = requests.get(f'{API_URL}/subjects/?semester_id={sem_id}', headers=headers)
    print(f"Status Code: {res.status_code}")
    if res.status_code != 200:
        print(f"ERROR fetching subjects: {res.text}")
        return
        
    subs = res.json()
    print(f"Result: Found {len(subs)} subjects.")
    if not subs:
        print("STOPPING: No subjects returned. The chain is broken here.")
        return
        
    for s in subs:
        print(f"  - Subject: {s.get('name')} (ID: {s.get('id')})")
        
    sub_id = subs[0].get('id')
    
    # 5. Test /documents API (Syllabus)
    print(f"\n[Test 3] Fetching Syllabus for subject {sub_id}...")
    res = requests.get(f'{API_URL}/documents/?subject_id={sub_id}&document_type=syllabus', headers=headers)
    print(f"Status Code: {res.status_code}")
    if res.status_code != 200:
        print(f"ERROR fetching syllabus: {res.text}")
        return
        
    docs = res.json()
    print(f"Result: Found {len(docs)} syllabus documents.")
    for d in docs:
        print(f"  - Document: {d.get('title')}")
        
    # 6. Test /documents API (PYQ)
    print(f"\n[Test 4] Fetching PYQs for subject {sub_id}...")
    res = requests.get(f'{API_URL}/documents/?subject_id={sub_id}&document_type=pyq', headers=headers)
    print(f"Status Code: {res.status_code}")
    if res.status_code != 200:
        print(f"ERROR fetching pyqs: {res.text}")
        return
        
    pyqs = res.json()
    print(f"Result: Found {len(pyqs)} PYQ documents.")
    for p in pyqs:
        print(f"  - Document: {p.get('title')}")
        
    print("\n--- Diagnostics Complete ---")

if __name__ == '__main__':
    asyncio.run(run_diagnostics())
