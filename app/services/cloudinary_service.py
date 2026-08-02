import cloudinary
import cloudinary.uploader
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# No global config, keys passed directly on upload

async def upload_file_to_cloudinary(file_bytes: bytes, filename: str, folder: str = "ggu_prep") -> str:
    """
    Uploads a file to Cloudinary and returns the secure URL.
    """
    try:
        response = cloudinary.uploader.upload(
            file_bytes, 
            folder=folder, 
            public_id=filename,
            resource_type="auto", # Auto detects pdf, image, etc.
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            cloud_name=settings.CLOUDINARY_CLOUD_NAME
        )
        return response.get("secure_url")
    except Exception as e:
        logger.error(f"Cloudinary upload failed: {str(e)}")
        raise
