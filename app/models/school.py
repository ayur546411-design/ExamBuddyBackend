from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
import uuid

class School(Base):
    __tablename__ = "schools"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, index=True, nullable=False)
    code = Column(String, unique=True, index=True, nullable=False)
    description = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    dean_details = Column(String, nullable=True)
    contact_info = Column(String, nullable=True)
    is_active = Column(Boolean(), default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    departments = relationship("Department", back_populates="school", cascade="all, delete-orphan")
    users = relationship("User", back_populates="school", cascade="all, delete-orphan")
