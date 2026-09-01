from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from jose import jwt
from typing import Optional

from app.db.session import get_db
from app.models.user import User, UserRoleEnum
from app.schemas.user import User as UserSchema
from app.core.config import settings

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")
http_bearer = HTTPBearer(auto_error=False)

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except jwt.JWTError:
        raise credentials_exception
        
    user = await db.get(User, user_id)
    if user is None:
        raise credentials_exception
    return user


async def optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    if credentials is None or not credentials.credentials:
        return None

    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
    except jwt.JWTError:
        return None

    return await db.get(User, user_id)

@router.get("/me", response_model=UserSchema)
async def read_users_me(current_user: User = Depends(get_current_user)):
    """
    Get current user profile
    """
    return current_user


@router.post("/me/promote-to-admin")
async def promote_current_user_to_admin(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Promote the current user to admin. This is allowed if:
    1. No admins exist yet (bootstrap mode), OR
    2. The current user is already an admin
    
    This prevents a non-admin user from promoting themselves unless they're the first admin.
    """
    # Check if any admins already exist
    admin_check = await db.execute(
        select(User).where(
            (User.role == UserRoleEnum.admin) | (User.is_admin == True)
        ).limit(1)
    )
    existing_admin = admin_check.scalars().first()
    
    # Only allow promotion if no admins exist (bootstrap) or user is already admin
    if existing_admin and existing_admin.id != current_user.id:
        # An admin already exists and it's not the current user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An admin already exists. Only admins can promote other users.",
        )
    
    # Promote to admin
    current_user.role = UserRoleEnum.admin
    current_user.is_admin = True
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    
    return {
        "message": "User promoted to admin",
        "user": current_user,
    }


def ensure_admin_user(current_user: User):
    if current_user.role != UserRoleEnum.admin and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
