"""
FasterWhisperLocalProvider: TranscriptionProvider implementation using
the faster-whisper library which is backed by the CTranslate2 inference engine.

Key advantages over openai-whisper:
- INT8 / FP16 quantization: 4x lower memory footprint
- ~4x faster inference on CPU; ~2x on CUDA
- No PyTorch required at runtime
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from providers.base import TranscriptionProvider, TranscriptionError, ProviderConfigError

logger = logging.getLogger(__name__)


class FasterWhisperLocalProvider(TranscriptionProvider):
    """
    Wraps faster-whisper (CTranslate2 backend) for local in-process transcription.
    Fully substitutable for the old WhisperLocalProvider — same config keys,
    same return contract (plain str).
    """

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        self._model = None  # Loaded lazily on first transcribe() call

        # Model identity
        self._model_size = self.config.get("model_size", "medium")

        # Hardware
        self._device_config = self.config.get("device", None)

        # compute_type: int8 on CPU (low memory), float16 on CUDA (speed)
        self._compute_type = self.config.get("compute_type", None)  # resolved in load_model()

        # Transcription options
        self._language = self.config.get("language", None)
        # Default to greedy decoding (beam_size=1) for much faster CPU inference
        self._beam_size = int(self.config.get("beam_size", 1))
        self._temperature = float(self.config.get("temperature", 0.0))

    @property
    def provider_name(self) -> str:
        return "faster_whisper"

    def is_available(self) -> bool:
        """
        Returns True if faster_whisper is importable.
        faster-whisper ships CTranslate2 as a bundled dependency — no separate check needed.
        """
        try:
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def load_model(self) -> None:
        """
        Load the faster-whisper model into memory.
        Called once on the first transcribe() call (lazy) or eagerly by the registry warmup thread.

        faster-whisper automatically downloads the model from HuggingFace Hub on first use
        and caches it to ~/.cache/huggingface/hub — no manual conversion step required.
        """
        if self._model is not None:
            logger.info(
                f"[faster_whisper] Model '{self._model_size}' already loaded in memory."
            )
            return

        from faster_whisper import WhisperModel
        import ctranslate2

        # Resolve device
        try:
            device = self._device_config or (
                "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            )
        except Exception:
            device = self._device_config or "cpu"

        # Resolve compute_type: INT8 is optimal on CPU; FP16 on CUDA
        if self._compute_type:
            compute_type = self._compute_type
        else:
            compute_type = "float16" if device == "cuda" else "int8"

        logger.info(
            f"[faster_whisper] Loading model='{self._model_size}' "
            f"on device='{device}' with compute_type='{compute_type}'"
        )

        def _load(dev: str, ctype: str) -> None:
            self._model = WhisperModel(
                self._model_size,
                device=dev,
                compute_type=ctype,
                cpu_threads=4,
            )
            self._resolved_device = dev
            logger.info(
                f"[faster_whisper] Model '{self._model_size}' loaded successfully "
                f"on device='{dev}' compute_type='{ctype}'."
            )

        try:
            _load(device, compute_type)
        except RuntimeError as e:
            # CUDA was detected but runtime libs (libcublas, libcudnn, etc.) are missing.
            # Transparently fall back to CPU + int8 so the server keeps running.
            _CUDA_LIB_HINTS = ("cannot be loaded", "not found", "libcublas", "libcudnn",
                               "libcurand", "CUDA error", "cudaErrorNoDevice")
            if device == "cuda" and any(h in str(e) for h in _CUDA_LIB_HINTS):
                logger.warning(
                    f"[faster_whisper] CUDA unavailable ({e}). "
                    "Falling back to device='cpu' compute_type='int8'."
                )
                try:
                    _load("cpu", "int8")
                except Exception as cpu_e:
                    raise ProviderConfigError(
                        f"[faster_whisper] CPU fallback also failed: {cpu_e}"
                    ) from cpu_e
            else:
                raise ProviderConfigError(
                    f"[faster_whisper] Failed to load model '{self._model_size}': {e}"
                ) from e
        except Exception as e:
            raise ProviderConfigError(
                f"[faster_whisper] Failed to load model '{self._model_size}': {e}"
            ) from e

    _CUDA_LIB_HINTS = frozenset([
        "cannot be loaded", "not found", "libcublas", "libcudnn",
        "libcurand", "CUDA error", "cudaErrorNoDevice",
    ])

    def transcribe(self, audio: np.ndarray, **kwargs: Any) -> str:
        """
        Transcribe a normalized float32 mono audio array.

        faster-whisper returns a generator of Segment objects; we join them into a single string
        to match the plain-str contract of the TranscriptionProvider ABC.
        """
        if self._model is None:
            self.load_model()

        language = kwargs.get("language", self._language)
        beam_size = int(kwargs.get("beam_size", self._beam_size))
        temperature = float(kwargs.get("temperature", self._temperature))

        if not isinstance(audio, np.ndarray):
            raise TranscriptionError(
                f"[faster_whisper] Expected np.ndarray, got {type(audio).__name__}"
            )

        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        def _run_transcribe() -> str:
            segments, _info = self._model.transcribe(
                audio,
                language=language,
                beam_size=beam_size,
                temperature=temperature,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
                # Suppress repetition typical of silence/noise
                no_speech_threshold=0.6,
                log_prob_threshold=-1.0,
            )
            # Materialise the lazy generator and join all segment texts
            return " ".join(segment.text for segment in segments).strip()

        try:
            return _run_transcribe()
        except RuntimeError as e:
            # The WhisperModel constructor can succeed even when libcublas is absent —
            # the error only fires when the CUDA encoder actually runs. Catch it here,
            # drop the CUDA model, force a CPU reload, and retry once.
            if any(h in str(e) for h in self._CUDA_LIB_HINTS):
                logger.warning(
                    f"[faster_whisper] CUDA inference failed ({e}). "
                    "Dropping model and reloading on CPU/int8 — this will only happen once."
                )
                self._model = None
                self._device_config = "cpu"
                self._compute_type = "int8"
                self.load_model()
                try:
                    return _run_transcribe()
                except Exception as retry_e:
                    raise TranscriptionError(
                        f"[faster_whisper] CPU retry also failed: {retry_e}"
                    ) from retry_e
            raise TranscriptionError(f"[faster_whisper] Transcription failed: {e}") from e
        except Exception as e:
            raise TranscriptionError(f"[faster_whisper] Transcription failed: {e}") from e
