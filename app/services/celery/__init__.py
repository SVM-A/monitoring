# services/celery/__init__.py

from celery import Celery

from app.core.config import get_rabbitmq_settings, get_redis_settings

celery_app = Celery(
    "services.celery.init_app",
    broker=get_rabbitmq_settings().tapi_rabbitmq_broker_url,
    backend=get_redis_settings().tapi_redis_broker_url,
    include=["services.celery.tasks"],
    broker_connection_retry_on_startup=True,
)
