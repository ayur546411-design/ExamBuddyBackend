from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import extract
from typing import List, Optional

from app.db.session import get_db
from app.models.calendar import AcademicCalendarEvent
from app.schemas.calendar import CalendarEvent
from app.models.user import User
from app.api.v1.endpoints.users import get_current_user

router = APIRouter()

@router.get("/", response_model=List[CalendarEvent])
async def get_calendar_events(
    month: int = Query(..., ge=1, le=12, description="Month (1-12)"),
    year: int = Query(..., ge=2000, le=2100, description="Year (e.g. 2026)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieve academic calendar events for a specific month and year,
    filtered automatically by the current user's school and department.
    """
    if not current_user.school_id:
        raise HTTPException(status_code=400, detail="User is not assigned to a school")

    # Fetch events that apply to the user's school
    # Additionally, department_id can be NULL (applies to whole school) or match the user's department
    query = select(AcademicCalendarEvent).where(
        AcademicCalendarEvent.school_id == current_user.school_id,
        extract('month', AcademicCalendarEvent.event_date) == month,
        extract('year', AcademicCalendarEvent.event_date) == year
    )

    if current_user.department_id:
        query = query.where(
            (AcademicCalendarEvent.department_id == None) | 
            (AcademicCalendarEvent.department_id == current_user.department_id)
        )
    else:
        query = query.where(AcademicCalendarEvent.department_id == None)

    query = query.order_by(AcademicCalendarEvent.event_date.asc())
    
    result = await db.execute(query)
    return result.scalars().all()
