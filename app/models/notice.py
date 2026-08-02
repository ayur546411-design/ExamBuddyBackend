from sqlalchemy import Column, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
import uuid

class Notice(Base):
    __tablename__ = "notices"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    school_id = Column(String, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    department_id = Column(String, ForeignKey("departments.id", ondelete="CASCADE"), nullable=True, index=True)
    
    title = Column(String, nullable=False, index=True)
    content = Column(String, nullable=False)
    attachment_url = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
