"""
gemini_service.py — AI extraction from PDF text
=================================================
Uses the new google.genai SDK (google-generativeai is deprecated).

Pipeline:
  1. Receive full PDF text (page-marked)
  2. Split into page-aware chunks
  3. For each chunk: call Gemini with strict extraction prompt
  4. Merge + deduplicate results
  5. Validate completeness and return
"""
from google import genai
from google.genai import types
from app.core.config import settings
import logging
import json
import re
import asyncio
import time

logger = logging.getLogger(__name__)

# Initialize the new SDK client
_client = genai.Client(api_key=settings.GEMINI_API_KEY)

# ── Confirmed-working model names (tested against this API key) ──────────────
# Priority: currently working models first, quota-limited fallbacks at end
GEMINI_MODELS = [
    "gemini-flash-lite-latest",   # ✅ WORKING — confirmed
    "gemini-3.5-flash-lite",      # ✅ WORKING — confirmed
    "gemini-3-flash-preview",     # ✅ WORKING — confirmed
    "gemini-3.1-flash-lite",      # ✅ WORKING — confirmed
    "gemini-3.1-flash-lite-preview",  # ✅ WORKING — confirmed
    "gemini-2.0-flash",           # QUOTA (free tier daily limit, resets daily)
    "gemini-2.0-flash-lite",      # QUOTA (free tier daily limit, resets daily)
    "gemini-pro-latest",          # QUOTA fallback
]

# ── Chunking config ──────────────────────────────────────────────────────────
PAGES_PER_CHUNK = 8       # Process 8 pages per Gemini call
MAX_CHARS_PER_CHUNK = 30000  # Hard cap per chunk


# ── Pre-extraction semester detection ────────────────────────────────────────

def detect_semester_from_text(pdf_text: str) -> int | None:
    """
    Detect the semester number from raw PDF text BEFORE sending to Gemini.
    Scans headings, titles, and structured patterns.
    Returns an integer (1-8) or None if uncertain.

    This prevents Gemini from guessing semester from subject codes like
    'ITUETK3' (3rd elective slot ≠ Semester 3).
    """
    text = pdf_text[:5000]  # Focus on first ~5000 chars (cover page + headings)
    text_upper = text.upper()

    ROMAN = {
        'VIII': 8, 'VII': 7, 'VI': 6, 'IV': 4, 'IX': 9, 'X': 10,
        'III': 3, 'II': 2, 'I': 1, 'V': 5
    }

    def roman_to_int(s: str) -> int | None:
        return ROMAN.get(s.upper())

    # Pattern order: most specific → least specific
    patterns = [
        # "Semester 5 Syllabus" / "5th Semester" / "V Semester"
        (r'(?:SEMESTER|SEM)[\s\-.:]*(\d{1,2})\b', 'digit'),
        (r'\b(\d{1,2})(?:ST|ND|RD|TH)?[\s\-]*SEMESTER\b', 'digit'),
        (r'(?:SEMESTER|SEM)[\s\-.:]*\b(VIII|VII|VI|IV|IX|X|III|II|I|V)\b', 'roman'),
        (r'\b(VIII|VII|VI|IV|IX|X|III|II|I|V)\b[\s\-]*SEMESTER\b', 'roman'),
        # "5th Sem" / "Sem-5"
        (r'\bSEM[\s\-.:]*(\d{1,2})\b', 'digit'),
        (r'\b(\d{1,2})[\s\-]*SEM\b', 'digit'),
        # "B.Tech 5th Semester" / "Year III Sem I"
        (r'B\.?TECH[\s\w]*?(\d{1,2})(?:ST|ND|RD|TH)?[\s\-]*(?:SEMESTER|SEM)\b', 'digit'),
    ]

    votes: dict[int, int] = {}

    for pattern, kind in patterns:
        for match in re.finditer(pattern, text_upper):
            raw = match.group(1)
            if kind == 'digit':
                num = int(raw)
            else:
                num = roman_to_int(raw)
            if num and 1 <= num <= 8:
                votes[num] = votes.get(num, 0) + 1

    if not votes:
        logger.warning("[Semester-Detect] No semester found in first 5000 chars. Scanning full text...")
        # Try full text with simplified pattern
        for match in re.finditer(r'(?:SEMESTER|SEM)[\s\-.:]*(\d{1,2})\b', pdf_text.upper()):
            num = int(match.group(1))
            if 1 <= num <= 8:
                votes[num] = votes.get(num, 0) + 1

    if not votes:
        logger.warning("[Semester-Detect] Could not determine semester from PDF text.")
        return None

    # Pick the semester with most votes (most mentions)
    best = max(votes, key=lambda k: votes[k])
    logger.info(f"[Semester-Detect] Vote results: {votes} → Detected Semester {best}")
    return best


