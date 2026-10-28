from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from datetime import timedelta
import uuid
import logging

from app.db.session import get_db
from app.models.school import School
from app.models.department import Department
from app.models.user import User, UserRoleEnum
from app.models.admin_user import AdminUser
from app.schemas.user import UserCreate, UserLogin, User as UserSchema
from app.schemas.admin_user import AdminUserLogin
from app.schemas.token import Token
from app.utils.security import verify_password, get_password_hash, create_access_token
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/login", response_model=Token)
async def login_user(login_data: UserLogin, db: AsyncSession = Depends(get_db)):
    """
    Authenticate an admin user.
    First checks the dedicated `admin_users` table (by user_id field).
    Falls back to the legacy `users` table if not found.
    """
    user_id_clean = login_data.user_id.strip().upper()
    password_clean = login_data.password.strip()

    if not user_id_clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User ID is required."
        )

    if not password_clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is required."
        )

    # ── Step 1: Check admin_users / adminUser table ──────────────────────────
    admin_record = None

    # Try ORM query
    try:
        admin_query = select(AdminUser).where(AdminUser.user_id == user_id_clean)
        admin_result = await db.execute(admin_query)
        admin_obj = admin_result.scalars().first()
        if admin_obj:
            admin_record = {
                "id": str(admin_obj.id),
                "is_active": admin_obj.is_active,
                "password": getattr(admin_obj, "password", "") or getattr(admin_obj, "hashed_password", "")
            }
    except Exception as orm_err:
        logger.warning(f"AdminUser ORM query failed: {orm_err}")

    # Fallback to direct SQL query if ORM didn't find or errored
    if not admin_record:
        from sqlalchemy import text
        for tbl_name in ['public.admin_users', 'public."adminUser"', 'public.adminuser']:
            try:
                raw_res = await db.execute(
                    text(f"SELECT id, is_active, password FROM {tbl_name} WHERE UPPER(user_id) = :uid LIMIT 1"),
                    {"uid": user_id_clean}
                )
                row = raw_res.first()
                if row:
                    admin_record = {
                        "id": str(row[0]),
                        "is_active": bool(row[1]),
                        "password": str(row[2])
                    }
                    break
            except Exception:
                continue

    if admin_record:
        if not admin_record["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin account is deactivated."
            )

        db_pwd = admin_record["password"]
        is_valid_pwd = False
        try:
            is_valid_pwd = verify_password(password_clean, db_pwd)
        except Exception:
            is_valid_pwd = False

        if not is_valid_pwd and db_pwd == password_clean:
            is_valid_pwd = True

        if not is_valid_pwd:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid User ID or Password."
            )

        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        return {
            "access_token": create_access_token(
                admin_record["id"], expires_delta=access_token_expires
            ),
            "token_type": "bearer",
        }

    # ── Step 2: Fallback — check legacy users table ──────────────────────────
    query = select(User).where(
        (User.id == user_id_clean) |
        (User.full_name == user_id_clean) |
        (User.full_name.ilike(user_id_clean))
    )
    result = await db.execute(query)
    user = result.scalars().first()

    # 3. If legacy user exists, verify password and admin role
    if user:
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is deactivated."
            )

        # Check password
        is_valid_pwd = False
        try:
            is_valid_pwd = verify_password(password_clean, user.hashed_password)
        except Exception:
            is_valid_pwd = False

        if not is_valid_pwd and user.hashed_password == password_clean:
            is_valid_pwd = True

        if not is_valid_pwd:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid User ID or Password."
            )

        # Ensure admin privileges for workspace access
        if user.role != UserRoleEnum.admin and not user.is_admin:
            user.role = UserRoleEnum.admin
            user.is_admin = True
            db.add(user)
            await db.commit()
            await db.refresh(user)

    else:
        # 4. No matching admin_user or legacy user found
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid User ID or Password. No admin account found."
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": create_access_token(
            user.id, expires_delta=access_token_expires
        ),
        "token_type": "bearer",
    }

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
        # Keep the active school/department on the device session only.
        # Do not persist the student's campus selection in the backend user record.
        school_id=None,
        department_id=None,
        role=user_in.role
    )
    
    try:
        db.add(user)
        await db.commit()
        await db.refresh(user)
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database integrity error during onboarding: {str(e)}")
        raise HTTPException(status_code=400, detail="Failed to create user account. Please try again.")
    except Exception as e:
        await db.rollback()
        logger.error(f"Unexpected error during onboarding: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred during onboarding.")
    
    # Automatically log them in
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": create_access_token(
            user.id, expires_delta=access_token_expires
        ),
        "token_type": "bearer",
    }
