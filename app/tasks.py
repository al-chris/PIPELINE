from celery import Celery # type: ignore[stub]
from app.config import settings

celery = Celery(
    "tasks",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL
)
# celery.config_from_object('app.tasks.celeryconfig')
celery.autodiscover_tasks(['app.tasks', 'app.main']) # type: ignore