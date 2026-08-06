from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging

from app.services.gemini_service import generate_answer
from app.models.user import User
from app.api.v1.endpoints.users import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

class AskAIRequest(BaseModel):
    question_text: str

class AskAIResponse(BaseModel):
    answer: str

@router.post("/solve", response_model=AskAIResponse)
async def solve_question(
    request: AskAIRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Generate an AI answer for a given question text.
    """
    logger.info(f"[AI API] Solving question for user {current_user.full_name}")
    
    if not request.question_text.strip():
        raise HTTPException(status_code=400, detail="Question text cannot be empty")
        
    answer = await generate_answer(request.question_text)
    
    return AskAIResponse(answer=answer)
