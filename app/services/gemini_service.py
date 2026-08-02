import google.generativeai as genai
from app.core.config import settings
import logging
import json
import re

logger = logging.getLogger(__name__)

genai.configure(api_key=settings.GEMINI_API_KEY)

def _get_prompt_for_type(doc_type: str, text: str) -> str:
    base_instructions = "Analyze the following extracted PDF text and strictly output ONLY valid JSON format. Do not include markdown code blocks or any other text before or after the JSON.\n\n"
    
    if doc_type == "syllabus":
        return base_instructions + f"""
Format the syllabus into this JSON structure:
{{
  "Semester": "string or null",
  "Subject Name": "string or null",
  "Subject Code": "string or null",
  "Credits": "number or null",
  "Units": [
    {{
      "Unit Name": "string",
      "Topics": ["string"]
    }}
  ],
  "Learning Outcomes": ["string"],
  "Practicals": ["string"],
  "Reference Books": ["string"],
  "Keywords": ["string"]
}}

Extracted Text:
{text}
"""
    elif doc_type == "pyq":
        return base_instructions + f"""
Format the Previous Year Question Paper into this JSON structure:
{{
  "Subject Name": "string or null",
  "Subject Code": "string or null",
  "Semester": "string or null",
  "Academic Year": "string or null",
  "Exam Type": "string or null",
  "Total Marks": "number or null",
  "Duration": "string or null",
  "Questions": [
    {{
      "Question Number": "string",
      "Question Text": "string",
      "Marks": "number or null",
      "Unit": "string or null"
    }}
  ],
  "Unit-wise Question Mapping": {{"Unit 1": ["Question 1"]}},
  "Frequently Asked Questions": ["string"],
  "Important Topics": ["string"],
  "Keywords": ["string"]
}}

Extracted Text:
{text}
"""
    elif doc_type == "academic_calendar":
        return base_instructions + f"""
Format the Academic Calendar into an array of events within this JSON structure:
{{
  "Events": [
    {{
      "event_title": "string",
      "event_date": "YYYY-MM-DD",
      "description": "string or null"
    }}
  ]
}}

Extracted Text:
{text}
"""
    else:
        # Generic fallback
        return base_instructions + f"""
Extract key metadata and summarize the document in this JSON structure:
{{
  "Title": "string",
  "Summary": "string",
  "Key Points": ["string"],
  "Keywords": ["string"]
}}

Extracted Text:
{text}
"""

async def extract_structured_data_from_pdf_text(pdf_text: str, document_type: str) -> dict:
    """
    Sends extracted PDF text to Gemini to generate structured JSON data based on document type.
    """
    prompt = _get_prompt_for_type(document_type.value if hasattr(document_type, 'value') else document_type, pdf_text)
    
    models_to_try = [
        'gemini-flash-latest',
        'gemini-2.5-flash',
        'gemini-2.0-flash',
        'gemini-3.5-flash',
        'gemini-pro-latest'
    ]
    
    for model_name in models_to_try:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            raw_text = response.text.strip()
            
            # Clean the response in case it contains markdown blocks like ```json ... ```
            cleaned_text = re.sub(r'^```json\s*', '', raw_text)
            cleaned_text = re.sub(r'\s*```$', '', cleaned_text).strip()
            
            return json.loads(cleaned_text)
        except Exception as e:
            logger.error(f"Gemini API failed with model {model_name}: {str(e)}")
            if model_name == models_to_try[-1]:
                # All models failed
                return {"error": "Failed to parse structured JSON from Gemini using all available models.", "details": str(e)}
