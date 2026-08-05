import asyncio
import os
import io
import re
import uuid
import json
import logging
import httpx
import cloudinary
import cloudinary.api
from dotenv import load_dotenv

from app.db.session import AsyncSessionLocal
from sqlalchemy import select, delete
from app.models.document import Document, DocumentTypeEnum
from app.models.semester import Semester
from app.models.subject import Subject
from app.models.department import Department
from app.models.school import School
from app.services.gemini_service import extract_structured_data_from_pdf_text
from app.services.pdf_service import extract_text_from_pdf
import google.generativeai as genai

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

cloudinary.config(
  cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME'),
  api_key = os.getenv('CLOUDINARY_API_KEY'),
  api_secret = os.getenv('CLOUDINARY_API_SECRET'),
  secure = True
)
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

def parse_semester(sem_str):
    if not sem_str or str(sem_str).strip().lower() == "null":
        return None
    sem_str = str(sem_str).upper()
    
    digit_match = re.search(r'\d+', sem_str)
    if digit_match:
        return int(digit_match.group())
        
    roman_map = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10}
    roman_match = re.search(r'\b(I|II|III|IV|V|VI|VII|VIII|IX|X)\b', sem_str)
    if roman_match:
        return roman_map.get(roman_match.group())
    return None

async def download_pdf(url):
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        if response.status_code == 200:
            return response.content
        return None

async def identify_department(pdf_text, db):
    # Just use the first 5000 chars to identify department
    prompt = f"""Based on the following syllabus text, identify the Department name. Return only the department name as a raw string.
    Example output: Information Technology
    Example output: Civil Engineering
    Text: {pdf_text[:5000]}
    """
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        dept_name = response.text.strip()
        
        # Look it up in DB
        # E.g. "Information Technology" -> "%Information Technology%"
        search_term = dept_name.replace("Department of", "").strip()
        dept_query = await db.execute(select(Department).where(Department.name.ilike(f"%{search_term[:8]}%")))
        dept = dept_query.scalars().first()
        if dept:
            return dept.id, dept.school_id
            
        # fallback
        dept_query = await db.execute(select(Department))
        dept = dept_query.scalars().first()
        return dept.id, dept.school_id
    except Exception as e:
        logger.error(f"Failed to identify dept: {e}")
        # Return first department as fallback
        dept_query = await db.execute(select(Department))
        dept = dept_query.scalars().first()
        return dept.id, dept.school_id

async def main():
    async with AsyncSessionLocal() as db:
        logger.info("Fetching all PDFs from Cloudinary...")
        res = cloudinary.api.resources(resource_type='raw', max_results=100)
        pdf_resources = [r for r in res.get('resources', []) if r['public_id'].endswith('.pdf')]
        
        # Filter out dummy/known non-syllabus files based on names
        valid_pdfs = [r for r in pdf_resources if "dummy" not in r['public_id'].lower() and "holiday" not in r['public_id'].lower() and "drone" not in r['public_id'].lower() and "ps-1" not in r['public_id'].lower()]
        
        logger.info(f"Found {len(valid_pdfs)} syllabus PDFs to process.")
        
        # Clean up any partial documents
        await db.execute(delete(Document).where(Document.document_type == 'syllabus'))
        await db.commit()
        
        total_subjects = 0
        
        for r in valid_pdfs:
            url = r.get('secure_url') or r.get('url')
            public_id = r['public_id']
            size = r['bytes']
            title = public_id.split('/')[-1].replace('.pdf', '')
            
            # Generate a signed URL to fix 401 Unauthorized
            signed_url, _ = cloudinary.utils.cloudinary_url(
                public_id, 
                resource_type='raw', 
                sign_url=True
            )
            
            logger.info(f"\nDownloading and processing: {title}")
            pdf_bytes = await download_pdf(signed_url)
            if not pdf_bytes:
                # Try the secure_url as a fallback
                fallback_url = r.get('secure_url')
                if fallback_url:
                    logger.info("Trying fallback secure_url...")
                    pdf_bytes = await download_pdf(fallback_url)
                    
            if not pdf_bytes:
                logger.error("Failed to download PDF using both signed and secure URLs.")
                continue
                
            extracted_text = await extract_text_from_pdf(pdf_bytes)
            if not extracted_text:
                continue
                
            department_id, school_id = await identify_department(extracted_text, db)
            
            logger.info(f"Extracted {len(extracted_text)} chars. Starting chunked AI extraction...")
            structured_data = await extract_structured_data_from_pdf_text(extracted_text, DocumentTypeEnum.syllabus)
            
            entities = structured_data.get("Subjects", [])
            logger.info(f"AI extracted {len(entities)} subjects.")
            
            for entity in entities:
                try:
                    sem_num = parse_semester(entity.get("Semester")) or 1
                        
                    sem_query = await db.execute(select(Semester).where(Semester.department_id == department_id, Semester.semester_number == sem_num))
                    found_sem = sem_query.scalars().first()
                    
                    if found_sem:
                        entity_semester_id = found_sem.id
                    else:
                        new_sem = Semester(id=str(uuid.uuid4()), department_id=department_id, semester_number=sem_num, is_active=True)
                        db.add(new_sem)
                        await db.commit()
                        await db.refresh(new_sem)
                        entity_semester_id = new_sem.id
                        
                    subject_name = entity.get("Subject Name", f"Unknown Subject {str(uuid.uuid4())[:4]}")
                    subject_code = entity.get("Subject Code", "")
                    
                    found_subj = None
                    if subject_code and subject_code.strip() != "" and subject_code.strip().lower() != "null":
                        code_query = await db.execute(select(Subject).where(Subject.code == subject_code))
                        found_subj = code_query.scalars().first()
                        
                    if not found_subj:
                        subj_query = await db.execute(select(Subject).where(Subject.semester_id == entity_semester_id, Subject.name.ilike(f"%{subject_name}%")))
                        found_subj = subj_query.scalars().first()
                        
                    if found_subj:
                        entity_subject_id = found_subj.id
                        if found_subj.semester_id != entity_semester_id:
                            entity_semester_id = found_subj.semester_id
                    else:
                        new_subj = Subject(
                            id=str(uuid.uuid4()), school_id=school_id, department_id=department_id,
                            semester_id=entity_semester_id, name=subject_name,
                            code=subject_code if (subject_code and subject_code.strip().lower() != "null") else f"AUTO-{str(uuid.uuid4())[:4]}",
                            credits=entity.get("Credits", 0) or 0
                        )
                        db.add(new_subj)
                        await db.commit()
                        await db.refresh(new_subj)
                        entity_subject_id = new_subj.id
                        
                    new_doc = Document(
                        document_type=DocumentTypeEnum.syllabus, cloudinary_url=url,
                        cloudinary_public_id=public_id, file_size=size, file_type="application/pdf",
                        title=f"{subject_name} Syllabus", description=entity.get("Summary", ""),
                        academic_year="2025-2026", keywords=str(entity.get("Keywords", [])),
                        school_id=school_id, department_id=department_id,
                        semester_id=entity_semester_id, subject_id=entity_subject_id,
                        structured_json=entity, extracted_text=extracted_text
                    )
                    db.add(new_doc)
                    await db.commit()
                    total_subjects += 1
                except Exception as e:
                    logger.error(f"Error saving {entity.get('Subject Name')}: {e}")
                    
        logger.info(f"\nSUCCESS! Fully recovered and rebuilt {total_subjects} complete subjects across all departments!")

if __name__ == "__main__":
    asyncio.run(main())
