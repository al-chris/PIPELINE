import os
import re
import base64
import asyncio
import cloudinary
from redis import Redis
from celery import chain # type: ignore[stub-missing]
from typing import Union, Any
from contextlib import asynccontextmanager
from cloudinary.uploader import upload
from fastapi import FastAPI, UploadFile, Body, Request
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, BaseMessage
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.config import settings
from app.tasks import celery
from app.email import send_email, generate_reminder_email
from app.file import upload_picture_to_cloudinary
from app.db import SessionDep, FileAnnotation, get_async_session, init_db
from sqlmodel import select
from app.logging import logger

redis = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB)

cloudinary.config( 
    cloud_name = settings.CLOUDINARY_CLOUD_NAME, 
    api_key = settings.CLOUDINARY_API_KEY, 
    api_secret = settings.CLOUDINARY_API_SECRET,
    secure = True
)

email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

def is_valid_email(email: str) -> bool:
    return re.match(email_regex, email) is not None


def encode_image_from_path(image_path: str) -> str:
    """Getting the base64 string"""
    with open(file=image_path, mode="rb") as image_file:
        return base64.b64encode(s=image_file.read()).decode(encoding="utf-8")

def encode_to_base64_string(image: Union[bytes, bytearray, memoryview]) -> str:
    return base64.b64encode(image).decode("utf-8")

app = FastAPI()
static_directory = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_directory), name="static")
templates_directory = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_directory)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing application")
    try:
        init_db()
    except Exception as e:
        logger.error(f"Failed to initialize the database: {e}")
        raise
    yield
    logger.info("Shutting down application")


vlm = ChatOllama(model="moondream:v2", base_url=settings.OLLAMA_BASE_URL)

prompt = """"What's in this image?"""



@app.get('/')
def main(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/results/{id}")
def results(id: str) -> HTMLResponse:
    return templates.TemplateResponse("results.html", context={"id": id})



@celery.task(bind=True) # type: ignore[decorator]
def invoke_llm(self, prompt: str, image_url: str) -> dict[str, Any]:
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

    return {"annotation": annotation, "task_id":self.request.id}

@celery.task(bind=True)
async def update_file_annotation(self, prev: dict) -> dict:
    """
    1. Grab an AsyncSession from your FastAPI dependency.
    2. Query and update the FileAnnotation record.
    3. Commit and return the same prev dict for the next step.
    """
    session = await get_async_session()
    stmt = select(FileAnnotation).where(FileAnnotation.task_id == prev["task_id"])
    result = await session.execute(stmt)
    file = result.scalar_one_or_none()
    if file is None:
        raise ValueError(f"No FileAnnotation found for task {prev['task_id']}")
    file.sqlmodel_update({"annotation": prev["annotation"].content})
    await session.commit()
    return prev


@celery.task(bind=True)
async def send_email_task(self, prev: dict, email: str) -> str:
    link = f"{settings.FRONTEND_HOST}/{prev['task_id']}"
    content = generate_reminder_email(email_to=email, link=link)
    # If your send_email is async, you can await it directly here.
    await send_email(
        email_to=email,
        subject="Your annotation is ready",
        html_content=content.html_content
    )
    return f"Email sent to {email} for task {prev['task_id']}"


def start_invocation_flow(prompt: str, image_url: str, email: str):
    flow = chain(
        invoke_llm.s(prompt, image_url),
        update_file_annotation.s(),
        send_email_task.s(email)
    )
    result = flow.apply_async()
    print(f"Workflow started, chain id = {result.id}")
    return result


@app.post("/annotate")
async def annotate(file: UploadFile, db: SessionDep, email: str = Body(...)) -> JSONResponse:
    """recieves base64 string, processes it and returns the annotation."""
    img_b64: str = encode_to_base64_string(file.file.read())

    image_url: str = f"data:image/jpeg;base64,{img_b64}"

    # background_task.add_task(invoke_llm, prompt, image_url)

    if is_valid_email(email):
        result = start_invocation_flow(prompt, image_url, email)
    else:    
        result = invoke_llm.delay(prompt, image_url) # type: ignore

    id = result.id

    # TODO: Chain the tasks
    # TODO: DO the frontend/jinja templates
    # TODO: Debug
    # TODO: Containerize

    url = await upload_picture_to_cloudinary(file, id)

    db_obj = FileAnnotation(
        task_id=id,
        file_url=url,
        annotation=None
    )

    db.add(db_obj)
    await db.commit()

    response: dict[str, Any] = {"message": "Annotation in progress", "id": id}
    
    return JSONResponse(response)