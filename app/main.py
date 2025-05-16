import os
import re
import base64
import cloudinary # type: ignore[no-stub]
from redis import Redis
from typing import Union, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, Body, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.config import settings
from app.tasks import upload_flow, start_invocation_flow, invoke_llm
from app.db import SessionDep, create_db_and_tables
from app.logging import logger

redis = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB)

cloudinary.config(  # type: ignore
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing application")
    try:
        await create_db_and_tables()
    except Exception as e:
        logger.error(f"Failed to initialize the database: {e}")
        raise
    yield
    logger.info("Shutting down application")


app = FastAPI(lifespan=lifespan)


static_directory = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_directory), name="static")
templates_directory = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_directory)


@app.get('/')
def main(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/results/{id}")
def results(id: str) -> HTMLResponse:
    return templates.TemplateResponse("results.html", context={"id": id})

prompt = "What's in this image?"

@app.post("/annotate")
async def annotate(file: UploadFile, db: SessionDep, email: str = Body(...)) -> JSONResponse:
    """receives base64 string, processes it and returns the annotation."""
    file_bytes = await file.read()
    filename = file.filename if file.filename else ""
    img_b64: str = encode_to_base64_string(file_bytes)
    image_url: str = f"data:image/jpeg;base64,{img_b64}"

    if is_valid_email(email):
        result = start_invocation_flow(prompt, image_url, email)
    else:
        result = invoke_llm.delay(prompt, image_url)

    task_id = result.id

    upload_flow(file_bytes=file_bytes, filename=filename, task_id=task_id)

    response: dict[str, Any] = {"message": "Annotation in progress", "id": task_id}
    return JSONResponse(response)