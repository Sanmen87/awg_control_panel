from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery("awg_control_panel", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    imports=("app.workers.tasks",),
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "sync-client-runtime-stats-every-minute": {
            "task": "app.workers.tasks.sync_client_runtime_stats",
            "schedule": crontab(),
        },
        "sync-server-runtime-metrics-every-minute": {
            "task": "app.workers.tasks.sync_server_runtime_metrics",
            "schedule": crontab(),
        },
        "sync-extra-service-runtime-every-minute": {
            "task": "app.workers.tasks.sync_extra_service_runtime",
            "schedule": crontab(),
        },
        "reconcile-stale-jobs-every-minute": {
            "task": "app.workers.tasks.reconcile_stale_jobs",
            "schedule": crontab(),
        },
        "run-scheduled-backups-every-minute": {
            "task": "app.workers.tasks.run_scheduled_backups",
            "schedule": crontab(),
        },
        "cleanup-old-backups-every-minute": {
            "task": "app.workers.tasks.cleanup_old_backups",
            "schedule": crontab(),
        },
    },
)