# ── Prompts ──────────────────────────────────────────────────────────────────

def _syllabus_prompt(text: str, chunk_index: int, total_chunks: int, confirmed_semester: int | None = None) -> str:
    # Build semester instruction based on whether we pre-detected the semester
    if confirmed_semester:
        semester_instruction = f"""
*** CONFIRMED SEMESTER = {confirmed_semester} ***
This has been verified from the PDF title/cover page BEFORE you were called.
Every single subject in this document belongs to Semester {confirmed_semester}.
You MUST set \"Semester\": \"{confirmed_semester}\" for EVERY subject extracted.
Do NOT use any other semester number. Do NOT use 'null'.
Do NOT infer semester from subject codes (e.g. 'ITUETK3' is an elective slot number, NOT semester 3)."""
    else:
        semester_instruction = """
SEMESTER RULE (CRITICAL):
University syllabuses often have ONE "Semester X" header at the top of a section,
following which ALL subjects belong to that semester.
  a) Scan for semester headers like "Semester 3", "SEM III", "THIRD SEMESTER"
  b) Apply that semester number to EVERY subject under that header
  c) Keep applying it until a DIFFERENT semester header appears
  d) NEVER infer semester from subject codes (e.g. 'ITUETK3' = 3rd elective slot, NOT semester 3)
  e) NEVER return null — use your best inference from document structure"""

    return f"""You are a university syllabus data extraction engine.

CRITICAL RULES — YOU MUST FOLLOW EVERY RULE WITHOUT EXCEPTION:
1. Extract EVERY subject found in this text. Do NOT skip any subject.
2. Do NOT summarize. Extract the EXACT content as written.
3. Do NOT stop early. Process EVERY line of text provided.
4. If a subject has multiple units, extract ALL units.
5. If a subject has topics, extract ALL topics for EACH unit.
6. If a subject has practicals, list ALL practicals.
7. If a subject has reference books, list ALL books.
8. If a subject has learning outcomes/objectives, list ALL of them.
9. Preserve exact subject names, codes, and numbering.
{semester_instruction}

10. This is chunk {chunk_index + 1} of {total_chunks} — extract all subjects visible in THIS chunk.
11. Output ONLY valid JSON. No markdown. No explanation. No preamble.

OUTPUT FORMAT (strictly follow this structure):
{{
  "Subjects": [
    {{
      "Semester": "{confirmed_semester if confirmed_semester else 'number as string, e.g. 3'}",
      "Subject Name": "exact name as in document",
      "Subject Code": "exact code as in document or null",
      "Credits": number or null,
      "Subject Type": "theory/lab/practical/elective or null",
      "Units": [
        {{
          "Unit Name": "exact unit name",
          "Topics": ["exact topic 1", "exact topic 2", "..."]
        }}
      ],
      "Learning Outcomes": ["exact outcome 1", "exact outcome 2"],
      "Practicals": ["exact practical 1", "exact practical 2"],
      "Reference Books": ["Author, Title, Publisher", "..."],
      "Keywords": ["keyword1", "keyword2"]
    }}
  ]
}}

TEXT TO EXTRACT FROM:
{text}

REMINDER: Extract ALL subjects. {f'Set Semester={confirmed_semester} for EVERY subject.' if confirmed_semester else 'Apply correct semester from section headers.'} Return valid JSON only."""



