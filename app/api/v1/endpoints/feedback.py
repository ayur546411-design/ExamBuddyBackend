from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.db.session import get_db
from app.models.userfeedback import UserFeedback
from app.models.user import User
from app.schemas.userfeedback import UserFeedback as FeedbackSchema, UserFeedbackCreate
from app.api.v1.endpoints.users import get_current_user, optional_current_user

router = APIRouter()


@router.post("/", response_model=FeedbackSchema, status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    payload: UserFeedbackCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    if not payload.full_name or not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="Full name and message are required.")

    feedback = UserFeedback(
        user_id=current_user.id if current_user else None,
        full_name=payload.full_name.strip(),
        feedback_type=(payload.feedback_type or "Suggestion").strip() or "Suggestion",
        message=payload.message.strip(),
        school_id=payload.school_id or (current_user.school_id if current_user else None),
        department_id=payload.department_id or (current_user.department_id if current_user else None),
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)
    return feedback


@router.get("/", response_model=List[FeedbackSchema])
async def list_feedback(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role.value != "admin" and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    result = await db.execute(select(UserFeedback).order_by(UserFeedback.created_at.desc()))
    return result.scalars().all()
