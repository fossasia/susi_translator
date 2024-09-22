# transcribe_app/apps.py
# (C) Michael Peter Christen 2024
# Licensed under Apache License Version 2.0

from django.apps import AppConfig
import threading
from .transcribe_utils import process_audio

class TranscribeAppConfig(AppConfig):
    name = 'transcribe_app'

    def ready(self):
        threading.Thread(target=process_audio, daemon=True).start()