def _pyq_prompt(text: str, chunk_index: int, total_chunks: int) -> str:
    return f"""You are a university question paper extraction engine.

CRITICAL RULES:
1. Extract EVERY question found in this text. Do NOT skip any question.
2. Extract EVERY question paper header (subject, year, marks, duration).
3. Do NOT summarize questions — copy them EXACTLY as written.
4. Preserve question numbers, marks, and units as shown.
5. This is chunk {chunk_index + 1} of {total_chunks}.
6. Output ONLY valid JSON. No markdown. No explanation.

OUTPUT FORMAT:
{{
  "QuestionPapers": [
    {{
      "Subject Name": "exact name",
      "Subject Code": "exact code or null",
      "Semester": "number as string or null",
      "Academic Year": "e.g. 2023-24 or null",
      "Exam Type": "Mid/End/Annual or null",
      "Total Marks": number or null,
      "Duration": "e.g. 3 Hours or null",
      "Questions": [
        {{
          "Question Number": "e.g. Q1(a)",
          "Question Text": "exact question text",
          "Marks": number or null,
          "Unit": "unit name or null"
        }}
      ],
      "Keywords": ["keyword1"]
    }}
  ]
}}

TEXT TO EXTRACT FROM:
{text}"""


def _calendar_prompt(text: str, chunk_index: int, total_chunks: int) -> str:
    return f"""You are an academic calendar extraction engine.

CRITICAL RULES:
1. Extract EVERY event and date found. Do NOT skip any.
2. This is chunk {chunk_index + 1} of {total_chunks}.
3. Output ONLY valid JSON.

OUTPUT FORMAT:
{{
  "Events": [
    {{
      "event_title": "exact event name",
      "event_date": "YYYY-MM-DD or approximate date string",
      "description": "any description or null",
      "event_type": "holiday/exam/academic/other"
    }}
  ]
}}

TEXT TO EXTRACT FROM:
{text}"""


def _generic_prompt(text: str) -> str:
    return f"""Extract key information from this document as JSON.

OUTPUT FORMAT:
{{
  "Title": "document title",
  "Summary": "brief summary",
  "Key Points": ["point 1", "point 2"],
  "Keywords": ["keyword1"]
}}

TEXT:
{text}"""


def _get_prompt(doc_type: str, text: str, chunk_index: int = 0, total_chunks: int = 1, confirmed_semester: int | None = None) -> str:
    if doc_type == "syllabus":
        return _syllabus_prompt(text, chunk_index, total_chunks, confirmed_semester)
    elif doc_type == "pyq":
        return _pyq_prompt(text, chunk_index, total_chunks)
    elif doc_type == "academic_calendar":
        return _calendar_prompt(text, chunk_index, total_chunks)
    else:
        return _generic_prompt(text)


# ── Chunking ─────────────────────────────────────────────────────────────────

def _split_into_page_chunks(pdf_text: str) -> list[str]:
    """
    Split PDF text on PAGE markers inserted by pdf_service.
    Each chunk = up to PAGES_PER_CHUNK pages.
    Falls back to character splitting if no markers found.
    """
    # Try page-boundary splitting first
    page_pattern = re.compile(r'--- PAGE \d+ ---')
    pages = page_pattern.split(pdf_text)
    markers = page_pattern.findall(pdf_text)
    
    if len(pages) > 2:  # Real page markers found
        # Reattach markers to their pages
        labeled_pages = []
        for i, content in enumerate(pages[1:], 0):  # skip first empty split
            marker = markers[i] if i < len(markers) else f"--- PAGE {i+1} ---"
            labeled_pages.append(f"{marker}\n{content}")
        
        # Group into chunks of PAGES_PER_CHUNK
        chunks = []
        for i in range(0, len(labeled_pages), PAGES_PER_CHUNK):
            chunk = "".join(labeled_pages[i:i + PAGES_PER_CHUNK])
            if len(chunk) > MAX_CHARS_PER_CHUNK:
                # Split oversized chunk further
                for j in range(0, len(chunk), MAX_CHARS_PER_CHUNK):
                    sub = chunk[j:j + MAX_CHARS_PER_CHUNK]
                    if sub.strip():
                        chunks.append(sub)
            elif chunk.strip():
                chunks.append(chunk)
        
        logger.info(f"[Gemini] Page-based chunking: {len(labeled_pages)} pages → {len(chunks)} chunks")
        return chunks
    
    # Fallback: character-based chunks with overlap
    logger.warning("[Gemini] No page markers found. Falling back to character chunking.")
    chunks = []
    CHUNK = 25000
    OVERLAP = 1000
    start = 0
    while start < len(pdf_text):
        chunk = pdf_text[start:start + CHUNK]
        if chunk.strip():
            chunks.append(chunk)
        start += CHUNK - OVERLAP
    logger.info(f"[Gemini] Character chunking: {len(chunks)} chunks")
    return chunks


