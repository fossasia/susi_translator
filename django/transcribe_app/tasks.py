# transcribe_app/tasks.py
# (C) Michael Peter Christen 2024
# Licensed under Apache License Version 2.0

"""
Celery task definitions for audio transcription and translation.

These tasks replace the ``while True`` background thread in the original
``transcribe_utils.process_audio()`` with discrete, independently
schedulable units of work.  Each task is idempotent and safe to retry.
"""

import io
import os
import logging

import base64
import numpy as np
import requests
import json
import time

from celery import shared_task
from scipy.io.wavfile import write as wav_write

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment / model configuration  (mirrors transcribe_utils.py)
# ---------------------------------------------------------------------------

use_whisper_server = os.getenv('WHISPER_SERVER_USE', 'true') == 'true'
whisper_server = os.getenv('WHISPER_SERVER', 'https://whisper.susi.ai')

model_fast_name = os.getenv('WHISPER_MODEL', 'small')
model_smart_name = os.getenv('WHISPER_MODEL', 'medium')

# Lazy-loaded whisper models (only when USE_CELERY=true AND local whisper)
_model_fast = None
_model_smart = None


def _get_model_fast():
    """Lazy-load the fast whisper model on first use inside a worker."""
    global _model_fast
    if _model_fast is None:
        import whisper, torch
        script_dir = os.path.dirname(os.path.abspath(__file__))
        models_path = os.path.join(script_dir, 'models')
        if os.path.exists(os.path.join(models_path, model_fast_name + ".pt")):
            _model_fast = whisper.load_model(model_fast_name, in_memory=True, download_root=models_path)
        else:
            _model_fast = whisper.load_model(model_fast_name, in_memory=True)
    return _model_fast


# ---------------------------------------------------------------------------
# Utility imports (kept in transcribe_utils to avoid duplication)
# ---------------------------------------------------------------------------

def _is_valid(transcript):
    """Re-use the validation logic from transcribe_utils."""
    from .transcribe_utils import is_valid
    return is_valid(transcript)


def _translate(text, source_language, target_language):
    """Re-use the translation logic from transcribe_utils."""
    from .transcribe_utils import translate
    return translate(text, source_language, target_language)


