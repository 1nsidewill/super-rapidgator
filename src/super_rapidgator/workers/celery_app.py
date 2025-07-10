"""Celery 애플리케이션 설정"""

from celery import Celery, Task
from loguru import logger

from ..core.config import settings

class LogErrorsTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(f'Task {task_id} failed: {exc!r}', exc_info=einfo)
        super().on_failure(exc, task_id, args, kwargs, einfo)

    def on_success(self, retval, task_id, args, kwargs):
        logger.info(f"Task {task_id} completed successfully")
        super().on_success(retval, task_id, args, kwargs)

# Celery 애플리케이션 인스턴스 생성
celery_app = Celery(
    "super_rapidgator",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["super_rapidgator.workers.tasks"]
)

# Celery 설정
celery_app.conf.update(
    task_serializer=settings.CELERY_TASK_SERIALIZER,
    accept_content=settings.CELERY_ACCEPT_CONTENT,
    result_serializer=settings.CELERY_RESULT_SERIALIZER,
    timezone=settings.CELERY_TIMEZONE,
    enable_utc=settings.CELERY_ENABLE_UTC,
    task_track_started=settings.CELERY_TASK_TRACK_STARTED,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    worker_concurrency=settings.CELERY_WORKER_CONCURRENCY,
    worker_prefetch_multiplier=1,  # 한 번에 하나씩 처리
    task_acks_late=True,  # 태스크 완료 후 확인
    worker_disable_rate_limits=True,  # 속도 제한 비활성화
    task_default_queue="downloads",  # 기본 큐 이름
    task_routes={
        "super_rapidgator.workers.tasks.download_file": {"queue": "downloads"},
        "super_rapidgator.workers.tasks.batch_download": {"queue": "downloads"},
    },
    result_expires=3600,  # 결과 만료 시간 (1시간)
    broker_connection_retry_on_startup=True,
    broker_heartbeat=10,
    broker_connection_retry=True,
    broker_connection_max_retries=5,
)

# 로깅 설정
logger.info(f"Celery 애플리케이션 설정 완료")
logger.info(f"Broker URL: {settings.CELERY_BROKER_URL}")
logger.info(f"Result Backend: {settings.CELERY_RESULT_BACKEND}")
logger.info(f"Worker Concurrency: {settings.CELERY_WORKER_CONCURRENCY}")

# 이벤트 핸들러
@celery_app.task(bind=True)
def debug_task(self):
    """디버깅용 태스크"""
    logger.info(f"Request: {self.request!r}")
    return f"Hello from Celery: {self.request!r}"

# 시작 이벤트
@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """주기적 태스크 설정"""
    logger.info("Celery 주기적 태스크 설정 완료")

# 애플리케이션 시작 시 실행
if __name__ == "__main__":
    celery_app.start()