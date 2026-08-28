from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import load_only
from typing import Optional, List
import json
import re
from datetime import datetime

from app.db.session import get_db
from app.models.document import Document, DocumentTypeEnum
from app.schemas.document import Document as DocumentSchema, DocumentUpdate
from app.services.cloudinary_service import upload_file_to_cloudinary
from app.services.gemini_service import extract_structured_data_from_pdf_text
from app.services.pdf_service import extract_text_from_pdf, extract_text_from_pdf_by_pages
from app.api.v1.endpoints.users import get_current_user
from app.models.user import User, UserRoleEnum
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


def extract_youtube_video_id(url: Optional[str]) -> Optional[str]:
    if not url:
        return None

    cleaned = url.strip()
    if not cleaned:
        return None

    patterns = [
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?v=([A-Za-z0-9_-]{11})',
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/embed\/([A-Za-z0-9_-]{11})',
        r'(?:https?:\/\/)?(?:www\.)?youtu\.be\/([A-Za-z0-9_-]{11})',
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/shorts\/([A-Za-z0-9_-]{11})',
    ]

    for pattern in patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            return match.group(1)

    if cleaned.startswith('https://') and 'youtube.com' in cleaned.lower():
        raise HTTPException(status_code=400, detail='Invalid YouTube URL. Use a standard watch, embed, short, or youtu.be link.')

    return None


def normalize_youtube_fields(url: Optional[str], title: Optional[str] = None) -> tuple[Optional[str], Optional[str], Optional[str]]:
    if url is None:
        return None, None, title.strip() if isinstance(title, str) and title.strip() else None

    cleaned = url.strip()
    if not cleaned:
        return None, None, title.strip() if isinstance(title, str) and title.strip() else None

    video_id = extract_youtube_video_id(cleaned)
    if not video_id:
        raise HTTPException(status_code=400, detail='Invalid YouTube URL. Please provide a valid YouTube watch/embed/short link.')

    return cleaned, video_id, title.strip() if isinstance(title, str) and title.strip() else None


def is_admin_user(user: User) -> bool:
    role_value = getattr(user, 'role', None)
    if isinstance(role_value, str):
        if role_value.lower() == UserRoleEnum.admin.value:
            return True
    if role_value == UserRoleEnum.admin:
        return True
    return bool(user.is_admin)

