import io
from PyPDF2 import PdfReader

async def extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    Extracts all text from a PDF file provided as bytes.
    """
    try:
        pdf_file = io.BytesIO(file_bytes)
        reader = PdfReader(pdf_file)
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text.strip()
    except Exception as e:
        raise Exception(f"Failed to extract text from PDF: {str(e)}")