# ── Core extraction ───────────────────────────────────────────────────────────

def _call_gemini_sync(prompt: str, model_name: str) -> str:
    """Synchronous Gemini call using the new google.genai SDK."""
    response = _client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=8192,
        )
    )
    return response.text.strip()


def _parse_gemini_response(raw_text: str) -> dict:
    """
    Parse Gemini response to dict.
    Handles: bare JSON, ```json...```, partial JSON, trailing commas.
    """
    # Remove markdown code blocks
    cleaned = re.sub(r'^```(?:json)?\s*', '', raw_text, flags=re.MULTILINE)
    cleaned = re.sub(r'\s*```$', '', cleaned, flags=re.MULTILINE).strip()
    
    # Remove trailing commas before } or ] (common Gemini mistake)
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
    
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Try to find JSON object within the text
        json_match = re.search(r'\{[\s\S]*\}', cleaned)
        if json_match:
            try:
                return json.loads(json_match.group())
            except Exception:
                pass
        raise ValueError(f"Cannot parse Gemini response as JSON: {e}\nRaw: {raw_text[:200]}")


async def _extract_chunk(chunk: str, doc_type: str, chunk_idx: int, total_chunks: int, confirmed_semester: int | None = None) -> dict:
    """
    Extract structured data from one chunk using Gemini.
    Tries each model with exponential backoff.
    confirmed_semester: if set, is injected into prompt to prevent wrong inference.
    """
    prompt = _get_prompt(doc_type, chunk, chunk_idx, total_chunks, confirmed_semester)
    
    last_error = None
    for model_name in GEMINI_MODELS:
        for attempt in range(3):  # 3 retries per model
            try:
                logger.info(f"[Gemini] Chunk {chunk_idx+1}/{total_chunks} | Model: {model_name} | Attempt {attempt+1}")
                
                # Run sync Gemini call in thread pool
                loop = asyncio.get_event_loop()
                raw = await loop.run_in_executor(None, _call_gemini_sync, prompt, model_name)
                
                parsed = _parse_gemini_response(raw)
                
                # Log extraction counts
                if "Subjects" in parsed:
                    count = len(parsed["Subjects"])
                    logger.info(f"[Gemini] Chunk {chunk_idx+1}: extracted {count} subjects with {model_name}")
                    # Log per-subject semester for debugging
                    for s in parsed["Subjects"]:
                        logger.debug(f"[Gemini]   -> '{s.get('Subject Name','?')[:40]}' | Semester={s.get('Semester','?')}")
                elif "QuestionPapers" in parsed:
                    logger.info(f"[Gemini] Chunk {chunk_idx+1}: extracted {len(parsed['QuestionPapers'])} QPs with {model_name}")
                elif "Events" in parsed:
                    logger.info(f"[Gemini] Chunk {chunk_idx+1}: extracted {len(parsed['Events'])} events with {model_name}")
                
                return parsed
                
            except Exception as e:
                last_error = e
                err_str = str(e)
                
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    wait = 30 * (attempt + 1)
                    logger.warning(f"[Gemini] Rate limited on {model_name}. Waiting {wait}s...")
                    await asyncio.sleep(wait)
                elif "API_KEY" in err_str or "403" in err_str:
                    logger.error(f"[Gemini] Auth error on {model_name}: {e}")
                    break  # Don't retry auth errors
                else:
                    wait = 5 * (attempt + 1)
                    logger.warning(f"[Gemini] {model_name} attempt {attempt+1} failed: {e}. Waiting {wait}s...")
                    await asyncio.sleep(wait)
        
        logger.warning(f"[Gemini] All attempts failed for model {model_name}. Trying next model...")
    
    logger.error(f"[Gemini] Chunk {chunk_idx+1}: ALL models failed. Last error: {last_error}")
    return {}


