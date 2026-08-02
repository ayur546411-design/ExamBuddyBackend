from sqlalchemy import Column, String, ForeignKey, DateTime, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
import uuid

class Result(Base):
    __tablename__ = "results"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    semester_id = Column(String, ForeignKey("semesters.id", ondelete="CASCADE"), nullable=False, index=True)
    
    sgpa = Column(Float, nullable=True)
    cgpa = Column(Float, nullable=True)
    result_pdf_url = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
