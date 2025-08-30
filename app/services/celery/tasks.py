# services/celery/tasks.py

from app.services.celery.__init__ import celery_app


@celery_app.task
def test():
    print("✅ Anwill Back Catalog: 🐰 Celery - test task выполнена")
