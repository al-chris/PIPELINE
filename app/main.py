import os
import base64
import cloudinary # type: ignore[no-stub]
from redis import Redis
from typing import Union
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, Body, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.config import settings
from app.tasks import full_annotation_flow
from app.logging import logger
from app.db import FileAnnotation, engine
from sqlmodel import select, Session

redis = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB)

cloudinary.config(  # type: ignore
    cloud_name = settings.CLOUDINARY_CLOUD_NAME, 
    api_key = settings.CLOUDINARY_API_KEY, 
    api_secret = settings.CLOUDINARY_API_SECRET,
    secure = True
)



def encode_image_from_path(image_path: str) -> str:
    """Getting the base64 string"""
    with open(file=image_path, mode="rb") as image_file:
        return base64.b64encode(s=image_file.read()).decode(encoding="utf-8")

def encode_to_base64_string(image: Union[bytes, bytearray, memoryview]) -> str:
    return base64.b64encode(image).decode("utf-8")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing application")
    # try:
    #     await create_db_and_tables()
    # except Exception as e:
    #     logger.error(f"Failed to initialize the database: {e}")
    #     raise
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
def results(id: str, request: Request) -> HTMLResponse:
    return templates.TemplateResponse("results.html", context={"request": request, "id": id})


prompt = "What's in this image?"


@app.post("/annotate")
async def annotate(file: UploadFile, email: str = Body(...)) -> JSONResponse:
    file_bytes = await file.read()
    filename = file.filename or ""

    result = full_annotation_flow(file_bytes, filename, prompt, email=email)
    response = {"message": "Annotation in progress", "id": result.id}
    return JSONResponse(response)


@app.get("/api/results/{id}")
def api_results(id: str):
    with Session(engine) as session:
        stmt = select(FileAnnotation).where(FileAnnotation.task_id == id)
        result = session.exec(stmt).first()
        if not result:
            return JSONResponse({"annotation": None, "file_url": None}, status_code=404)
        return JSONResponse({
            "annotation": result.annotation,
            "file_url": result.file_url
        })