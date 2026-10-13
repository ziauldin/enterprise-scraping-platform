import os

from celery import Celery


CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', CELERY_BROKER_URL)
SCHEDULE_POLL_SECONDS = max(5.0, float(os.getenv('SCHEDULED_RUN_POLL_SECONDS', '10')))

celery_app = Celery(
    'parsehub_scheduler',
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    timezone='UTC',
    enable_utc=True,
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    broker_connection_retry_on_startup=True,
    beat_schedule={
        'check-due-project-schedules': {
            'task': 'backend.celery_tasks.process_due_schedules',
            'schedule': SCHEDULE_POLL_SECONDS,
        }
    },
    imports=(
        'backend.celery_tasks',
        'celery_tasks',
    ),
)

celery_app.autodiscover_tasks(['backend'])
