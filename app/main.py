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
from app.db import FileAnnotation, engine, create_db_and_tables
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
    try:
        create_db_and_tables()
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
    """
    Renders the main index page using a template.
    Args:
        request (Request): The FastAPI request object.
    Returns:
        HTMLResponse: The rendered template response containing the index page.
    """

    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/results/{id}")
def results(id: str, request: Request) -> HTMLResponse:
    """
    Renders the results page with the specified ID.
    Args:
        id (str): The unique identifier for the results to display.
        request (Request): The FastAPI request object.
    Returns:
        HTMLResponse: The rendered HTML template response containing the results page.
    Notes:
        - Uses the 'results.html' template for rendering
        - Passes the request and id to the template context
    """

    return templates.TemplateResponse("results.html", context={"request": request, "id": id})


prompt = "What's in this image?"


@app.post("/annotate")
async def annotate(file: UploadFile, email: str = Body(...)) -> JSONResponse:
    """
    Asynchronously handles file annotation requests.
    This endpoint receives a file and an email address, initiates the annotation process,
    and returns a response with a tracking ID.
    Args:
        file (UploadFile): The file to be annotated, uploaded through FastAPI
        email (str): Email address of the user requesting annotation, passed in request body
    Returns:
        JSONResponse: A JSON response containing:
            - message: Status message indicating annotation has started
            - id: Unique identifier for tracking the annotation process
    Raises:
        HTTPException: If file upload fails or file format is invalid
    Example:
        {
            "message": "Annotation in progress",
            "id": "66a3183c-969c-47c8-9039-26892c6bd911"
        }
    """

    file_bytes = await file.read()
    filename = file.filename or ""

    result = full_annotation_flow(file_bytes, filename, prompt, email=email)
    response = {"message": "Annotation in progress", "id": result.id}
    return JSONResponse(response)


@app.get("/api/results/{id}")
def api_results(id: str):
    """
    Retrieves annotation results for a specific task ID from the database.
    Parameters:
        id (str): The task ID to search for in the database.
    Returns:
        JSONResponse: A JSON response containing:
            - annotation: The annotation data for the task (None if not found)
            - file_url: The associated file URL (None if not found)
            With status code 200 if found, 404 if not found.
    Note:
        Uses SQLModel Session to query the FileAnnotation table.
        Returns 404 if no matching task_id is found.
    """

    with Session(engine) as session:
        stmt = select(FileAnnotation).where(FileAnnotation.task_id == id)
        result = session.exec(stmt).first()
        if not result:
            return JSONResponse({"annotation": None, "file_url": None}, status_code=404)
        return JSONResponse({
            "annotation": result.annotation,
            "file_url": result.file_url
        })