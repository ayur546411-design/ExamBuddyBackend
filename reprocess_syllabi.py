import asyncio
import re
import uuid
import json
import logging

from app.db.session import AsyncSessionLocal
from sqlalchemy import select, delete
from app.models.document import Document, DocumentTypeEnum
from app.models.semester import Semester
from app.models.subject import Subject
from app.services.gemini_service import extract_structured_data_from_pdf_text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

async def main():
    async with AsyncSessionLocal() as db:
        logger.info("Fetching unique syllabus PDFs...")
        # Get one representative document for each unique PDF url
        docs = (await db.execute(select(Document).where(Document.document_type == 'syllabus'))).scalars().all()
        
        unique_pdfs = {}
        for d in docs:
            if d.cloudinary_url not in unique_pdfs:
                unique_pdfs[d.cloudinary_url] = {
                    "cloudinary_public_id": d.cloudinary_public_id,
                    "file_size": d.file_size,
                    "file_type": d.file_type,
                    "school_id": d.school_id,
                    "department_id": d.department_id,
                    "academic_year": d.academic_year,
                    "extracted_text": d.extracted_text,
                    "original_title": d.title
                }
                
        logger.info(f"Found {len(unique_pdfs)} unique PDFs to reprocess.")
        
        # Delete existing syllabus documents
        logger.info("Deleting old incomplete syllabus documents...")
        await db.execute(delete(Document).where(Document.document_type == 'syllabus'))
        await db.commit()
        
        total_subjects_created = 0
        
        for url, pdf_data in unique_pdfs.items():
            logger.info(f"\nReprocessing PDF: {pdf_data['original_title']} (Length: {len(pdf_data['extracted_text'] or '')})")
            if not pdf_data["extracted_text"]:
                logger.warning("No extracted text found for this PDF, skipping.")
                continue
                
            structured_data = await extract_structured_data_from_pdf_text(pdf_data["extracted_text"], DocumentTypeEnum.syllabus)
            
            entities = structured_data.get("Subjects", [])
            logger.info(f"Extracted {len(entities)} unique subjects from this PDF.")
            
            for entity in entities:
                try:
                    # 1. Semester
                    extracted_semester = entity.get("Semester")
                    sem_num = parse_semester(extracted_semester)
                    if not sem_num:
                        sem_num = 1
                        
                    sem_query = await db.execute(
                        select(Semester).where(
                            Semester.department_id == pdf_data["department_id"],
                            Semester.semester_number == sem_num
                        )
                    )
                    found_sem = sem_query.scalars().first()
                    
                    if found_sem:
                        entity_semester_id = found_sem.id
                    else:
                        new_sem = Semester(
                            id=str(uuid.uuid4()),
                            department_id=pdf_data["department_id"],
                            semester_number=sem_num,
                            is_active=True
                        )
                        db.add(new_sem)
                        await db.commit()
                        await db.refresh(new_sem)
                        entity_semester_id = new_sem.id
                        
                    # 2. Subject
                    subject_name = entity.get("Subject Name")
                    subject_code = entity.get("Subject Code", "")
                    
                    if not subject_name:
                        subject_name = f"Unknown Subject {str(uuid.uuid4())[:4]}"
                        
                    found_subj = None
                    if subject_code and subject_code.strip() != "" and subject_code.strip().lower() != "null":
                        code_query = await db.execute(select(Subject).where(Subject.code == subject_code))
                        found_subj = code_query.scalars().first()
                        
                    if not found_subj:
                        subj_query = await db.execute(
                            select(Subject).where(
                                Subject.semester_id == entity_semester_id,
                                Subject.name.ilike(f"%{subject_name}%")
                            )
                        )
                        found_subj = subj_query.scalars().first()
                        
                    if found_subj:
                        entity_subject_id = found_subj.id
                        if found_subj.semester_id != entity_semester_id:
                            entity_semester_id = found_subj.semester_id
                    else:
                        new_subj = Subject(
                            id=str(uuid.uuid4()),
                            school_id=pdf_data["school_id"],
                            department_id=pdf_data["department_id"],
                            semester_id=entity_semester_id,
                            name=subject_name,
                            code=subject_code if (subject_code and subject_code.strip().lower() != "null") else f"AUTO-{str(uuid.uuid4())[:4]}",
                            credits=entity.get("Credits", 0) or 0
                        )
                        db.add(new_subj)
                        await db.commit()
                        await db.refresh(new_subj)
                        entity_subject_id = new_subj.id
                        
                    # 3. Document
                    title = f"{subject_name} Syllabus"
                    description = entity.get("Summary", "") or ""
                    keywords_list = entity.get("Keywords", [])
                    keywords = ", ".join(keywords_list) if isinstance(keywords_list, list) else str(keywords_list or "")
                    
                    new_doc = Document(
                        document_type=DocumentTypeEnum.syllabus,
                        cloudinary_url=url,
                        cloudinary_public_id=pdf_data["cloudinary_public_id"],
                        file_size=pdf_data["file_size"],
                        file_type=pdf_data["file_type"],
                        title=title,
                        description=description,
                        academic_year=pdf_data["academic_year"] or entity.get("Academic Year"),
                        keywords=keywords,
                        school_id=pdf_data["school_id"],
                        department_id=pdf_data["department_id"],
                        semester_id=entity_semester_id,
                        subject_id=entity_subject_id,
                        structured_json=entity,
                        extracted_text=pdf_data["extracted_text"]
                    )
                    db.add(new_doc)
                    await db.commit()
                    total_subjects_created += 1
                    
                except Exception as e:
                    logger.error(f"Error saving entity {entity.get('Subject Name')}: {e}")
                    
        logger.info(f"\nSUCCESS! Rebuilt {total_subjects_created} complete syllabus documents across all departments.")

if __name__ == "__main__":
    asyncio.run(main())
