"""
NLLBCTranslate2Provider: TranslationProvider implementation using
NLLB-200 via CTranslate2, a quantized, high-performance inference engine
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Optional

from providers.base import TranslationProvider, TranslationError, ProviderConfigError

logger = logging.getLogger(__name__)


# Shared BCP-47 to NLLB language code mapping
# Mirrors the mapping in nllb_local for full language parity
LANG_CODE_MAP = {
    "en": "eng_Latn",
    "es": "spa_Latn",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "hi": "hin_Deva",
    "zh": "zho_Hans",
    "ar": "arb_Arab",
    "pt": "por_Latn",
    "ru": "rus_Cyrl",
    "ja": "jpn_Jpan",
    "ko": "kor_Hang",
    "it": "ita_Latn",
}


def _resolve_lang_code(lang: str) -> str:
    """Resolve short BCP-47 code to NLLB format. Returns as-is if already NLLB format or unknown."""
    return LANG_CODE_MAP.get(lang, lang)


def _get_ct2_model_path(model_id: str) -> str:
    """
    Return the path to a CTranslate2 converted model directory,
    If the model has not been converted yet, convert it and cache it
    """
    safe_name = model_id.replace("/", "_")
    cache_dir = os.path.join(
        os.path.expanduser("~"), ".cache", "ctranslate2", f"{safe_name}_int8"
    )
    marker = os.path.join(cache_dir, "model.bin")

    if os.path.exists(marker):
        logger.info(f"[nllb_ctranslate2] Using cached CTranslate2 model at '{cache_dir}'")
        return cache_dir

    logger.info(
        f"[nllb_ctranslate2] Converting '{model_id}' to CTranslate2 format... "
    )

    try:
        from ctranslate2.converters import TransformersConverter
        converter = TransformersConverter(
            model_name_or_path=model_id,
            low_cpu_mem_usage=True,
        )
        converter.convert(cache_dir, quantization="int8", force=True)
        logger.info(f"[nllb_ctranslate2] Conversion complete. Model saved to '{cache_dir}'")
    except Exception as e:
        raise ProviderConfigError(
            f"[nllb_ctranslate2] Failed to convert model '{model_id}' to CTranslate2 format: {e}"
        ) from e

    return cache_dir


class NLLBCTranslate2Provider(TranslationProvider):
    """
    Wraps NLLB-200 via CTranslate2 for high-performance translation
    """

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        self._translator = None
        self._tokenizer = None
        self._lock = threading.Lock()

        self._model_id = self.config.get("model_id", "facebook/nllb-200-distilled-600M")
        self._device_config = self.config.get("device", None)
        self._compute_type = self.config.get("compute_type", None)  # resolved in load_model()
        self._num_beams = int(self.config.get("num_beams", 1))
        self._inter_threads = int(self.config.get("inter_threads", 1))
        self._intra_threads = int(self.config.get("intra_threads", 0))  # 0 = auto

        self.device = "cpu"  # resolved dynamically in load_model()

    @property
    def provider_name(self) -> str:
        return "nllb_ctranslate2"

    def is_available(self) -> bool:
        try:
            import ctranslate2  # noqa: F401
            import transformers  # noqa: F401
            return True
        except ImportError:
            return False

    def load_model(self) -> None:
        """
        Convert and load the CTranslate2 model with HuggingFace tokenizer.
        Auto hardware detection with safe fallback to CPU.
        """
        with self._lock:
            if self._translator is not None and self._tokenizer is not None:
                logger.info(
                    f"[{self.provider_name}] Model '{self._model_id}' already loaded in memory."
                )
                return

            import ctranslate2
            from transformers import AutoTokenizer

        # Resolve device
        try:
            device = self._device_config or (
                "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            )
        except Exception:
            device = self._device_config or "cpu"

        if device == "cuda":
            try:
                if ctranslate2.get_cuda_device_count() == 0:
                    logger.warning(
                        f"[{self.provider_name}] CUDA requested, but no GPU found. "
                        "Falling back to CPU."
                    )
                    device = "cpu"
            except Exception:
                device = "cpu"

        self.device = device

        # Resolve compute_type
        compute_type = self._compute_type or (
            "float16" if device == "cuda" else "int8"
        )

        logger.info(
            f"[{self.provider_name}] Loading '{self._model_id}' "
            f"on '{self.device}' with compute_type='{compute_type}'..."
        )

        _CUDA_LIB_HINTS = frozenset([
            "cannot be loaded", "not found", "libcublas", "libcudnn",
            "libcurand", "CUDA error", "cudaErrorNoDevice",
        ])

        def _load(dev: str, ctype: str) -> None:
            ct2_model_path = _get_ct2_model_path(self._model_id)
            self._translator = ctranslate2.Translator(
                ct2_model_path,
                device=dev,
                compute_type=ctype,
                inter_threads=self._inter_threads,
                intra_threads=self._intra_threads,
            )
            # Tokenizer is pure Python/sentencepiece — device-agnostic
            self._tokenizer = AutoTokenizer.from_pretrained(self._model_id)
            self.device = dev
            logger.info(
                f"[{self.provider_name}] Model '{self._model_id}' loaded successfully "
                f"on device='{dev}' compute_type='{ctype}'."
            )

        try:
            _load(device, compute_type)
        except RuntimeError as e:
            if device == "cuda" and any(h in str(e) for h in _CUDA_LIB_HINTS):
                logger.warning(
                    f"[{self.provider_name}] CUDA unavailable ({e}). "
                    "Falling back to device='cpu' compute_type='int8'."
                )
                try:
                    _load("cpu", "int8")
                except Exception as cpu_e:
                    raise ProviderConfigError(
                        f"[{self.provider_name}] CPU fallback also failed: {cpu_e}"
                    ) from cpu_e
            else:
                raise ProviderConfigError(
                    f"[{self.provider_name}] Failed to load NLLB CTranslate2 model: {e}"
                ) from e
        except ProviderConfigError:
            raise
        except Exception as e:
            raise ProviderConfigError(
                f"[{self.provider_name}] Failed to load NLLB CTranslate2 model: {e}"
            ) from e

    def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        **kwargs: Any,
    ) -> str:
        """
        Translate text from source_lang to target_lang using CTranslate2.
        """
        if not text or not text.strip():
            return ""

        source_lang = _resolve_lang_code(source_lang)
        target_lang = _resolve_lang_code(target_lang)

        if self._translator is None:
            self.load_model()

        max_decoding_length = int(kwargs.get("max_length", 512))

        def _run_translate() -> str:
            with self._lock:
                # _translator may have been nulled by another thread's CUDA fallback
                if self._translator is None or self._tokenizer is None:
                    raise TranslationError(
                        f"[{self.provider_name}] Model not loaded — reload in progress."
                    )

                # Set source language on the tokenizer for correct special token injection
                self._tokenizer.src_lang = source_lang

                # Validate the target language token exists in the vocabulary
                target_lang_id = self._tokenizer.convert_tokens_to_ids(target_lang)
                if target_lang_id == self._tokenizer.unk_token_id:
                    raise TranslationError(
                        f"[{self.provider_name}] Unsupported target language code: '{target_lang}'. "
                        "Ensure you are using NLLB BCP-47 codes."
                    )

                # Tokenize to token strings
                encoded = self._tokenizer(text)
                input_tokens = self._tokenizer.convert_ids_to_tokens(encoded["input_ids"])
                results = self._translator.translate_batch(
                    [input_tokens],
                    target_prefix=[[target_lang]],
                    beam_size=self._num_beams,
                    max_decoding_length=max_decoding_length,
                    repetition_penalty=1.2,
                    no_repeat_ngram_size=3,
                )

                # Strip the forced target-lang prefix token before decoding
                output_tokens = results[0].hypotheses[0][1:]
                output_ids = self._tokenizer.convert_tokens_to_ids(output_tokens)
                result = self._tokenizer.decode(output_ids, skip_special_tokens=True)
            return result.strip()

        try:
            return _run_translate()
        except RuntimeError as e:
            # Catch inference time CUDA missing lib errors
            _CUDA_LIB_HINTS = ("cannot be loaded", "not found", "libcublas", "libcudnn",
                               "libcurand", "CUDA error", "cudaErrorNoDevice")
            if any(h in str(e) for h in _CUDA_LIB_HINTS):
                with self._lock:
                    if self.device != "cpu":
                        logger.warning(
                            f"[{self.provider_name}] CUDA inference failed ({e}). "
                            "Dropping model and reloading on CPU, this will only happen once."
                        )
                        self._translator = None
                        self._device_config = "cpu"
                        self._compute_type = "int8"
                self.load_model()
                try:
                    return _run_translate()
                except Exception as retry_e:
                    raise TranslationError(
                        f"[{self.provider_name}] CPU retry also failed: {retry_e}"
                    ) from retry_e
            raise TranslationError(f"[{self.provider_name}] Inference failed: {e}") from e
        except TranslationError:
            raise
        except Exception as e:
            raise TranslationError(f"[{self.provider_name}] Inference failed: {e}") from e
