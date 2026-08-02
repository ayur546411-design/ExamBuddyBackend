import io
import PyPDF2
import logging

logger = logging.getLogger(__name__)

async def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """
    Extracts text from a PDF file provided as bytes.
    """
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text
    except Exception as e:
        logger.error(f"Failed to extract text from PDF: {str(e)}")
        raise
