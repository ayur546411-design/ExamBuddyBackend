from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import timedelta
import uuid

from app.db.session import get_db
from app.models.school import School
from app.models.department import Department
from app.models.user import User
from app.schemas.user import UserCreate, User as UserSchema
from app.schemas.token import Token
from app.utils.security import verify_password, get_password_hash, create_access_token
from app.core.config import settings

router = APIRouter()

@router.post("/onboard", response_model=Token, status_code=status.HTTP_201_CREATED)
async def onboard_student(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    """
    Seamless onboarding: registers the student with just Name, School, and Department,
    and returns an access token immediately.
    """
    if not user_in.full_name or not user_in.school_id or not user_in.department_id:
        raise HTTPException(status_code=400, detail="Name, School, and Department are required.")

    school = await db.get(School, user_in.school_id)
    if school is None or not school.is_active:
        raise HTTPException(status_code=400, detail="Selected school is invalid or inactive.")

    department = await db.get(Department, user_in.department_id)
    if department is None or not department.is_active:
        raise HTTPException(status_code=400, detail="Selected department is invalid or inactive.")

    if department.school_id != user_in.school_id:
        raise HTTPException(status_code=400, detail="Selected department does not belong to the selected school.")

    user_id = str(uuid.uuid4())
    
    # We set a dummy password for the database constraint since they won't use it directly
    # Bcrypt limits passwords to 72 bytes. uuid.uuid4() string is 36 chars.
    # To be perfectly safe across all encoding layers, we truncate to 32 chars.
    dummy_password = str(uuid.uuid4())[:32]
    
    user = User(
        id=user_id,
        full_name=user_in.full_name,
        hashed_password=get_password_hash(dummy_password),
        school_id=user_in.school_id,
        department_id=user_in.department_id,
        role=user_in.role
    )
    
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    # Automatically log them in
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": create_access_token(
            user.id, expires_delta=access_token_expires
        ),
        "token_type": "bearer",
    }
