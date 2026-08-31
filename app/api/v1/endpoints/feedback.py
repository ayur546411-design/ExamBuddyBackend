from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.db.session import get_db, engine
from app.models.userfeedback import UserFeedback
from app.models.user import User
from app.schemas.userfeedback import UserFeedback as FeedbackSchema, UserFeedbackCreate
from app.api.v1.endpoints.users import get_current_user

router = APIRouter()


async def ensure_feedback_table() -> None:
    try:
        async with engine.begin() as conn:
            table_exists = await conn.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                        AND table_name = 'userfeedback'
                    );
                    """
                )
            )
            if table_exists.scalar():
                return

            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS userfeedback (
                        id VARCHAR PRIMARY KEY,
                        user_id VARCHAR NULL,
                        full_name VARCHAR NOT NULL,
                        feedback_type VARCHAR NOT NULL DEFAULT 'Suggestion',
                        message TEXT NOT NULL,
                        school_id VARCHAR NULL,
                        department_id VARCHAR NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        CONSTRAINT fk_userfeedback_user
                            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
                    );
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_userfeedback_user_id ON userfeedback (user_id);
                    CREATE INDEX IF NOT EXISTS ix_userfeedback_full_name ON userfeedback (full_name);
                    CREATE INDEX IF NOT EXISTS ix_userfeedback_school_id ON userfeedback (school_id);
                    CREATE INDEX IF NOT EXISTS ix_userfeedback_department_id ON userfeedback (department_id);
                    """
                )
            )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Feedback table initialization failed: {exc}") from exc


@router.post("/", response_model=FeedbackSchema, status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    payload: UserFeedbackCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not payload.full_name or not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="Full name and message are required.")

    await ensure_feedback_table()

    feedback = UserFeedback(
        user_id=current_user.id,
        full_name=payload.full_name.strip(),
        feedback_type=(payload.feedback_type or "Suggestion").strip() or "Suggestion",
        message=payload.message.strip(),
        school_id=payload.school_id or current_user.school_id,
        department_id=payload.department_id or current_user.department_id,
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
    await ensure_feedback_table()

    if current_user.role.value != "admin" and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    result = await db.execute(select(UserFeedback).order_by(UserFeedback.created_at.desc()))
    return result.scalars().all()
