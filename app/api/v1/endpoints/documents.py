from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import load_only
from typing import Optional, List
import json

from app.db.session import get_db
from app.models.document import Document, DocumentTypeEnum
from app.schemas.document import Document as DocumentSchema
from app.services.cloudinary_service import upload_file_to_cloudinary
from app.services.gemini_service import extract_structured_data_from_pdf_text
from app.services.pdf_service import extract_text_from_pdf, extract_text_from_pdf_by_pages
from app.api.v1.endpoints.users import get_current_user
from app.models.user import User
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/", response_model=List[DocumentSchema])
async def get_documents(
    subject_id: Optional[str] = None,
    document_type: Optional[DocumentTypeEnum] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieve documents for the current user.
    - When subject_id is provided: returns all active docs for that subject (no dept filter).
    - When subject_id is absent: scopes to the user's department.
    structured_json is always included so SyllabusViewerScreen can render units/topics.
    """
    import time
    t0 = time.perf_counter()

    # ── Detailed request logging ─────────────────────────────────────
    logger.info("[Documents] ---- REQUEST START ----")
    logger.info(f"[Documents] user_id       = {current_user.id}")
    logger.info(f"[Documents] user_name     = {current_user.full_name}")
    logger.info(f"[Documents] dept_id       = {current_user.department_id}")
    logger.info(f"[Documents] school_id     = {current_user.school_id}")
    logger.info(f"[Documents] param subject_id     = {subject_id}")
    logger.info(f"[Documents] param document_type  = {document_type}")

    if not current_user.department_id:
        logger.error("[Documents] REJECTED: user has no department_id")
        raise HTTPException(status_code=400, detail="User is not assigned to a department")

    # Build query — include ALL fields the Pydantic schema accesses.
    # CRITICAL: In async SQLAlchemy, any column NOT in load_only() will trigger
    # a lazy-load during Pydantic serialization → MissingGreenlet crash.
    # metadata_json and extracted_text MUST be included even if unused by the frontend.
    query = (
        select(Document)
        .options(load_only(
            Document.id,
            Document.title,
            Document.description,
            Document.document_type,
            Document.academic_year,
            Document.cloudinary_url,
            Document.thumbnail_url,
            Document.file_size,
            Document.file_type,
            Document.keywords,
            Document.status,
            Document.school_id,
            Document.department_id,
            Document.semester_id,
            Document.subject_id,
            Document.uploaded_by_admin,
            Document.created_at,
            Document.structured_json,
            Document.metadata_json,    # Required: schema includes this, omitting causes MissingGreenlet
            Document.extracted_text,   # Required: schema includes this, omitting causes MissingGreenlet
        ))
        .where(Document.status == "active")
    )

    if subject_id:
        # subject_id is the tightest scope — no dept filter needed
        query = query.where(Document.subject_id == subject_id)
        logger.info(f"[Documents] filter: subject_id = {subject_id}")
    else:
        # Scope to user's department
        query = query.where(Document.department_id == current_user.department_id)
        logger.info(f"[Documents] filter: department_id = {current_user.department_id}")

    if document_type:
        query = query.where(Document.document_type == document_type)
        logger.info(f"[Documents] filter: document_type = {document_type}")

    result = await db.execute(query.order_by(Document.created_at.desc()))
    documents = result.scalars().all()

    elapsed = round((time.perf_counter() - t0) * 1000, 2)
    logger.info(f"[Documents] RESULT: {len(documents)} document(s) returned in {elapsed}ms")
    if len(documents) == 0:
        logger.warning(f"[Documents] EMPTY RESULT — subject_id={subject_id} dept={current_user.department_id} type={document_type}")
    logger.info("[Documents] ---- REQUEST END ----")
    return documents

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    school_id: str = Form(...),
    department_id: str = Form(...),
    subject_id: Optional[str] = Form(None),
    semester_id: Optional[str] = Form(None),
    academic_year: Optional[str] = Form(None),
    document_type: DocumentTypeEnum = Form(DocumentTypeEnum.syllabus),  # default = syllabus (most common upload)
    db: AsyncSession = Depends(get_db)
):
    """
    Upload a PDF, extract text, process with Gemini, and save to DB.
    """
    from app.models.school import School
    from app.models.department import Department
    from app.models.semester import Semester
    from app.models.subject import Subject
    
    # 1. Validate foreign keys first, auto-fallback to first available if dummy data provided
    school = await db.execute(select(School).where(School.id == school_id))
    if not school.scalar_one_or_none():
        logger.warning(f"[Upload API] Invalid school_id '{school_id}', auto-falling back")
        # Try to use current_user's school if logged in? We don't have current_user here by default for upload testing
        first_school = (await db.execute(select(School))).scalars().first()
        school_id = first_school.id if first_school else None
        
    department = await db.execute(select(Department).where(Department.id == department_id))
    if not department.scalar_one_or_none():
        logger.warning(f"[Upload API] Invalid department_id '{department_id}', auto-falling back")
        # Ensure we pick a department from the same school
        first_dept = (await db.execute(select(Department).where(Department.school_id == school_id))).scalars().first()
        department_id = first_dept.id if first_dept else None
        
    if semester_id:
        from app.models.semester import Semester
        semester = await db.execute(select(Semester).where(Semester.id == semester_id))
        if not semester.scalar_one_or_none():
            semester_id = None # Just ignore if invalid
            
    if subject_id:
        from app.models.subject import Subject
        subject = await db.execute(select(Subject).where(Subject.id == subject_id))
        if not subject.scalar_one_or_none():
            subject_id = None # Just ignore if invalid
            
    doc_type_enum = document_type
        
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
        
    try:
        # Read file bytes
        file_bytes = await file.read()
        
        # 1. Upload to Cloudinary
        cloudinary_res = await upload_file_to_cloudinary(file_bytes, file.filename)
        cloudinary_url = cloudinary_res.get("url")
        cloudinary_public_id = cloudinary_res.get("public_id")
        file_size = cloudinary_res.get("bytes")
        file_format = cloudinary_res.get("format")
        
        # 2. Extract Text from PDF (page-by-page for full coverage)
        logger.info("[Upload] Starting PDF text extraction...")
        pages_dict = await extract_text_from_pdf_by_pages(file_bytes)
        total_pages = len(pages_dict)
        non_empty_pages = sum(1 for t in pages_dict.values() if t.strip())
        logger.info(f"[Upload] PDF pages: {total_pages} total, {non_empty_pages} with text")
        
        # Build full text with page markers for Gemini
        pdf_text = ""
        for page_num, text in pages_dict.items():
            if text.strip():
                pdf_text += f"\n--- PAGE {page_num} ---\n{text}\n"
            else:
                pdf_text += f"\n--- PAGE {page_num} (empty) ---\n"
        
        if not pdf_text.strip():
            raise HTTPException(status_code=422, detail="Could not extract any text from this PDF. It may be a scanned image-only PDF.")
        
        # 3. Get Structured JSON from Gemini
        logger.info(f"[Upload] Sending {len(pdf_text)} chars to Gemini for {document_type} extraction...")
        structured_data = {}
        try:
            structured_data = await extract_structured_data_from_pdf_text(pdf_text, document_type)
            if "error" in structured_data:
                logger.error(f"[Upload] Gemini extraction error: {structured_data['error']}")
        except Exception as gemini_e:
            logger.error(f"[Upload] Gemini extraction exception: {gemini_e}")
            structured_data = {"error": f"Gemini extraction failed: {str(gemini_e)}"}
        
        # 4. Process all entities in structured_json and Save to Database
        entities = []
        if doc_type_enum == DocumentTypeEnum.syllabus and "Subjects" in structured_data:
            entities = structured_data["Subjects"]
        elif doc_type_enum == DocumentTypeEnum.pyq and "QuestionPapers" in structured_data:
            entities = structured_data["QuestionPapers"]
        elif doc_type_enum == DocumentTypeEnum.academic_calendar and "Events" in structured_data:
            # Calendar is a single document containing an array of events
            # We don't want 50 different Document rows for 50 events. We want 1 document that holds the events array
            entities = [structured_data]
        else:
            # Fallback for generic documents or if the model ignored the array wrapper
            entities = [structured_data]
            
        logger.info(f"[Upload API] PDF uploaded. Total pages extracted: {len(pdf_text) // 2000 + 1}. Total text extracted: {len(pdf_text)} characters.")
        logger.info(f"[Upload API] Gemini returned {len(entities)} entities from the document.")

        inserted_count = 0
        skipped_count = 0
        
        # ── Post-processing: Propagate semesters from neighbours ────────────────────────
        # University PDFs often have ONE semester header for a SECTION of subjects.
        # Gemini may correctly tag the first subject but return null for the rest.
        # This pass propagates the semester forward (and backward) to fill gaps.
        def parse_semester(sem_str):
            """Convert semester string to integer. Handles digits and roman numerals."""
            if not sem_str or str(sem_str).strip().lower() in ("null", "none", ""):
                return None
            sem_str = str(sem_str).upper().strip()
            import re
            digit_match = re.search(r'\d+', sem_str)
            if digit_match:
                num = int(digit_match.group())
                if 1 <= num <= 12:  # Valid semester range
                    return num
            roman_map = {'VIII': 8, 'VII': 7, 'VI': 6, 'IV': 4, 'IX': 9, 'X': 10,
                         'III': 3, 'II': 2, 'I': 1, 'V': 5}
            roman_match = re.search(r'\b(VIII|VII|VI|IV|IX|X|III|II|I|V)\b', sem_str)
            if roman_match:
                return roman_map.get(roman_match.group())
            return None
        
        if doc_type_enum == DocumentTypeEnum.syllabus and entities:
            # Forward pass: propagate last known semester to subjects with null semester
            last_known_sem = None
            for entity in entities:
                sem = parse_semester(entity.get("Semester"))
                if sem:
                    last_known_sem = sem
                elif last_known_sem:
                    entity["Semester"] = str(last_known_sem)
                    logger.info(f"[Upload] Propagated Semester {last_known_sem} to '{entity.get('Subject Name', '?')}' (was null)")
            
            # Backward pass: if first few subjects still have null, use the first known sem from later
            first_known_sem = None
            for entity in entities:
                sem = parse_semester(entity.get("Semester"))
                if sem:
                    first_known_sem = sem
                    break
            if first_known_sem:
                for entity in entities:
                    if not parse_semester(entity.get("Semester")):
                        entity["Semester"] = str(first_known_sem)
                        logger.info(f"[Upload] Back-filled Semester {first_known_sem} to '{entity.get('Subject Name', '?')}' (backward pass)")
            
            # Log any subjects still without a semester
            still_null = [e.get('Subject Name', '?') for e in entities if not parse_semester(e.get("Semester"))]
            if still_null:
                logger.warning(f"[Upload] {len(still_null)} subjects still have null semester after propagation: {still_null}")
                logger.warning(f"[Upload] If a semester_id was provided in the form, it will be used as override for these.")
        
        for entity in entities:
            try:
                # Helper to convert roman numeral to int
                def parse_semester(sem_str):
                    if not sem_str or str(sem_str).strip().lower() == "null":
                        return None
                    sem_str = str(sem_str).upper()
                    import re
                    # Check for digits first
                    digit_match = re.search(r'\d+', sem_str)
                    if digit_match:
                        return int(digit_match.group())
                    
                    # Check for roman numerals
                    roman_map = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10}
                    # Extract standalone roman numeral words
                    roman_match = re.search(r'\b(I|II|III|IV|V|VI|VII|VIII|IX|X)\b', sem_str)
                    if roman_match:
                        return roman_map.get(roman_match.group())
                    return None

                # 1. Dynamic Semester Parsing & Creation
                # Priority: (a) Gemini-extracted semester, (b) form semester_id
                entity_semester_id = semester_id  # form-provided override as default
                extracted_semester = entity.get("Semester")
                
                sem_num = parse_semester(extracted_semester)
                
                if not sem_num:
                    # No semester from Gemini and no propagation filled it
                    if semester_id:
                        # Use the form-provided semester_id directly
                        logger.warning(f"[Upload] Subject '{entity.get('Subject Name', '?')}' has no semester from Gemini. Using form semester_id={semester_id[:8]}")
                        # entity_semester_id already set to semester_id above
                    else:
                        logger.error(f"[Upload] Subject '{entity.get('Subject Name', '?')}' has no semester. Skipping to avoid wrong assignment. Upload again with semester_id form field.")
                        skipped_count += 1
                        continue  # Skip rather than assign to wrong semester
                
                if sem_num:
                    try:
                        # Find or Create Semester by number
                        sem_query = await db.execute(
                            select(Semester).where(
                                Semester.department_id == department_id,
                                Semester.semester_number == sem_num
                            )
                        )
                        found_sem = sem_query.scalars().first()
                        
                        if found_sem:
                            entity_semester_id = found_sem.id
                        else:
                            import uuid
                            new_sem = Semester(
                                id=str(uuid.uuid4()),
                                department_id=department_id,
                                semester_number=sem_num,
                                is_active=True
                            )
                            db.add(new_sem)
                            await db.commit()
                            await db.refresh(new_sem)
                            entity_semester_id = new_sem.id
                            logger.info(f"[Upload] Auto-created Semester {sem_num} for dept {department_id[:8]}")
                    except Exception as e:
                        logger.warning(f"[Upload] Failed to find/create semester {sem_num}: {e}")
                
                # 2. Dynamic Subject Parsing & Creation
                entity_subject_id = subject_id
                subject_name = entity.get("Subject Name")
                subject_code = entity.get("Subject Code", "")
                
                if subject_name and entity_semester_id:
                    # Find or Create Subject
                    # Use bidirectional ilike: DB name contains Gemini name OR Gemini name contains DB name.
                    # This prevents duplicate subjects when Gemini returns a slightly different
                    # abbreviation (e.g. "ML Lab" vs "Machine Learning Lab").
                    from sqlalchemy import or_
                    subj_query = await db.execute(
                        select(Subject).where(
                            Subject.semester_id == entity_semester_id,
                            or_(
                                Subject.name.ilike(f"%{subject_name}%"),
                                Subject.name.ilike(f"{subject_name[:10]}%")  # prefix match as fallback
                            )
                        )
                    )
                    found_subj = subj_query.scalars().first()
                    
                    if found_subj:
                        entity_subject_id = found_subj.id
                    else:
                        import uuid
                        new_subj = Subject(
                            id=str(uuid.uuid4()),
                            school_id=school_id,
                            department_id=department_id,
                            semester_id=entity_semester_id,
                            name=subject_name,
                            code=subject_code if subject_code else f"AUTO-{str(uuid.uuid4())[:4]}",
                            credits=entity.get("Credits", 0) or 0
                        )
                        db.add(new_subj)
                        await db.commit()
                        await db.refresh(new_subj)
                        entity_subject_id = new_subj.id
                        logger.info(f"[Upload API] Auto-created Subject '{subject_name}' for semester {entity_semester_id}")
                
                # 3. Document Creation
                # Infer title based on doc type
                title = file.filename
                if doc_type_enum == DocumentTypeEnum.syllabus and entity.get("Subject Name"):
                    title = f"{entity['Subject Name']} {doc_type_enum.value.capitalize()}"
                elif doc_type_enum == DocumentTypeEnum.pyq and entity.get("Subject Name"):
                    title = f"{entity['Subject Name']} PYQ"
                elif entity.get("Title"):
                    title = entity["Title"]
                    
                description = entity.get("Summary", "") or ""
                
                keywords_list = entity.get("Keywords", [])
                keywords = ", ".join(keywords_list) if isinstance(keywords_list, list) else str(keywords_list or "")
                
                final_academic_year = academic_year or entity.get("Academic Year")
                
                new_doc = Document(
                    document_type=doc_type_enum,
                    cloudinary_url=cloudinary_url,
                    cloudinary_public_id=cloudinary_public_id,
                    file_size=file_size,
                    file_type=file_format,
                    title=title,
                    description=description,
                    academic_year=final_academic_year,
                    keywords=keywords,
                    extracted_text=pdf_text,
                    structured_json=entity,
                    school_id=school_id,
                    department_id=department_id,
                    semester_id=entity_semester_id,
                    subject_id=entity_subject_id
                )
                db.add(new_doc)
                await db.commit() # Commit individually to ensure foreign keys are saved
                inserted_count += 1
            except Exception as e:
                # If an entity fails, rollback the transaction state so the loop can continue
                await db.rollback()
                skipped_count += 1
                logger.error(f"[Upload API] Skipped entity due to error: {str(e)}\nEntity: {entity}")
                
        logger.info(f"[Upload] Upload complete. Pages: {total_pages} | Inserted: {inserted_count} | Skipped: {skipped_count}")
        
        # Build extraction validation report
        extracted_count = len(entities)
        validation_report = {
            "pdf_pages_total": total_pages,
            "pdf_pages_with_text": non_empty_pages,
            "pdf_pages_empty": total_pages - non_empty_pages,
            "gemini_entities_extracted": extracted_count,
            "db_documents_inserted": inserted_count,
            "db_documents_skipped": skipped_count,
            "extraction_success": inserted_count > 0,
            "coverage_pct": round((inserted_count / max(extracted_count, 1)) * 100, 1)
        }
        
        return {
            "message": "Document processed and saved to database successfully",
            "validation_report": validation_report,
            "inserted_entities": inserted_count,
            "skipped_entities": skipped_count,
            "cloudinary_url": cloudinary_url,
            "structured_json": structured_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@router.post("/admin/repair-semesters")
async def repair_semester_assignments(
    db: AsyncSession = Depends(get_db)
):
    """
    Admin endpoint: Audit and repair subjects assigned to wrong semester.

    Detects subjects where the subject code contains an elective slot number
    (e.g. ITUETK3 = 3rd elective slot) that Gemini incorrectly treated as
    a semester number (semester 3).

    Steps:
      1. Show full audit of all semesters and subjects
      2. Detect subjects in wrong semester based on structured_json vs DB
      3. Move mis-assigned subjects and their documents to the correct semester
    """
    from app.models.semester import Semester
    from app.models.subject import Subject

    report = {
        "semesters": [],
        "mismatches_found": 0,
        "mismatches_fixed": 0,
        "audit": []
    }

    # ── 1. Collect all semesters and their subjects ────────────────────────
    all_sems = (await db.execute(
        select(Semester).order_by(Semester.semester_number)
    )).scalars().all()

    for sem in all_sems:
        subjects = (await db.execute(
            select(Subject).where(Subject.semester_id == sem.id, Subject.is_active == True)
        )).scalars().all()

        sem_info = {
            "semester_number": sem.semester_number,
            "id": sem.id,
            "subjects": [{"name": s.name, "code": s.code, "id": s.id} for s in subjects]
        }
        report["semesters"].append(sem_info)

    # ── 2. Find documents whose structured_json semester != DB semester ────
    all_docs = (await db.execute(
        select(Document)
        .where(Document.document_type == DocumentTypeEnum.syllabus, Document.status == "active")
    )).scalars().all()

    mismatched_docs = []
    for doc in all_docs:
        if not doc.semester_id:
            continue
        sj = doc.structured_json or {}
        json_sem_str = str(sj.get("Semester", "")).strip()
        if not json_sem_str or json_sem_str.lower() in ("null", "none", ""):
            continue
        try:
            json_sem_num = int(json_sem_str)
        except ValueError:
            continue

        stored_sem = await db.get(Semester, doc.semester_id)
        if stored_sem and stored_sem.semester_number != json_sem_num:
            mismatched_docs.append({
                "doc_id": doc.id,
                "title": doc.title,
                "json_semester": json_sem_num,
                "stored_semester": stored_sem.semester_number,
                "subject_id": doc.subject_id
            })

    report["mismatches_found"] = len(mismatched_docs)
    report["mismatch_details"] = mismatched_docs

    # ── 3. Auto-repair: move subjects/docs to correct semester per JSON ────
    sems_by_num = {s.semester_number: s for s in all_sems}
    fixed = 0

    for mismatch in mismatched_docs:
        correct_num = mismatch["json_semester"]
        target_sem = sems_by_num.get(correct_num)

        if not target_sem:
            # Create the semester if it doesn't exist
            import uuid
            from app.models.department import Department
            # Use the department from the document's existing semester
            existing_sem = await db.get(Semester, (await db.get(Document, mismatch["doc_id"])).semester_id)
            if not existing_sem:
                continue
            import uuid as _uuid
            target_sem = Semester(
                id=str(_uuid.uuid4()),
                department_id=existing_sem.department_id,
                semester_number=correct_num,
                is_active=True
            )
            db.add(target_sem)
            await db.commit()
            await db.refresh(target_sem)
            sems_by_num[correct_num] = target_sem
            logger.info(f"[Repair] Created Semester {correct_num}")

        # Move the document
        doc = await db.get(Document, mismatch["doc_id"])
        if doc:
            doc.semester_id = target_sem.id
            db.add(doc)

        # Move the subject if it exists
        if mismatch["subject_id"]:
            subj = await db.get(Subject, mismatch["subject_id"])
            if subj and subj.semester_id != target_sem.id:
                subj.semester_id = target_sem.id
                db.add(subj)
                logger.info(f"[Repair] Moved subject '{subj.name}' -> Semester {correct_num}")

        fixed += 1

    if fixed > 0:
        await db.commit()

    report["mismatches_fixed"] = fixed
    logger.info(f"[Repair] Fixed {fixed} semester mismatches")

    return report
