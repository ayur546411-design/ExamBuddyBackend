from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.db.session import get_db
from app.models.notification import Notification
from app.models.user import User, UserRoleEnum
from app.schemas.notification import Notification as NotificationSchema, NotificationCreate
from app.api.v1.endpoints.users import get_current_user

router = APIRouter()


def is_admin_user(user: User) -> bool:
    role_value = getattr(user, 'role', None)
    if isinstance(role_value, str):
        if role_value.lower() == UserRoleEnum.admin.value:
            return True
    if role_value == UserRoleEnum.admin:
        return True
    return bool(user.is_admin)


@router.get("/", response_model=List[NotificationSchema])
async def get_notifications(
    user_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Notification)
    if is_admin_user(current_user):
        if user_id:
            query = query.where(Notification.user_id == user_id)
        else:
            query = query.where(Notification.user_id == current_user.id)
    else:
        query = query.where(Notification.user_id == current_user.id)

    query = query.order_by(Notification.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/", response_model=NotificationSchema, status_code=status.HTTP_201_CREATED)
async def create_notification(
    notification_in: NotificationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Only admins can create notifications")

    target_user_id = notification_in.user_id or current_user.id
    notification = Notification(
        user_id=target_user_id,
        title=notification_in.title,
        body=notification_in.body,
        is_read=False,
    )
    db.add(notification)
    await db.commit()
    await db.refresh(notification)
    return notification


@router.post("/broadcast", response_model=List[NotificationSchema])
async def broadcast_notification(
    payload: NotificationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Only admins can broadcast notifications")
    # Add defensive error handling to surface runtime exceptions during broadcast
    try:
        from sqlalchemy import select as sa_select
        result = await db.execute(sa_select(User.id).where(User.is_active == True))
        user_ids = result.scalars().all()

        created = []
        for user_id in user_ids:
            item = Notification(
                user_id=user_id,
                title=payload.title,
                body=payload.body,
                is_read=False,
            )
            db.add(item)
            await db.flush()
            created.append(item)

        await db.commit()
        return created
    except Exception as exc:
        # Log and return the exception detail to help debugging (temporary)
        import logging

        logger = logging.getLogger(__name__)
        logger.exception('Broadcast failed')
        raise HTTPException(status_code=500, detail=f'Broadcast failed: {exc}')


@router.patch("/{notification_id}/read", response_model=NotificationSchema)
async def mark_notification_read(
    notification_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notification = await db.get(Notification, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    if notification.user_id != current_user.id and not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Not allowed to update this notification")

    notification.is_read = True
    db.add(notification)
    await db.commit()
    await db.refresh(notification)
    return notification


@router.post("/mark-all-read")
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Notification).where(Notification.user_id == current_user.id, Notification.is_read == False)
    )
    items = result.scalars().all()

    for item in items:
        item.is_read = True
        db.add(item)

    await db.commit()
    return {"updated": len(items)}
