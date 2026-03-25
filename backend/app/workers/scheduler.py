from app.workers import tasks  # noqa: F401
from app.workers.celery_app import celery_app


if __name__ == "__main__":
    celery_app.start(["celery", "beat", "--loglevel=info"])
