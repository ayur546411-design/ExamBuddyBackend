"""
pdf_service.py — Page-by-page PDF text extraction
===================================================
Strategy (in priority order):
  1. pdfplumber  — handles tables, multi-column, complex layouts
  2. pypdf        — modern, handles most standard PDFs
  3. PyPDF2       — legacy fallback

Every page is processed individually and logged.
Empty pages are noted but never silently skipped.
"""
import io
import logging

logger = logging.getLogger(__name__)


async def extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    Extract ALL text from a PDF, page by page.
    Returns the full concatenated text with page markers.
    Never silently drops pages — logs every empty or failed page.
    """
    pages_text = await _extract_pages(file_bytes)
    
    if not pages_text:
        raise Exception("No text could be extracted from the PDF. It may be a scanned image-only PDF.")
    
    # Combine with page markers so Gemini can understand page boundaries
    full_text = ""
    for page_num, text in pages_text.items():
        if text.strip():
            full_text += f"\n--- PAGE {page_num} ---\n{text}\n"
        else:
            full_text += f"\n--- PAGE {page_num} (empty) ---\n"
    
    non_empty = sum(1 for t in pages_text.values() if t.strip())
    logger.info(f"[PDF] Extracted {non_empty}/{len(pages_text)} non-empty pages | Total chars: {len(full_text)}")
    
    return full_text.strip()


async def extract_text_from_pdf_by_pages(file_bytes: bytes) -> dict:
    """
    Returns a dict of {page_number: text} for page-aware chunking in Gemini service.
    """
    return await _extract_pages(file_bytes)


async def _extract_pages(file_bytes: bytes) -> dict:
    """
    Try pdfplumber → pypdf → PyPDF2, return {page_num: text}.
    """
    # Method 1: pdfplumber (best for tables and multi-column)
    try:
        return _extract_with_pdfplumber(file_bytes)
    except Exception as e:
        logger.warning(f"[PDF] pdfplumber failed: {e}. Trying pypdf...")

    # Method 2: pypdf (modern, good for standard PDFs)
    try:
        return _extract_with_pypdf(file_bytes)
    except Exception as e:
        logger.warning(f"[PDF] pypdf failed: {e}. Trying PyPDF2...")

    # Method 3: PyPDF2 (legacy fallback)
    try:
        return _extract_with_pypdf2(file_bytes)
    except Exception as e:
        logger.error(f"[PDF] All extraction methods failed: {e}")
        raise Exception(f"Failed to extract text from PDF using all available methods: {e}")


def _extract_with_pdfplumber(file_bytes: bytes) -> dict:
    """
    pdfplumber: best for tables, multi-column, complex layouts.
    Extracts text character by character in reading order.
    """
    import pdfplumber
    pages = {}
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        total = len(pdf.pages)
        logger.info(f"[PDF:pdfplumber] Total pages detected: {total}")
        for i, page in enumerate(pdf.pages, start=1):
            try:
                # extract_text with layout=True preserves column order
                text = page.extract_text(layout=True) or ""
                if not text.strip():
                    # Try without layout if layout mode returns empty
                    text = page.extract_text() or ""
                
                # Also extract any tables as text
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if row:
                            row_text = " | ".join(str(cell or "").strip() for cell in row)
                            if row_text.strip():
                                text += "\n" + row_text
                
                pages[i] = text
                status = f"{len(text)} chars" if text.strip() else "EMPTY"
                logger.info(f"[PDF:pdfplumber] Page {i}/{total}: {status}")
            except Exception as e:
                logger.warning(f"[PDF:pdfplumber] Page {i} failed: {e}")
                pages[i] = ""
    return pages


def _extract_with_pypdf(file_bytes: bytes) -> dict:
    """
    pypdf: modern successor to PyPDF2.
    """
    from pypdf import PdfReader
    pages = {}
    reader = PdfReader(io.BytesIO(file_bytes))
    total = len(reader.pages)
    logger.info(f"[PDF:pypdf] Total pages: {total}")
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
            pages[i] = text
            status = f"{len(text)} chars" if text.strip() else "EMPTY"
            logger.info(f"[PDF:pypdf] Page {i}/{total}: {status}")
        except Exception as e:
            logger.warning(f"[PDF:pypdf] Page {i} failed: {e}")
            pages[i] = ""
    return pages


def _extract_with_pypdf2(file_bytes: bytes) -> dict:
    """
    PyPDF2: legacy fallback.
    """
    from PyPDF2 import PdfReader
    pages = {}
    reader = PdfReader(io.BytesIO(file_bytes))
    total = len(reader.pages)
    logger.info(f"[PDF:PyPDF2] Total pages: {total}")
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
            pages[i] = text
            status = f"{len(text)} chars" if text.strip() else "EMPTY"
            logger.info(f"[PDF:PyPDF2] Page {i}/{total}: {status}")
        except Exception as e:
            logger.warning(f"[PDF:PyPDF2] Page {i} failed: {e}")
            pages[i] = ""
    return pages
