import google.generativeai as genai
from app.core.config import settings
import logging
import json
import re

logger = logging.getLogger(__name__)

genai.configure(api_key=settings.GEMINI_API_KEY)

def _get_prompt_for_type(doc_type: str, text: str) -> str:
    base_instructions = (
        "Analyze the ENTIRE provided PDF text. Do not stop after the first detected entity. "
        "Extract every single subject, question paper, or event found in the document. "
        "Strictly output ONLY valid JSON format. Do not include markdown code blocks or any other text before or after the JSON.\n\n"
    )
    
    if doc_type == "syllabus":
        return base_instructions + f"""
Format the syllabus into this JSON structure containing an array of ALL subjects found:
{{
  "Subjects": [
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
  ]
}}

Extracted Text:
{text}
"""
    elif doc_type == "pyq":
        return base_instructions + f"""
Format the Previous Year Question Papers into this JSON structure containing an array of ALL question papers found:
{{
  "QuestionPapers": [
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
  ]
}}

Extracted Text:
{text}
"""
    elif doc_type == "academic_calendar":
        return base_instructions + f"""
Format the Academic Calendar into this JSON structure containing an array of ALL events found:
{{
  "Events": [
    {{
      "event_title": "string",
      "event_date": "YYYY-MM-DD",
      "description": "string or null",
      "event_type": "string (e.g. standard, restricted, academic)"
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
    CHUNK_SIZE = 25000
    OVERLAP = 2000
    
    chunks = []
    start = 0
    while start < len(pdf_text):
        end = start + CHUNK_SIZE
        chunks.append(pdf_text[start:end])
        start += CHUNK_SIZE - OVERLAP
        
    all_subjects = []
    all_events = []
    all_pyqs = []
    
    models_to_try = [
        'gemini-flash-latest',
        'gemini-pro-latest',
        'gemini-3.5-flash',
        'gemini-2.0-flash'
    ]
    
    for i, chunk in enumerate(chunks):
        logger.info(f"Processing chunk {i+1}/{len(chunks)} of PDF text ({len(chunk)} chars)...")
        prompt = _get_prompt_for_type(document_type.value if hasattr(document_type, 'value') else document_type, chunk)
        
        chunk_success = False
        import time
        import asyncio
        for retry in range(3):
            for model_name in models_to_try:
                try:
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content(prompt)
                    raw_text = response.text.strip()
                    
                    cleaned_text = re.sub(r'^```json\s*', '', raw_text)
                    cleaned_text = re.sub(r'\s*```$', '', cleaned_text).strip()
                    
                    parsed = json.loads(cleaned_text)
                    
                    if "Subjects" in parsed:
                        all_subjects.extend(parsed["Subjects"])
                    elif "QuestionPapers" in parsed:
                        all_pyqs.extend(parsed["QuestionPapers"])
                    elif "Events" in parsed:
                        all_events.extend(parsed["Events"])
                    else:
                        pass
                        
                    chunk_success = True
                    break # Break out of models loop
                except Exception as e:
                    if "429" in str(e):
                        logger.warning(f"Rate limited on {model_name}. Trying next model...")
                    else:
                        logger.warning(f"Gemini API failed with model {model_name} on chunk {i+1}: {str(e)}")
            
            if chunk_success:
                break # Break out of retries loop
                
            logger.warning(f"All models failed for chunk {i+1} on attempt {retry+1}. Sleeping for 30s before retry...")
            await asyncio.sleep(30) 
            
        if not chunk_success:
            logger.error(f"Failed to parse chunk {i+1} using all available models.")
            
    # Deduplicate entities
    def deduplicate(entities, key_fields):
        unique = []
        seen = set()
        for ent in entities:
            key = "_".join(str(ent.get(k, "")).strip().lower() for k in key_fields)
            if key not in seen and key.replace("_", "") != "":
                seen.add(key)
                unique.append(ent)
        return unique

    final_dict = {}
    if all_subjects:
        final_dict["Subjects"] = deduplicate(all_subjects, ["Subject Code", "Subject Name"])
    if all_pyqs:
        final_dict["QuestionPapers"] = deduplicate(all_pyqs, ["Subject Code", "Subject Name"])
    if all_events:
        final_dict["Events"] = deduplicate(all_events, ["event_title", "event_date"])
        
    return final_dict if final_dict else {"error": "Failed to parse structured JSON from Gemini using all available models."}

async def generate_answer(question_text: str) -> str:
    """Generates an answer for a PYQ question using Gemini."""
    try:
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        prompt = f"""
You are an expert academic tutor for university students. 
Please provide a comprehensive, well-structured, and accurate answer to the following exam question. 
If the question asks for code, provide clean code with explanations.
If the question is theoretical, explain it with points or paragraphs.
Format your answer using markdown for readability.

Question: {question_text}
"""
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        logger.error(f"Error generating AI answer: {e}")
        return "I'm sorry, I couldn't generate an answer at this time due to an error."
