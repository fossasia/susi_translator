"""
WhisperLocalProvider, TranscriptionProvider implementation using
openai whisper library loaded directly into process memory
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from providers.base import TranscriptionProvider, TranscriptionError, ProviderConfigError

logger = logging.getLogger(__name__)


class WhisperLocalProvider(TranscriptionProvider):
    """
    Wraps openai Whisper loaded locally into RAM via the whisper Python library
    """

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        self._model = None  # loaded lazily on first transcribe() call
        self._model_size = self.config.get("model_size", "small")
        self._device = self.config.get("device", None)
        self._language = self.config.get("language", None)
        self._temperature = self.config.get("temperature", 0)

    @property
    def provider_name(self) -> str:
        return "whisper_local"

    def is_available(self) -> bool:
        """
        Returns True if torch and whisper are importable and the model can be loaded successfully
        """
        try:
            import torch    
            import whisper  
            return True
        except ImportError:
            return False

    def _make_ssl_ctx(self) -> "ssl.SSLContext":
        import ssl
        ctx = ssl.create_default_context()
        ctx.options |= getattr(ssl, "OP_IGNORE_UNEXPECTED_EOF", 0)
        ctx.options |= 0x4  
        return ctx

    def load_model(self):
        """
        Load the Whisper model into RAM. Called once on first transcribe() call
        """
        import ssl
        import urllib.request
        import torch
        import whisper

        device = self._device or ("cuda" if torch.cuda.is_available() else "cpu")

        #Force CPU if CUDA is requested but the machine lacks a GPU
        if device == "cuda" and not torch.cuda.is_available():
            logger.warning(
                f"[whisper_local] CUDA was requested, but no GPU is available. "
                f"falling back to CPU."
            )
            device = "cpu"

        logger.info(
            f"[whisper_local] Loading model='{self._model_size}' on device='{device}'"
        )

        # Scope the relaxed SSL context to the whisper download only.
        _scoped_opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self._make_ssl_ctx())
        )
        _original_urlopen = urllib.request.urlopen
        urllib.request.urlopen = _scoped_opener.open
        try:
            self._model = whisper.load_model(self._model_size, device=device)
            logger.info(f"[whisper_local] Model '{self._model_size}' loaded successfully")
        except Exception as e:
            raise ProviderConfigError(
                f"[whisper_local] Failed to load model '{self._model_size}': {e}"
            )
        finally:
            urllib.request.urlopen = _original_urlopen

    def transcribe(self, audio: np.ndarray, **kwargs: Any) -> str:
        """
        Transcribe a normalized float32 mono audio array
        """
        if self._model is None:
            self.load_model()

        language = kwargs.get("language", self._language)
        temperature = kwargs.get("temperature", self._temperature)

        if not isinstance(audio, np.ndarray):
            raise TranscriptionError(
                f"[whisper_local] Expected np.ndarray, got {type(audio).__name__}"
            )

        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        try:
            #dynamically toggle fp16 evaluation based on backend device capability
            is_fp16 = self._model.device.type == "cuda"

            #whisper natively ingests normalized float32 numpy arrays directly
            result = self._model.transcribe(
                audio,
                language=language,
                temperature=temperature,
                fp16=is_fp16,
            )
            return (result.get("text") or "").strip()
        except Exception as e:
            raise TranscriptionError(f"[whisper_local] Transcription failed: {e}")