from sqlmodel import select
from celery import Celery, Task, chain # type: ignore[stub]
from typing import Any
from app.file import upload_picture_to_cloudinary
from app.db import engine, FileAnnotation
from app.config import settings
from app.email import send_email, generate_reminder_email
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, BaseMessage
from celery.app.task import Task
from sqlalchemy.ext.asyncio import AsyncSession

Task.__class_getitem__ = classmethod(lambda cls, *args, **kwargs: cls) # type: ignore[attr-defined]

celery = Celery(
    "tasks",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL
)
# celery.config_from_object('app.tasks.celeryconfig')
celery.autodiscover_tasks(['app.tasks', 'app.main']) # type: ignore

@celery.task(bind=True)
async def upload_to_cloudinary_task(self: Task[Any, Any], file_bytes: bytes, filename: str, task_id: str) -> str:
    url = await upload_picture_to_cloudinary(file_bytes, filename, task_id)
    return url if url else ""

@celery.task(bind=True)
async def db_commit_file_annotation(self: Task[Any, Any], file_url: str, task_id: str):
    async with AsyncSession(engine) as session:
        db_obj = FileAnnotation(
            task_id=task_id,
            file_url=file_url,
            annotation=None
        )
        session.add(db_obj)
        await session.commit()

vlm = ChatOllama(model="moondream:v2", base_url=settings.OLLAMA_BASE_URL)

@celery.task(bind=True) # type: ignore[decorator]
async def invoke_llm(self: Task[Any, Any], prompt: str, image_url: str) -> dict[str, Any]:
    annotation: BaseMessage = vlm.invoke(
        input=[
            HumanMessage(
                content = [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": image_url}
                ]
            )
        ]
    )

    return {"annotation": annotation.model_dump(), "task_id": self.request.id}

@celery.task(bind=True)
async def update_file_annotation(self: Task[Any, Any], prev: dict[str, Any]) -> dict[str, Any]:
    """
    1. Create a new async event loop and session.
    2. Query and update the FileAnnotation record.
    3. Commit and return the same prev dict for the next step.
    """
    async with AsyncSession(engine) as session:
        stmt = select(FileAnnotation).where(FileAnnotation.task_id == prev["task_id"])
        result = await session.execute(stmt)
        file = result.scalar_one_or_none()
        if file is None:
            raise ValueError(f"No FileAnnotation found for task {prev['task_id']}")
        file.sqlmodel_update({"annotation": prev["annotation"].content})
        await session.commit()
        return prev

@celery.task(bind=True)
async def send_email_task(self: Task[Any, Any], prev: dict[str, Any], email: str) -> str:
    """
    1. Generate the email content and send the email.
    2. Return a status message.
    """
    link = f"{settings.FRONTEND_HOST}/{prev['task_id']}"
    content = generate_reminder_email(email_to=email, link=link)
    await send_email(
        email_to=email,
        subject="Your annotation is ready",
        html_content=content.html_content,
    )
    return f"Email sent to {email} for task {prev['task_id']}"

def start_invocation_flow(prompt: str, image_url: str, email: str):
    flow = chain(
        invoke_llm.s(prompt, image_url),
        update_file_annotation.s(),
        send_email_task.s(email=email)
    )
    result = flow.apply_async()
    print(f"Invokation workflow started, chain id = {result.id}")
    return result

def upload_flow(file_bytes: bytes, filename: str, task_id: str):
    # Start background tasks for cloudinary upload and DB commit
    upload_chain = (
        upload_to_cloudinary_task.s(file_bytes, filename, task_id)
        | db_commit_file_annotation.s(task_id=task_id)
    )
    result = upload_chain.apply_async()
    print(f"Upload workflow started, chain id = {result.id}")
    return result