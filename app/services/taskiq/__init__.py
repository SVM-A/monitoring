# services/taskiq/__init__.py


from taskiq_redis import ListQueueBroker

from app.core.config import get_redis_settings

taskiq_redis_broker = ListQueueBroker(get_redis_settings().tapi_redis_broker_url)
