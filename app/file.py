
from cloudinary.uploader import upload # type: ignore
from app.logging import logger
from fastapi import UploadFile, HTTPException
from app.config import settings


async def upload_to_cloudinary(media_file: UploadFile, new_media_name: str, folder_path: str, resource_type: str):
    """Upload the media file to Cloudinary."""
    try:
        # Reset the file pointer to the beginning of the file
        await media_file.seek(0)
        
        # Read the file content
        file_content = await media_file.read()
        
        logger.info(f"Uploading {media_file.filename} to Cloudinary...")
        logger.info(f"Folder path: {folder_path}")
        logger.info(f"File content size: {len(file_content)} bytes")

        # Upload the file to Cloudinary
        result = upload(
            file=file_content,
            resource_type=resource_type,
            public_id=new_media_name,
            folder=folder_path,
        )

        logger.info(f"Uploaded {media_file.filename} to Cloudinary successfully")
        return result
    except Exception as e:
        logger.error(f"Error in upload_to_cloudinary: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error in upload: {str(e)}")
    finally:
        # Make sure to reset the file cursor after reading
        await media_file.seek(0)

    
async def upload_picture_to_cloudinary(picture: UploadFile, id: str) -> str | None:
    """Upload the profile picture file to Cloudinary."""
    # Validate file type
    allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif']
    file_extension = '.' + picture.filename.split('.')[-1].lower() # type: ignore
    
    if file_extension not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format. Allowed formats: {', '.join(allowed_extensions)}"
        )
    
    # Read file content
    file_content = await picture.read()
    
    # Check file size (limit to config limit)
    if len(file_content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {settings.MAX_UPLOAD_SIZE / (1024 * 1024)}MB."
        )
    
    # Upload to Cloudinary
    try:
        drive_file = await upload_to_cloudinary(
            picture,
            picture.filename, # type: ignore
            f"pictures/{id}",
            "image"
        )
        url = drive_file["secure_url"]
        return url
    except Exception as e:
        print(f"Error uploading picture: {str(e)}")
        return None