# ---------------------------------------------------------------------------
# Core Celery tasks
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    name='transcribe_app.tasks.process_audio_chunk',
    acks_late=True,
    max_retries=3,
    default_retry_delay=5,
)
def process_audio_chunk(self, tenant_id, chunk_id, audio_b64, translate_from, translate_to):
    """
    Transcribe a single audio chunk using Whisper and store the result.

    This is the Celery equivalent of the inner loop body from the original
    ``transcribe_utils.process_audio()`` function.

    Parameters
    ----------
    tenant_id : str
        Tenant identifier for multi-tenant isolation.
    chunk_id : str
        Unique identifier for this audio chunk (typically a millisecond timestamp).
    audio_b64 : str
        Base64-encoded raw PCM audio (int16, 16 kHz mono).
    translate_from : str or None
        Source language code for optional translation.
    translate_to : str or None
        Target language code for optional translation.
    """
    from .transcript_store import store

    try:
        # Decode base64 audio
        audio_data = base64.b64decode(audio_b64)
        audio_array = np.frombuffer(audio_data, dtype=np.int16)

        if audio_array.size == 0:
            logger.warning("Invalid audio data for chunk_id %s", chunk_id)
            return {'status': 'skipped', 'reason': 'empty_audio'}

        if np.isnan(audio_array.astype(np.float32)).any():
            logger.warning("NaN values in audio array for chunk_id %s", chunk_id)
            return {'status': 'skipped', 'reason': 'nan_values'}

        # ----- Transcribe -----
        transcript = ''
        if use_whisper_server:
            # Whisper.cpp HTTP server
            if audio_array.dtype != np.int16:
                audio_array = audio_array.astype(np.int16)

            wav_buffer = io.BytesIO()
            wav_write(wav_buffer, 16000, audio_array)
            wav_buffer.seek(0)

            files = {'file': ('audio.wav', wav_buffer, 'audio/wav')}
            data = {
                'temperature': '0.0',
                'temperature_inc': '0.0',
                'response_format': 'json',
            }
            response = requests.post(f"{whisper_server}/inference", files=files, data=data)

            if response.status_code == 200:
                transcript = response.json().get('text', '').strip()
            else:
                logger.error("Whisper server error: %s %s", response.status_code, response.text)
                raise self.retry(exc=Exception(f"Whisper server returned {response.status_code}"))
        else:
            # Local PyTorch whisper model
            import torch
            model = _get_model_fast()
            audio_float = audio_array.astype(np.float32) / 32768.0
            audio_tensor = torch.from_numpy(audio_float)
            result = model.transcribe(audio_tensor, temperature=0)
            transcript = result.get('text', '').strip()

        # ----- Validate & store -----
        if _is_valid(transcript):
            logger.info("VALID transcript for chunk_id %s: %s", chunk_id, transcript)

            # Check if this chunk_id already exists (overwrite case)
            existing = store.get_transcript_event(tenant_id, chunk_id)
            if not existing:
                # New chunk — trigger translation on previous chunks
                chunk_ids = store.get_chunk_ids(tenant_id)
                if len(chunk_ids) >= 1:
                    _try_translate_chunk(tenant_id, chunk_ids[-1])

            transcript_event = {
                'translated': False,
                'transcript': transcript,
                'translate_from': translate_from,
                'translate_to': translate_to,
            }
            store.set_transcript(tenant_id, chunk_id, transcript_event)
        else:
            logger.warning("INVALID transcript for chunk_id %s: %s", chunk_id, transcript)

        return {'status': 'ok', 'chunk_id': chunk_id, 'transcript': transcript}

    except Exception as exc:
        logger.error("Error processing audio chunk %s", chunk_id, exc_info=True)
        raise self.retry(exc=exc)


def _try_translate_chunk(tenant_id, chunk_id):
    """
    Check whether a transcript event needs translation and dispatch it.
    """
    from .transcript_store import store

    event = store.get_transcript_event(tenant_id, chunk_id)
    if not event:
        return

    translated = event.get('translated', False)
    translate_to = event.get('translate_to', '')

    if not translate_to or translate_to == '_' or translated:
        return

    # Dispatch the translation as a separate Celery task
    translate_transcript.delay(tenant_id, chunk_id)


@shared_task(
    name='transcribe_app.tasks.translate_transcript',
    acks_late=True,
    max_retries=2,
    default_retry_delay=3,
)
def translate_transcript(tenant_id, chunk_id):
    """
    Translate a single stored transcript event.
    """
    from .transcript_store import store

    event = store.get_transcript_event(tenant_id, chunk_id)
    if not event:
        return {'status': 'skipped', 'reason': 'not_found'}

    if event.get('translated', False):
        return {'status': 'skipped', 'reason': 'already_translated'}

    translate_from = event.get('translate_from', '')
    translate_to = event.get('translate_to', '')
    transcript = event.get('transcript', '')

    if not translate_to or translate_to == '_':
        return {'status': 'skipped', 'reason': 'no_target_language'}

    # Mark translated early to prevent duplicate work
    event['translated'] = True
    store.set_transcript(tenant_id, chunk_id, event)

    translation = _translate(transcript, translate_from, translate_to)
    if translation:
        event['transcript'] = translation
        event['original'] = transcript
        store.set_transcript(tenant_id, chunk_id, event)

    return {'status': 'ok', 'chunk_id': chunk_id}


@shared_task(name='transcribe_app.tasks.cleanup_old_transcripts_task')
def cleanup_old_transcripts_task():
    """
    Periodic task: remove transcript events older than two hours.
    Intended to be called via Celery Beat every 10 minutes.
    """
    from .transcript_store import store
    store.cleanup_old()
    logger.info("Cleaned up old transcripts")
    return {'status': 'ok'}
