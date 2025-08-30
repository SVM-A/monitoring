# services/taskiq/tasks.py

from app.services.taskiq import taskiq_redis_broker


@taskiq_redis_broker.task
async def test_task():
    print("✅ Anwill Back Catalog: 🧠 TaskIQ - test task выполнена")
