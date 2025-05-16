from cloudinary.uploader import upload # type: ignore
from app.logging import logger
from fastapi import HTTPException
from app.config import settings


async def upload_to_cloudinary_bytes(file_content: bytes, filename: str, folder_path: str, resource_type: str):
    """Upload the media file to Cloudinary given file bytes and metadata."""
    try:
        logger.info(f"Uploading {filename} to Cloudinary...")
        logger.info(f"Folder path: {folder_path}")
        logger.info(f"File content size: {len(file_content)} bytes")

        # Upload the file to Cloudinary
        result = upload(
            file=file_content,
            resource_type=resource_type,
            public_id=filename,
            folder=folder_path,
            format="jpg"
        )

        logger.info(f"Uploaded {filename} to Cloudinary successfully")
        return result
    except Exception as e:
        logger.error(f"Error in upload_to_cloudinary: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error in upload: {str(e)}")

async def upload_picture_to_cloudinary(file_content: bytes, filename: str, id: str) -> str | None:
    """Upload the profile picture file to Cloudinary using file bytes."""
    # Validate file type
    allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif']
    file_extension = '.' + filename.split('.')[-1].lower()  # type: ignore

    if file_extension not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format. Allowed formats: {', '.join(allowed_extensions)}"
        )

    # Check file size (limit to config limit)
    if len(file_content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {settings.MAX_UPLOAD_SIZE / (1024 * 1024)}MB."
        )

    # Upload to Cloudinary
    try:
        drive_file = await upload_to_cloudinary_bytes(
            file_content,
            filename,
            f"pictures/{id}",
            "image"
        )
        url = drive_file["secure_url"]
        return url
    except Exception as e:
        logger.error(f"Error uploading picture: {str(e)}")
        return None