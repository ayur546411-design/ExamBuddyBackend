#!/usr/bin/env python
"""Test the onboard endpoint directly"""
import asyncio
import httpx
from app.db.session import AsyncSessionLocal
from app.models.school import School
from app.models.department import Department
from sqlalchemy.future import select

BASE_URL = "https://projectb-p0tv.onrender.com/api/v1"

async def test_onboard():
    # Get a real school and department from DB
    async with AsyncSessionLocal() as session:
        # Get first active school
        result = await session.execute(select(School).filter(School.is_active == True).limit(1))
        school = result.scalars().first()
        
        if not school:
            print("No active schools found")
            return
        
        # Get first active department for that school
        result = await session.execute(
            select(Department).filter(
                Department.school_id == school.id,
                Department.is_active == True
            ).limit(1)
        )
        department = result.scalars().first()
        
        if not department:
            print("No active departments found")
            return
        
        print(f"Testing with:")
        print(f"  School: {school.name} ({school.id})")
        print(f"  Department: {department.name} ({department.id})")
        print()
        
        # Test onboard endpoint
        async with httpx.AsyncClient() as client:
            payload = {
                "full_name": "Test User 12345",
                "school_id": school.id,
                "department_id": department.id
            }
            
            print(f"POST {BASE_URL}/auth/onboard")
            print(f"Payload: {payload}")
            print()
            
            try:
                response = await client.post(
                    f"{BASE_URL}/auth/onboard",
                    json=payload,
                    timeout=30
                )
                
                print(f"Status: {response.status_code}")
                print(f"Response: {response.json()}")
                
            except Exception as e:
                print(f"Error: {e}")

asyncio.run(test_onboard())