# ── Deduplication ─────────────────────────────────────────────────────────────

def _deduplicate(entities: list, key_fields: list) -> list:
    """
    Remove duplicates based on key fields.
    Keeps the entry with the most data (most non-null fields).
    """
    groups = {}
    for ent in entities:
        key = "_".join(str(ent.get(k, "") or "").strip().lower()[:30] for k in key_fields)
        key = re.sub(r'\s+', ' ', key).strip()
        if not key.replace("_", "").strip():
            continue
        if key not in groups:
            groups[key] = ent
        else:
            # Keep the richer entry
            existing = groups[key]
            existing_fields = sum(1 for v in existing.values() if v)
            new_fields = sum(1 for v in ent.values() if v)
            if new_fields > existing_fields:
                groups[key] = ent
    
    return list(groups.values())


# ── Main public function ──────────────────────────────────────────────────────

async def extract_structured_data_from_pdf_text(pdf_text: str, document_type) -> dict:
    """
    Main extraction function:
      1. Pre-detect semester from PDF headings (regex, before Gemini)
      2. Chunk by page boundaries
      3. Call Gemini per chunk with confirmed semester injected into prompt
      4. Enforce confirmed semester on every extracted subject
      5. Merge, deduplicate, validate and return
    """
    doc_type = document_type.value if hasattr(document_type, 'value') else str(document_type)
    
    logger.info(f"[Gemini] Starting extraction | type={doc_type} | text_length={len(pdf_text)}")
    t0 = time.perf_counter()
    
    # ── Step 1: Pre-detect semester from raw PDF text ─────────────────────────
    confirmed_semester: int | None = None
    if doc_type == "syllabus":
        confirmed_semester = detect_semester_from_text(pdf_text)
        if confirmed_semester:
            logger.info(f"[Gemini] *** PRE-DETECTED SEMESTER = {confirmed_semester} *** (will be enforced on all subjects)")
        else:
            logger.warning("[Gemini] Could not pre-detect semester. Gemini will attempt to infer from section headers.")
    
    # Split into page-aware chunks
    chunks = _split_into_page_chunks(pdf_text)
    logger.info(f"[Gemini] Processing {len(chunks)} chunk(s)")
    
    all_subjects = []
    all_pyqs = []
    all_events = []
    fallback_data = {}
    
    for i, chunk in enumerate(chunks):
        logger.info(f"[Gemini] --- Chunk {i+1}/{len(chunks)} | {len(chunk)} chars ---")
        result = await _extract_chunk(chunk, doc_type, i, len(chunks), confirmed_semester)
        
        if "Subjects" in result:
            count = len(result["Subjects"])
            all_subjects.extend(result["Subjects"])
            logger.info(f"[Gemini] Chunk {i+1}: +{count} subjects (running total: {len(all_subjects)})")
        elif "QuestionPapers" in result:
            count = len(result["QuestionPapers"])
            all_pyqs.extend(result["QuestionPapers"])
            logger.info(f"[Gemini] Chunk {i+1}: +{count} question papers (running total: {len(all_pyqs)})")
        elif "Events" in result:
            count = len(result["Events"])
            all_events.extend(result["Events"])
            logger.info(f"[Gemini] Chunk {i+1}: +{count} events (running total: {len(all_events)})")
        elif result:
            fallback_data.update(result)
        else:
            logger.warning(f"[Gemini] Chunk {i+1}: empty result")
    
    # ── Step 2: Enforce confirmed semester on every subject ───────────────────
    if confirmed_semester and all_subjects:
        overridden = 0
        for subj in all_subjects:
            raw_sem = str(subj.get("Semester", "")).strip()
            if raw_sem != str(confirmed_semester):
                logger.warning(
                    f"[Gemini] Semester override: '{subj.get('Subject Name','?')[:40]}' "
                    f"had Semester='{raw_sem}' → forced to {confirmed_semester}"
                )
                subj["Semester"] = str(confirmed_semester)
                overridden += 1
        if overridden:
            logger.info(f"[Gemini] Enforced Semester {confirmed_semester} on {overridden} subject(s) that had wrong/null value")
    
    # Deduplicate
    final = {}
    if all_subjects:
        deduped = _deduplicate(all_subjects, ["Subject Code", "Subject Name"])
        final["Subjects"] = deduped
        logger.info(f"[Gemini] Subjects: {len(all_subjects)} raw -> {len(deduped)} after dedup")
    
    if all_pyqs:
        deduped = _deduplicate(all_pyqs, ["Subject Code", "Subject Name", "Academic Year"])
        final["QuestionPapers"] = deduped
        logger.info(f"[Gemini] QuestionPapers: {len(all_pyqs)} raw -> {len(deduped)} after dedup")
    
    if all_events:
        deduped = _deduplicate(all_events, ["event_title", "event_date"])
        final["Events"] = deduped
        logger.info(f"[Gemini] Events: {len(all_events)} raw -> {len(deduped)} after dedup")
    
    if fallback_data:
        final.update(fallback_data)
    
    elapsed = round(time.perf_counter() - t0, 2)
    
    if not final:
        logger.error(f"[Gemini] EXTRACTION FAILED: no data returned after {len(chunks)} chunk(s) in {elapsed}s")
        return {"error": "Gemini extraction returned no structured data. Check model availability and API key."}
    
    total_entities = len(final.get("Subjects", [])) + len(final.get("QuestionPapers", [])) + len(final.get("Events", []))
    logger.info(f"[Gemini] Extraction complete: {total_entities} total entities in {elapsed}s")
    return final


