# transcribe_app/apps.py
from django.apps import AppConfig
import threading
from .transcribe_utils import process_audio

class TranscribeAppConfig(AppConfig):
    name = 'transcribe_app'

    def ready(self):
        threading.Thread(target=process_audio, daemon=True).start()
