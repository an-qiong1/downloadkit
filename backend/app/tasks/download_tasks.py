import asyncio
from celery import Celery
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.download_task import DownloadTask
from app.services.downloader import DownloadManager

celery_app = Celery(
    "media_fetch",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.task_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.result_serializer = "json"
celery_app.conf.task_track_started = True
celery_app.conf.task_time_limit = 3600


@celery_app.task(bind=True, name="download_media")
def download_media(self, task_id: str):
    db = SessionLocal()
    try:
        task = db.query(DownloadTask).filter(DownloadTask.id == task_id).first()
        if not task:
            return {"error": f"Task {task_id} not found"}

        async def progress_callback(tid, progress, status):
            self.update_state(
                state="PROGRESS",
                meta={"task_id": tid, "progress": progress, "status": status},
            )

        manager = DownloadManager(db)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(manager.execute_download(task, progress_callback))
        loop.close()

        return {"task_id": task_id, "status": task.status}
    finally:
        db.close()