# ── AI Answer generation ──────────────────────────────────────────────────────

def _normalize_syllabus_payload(payload: dict | None) -> dict:
    """Normalize syllabus JSON from Gemini so it matches the app's Units/Topics schema."""
    if not isinstance(payload, dict):
        return {"Units": []}

    def normalize_unit(unit, index):
        if not isinstance(unit, dict):
            return None
        topics = unit.get("Topics") or unit.get("topics") or []
        if not isinstance(topics, list):
            topics = []

        def normalize_topic(topic):
            if isinstance(topic, dict):
                return str(topic.get("name") or topic.get("Topic") or topic.get("title") or topic.get("topic") or "").strip()
            return str(topic).strip()

        return {
            "Unit Name": unit.get("Unit Name") or unit.get("unit_name") or unit.get("name") or f"Unit {index + 1}",
            "Topics": [topic for topic in [normalize_topic(item) for item in topics] if topic],
        }

    units = payload.get("Units") or payload.get("units") or []
    if not isinstance(units, list):
        units = []

    normalized_units = [normalized for normalized in [normalize_unit(unit, i) for i, unit in enumerate(units)] if normalized is not None]

    if not normalized_units and isinstance(payload.get("Subjects") or payload.get("subjects"), list):
        subject_rows = payload.get("Subjects") or payload.get("subjects") or []
        for subject in subject_rows:
            if not isinstance(subject, dict):
                continue
            subject_units = subject.get("Units") or subject.get("units") or []
            if not isinstance(subject_units, list):
                continue
            for i, unit in enumerate(subject_units):
                normalized = normalize_unit(unit, i)
                if normalized:
                    normalized_units.append(normalized)

    if not normalized_units and isinstance(payload.get("subjects"), list):
        for subject in payload["subjects"]:
            if not isinstance(subject, dict):
                continue
            units_list = subject.get("Units") or subject.get("units") or []
            if not isinstance(units_list, list):
                continue
            for i, unit in enumerate(units_list):
                normalized = normalize_unit(unit, i)
                if normalized:
                    normalized_units.append(normalized)

    payload_copy = {k: v for k, v in payload.items() if not isinstance(v, (dict, list)) or k not in {"Units", "units", "Subjects", "subjects"}}
    payload_copy["Units"] = normalized_units
    return payload_copy


