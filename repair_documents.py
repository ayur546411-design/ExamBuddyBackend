import asyncio
import re
import uuid
from app.db.session import AsyncSessionLocal
from sqlalchemy import select
from app.models.document import Document
from app.models.semester import Semester
from app.models.subject import Subject

def parse_semester(sem_str):
    if not sem_str or str(sem_str).strip().lower() == "null":
        return None
    sem_str = str(sem_str).upper()
    
    # Check for digits first
    digit_match = re.search(r'\d+', sem_str)
    if digit_match:
        return int(digit_match.group())
    
    # Check for roman numerals
    roman_map = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10}
    roman_match = re.search(r'\b(I|II|III|IV|V|VI|VII|VIII|IX|X)\b', sem_str)
    if roman_match:
        return roman_map.get(roman_match.group())
    return None

async def main():
    async with AsyncSessionLocal() as db:
        docs = (await db.execute(select(Document).where(Document.subject_id == None))).scalars().all()
        print(f"Found {len(docs)} documents with NULL subject_id")
        
        repaired_count = 0
        
        for d in docs:
            if not d.structured_json:
                continue
                
            print(f"Repairing doc: {d.title}")
            entity = d.structured_json
            
            # 1. Get Semester
            extracted_semester = entity.get("Semester")
            sem_num = parse_semester(extracted_semester)
            
            if not sem_num:
                sem_num = 1 # Fallback
                
            # Find or Create Semester
            sem_query = await db.execute(
                select(Semester).where(
                    Semester.department_id == d.department_id,
                    Semester.semester_number == sem_num
                )
            )
            found_sem = sem_query.scalars().first()
            
            if found_sem:
                entity_semester_id = found_sem.id
            else:
                new_sem = Semester(
                    id=str(uuid.uuid4()),
                    department_id=d.department_id,
                    semester_number=sem_num,
                    is_active=True
                )
                db.add(new_sem)
                await db.commit()
                await db.refresh(new_sem)
                entity_semester_id = new_sem.id
                print(f"  Created Semester {sem_num}")
                
            # 2. Get Subject
            subject_name = entity.get("Subject Name")
            subject_code = entity.get("Subject Code", "")
            
            if not subject_name:
                subject_name = d.title.replace(" Syllabus", "").replace(" PYQ", "").strip()
                if not subject_name:
                    subject_name = "Unknown Subject"
                    
            # Find or Create Subject
            found_subj = None
            if subject_code:
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
                # Ensure the semester matches if we found it by code
                if found_subj.semester_id != entity_semester_id:
                    entity_semester_id = found_subj.semester_id
            else:
                new_subj = Subject(
                    id=str(uuid.uuid4()),
                    school_id=d.school_id,
                    department_id=d.department_id,
                    semester_id=entity_semester_id,
                    name=subject_name,
                    code=subject_code if subject_code else f"AUTO-{str(uuid.uuid4())[:4]}",
                    credits=entity.get("Credits", 0) or 0
                )
                db.add(new_subj)
                await db.commit()
                await db.refresh(new_subj)
                entity_subject_id = new_subj.id
                print(f"  Created Subject {subject_name}")
                
            # 3. Link Document
            d.semester_id = entity_semester_id
            d.subject_id = entity_subject_id
            
            db.add(d)
            await db.commit()
            repaired_count += 1
            print(f"  Successfully repaired {d.title}")
            
        print(f"Successfully repaired {repaired_count} documents!")

if __name__ == "__main__":
    asyncio.run(main())
