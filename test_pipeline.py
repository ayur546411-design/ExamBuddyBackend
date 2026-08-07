"""
test_pipeline.py — End-to-end extraction pipeline test (no PDF needed)
Tests pdf_service and gemini_service with a synthetic syllabus text.
"""
import asyncio
import sys

async def main():
    print("=" * 60)
    print("  PIPELINE TEST")
    print("=" * 60)

    # ─── Test 1: PDF service (pdfplumber import) ──────────────────
    print("\n[1/4] Testing PDF service imports...")
    try:
        import pdfplumber
        print("  pdfplumber: OK")
    except ImportError as e:
        print(f"  pdfplumber: MISSING - {e}")

    try:
        from pypdf import PdfReader
        print("  pypdf: OK")
    except ImportError as e:
        print(f"  pypdf: MISSING - {e}")

    try:
        from PyPDF2 import PdfReader as LegacyReader
        print("  PyPDF2: OK (fallback)")
    except ImportError as e:
        print(f"  PyPDF2: MISSING - {e}")

    # ─── Test 2: Gemini model validation ────────────────────────
    print("\n[2/4] Testing Gemini model names...")
    import google.generativeai as genai
    from app.core.config import settings
    genai.configure(api_key=settings.GEMINI_API_KEY)
    
    MODELS = [
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "gemini-1.5-flash-latest",
    ]
    working_models = []
    for model_name in MODELS:
        try:
            model = genai.GenerativeModel(model_name)
            # Quick ping with minimal prompt
            resp = model.generate_content("Say 'OK' only.", 
                generation_config=genai.GenerationConfig(max_output_tokens=5))
            text = resp.text.strip()
            print(f"  {model_name}: OK (response='{text[:20]}')")
            working_models.append(model_name)
            break  # Only test first working model to save quota
        except Exception as e:
            print(f"  {model_name}: FAILED - {str(e)[:80]}")
    
    if not working_models:
        print("  WARNING: No working Gemini models found. Check API key!")

    # ─── Test 3: Page-chunking logic ─────────────────────────────
    print("\n[3/4] Testing page-chunking logic...")
    from app.services.gemini_service import _split_into_page_chunks
    
    # Simulate PDF text with page markers
    sample = "\n".join([
        f"\n--- PAGE {i} ---\nSubject {i}: Some content for page {i}. " * 5
        for i in range(1, 25)
    ])
    chunks = _split_into_page_chunks(sample)
    print(f"  Input: 24 pages of text")
    print(f"  Chunks produced: {len(chunks)}")
    print(f"  Avg chunk size: {sum(len(c) for c in chunks)//len(chunks)} chars")
    assert len(chunks) >= 3, "Expected multiple chunks"
    print("  Chunking logic: OK")

    # ─── Test 4: Mini Gemini extraction (1 subject) ──────────────
    print("\n[4/4] Testing Gemini extraction with real API call...")
    from app.services.gemini_service import extract_structured_data_from_pdf_text
    
    test_text = """
--- PAGE 1 ---
GGU B.Tech Information Technology
SEMESTER III SYLLABUS

Subject Code: IT301
Subject Name: DATA STRUCTURES AND ALGORITHMS
Credits: 4 (3L + 1T)

UNIT 1: Introduction to Data Structures
Topics: Arrays, Linked Lists, Stacks, Queues, Introduction to complexity analysis

UNIT 2: Trees and Graphs  
Topics: Binary Trees, BST, AVL Trees, Graph representations, BFS, DFS

Learning Outcomes:
1. Understand fundamental data structures
2. Analyze algorithm complexity

Reference Books:
1. Cormen, Introduction to Algorithms, MIT Press
2. Goodrich, Data Structures in Python, Wiley
"""

    try:
        result = await extract_structured_data_from_pdf_text(test_text, "syllabus")
        subjects = result.get("Subjects", [])
        print(f"  Subjects extracted: {len(subjects)}")
        if subjects:
            s = subjects[0]
            print(f"  Subject Name: {s.get('Subject Name')}")
            print(f"  Subject Code: {s.get('Subject Code')}")
            print(f"  Credits: {s.get('Credits')}")
            units = s.get('Units', [])
            print(f"  Units: {len(units)}")
            if units:
                print(f"  Unit 1: {units[0].get('Unit Name')}")
                print(f"  Unit 1 topics: {len(units[0].get('Topics', []))}")
        print("  Gemini extraction: OK")
    except Exception as e:
        print(f"  Gemini extraction: FAILED - {e}")

    print("\n" + "=" * 60)
    print("  PIPELINE TEST COMPLETE")
    print("=" * 60 + "\n")

asyncio.run(main())