async def extract_subject_list_from_text(raw_text: str) -> dict:
    """Extract a list of subject rows from pasted text or an uploaded PDF/image."""
    prompt = f"""You are extracting a university subject list. Return ONLY valid JSON.

Rules:
1. Detect each subject as an object with: Subject Name, Subject Code, Credits.
2. Credits must be an integer number; if missing, use null.
3. Deduplicate repeated subjects.
4. Prefer the source document text; do not invent values.
5. If no subject names are found, return {{"Subjects": []}}.

JSON FORMAT:
{{
  "Subjects": [
    {{"Subject Name": "", "Subject Code": "", "Credits": 3}}
  ]
}}

TEXT:
{raw_text}
"""
    try:
        response = _client.models.generate_content(
            model="gemini-flash-lite-latest",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=4096,
            )
        )
        parsed = _parse_gemini_response(response.text)
        if not isinstance(parsed, dict):
            return {"Subjects": []}
        subjects = parsed.get("Subjects") or parsed.get("subjects") or []
        cleaned_items = []
        for item in subjects:
            if not isinstance(item, dict):
                continue
            cleaned_items.append({
                "Subject Name": str(item.get("Subject Name") or item.get("subject_name") or "").strip(),
                "Subject Code": str(item.get("Subject Code") or item.get("subject_code") or "").strip(),
                "Credits": item.get("Credits") or item.get("credits") or None,
            })
        return {"Subjects": [i for i in cleaned_items if i["Subject Name"]]}
    except Exception as exc:
        logger.warning(f"[Gemini] Subject list extraction failed: {exc}")
        return {"Subjects": []}


async def extract_syllabus_from_image(file_bytes: bytes, mime_type: str) -> dict:
    """Extract syllabus from an uploaded image using Gemini vision capability."""
    prompt = """Extract the syllabus as clean structured data. Return ONLY valid JSON.

Required JSON format:
{
  "Subjects": [
    {
      "Semester": "number or null",
      "Subject Name": "exact subject name",
      "Subject Code": "exact code or null",
      "Credits": number or null,
      "Units": [{"Unit Name": "", "Topics": [""]}]
    }
  ]
}

Please be faithful to the original document and preserve names/codes accurately.
"""
    try:
        response = _client.models.generate_content(
            model="gemini-flash-lite-latest",
            contents=[
                types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                prompt,
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=8192,
            )
        )
        parsed = _parse_gemini_response(response.text)
        if not isinstance(parsed, dict):
            return {"Subjects": []}
        payload = {"Subjects": parsed.get("Subjects") or parsed.get("subjects") or []}
        return _normalize_syllabus_payload({"Subjects": payload["Subjects"]})
    except Exception as exc:
        logger.warning(f"[Gemini] Image syllabus extraction failed: {exc}")
        return {"error": str(exc), "Subjects": []}


async def generate_answer(question_text: str) -> str:
    """Generates an answer for a PYQ question using Gemini."""
    prompt = f"""You are an expert academic tutor for university students.
Provide a comprehensive, well-structured, and accurate answer to the following exam question.
If the question asks for code, provide clean code with explanations.
If the question is theoretical, explain with clear points or paragraphs.
Format your answer using markdown for readability.

Question: {question_text}
"""
    for model_name in GEMINI_MODELS:
        try:
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(None, _call_gemini_sync, prompt, model_name)
            return raw
        except Exception as e:
            logger.warning(f"[Gemini:AI] {model_name} failed for answer generation: {e}")
    
    return "I'm sorry, I couldn't generate an answer at this time. Please try again."
