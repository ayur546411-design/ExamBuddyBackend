from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class UserFeedback(Base):
    __tablename__ = "userfeedback"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    full_name = Column(String, nullable=False, index=True)
    feedback_type = Column(String, nullable=False, default="Suggestion")
    message = Column(Text, nullable=False)
    school_id = Column(String, nullable=True, index=True)
    department_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="feedback_entries")
