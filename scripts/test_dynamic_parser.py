import asyncio
import sys
import os
import io
import uuid
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal
from sqlalchemy.future import select
from app.models.school import School
from app.models.department import Department
from app.models.semester import Semester
from app.models.subject import Subject
from app.models.document import Document, DocumentTypeEnum
from fastapi import UploadFile

# Mock the module dependencies
import app.api.v1.endpoints.documents as docs_module
from starlette.datastructures import Headers

async def mock_upload_to_cloudinary(file_bytes, filename):
    return {"url": "http://mock-cloudinary.com/test.pdf", "public_id": "test_pdf", "bytes": 1024, "format": "pdf"}

async def mock_extract_text(file_bytes):
    return "This is a mock PDF text"

async def mock_gemini(pdf_text, doc_type):
    return {
        "Subjects": [
            {
                "Semester": "Semester 7",
                "Subject Name": "Advanced Machine Learning",
                "Subject Code": "CS701"
            },
            {
                "Semester": "Semester 7",
                "Subject Name": "Quantum Computing Basics",
                "Subject Code": "CS702"
            }
        ]
    }

# Inject mocks
docs_module.upload_file_to_cloudinary = mock_upload_to_cloudinary
docs_module.extract_text_from_pdf = mock_extract_text
docs_module.extract_structured_data_from_pdf_text = mock_gemini

async def test_upload():
    async with AsyncSessionLocal() as db:
        # Get random school and department
        school = (await db.execute(select(School))).scalars().first()
        dept = (await db.execute(select(Department).where(Department.school_id == school.id))).scalars().first()
        
        # Create a dummy UploadFile
        headers = Headers({'content-disposition': 'form-data; name="file"; filename="test.pdf"'})
        file_obj = UploadFile(filename="test.pdf", file=io.BytesIO(b"dummy pdf content"), headers=headers)
        
        print(f"Testing with School: {school.id}, Dept: {dept.id}")
        
        # Call the endpoint
        res = await docs_module.upload_document(
            file=file_obj,
            school_id=school.id,
            department_id=dept.id,
            subject_id=None,
            semester_id=None,
            academic_year="2026",
            document_type=DocumentTypeEnum.syllabus,
            db=db
        )
        
        print("Upload Result:", res)
        
        # Verify
        sem = (await db.execute(select(Semester).where(Semester.department_id == dept.id, Semester.semester_number == 7))).scalars().first()
        print(f"Verified Semester 7 created: {sem.id if sem else 'FAILED'}")
        
        subs = (await db.execute(select(Subject).where(Subject.semester_id == sem.id))).scalars().all()
        print(f"Verified Subjects created: {len(subs)}")
        for s in subs:
            print(f" - {s.name} ({s.code})")
            
        docs = (await db.execute(select(Document).where(Document.semester_id == sem.id))).scalars().all()
        print(f"Verified Documents created: {len(docs)}")
        for d in docs:
            print(f" - Doc ID: {d.id}, Subject ID: {d.subject_id} (Is Null? {d.subject_id is None})")

if __name__ == "__main__":
    asyncio.run(test_upload())
