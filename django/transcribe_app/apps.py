# transcribe_app/apps.py
# (C) Michael Peter Christen 2024
# Licensed under Apache License Version 2.0

import os
from django.apps import AppConfig


class TranscribeAppConfig(AppConfig):
    name = 'transcribe_app'

    def ready(self):
        use_celery = os.getenv('USE_CELERY', 'false').lower() == 'true'
        if not use_celery:
            # Legacy mode: start the background processing thread
            import threading
            from .transcribe_utils import process_audio
            threading.Thread(target=process_audio, daemon=True).start()
