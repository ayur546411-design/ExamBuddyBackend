from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(50), unique=True, nullable=False, index=True)   # e.g. "AYU07"
    password = Column(String, nullable=False)                               # stores plain text or bcrypt hash
    full_name = Column(String, nullable=True)

    is_active = Column(Boolean(), default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    @property
    def hashed_password(self):
        return self.password
