from fastapi import FastAPI, UploadFile
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import base64
import re
from typing import Union, Any
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, BaseMessage
from redis import Redis
from app.config import settings
from app.tasks import celery
from app.email import send_email, generate_reminder_email
import asyncio

redis = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB)


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

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

vlm = ChatOllama(model="moondream:v2")

prompt = """"What's in this image?"""



@app.get('/')
def main() -> HTMLResponse:
    return templates.TemplateResponse("index.html")

@app.get("/results/{id}")
def results(id: str) -> HTMLResponse:
    return templates.TemplateResponse("results.html", context={"id": id})

@celery.task # type: ignore[decorator]
def invoke_llm(prompt: str, image_url: str) -> BaseMessage:
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

    return annotation

@celery.task # type: ignore
def send_email_task(email:str, link: str):
    content = generate_reminder_email(email_to=email, link=link)
    asyncio.run(send_email(email_to=email, subject="Task Reminder", html_content=content.html_content))


@app.post("/annotate")
async def annotate(file: UploadFile, email: str="") -> JSONResponse:
    """recieves base64 string, processes it and returns the annotation."""
    img_b64: str = encode_to_base64_string(file.file.read())

    image_url: str = f"data:image/jpeg;base64,{img_b64}"

    # background_task.add_task(invoke_llm, prompt, image_url)
    
    result = invoke_llm.delay(prompt, image_url) # type: ignore

    link = result.id

    # if is_valid_email(email):
    #     send = 

    # TODO: Chain the tasks
    # TODO: DO the frontend/jinja templates
    # TODO: Debug
    # TODO: Containerize

    response: dict[str, Any] = {"message": "Annotation in progress", "id": result.id}
    
    return JSONResponse(response)