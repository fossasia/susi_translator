# transcribe_project/__init__.py
# (C) Michael Peter Christen 2024
# Licensed under Apache License Version 2.0

# Import the Celery app so that shared_task will use this app.
from .celery import app as celery_app

__all__ = ('celery_app',)
