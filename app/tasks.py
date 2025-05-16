import re
import time
import base64
import asyncio
import requests
from sqlmodel import select, Session
from celery import Celery, Task
from typing import Any
from app.file import upload_picture_to_cloudinary
from app.db import engine, FileAnnotation
from app.config import settings
from app.email import send_email, generate_reminder_email
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, BaseMessage
# from sqlalchemy.ext.asyncio import AsyncSession
import uuid

celery = Celery(
    "tasks",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL
)
celery.autodiscover_tasks(['app.tasks', 'app.main'])

@celery.task(bind=True)
def upload_to_cloudinary_task(self: Task, file_bytes: bytes, filename: str, task_id: str) -> dict[str, Any]:
    url = asyncio.run(upload_picture_to_cloudinary(file_bytes, filename, task_id)) or ""
    return {"file_url": url, "task_id": task_id}

@celery.task(bind=True)
def db_commit_file_annotation(self: Task, prev: dict[str, Any]) -> dict[str, Any]:
    # async def _commit():
    with Session(engine) as session:
        db_obj = FileAnnotation(
            task_id=prev["task_id"],
            file_url=prev["file_url"],
            annotation=None
        )
        session.add(db_obj)
        session.commit()
    return prev
    # return asyncio.run(_commit())

vlm = ChatOllama(model="moondream:v2", base_url=settings.OLLAMA_BASE_URL)

@celery.task(bind=True)
def invoke_llm(self: Task, prev: dict[str, Any], prompt: str) -> dict[str, Any]:
    url = prev["file_url"]
    max_retries = 5
    image_bytes = None

    for i in range(max_retries):
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

@celery.task(bind=True)
def update_file_annotation(self: Task, prev: dict[str, Any]) -> dict[str, Any]:
    # async def _update():
    with Session(engine) as session:
        stmt = select(FileAnnotation).where(FileAnnotation.task_id == prev["task_id"])
        result = session.exec(stmt)
        file = result.first()
        if file is None:
            raise ValueError(f"No FileAnnotation found for task {prev['task_id']}")
        file.sqlmodel_update({"annotation": prev["annotation"].get("content")})
        session.commit()
    return prev
    # return asyncio.run(_update())

@celery.task(bind=True)
def send_email_task(self: Task, prev: dict[str, Any], email: str) -> str:
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
    return re.match(email_regex, email) is not None

def full_annotation_flow(file_bytes: bytes, filename: str, prompt: str, email: str = ""):
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