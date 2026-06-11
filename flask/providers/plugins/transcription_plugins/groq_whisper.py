"""
GroqWhisperProvider, TranscriptionProvider implementation using
Groq's hosted models via the official groq Python SDK
"""

from __future__ import annotations

import io
import logging
import os
import threading
import time
import wave
from typing import Any, Optional

import numpy as np

from providers.base import TranscriptionProvider, TranscriptionError, ProviderConfigError

logger = logging.getLogger(__name__)

_MIN_INTERVAL_SECONDS: float = 3.1


def _xor_mask(data: bytes, key: bytes) -> bytes:
    """Keeps the key out of plain-text memory"""
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


class GroqWhisperProvider(TranscriptionProvider):
    """
     imp: enforces a 3.1-second pacing interval to stay safely under 20 RPM
    """

    MODEL = "whisper-large-v3-turbo"
    SAMPLE_RATE = 16000

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)

        raw_key = self.config.get("api_key", "").strip()
        if not raw_key:
            raise ProviderConfigError(
                "[groq_whisper] api_key is required. "
                "Get a free key at https://console.groq.com"
            )

        # XOR obfuscate the key so it is not visible in memory dumps or logs
        self._salt = os.urandom(32)
        self._masked_key: bytes = _xor_mask(raw_key.encode(), self._salt)

        # Rate-limit state
        self._last_call_ts: float = 0.0
        self._rate_lock = threading.Lock()
        self._language = self.config.get("language", None)

    @property
    def provider_name(self) -> str:
        return "groq_whisper"

    def is_available(self) -> bool:
        try:
            import groq as _groq
            _groq.Groq(api_key=self._reveal_key())
            return True
        except Exception:
            return False

    def _reveal_key(self) -> str:
        """Reconstruct the clear text API key for one SDK call"""
        return _xor_mask(self._masked_key, self._salt).decode()

    def _wait_for_rate_limit(self) -> None:
        """throtlling here for the rate limiters"""
        with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_call_ts
            if elapsed < _MIN_INTERVAL_SECONDS:
                wait = _MIN_INTERVAL_SECONDS - elapsed
                logger.debug(f"[groq_whisper] Rate-limit pacing: sleeping {wait:.2f}s")
                time.sleep(wait)
            self._last_call_ts = time.monotonic()

    @staticmethod
    def _float32_to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
        """Convert float32 numpy array to an in-memory 16-bit mono WAV file."""
        pcm_int16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_int16.tobytes())
        buf.seek(0)
        return buf.read()

    def transcribe(self, audio: np.ndarray, **kwargs: Any) -> str:
        """
        Transcribe a float32 mono audio array via Groq's Whisper endpoint
        """
        if not isinstance(audio, np.ndarray):
            raise TranscriptionError(
                f"[groq_whisper] Expected np.ndarray, got {type(audio).__name__}"
            )
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        if audio.size == 0:
            return ""

        # Enforce rate limit before calling the API.
        self._wait_for_rate_limit()

        wav_bytes = self._float32_to_wav_bytes(audio, self.SAMPLE_RATE)
        language = kwargs.get("language", self._language)

        try:
            import groq as _groq

            client = _groq.Groq(api_key=self._reveal_key())
            transcription = client.audio.transcriptions.create(
                file=("audio.wav", wav_bytes),
                model=self.MODEL,
                response_format="text",
                temperature=0,
                **({"language": language} if language else {}),
            )
            # When response_format="text", the SDK returns a plain string
            if isinstance(transcription, str):
                return transcription.strip()
            # Fallback: some SDK versions may wrap it in an object
            return (getattr(transcription, "text", None) or str(transcription)).strip()

        except _groq.RateLimitError:
            logger.warning("[groq_whisper] 429 Too Many Requests — backing off 5s")
            time.sleep(5)
            raise TranscriptionError("[groq_whisper] Rate limited by Groq. Will retry next chunk.")
        except _groq.APIError as exc:
            raise TranscriptionError(f"[groq_whisper] Groq API error: {exc}") from exc
        except Exception as exc:
            raise TranscriptionError(f"[groq_whisper] Unexpected error: {exc}") from exc