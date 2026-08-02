from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
import uuid
import enum

class UserRoleEnum(str, enum.Enum):
    student = "student"
    admin = "admin"

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    school_id = Column(String, ForeignKey("schools.id", ondelete="SET NULL"), nullable=True, index=True)
    department_id = Column(String, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True)
    
    mobile_number = Column(String, unique=True, index=True, nullable=True) # Optional
    hashed_password = Column(String, nullable=False)
    
    full_name = Column(String, index=True, nullable=False)
    role = Column(Enum(UserRoleEnum), default=UserRoleEnum.student)
    profile_photo_url = Column(String, nullable=True)
    device_token = Column(String, nullable=True)
    
    is_active = Column(Boolean(), default=True)
    is_admin = Column(Boolean(), default=False) # Legacy admin flag, though role Enum exists
    last_login = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    school = relationship("School", back_populates="users")
    department = relationship("Department", back_populates="users")