@router.get("/", response_model=List[DocumentSchema])
async def get_documents(
    subject_id: Optional[str] = None,
    document_type: Optional[DocumentTypeEnum] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 25,
    department_id: Optional[str] = None,
    semester_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieve documents for the current user.
    The response is paginated so the admin dashboard can render faster.
    - When subject_id is provided: returns documents for that subject.
    - When subject_id is absent: scopes to the user's department.
    - Optionally filter by document_type and status.
    structured_json is always included so SyllabusViewerScreen can render units/topics.
    """
    import time
    t0 = time.perf_counter()

    # ── Detailed request logging ─────────────────────────────────────
    logger.info("[Documents] ---- REQUEST START ----")
    logger.info(f"[Documents] user_id       = {current_user.id}")
    logger.info(f"[Documents] user_name     = {current_user.full_name}")
    logger.info(f"[Documents] role          = {current_user.role}")
    logger.info(f"[Documents] is_admin      = {current_user.is_admin}")
    logger.info(f"[Documents] admin_user    = {is_admin_user(current_user)}")
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
            Document.youtube_url,
            Document.youtube_video_id,
            Document.video_title,
            Document.created_at,
            Document.updated_at,
            Document.structured_json,
            Document.metadata_json,
            Document.extracted_text,
        ))
    )

    if status:
        query = query.where(Document.status == status)
        logger.info(f"[Documents] filter: status = {status}")
    elif not is_admin_user(current_user):
        query = query.where(Document.status == "active")

    if subject_id:
        # subject_id is the tightest scope — no dept filter needed
        query = query.where(Document.subject_id == subject_id)
        logger.info(f"[Documents] filter: subject_id = {subject_id}")
    elif department_id:
        # explicit department filter (admins can scope by department)
        query = query.where(Document.department_id == department_id)
        logger.info(f"[Documents] filter: department_id = {department_id}")
    elif not is_admin_user(current_user):
        # Non-admins only see documents for their own department
        query = query.where(Document.department_id == current_user.department_id)
        logger.info(f"[Documents] filter: department_id = {current_user.department_id}")
    else:
        logger.info("[Documents] admin user: no department filter applied")

    if document_type:
        query = query.where(Document.document_type == document_type)
        logger.info(f"[Documents] filter: document_type = {document_type}")

    if semester_id:
        query = query.where(Document.semester_id == semester_id)
        logger.info(f"[Documents] filter: semester_id = {semester_id}")

    query = query.order_by(Document.created_at.desc())
    # Pagination: allow page_size <= 0 to indicate "no limit" (return all matching rows)
    if page_size and page_size > 0:
        query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    documents = result.scalars().all()

    elapsed = round((time.perf_counter() - t0) * 1000, 2)
    logger.info(f"[Documents] RESULT: {len(documents)} document(s) returned in {elapsed}ms page={page} page_size={page_size}")
    if len(documents) == 0:
        logger.warning(f"[Documents] EMPTY RESULT — subject_id={subject_id} dept={current_user.department_id} type={document_type}")
    logger.info("[Documents] ---- REQUEST END ----")
    return documents

@router.get("/{document_id}", response_model=DocumentSchema)
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieve a single document by its ID for the current user."""
    logger.info(f"[DocumentDetail] user_id={current_user.id} role={current_user.role} is_admin={current_user.is_admin} admin={is_admin_user(current_user)} dept={current_user.department_id}")

    if not is_admin_user(current_user) and not current_user.department_id:
        raise HTTPException(status_code=400, detail="User is not assigned to a department")

    document_query = select(Document).where(Document.id == document_id)
    if not is_admin_user(current_user):
        document_query = document_query.where(Document.department_id == current_user.department_id)

    result = await db.execute(document_query)
    document = result.scalars().first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document

@router.put("/{document_id}", response_model=DocumentSchema)
async def update_document(
    document_id: str,
    document_in: DocumentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update editable document fields and structured JSON."""
    if not is_admin_user(current_user) and not current_user.department_id:
        raise HTTPException(status_code=400, detail="User is not assigned to a department")

    document_query = select(Document).where(Document.id == document_id)
    if not is_admin_user(current_user):
        document_query = document_query.where(Document.department_id == current_user.department_id)

    result = await db.execute(document_query)
    document = result.scalars().first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document_in.youtube_url is not None:
        if document_in.youtube_url.strip() == "":
            document.youtube_url = None
            document.youtube_video_id = None
            document.video_title = document_in.video_title.strip() if document_in.video_title and document_in.video_title.strip() else None
        else:
            normalized_url, video_id, title_value = normalize_youtube_fields(document_in.youtube_url, document_in.video_title)
            document.youtube_url = normalized_url
            document.youtube_video_id = video_id
            document.video_title = title_value or document.video_title

    if document_in.video_title is not None and document_in.youtube_url is None:
        if document_in.video_title.strip() == "":
            document.video_title = None
        elif document.youtube_url:
            document.video_title = document_in.video_title.strip()

    if document.youtube_url:
        document.metadata_json = {
            **(document.metadata_json or {}),
            "pyq_id": document.id,
            "youtube_url": document.youtube_url,
            "youtube_video_id": document.youtube_video_id,
            "video_title": document.video_title,
            "updated_at": datetime.utcnow().isoformat(),
        }
    updatable_fields = [
        "title",
        "description",
        "academic_year",
        "keywords",
        "metadata_json",
        "structured_json",
        "status",
        "semester_id",
        "subject_id",
    ]

    for field in updatable_fields:
        value = getattr(document_in, field)
        if value is not None:
            setattr(document, field, value)

    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document

@router.post("/upload")
async def upload_document(
    file: Optional[UploadFile] = File(None),
    school_id: str = Form(...),
    department_id: str = Form(...),
    subject_id: Optional[str] = Form(None),
    semester_id: Optional[str] = Form(None),
    academic_year: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    document_type: DocumentTypeEnum = Form(DocumentTypeEnum.syllabus),  # default = syllabus (most common upload)
    exam_type: Optional[str] = Form(None),
    pdf_url: Optional[str] = Form(None),
    youtube_url: Optional[str] = Form(None),
    video_title: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
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
            
    # FIX 1: Sanitize empty-string subject_id (admin form sends "" when blank)
    subject_id = subject_id.strip() if subject_id else None

    if subject_id:
        from app.models.subject import Subject
        subject_result = await db.execute(select(Subject).where(Subject.id == subject_id))
        selected_subject = subject_result.scalar_one_or_none()
        if not selected_subject:
            logger.warning(f"[Upload API] subject_id '{subject_id}' not found in DB — ignoring")
            subject_id = None  # Ignore invalid ID
        elif selected_subject.department_id != department_id:
            raise HTTPException(status_code=400, detail="Selected subject does not belong to the selected department")
        elif not semester_id:
            semester_id = selected_subject.semester_id
            
    doc_type_enum = document_type

    allowed_exts = {'.pdf'}
    if document_type == DocumentTypeEnum.pyq:
        allowed_exts = {'.pdf', '.png', '.jpg', '.jpeg', '.webp'}

    try:
        file_bytes = None
        cloudinary_url = None
        cloudinary_public_id = None
        file_size = None
        file_format = None
        resource_type = 'raw'

        if file is not None and file.filename:
            filename = file.filename.lower()
            extension = '.' + filename.rsplit('.', 1)[-1] if '.' in filename else ''
            if extension not in allowed_exts:
                raise HTTPException(status_code=400, detail=f"Only {', '.join(sorted(allowed_exts))} files are supported for this document type.")

            if extension in {'.png', '.jpg', '.jpeg', '.webp'}:
                resource_type = 'image'

            file_bytes = await file.read()
            
            # Validate file size (Cloudinary free tier limit is 10 MB)
            max_file_size = 10 * 1024 * 1024  # 10 MB
            if len(file_bytes) > max_file_size:
                size_mb = len(file_bytes) / (1024 * 1024)
                raise HTTPException(
                    status_code=413,
                    detail=f"File size ({size_mb:.1f} MB) exceeds maximum allowed size of 10 MB"
                )
            
            cloudinary_res = await upload_file_to_cloudinary(file_bytes, file.filename, resource_type=resource_type)
            cloudinary_url = cloudinary_res.get("url")
            cloudinary_public_id = cloudinary_res.get("public_id")
            file_size = cloudinary_res.get("bytes")
            file_format = cloudinary_res.get("format")

        if document_type == DocumentTypeEnum.pyq and not cloudinary_url and not pdf_url and not youtube_url:
            raise HTTPException(status_code=400, detail="PYQ uploads require a PDF/image file, a direct pdf_url, or a YouTube video URL")

        normalized_youtube_url = None
        normalized_youtube_video_id = None
        normalized_video_title = None
        if youtube_url:
            normalized_youtube_url, normalized_youtube_video_id, normalized_video_title = normalize_youtube_fields(youtube_url, video_title)
        
        # 2. Extract text only for non-PYQ documents; PYQ uploads are stored as direct PDF/video references.
        pdf_text = None
        structured_data = {}
        if file_bytes is not None and document_type != DocumentTypeEnum.pyq:
            logger.info("[Upload] Starting PDF text extraction...")
            pages_dict = await extract_text_from_pdf_by_pages(file_bytes)
            total_pages = len(pages_dict)
            non_empty_pages = sum(1 for t in pages_dict.values() if t.strip())
            logger.info(f"[Upload] PDF pages: {total_pages} total, {non_empty_pages} with text")
            
            pdf_text = ""
            for page_num, text in pages_dict.items():
                if text.strip():
                    pdf_text += f"\n--- PAGE {page_num} ---\n{text}\n"
                else:
                    pdf_text += f"\n--- PAGE {page_num} (empty) ---\n"
            
            if not pdf_text.strip():
                raise HTTPException(status_code=422, detail="Could not extract any text from this PDF. It may be a scanned image-only PDF.")
            
            logger.info(f"[Upload] Sending {len(pdf_text)} chars to Gemini for {document_type} extraction...")
            try:
                structured_data = await extract_structured_data_from_pdf_text(pdf_text, document_type)
                if "error" in structured_data:
                    logger.error(f"[Upload] Gemini extraction error: {structured_data['error']}")
            except Exception as gemini_e:
                logger.error(f"[Upload] Gemini extraction exception: {gemini_e}")
                structured_data = {"error": f"Gemini extraction failed: {str(gemini_e)}"}
        else:
            total_pages = 0
            non_empty_pages = 0
            pdf_text = ""
        
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
                # Determine the correct semester number:
                # Priority: (a) form-provided semester_id → look up its number, (b) Gemini-extracted "Semester" field
                extracted_semester = entity.get("Semester")
                form_semester_num = None
                if semester_id:
                    form_sem_res = await db.execute(select(Semester).where(Semester.id == semester_id))
                    form_sem = form_sem_res.scalar_one_or_none()
                    if form_sem:
                        form_semester_num = form_sem.semester_number

                sem_num = form_semester_num or parse_semester(extracted_semester)
                entity_semester_id = semester_id  # start with form value, may be overridden below
                
                if not sem_num:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Could not determine semester for subject '{entity.get('Subject Name', '?')}'. "
                            f"Please specify a valid semester_id in the form, or ensure the PDF contains "
                            f"clear semester headings (e.g. 'Semester 5' or 'V Semester')."
                        )
                    )

                
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
                subject_code = (entity.get("Subject Code") or '').strip()
                
                if subject_name and entity_semester_id and not subject_id:
                    normalized_name = str(subject_name).strip()
                    normalized_code = subject_code
                    candidate_identifiers = []
                    if normalized_code:
                        candidate_identifiers.append(("code", normalized_code.lower()))
                    candidate_identifiers.append(("name", normalized_name.lower()))

                    matching_subject = None
                    for field_name, field_value in candidate_identifiers:
                        if not field_value:
                            continue
                        subj_query = await db.execute(
                            select(Subject).where(
                                Subject.is_active == True,
                                Subject.school_id == school_id,
                                Subject.department_id == department_id,
                                Subject.semester_id == entity_semester_id,
                                ((Subject.code.ilike(normalized_code)) if field_name == 'code' and normalized_code else Subject.name.ilike(normalized_name))
                            )
                        )
                        matching_subject = subj_query.scalars().first()
                        if matching_subject:
                            break

                    if not matching_subject:
                        code_lookup = await db.execute(
                            select(Subject).where(
                                Subject.is_active == True,
                                Subject.code == normalized_code,
                            )
                        )
                        matching_subject = code_lookup.scalars().first() if normalized_code else None

                    if matching_subject:
                        entity_subject_id = matching_subject.id
                        have_real_code = bool(normalized_code)
                        if have_real_code and (not matching_subject.code or matching_subject.code.startswith('AUTO-')):
                            matching_subject.code = normalized_code
                        if not matching_subject.name:
                            matching_subject.name = normalized_name
                        if not matching_subject.school_id:
                            matching_subject.school_id = school_id
                        if not matching_subject.department_id:
                            matching_subject.department_id = department_id
                        if not matching_subject.semester_id:
                            matching_subject.semester_id = entity_semester_id
                        db.add(matching_subject)
                        await db.commit()
                        logger.info(f"[Upload API] Reused existing subject '{matching_subject.name}' for dept {department_id[:8]} / sem {entity_semester_id[:8]}")
                    else:
                        import uuid
                        new_subj = Subject(
                            id=str(uuid.uuid4()),
                            school_id=school_id,
                            department_id=department_id,
                            semester_id=entity_semester_id,
                            name=normalized_name,
                            code=normalized_code or f"AUTO-{str(uuid.uuid4())[:4]}",
                            credits=entity.get("Credits", 0) or 0
                        )
                        db.add(new_subj)
                        await db.commit()
                        await db.refresh(new_subj)
                        entity_subject_id = new_subj.id
                        logger.info(f"[Upload API] Auto-created Subject '{normalized_name}' for semester {entity_semester_id}")
                
                # 3. Document Creation
                # FIX 2: Guard — skip saving a syllabus with no resolved subject (broken PDF)
                if doc_type_enum == DocumentTypeEnum.syllabus and not entity_subject_id:
                    logger.error(
                        f"[Upload API] Skipping syllabus entity — could not resolve subject_id. "
                        f"This usually means the PDF is a scanned image with no extractable text. "
                        f"Entity Subject Name='{entity.get('Subject Name', '?')}' | "
                        f"Please re-upload as a text-based PDF or manually select a subject."
                    )
                    skipped_count += 1
                    continue

                # FIX 3: Guard against file.filename crash when file=None (pdf_url/youtube upload path)
                # Infer title based on doc type
                safe_filename = (file.filename if file and file.filename else None)
                title = safe_filename or 'Untitled'
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
                    cloudinary_url=cloudinary_url or pdf_url or normalized_youtube_url or '',
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
                    subject_id=entity_subject_id,
                    youtube_url=normalized_youtube_url,
                    youtube_video_id=normalized_youtube_video_id,
                    video_title=normalized_video_title,
                    status="draft",
                )
                if doc_type_enum == DocumentTypeEnum.pyq:
                    normalized_exam_type = (exam_type or '').strip().lower() if exam_type else None
                    new_doc.metadata_json = {
                        **(new_doc.metadata_json or {}),
                        "exam_type": normalized_exam_type,
                        "pdf_url": pdf_url,
                        "youtube_url": normalized_youtube_url,
                        "youtube_video_id": normalized_youtube_video_id,
                        "video_title": normalized_video_title,
                    }
                    new_doc.structured_json = {
                        "exam_type": normalized_exam_type,
                        "pdf_url": pdf_url,
                        "youtube_url": normalized_youtube_url,
                        "youtube_video_id": normalized_youtube_video_id,
                        "video_title": normalized_video_title,
                    }
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


@router.get("/admin/db-status")
async def db_status(db: AsyncSession = Depends(get_db)):
    """Debug: show what database the server is connected to and what it contains."""
    from app.models.semester import Semester
    from app.models.subject import Subject
    from app.models.department import Department
    from app.models.school import School
    from app.core.config import settings

    result = {
        "db_url_prefix": settings.DATABASE_URL[:60] + "...",
        "counts": {}
    }

    try:
        result["counts"]["schools"] = len((await db.execute(select(School))).scalars().all())
        result["counts"]["departments"] = len((await db.execute(select(Department))).scalars().all())
        result["counts"]["semesters"] = len((await db.execute(select(Semester))).scalars().all())
        result["counts"]["subjects"] = len((await db.execute(select(Subject))).scalars().all())
        result["counts"]["documents"] = len((await db.execute(select(Document))).scalars().all())

        sems = (await db.execute(select(Semester).order_by(Semester.semester_number))).scalars().all()
        result["semesters"] = []
        for sem in sems:
            subjects = (await db.execute(
                select(Subject).where(Subject.semester_id == sem.id)
            )).scalars().all()
            result["semesters"].append({
                "number": sem.semester_number,
                "id": sem.id[:8],
                "subjects": [{"name": s.name, "code": s.code} for s in subjects]
            })

    except Exception as e:
        result["error"] = str(e)

    return result


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

@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a document by its ID."""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Only admins can delete documents")

    doc = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        await db.delete(doc)
        await db.commit()
        return {"status": "success", "message": "Document deleted successfully"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {str(e)}")

