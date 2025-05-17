import re
import time
import uuid
import base64
import asyncio
import requests
from typing import Any
from celery import Celery
from sqlmodel import select, Session
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, BaseMessage
from app.config import settings
from app.db import engine, FileAnnotation
from app.file import upload_picture_to_cloudinary
from app.email import send_email, generate_reminder_email

celery = Celery(
    "tasks",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL
)
celery.autodiscover_tasks(['app.tasks', 'app.main'])

@celery.task()
def upload_to_cloudinary_task(file_bytes: bytes, filename: str, task_id: str) -> dict[str, Any]:
    """
    Uploads a file to Cloudinary asynchronously and returns the URL.
    Args:
        file_bytes (bytes): The binary content of the file to upload.
        filename (str): Name of the file to be uploaded.
        task_id (str): Unique identifier for the upload task.
    Returns:
        dict[str, Any]: Dictionary containing:
            - file_url (str): URL of the uploaded file on Cloudinary, empty string if upload fails
            - task_id (str): The original task ID passed in
    Note:
        This function runs an async operation synchronously using asyncio.run()
    """

    url = asyncio.run(upload_picture_to_cloudinary(file_bytes, filename, task_id)) or ""
    return {"file_url": url, "task_id": task_id}

@celery.task()
def db_commit_file_annotation(prev: dict[str, Any]) -> dict[str, Any]:
    """
    Commits file annotation data to the database.
    This function takes a dictionary containing task and file information and creates a new
    FileAnnotation record in the database with null annotation.
    Args:
        prev (dict[str, Any]): Dictionary containing:
            - task_id: ID of the associated task
            - file_url: URL of the file to be annotated
    Returns:
        dict[str, Any]: The input dictionary unchanged
    """

    with Session(engine) as session:
        db_obj = FileAnnotation(
            task_id=prev["task_id"],
            file_url=prev["file_url"],
            annotation=None
        )
        session.add(db_obj)
        session.commit()
    return prev

vlm = ChatOllama(model="moondream:v2", base_url=settings.OLLAMA_BASE_URL)

@celery.task()
def invoke_llm(prev: dict[str, Any], prompt: str) -> dict[str, Any]:
    """
    Invokes a vision-language model (VLM) with an image and prompt to generate annotations.
    This function downloads an image from a URL, converts it to base64 format, and passes it along
    with a text prompt to a VLM for analysis. The results are stored in the input dictionary.
    Args:
        prev (dict[str, Any]): Dictionary containing at minimum a 'file_url' key with the image URL
        prompt (str): The text prompt to send to the VLM along with the image
    Returns:
        dict[str, Any]: Updated input dictionary with new 'annotation' key containing the VLM response
    Raises:
        ValueError: If the image file cannot be accessed after maximum retry attempts
    Example:
        result = invoke_llm({
            'file_url': 'https://example.com/image.jpg'
        }, 'Describe this image')
    """

    url = prev["file_url"]
    max_retries = 5
    image_bytes = None

    for _ in range(max_retries):
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                image_bytes = resp.content
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        raise ValueError(f"File {url} is not accessible after {max_retries} retries.")

    # Encode the image to base64 string as required for input
    img_b64 = base64.b64encode(image_bytes).decode("utf-8")
    image_data = f"data:image/jpeg;base64,{img_b64}"

    def _invoke():
        return vlm.invoke(
            input=[
                HumanMessage(
                    content=[
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": image_data}
                    ]
                )
            ]
        )
    annotation: BaseMessage = _invoke()
    prev["annotation"] = annotation.model_dump()
    return prev

@celery.task()
def update_file_annotation(prev: dict[str, Any]) -> dict[str, Any]:
    """Updates the annotation content of a FileAnnotation record.
    This function takes a task dictionary containing task_id and annotation details,
    updates the corresponding FileAnnotation record in the database with the new
    annotation content.
    Args:
        prev (dict[str, Any]): Dictionary containing:
            - task_id: ID of the task associated with the file annotation
            - annotation: Dictionary containing the content to update
    Returns:
        dict[str, Any]: The input dictionary unchanged
    Raises:
        ValueError: If no FileAnnotation is found for the given task_id
    """

    with Session(engine) as session:
        stmt = select(FileAnnotation).where(FileAnnotation.task_id == prev["task_id"])
        result = session.exec(stmt)
        file = result.first()
        if file is None:
            raise ValueError(f"No FileAnnotation found for task {prev['task_id']}")
        file.sqlmodel_update({"annotation": prev["annotation"].get("content")})
        session.commit()
    return prev

@celery.task()
def send_email_task(prev: dict[str, Any], email: str) -> str:
    """Send an email notification with results link to the specified recipient.
    This function sends an email containing a link to the annotation results page.
    It uses the task ID from the previous task's output to generate the results URL.
    Args:
        prev (dict[str, Any]): Dictionary containing the previous task's output,
            must include 'task_id' key.
        email (str): Recipient's email address.
    Returns:
        str: Confirmation message indicating the email was sent, including recipient
            email and task ID.
    Raises:
        KeyError: If 'task_id' is not present in prev dictionary.
        RuntimeError: If email sending fails.
    """

    async def _send():
        link = f"{settings.FRONTEND_HOST}/results/{prev['task_id']}"
        content = generate_reminder_email(email_to=email, link=link)
        await send_email(
            email_to=email,
            subject="Your annotation is ready",
            html_content=content.html_content,
        )
        return f"Email sent to {email} for task {prev['task_id']}"
    return asyncio.run(_send())

email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

def is_valid_email(email: str) -> bool:
    """
    Validates an email address format using a regular expression pattern.
    Args:
        email (str): The email address to validate.
    Returns:
        bool: True if the email format is valid, False otherwise.
    Example:
        >>> is_valid_email("user@example.com")
        True
        >>> is_valid_email("invalid-email")
        False
    """

    return re.match(email_regex, email) is not None

def full_annotation_flow(file_bytes: bytes, filename: str, prompt: str, email: str = ""):
    """
    Orchestrates a complete file annotation workflow using Celery task chaining.
    This function coordinates multiple tasks including file upload, database operations,
    LLM processing, and optional email notification in a sequential chain.
    Args:
        file_bytes (bytes): The binary content of the file to be processed
        filename (str): Name of the file being processed
        prompt (str): The prompt to be used for LLM annotation
        email (str, optional): Email address for notification. Defaults to empty string
    Returns:
        celery.result.AsyncResult: A Celery result object representing the chained task execution
    Example:
        >>> result = full_annotation_flow(file_content, "document.pdf", "Analyze this text", "user@example.com")
        >>> print(result.id)
    """

    task_id = str(uuid.uuid4())
    chain_tasks = (
        upload_to_cloudinary_task.s(file_bytes, filename, task_id)
        | db_commit_file_annotation.s()
        | invoke_llm.s(prompt)
        | update_file_annotation.s()
    )
    if is_valid_email(email):
        chain_tasks |= send_email_task.s(email=email)
    result = chain_tasks.apply_async()
    print(f"Full annotation workflow started, chain id = {result.id}")
    return result