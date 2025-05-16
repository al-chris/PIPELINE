import re
import asyncio
from sqlmodel import select
from celery import Celery, chain, Task
from typing import Any
from app.file import upload_picture_to_cloudinary
from app.db import engine, FileAnnotation
from app.config import settings
from app.email import send_email, generate_reminder_email
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, BaseMessage
from sqlalchemy.ext.asyncio import AsyncSession

celery = Celery(
    "tasks",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL
)
celery.autodiscover_tasks(['app.tasks', 'app.main'])

@celery.task(bind=True)
def upload_to_cloudinary_task(self: Task[Any, Any], file_bytes: bytes, filename: str) -> str:
    task_id = self.request.root_id
    if not task_id:
        raise ValueError("No task id")
    # Run async upload in sync context
    return asyncio.run(upload_picture_to_cloudinary(file_bytes, filename, task_id)) or ""

@celery.task(bind=True)
def db_commit_file_annotation(self: Task[Any, Any], file_url: str):
    task_id = self.request.root_id
    if not task_id:
        raise ValueError("No task id")
    async def _commit():
        async with AsyncSession(engine) as session:
            db_obj = FileAnnotation(
                task_id=task_id,
                file_url=file_url,
                annotation=None
            )
            session.add(db_obj)
            await session.commit()
            return file_url
    asyncio.run(_commit())

vlm = ChatOllama(model="moondream:v2", base_url=settings.OLLAMA_BASE_URL)

@celery.task(bind=True)
def invoke_llm(self: Task[Any, Any], prompt: str, image_url: str) -> dict[str, Any]:
    # If vlm.invoke is async, wrap in asyncio.run. If not, call directly.
    def _invoke():
        return vlm.invoke(
            input=[
                HumanMessage(
                    content=[
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": image_url}
                    ]
                )
            ]
        )
    annotation: BaseMessage = _invoke()
    return {"annotation": annotation.model_dump(), "task_id": self.request.id}

@celery.task(bind=True)
def update_file_annotation(self: Task[Any, Any], prev: dict[str, Any]) -> dict[str, Any]:
    async def _update():
        async with AsyncSession(engine) as session:
            stmt = select(FileAnnotation).where(FileAnnotation.task_id == prev["task_id"])
            result = await session.execute(stmt)
            file = result.scalar_one_or_none()
            if file is None:
                raise ValueError(f"No FileAnnotation found for task {prev['task_id']}")
            file.sqlmodel_update({"annotation": prev["annotation"].get("content")})
            await session.commit()
        return prev
    return asyncio.run(_update())

@celery.task(bind=True)
def send_email_task(self: Task[Any, Any], prev: dict[str, Any], email: str) -> str:
    async def _send():
        link = f"{settings.FRONTEND_HOST}/{prev['task_id']}"
        content = generate_reminder_email(email_to=email, link=link)
        await send_email(
            email_to=email,
            subject="Your annotation is ready",
            html_content=content.html_content,
        )
        return f"Email sent to {email} for task {prev['task_id']}"
    return asyncio.run(_send())

def start_invocation_flow(prompt: str, image_url: str, email: str):
    flow = chain(
        invoke_llm.s(prompt, image_url),
        update_file_annotation.s(),
        send_email_task.s(email=email)
    )
    result = flow.apply_async()
    print(f"Invocation workflow started, chain id = {result.id}")
    return result

def upload_flow(file_bytes: bytes, filename: str, task_id: str):
    upload_chain = (
        upload_to_cloudinary_task.s(file_bytes, filename, task_id)
        | db_commit_file_annotation.s(task_id=task_id)
    )
    result = upload_chain.apply_async()
    print(f"Upload workflow started, chain id = {result.id}")
    return result


email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

def is_valid_email(email: str) -> bool:
    return re.match(email_regex, email) is not None

def full_annotation_flow(file_bytes: bytes, filename: str, prompt: str, email: str = ""):
    # Chain the upload -> DB commit -> LLM -> (optional: email)
    chain_tasks = (
        upload_to_cloudinary_task.s(file_bytes, filename)
        | db_commit_file_annotation.s()
        | invoke_llm.s(prompt)
    )
    if is_valid_email(email):
        chain_tasks |= send_email_task.s(email=email)
    result = chain_tasks.apply_async()
    print(f"Full annotation workflow started, chain id = {result.id}")
    return result