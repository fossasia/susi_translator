# transcribe_project/celery.py
# (C) Michael Peter Christen 2024
# Licensed under Apache License Version 2.0

"""
Celery application configuration for the transcription project.

When USE_CELERY=true, audio processing tasks are dispatched to Celery workers
backed by a Redis broker. This replaces the in-process threading.Thread +
queue.Queue() approach and allows horizontal scaling of Whisper inference
across multiple worker processes or machines.

Quick start:
    # 1. Make sure Redis is running (default: localhost:6379)
    # 2. Set environment variable: export USE_CELERY=true
    # 3. Start the Celery worker:
    #    celery -A transcribe_project worker --loglevel=info --concurrency=2
    # 4. (Optional) Start the periodic beat scheduler:
    #    celery -A transcribe_project beat --loglevel=info
"""

import os

from celery import Celery

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'transcribe_project.settings')

app = Celery('transcribe_project')

# Read config from Django settings, using the CELERY_ namespace.
# e.g.  CELERY_BROKER_URL in settings.py  →  broker_url for Celery.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Autodiscover tasks.py in every installed Django app.
app.autodiscover_tasks()

# ---------- Periodic tasks (Celery Beat) ----------
app.conf.beat_schedule = {
    'cleanup-old-transcripts-every-10-minutes': {
        'task': 'transcribe_app.tasks.cleanup_old_transcripts_task',
        'schedule': 600.0,  # every 10 minutes
    },
}
