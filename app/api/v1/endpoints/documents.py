from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional, List

from app.db.session import get_db
from app.models.document import Document, DocumentTypeEnum
from app.schemas.document import Document as DocumentSchema
from app.services.cloudinary_service import upload_file_to_cloudinary
from app.services.gemini_service import extract_structured_data_from_pdf_text
from app.utils.pdf_utils import extract_text_from_pdf
from app.api.v1.endpoints.users import get_current_user
from app.models.user import User

router = APIRouter()

@router.get("/", response_model=List[DocumentSchema])
async def get_documents(
    subject_id: Optional[str] = None,
    document_type: Optional[DocumentTypeEnum] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieve documents relevant to the current user.
    Optionally filter by subject_id and document_type.
    """
    if not current_user.department_id:
        raise HTTPException(status_code=400, detail="User is not assigned to a department")
        
    query = select(Document).where(
        Document.department_id == current_user.department_id,
        Document.status == "active"
    )
    
    if subject_id:
        query = query.where(Document.subject_id == subject_id)
        
    if document_type:
        query = query.where(Document.document_type == document_type)
        
    result = await db.execute(query.order_by(Document.created_at.desc()))
    return result.scalars().all()

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
    # current_user = Depends(get_current_admin_user) # To be implemented
):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
        
    try:
        # Read file bytes
        file_bytes = await file.read()
        
        # 1. Upload to Cloudinary
        cloudinary_url = await upload_file_to_cloudinary(file_bytes, file.filename)
        
        # 2. Extract Text from PDF
        pdf_text = await extract_text_from_pdf(file_bytes)
        
        # 3. Get Structured JSON from Gemini
        structured_data = await extract_structured_data_from_pdf_text(pdf_text)
        
        # 4. Save to Database
        from app.models.document import Document
        from app.models.document import DocumentTypeEnum
        import json
        
        # We store the raw JSON from Gemini into our JSON column
        # Assuming the document is a "notice" since we don't have Subject ID yet
        new_doc = Document(
            document_type=DocumentTypeEnum.notice,
            cloudinary_url=cloudinary_url,
            title=structured_data.get("title", "Untitled Document"),
            description=structured_data.get("description", ""),
            metadata_json=structured_data
        )
        
        db.add(new_doc)
        await db.commit()
        await db.refresh(new_doc)
        
        return {
            "message": "Document processed and saved to database successfully",
            "document_id": new_doc.id,
            "cloudinary_url": cloudinary_url,
            "extracted_data": structured_data
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")
