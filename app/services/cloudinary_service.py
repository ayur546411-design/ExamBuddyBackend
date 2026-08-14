import cloudinary
import cloudinary.uploader
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# No global config, keys passed directly on upload

async def upload_file_to_cloudinary(file_bytes: bytes, filename: str, folder: str = "ggu_prep", resource_type: str = "raw") -> dict:
    """
    Uploads a file to Cloudinary and returns a dict with secure_url and public_id.
    """
    try:
        import re
        safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', filename.rsplit('.', 1)[0])
        response = cloudinary.uploader.upload(
            file_bytes,
            folder=folder,
            public_id=safe_name,
            resource_type=resource_type,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            cloud_name=settings.CLOUDINARY_CLOUD_NAME
        )
        return {
            "url": response.get("secure_url"),
            "public_id": response.get("public_id"),
            "format": response.get("format"),
            "bytes": response.get("bytes")
        }
    except Exception as e:
        logger.error(f"Cloudinary upload failed: {str(e)}")
        raise
