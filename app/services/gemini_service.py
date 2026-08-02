import google.generativeai as genai
from app.core.config import settings
import logging
import json

logger = logging.getLogger(__name__)

genai.configure(api_key=settings.GEMINI_API_KEY)

# Use the latest recommended model for general tasks
model = genai.GenerativeModel('gemini-flash-latest') 

async def extract_structured_data_from_pdf_text(pdf_text: str) -> dict:
    """
    Sends extracted PDF text to Gemini to generate structured JSON data.
    """
    prompt = f"""
    Analyze the following extracted text from a university document (e.g., PYQ, Notes, Syllabus) 
    and extract key information into a well-structured JSON format.
    
    Required JSON keys:
    - title: Document title
    - subject: Subject name if applicable
    - semester: Semester number if mentioned
    - unit: Unit number if mentioned
    - description: A brief summary
    - keywords: Array of important keywords
    - important_topics: Array of key topics
    - metadata: Any other relevant information
    
    Return ONLY valid JSON.
    
    Text:
    {pdf_text}
    """
    
    try:
        response = model.generate_content(prompt)
        # Attempt to parse the response text as JSON
        # It's good practice to clean the response in case Gemini wraps it in ```json ... ```
        raw_text = response.text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
            
        return json.loads(raw_text.strip())
    except Exception as e:
        logger.error(f"Gemini API failed: {str(e)}")
        raise
