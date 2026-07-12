from app.tasks.download_tasks import celery_app

if __name__ == "__main__":
    celery_app.start()
