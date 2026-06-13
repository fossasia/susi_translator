

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

from providers.base import TranslationProvider, TranslationError, ProviderConfigError

logger = logging.getLogger(__name__)

_LANG_NAMES: dict[str, str] = {
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "hi": "Hindi",
    "zh": "Simplified Chinese",
    "ar": "Arabic",
    "pt": "Portuguese",
    "ru": "Russian",
    "ja": "Japanese",
    "ko": "Korean",
    "it": "Italian",
}




class GroqLlamaProvider(TranslationProvider):
    """
    Translates text via Groq's llama-3.1-8b-instant model
    """

    MODEL = "llama-3.1-8b-instant"

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)

        raw_key = self.config.get("api_key", "").strip()
        if not raw_key:
            raise ProviderConfigError(
                "[groq_llama] api_key is required. "
                "Get a free key at https://console.groq.com"
            )

        # Instantiate client once and remove key from config dict
        import groq as _groq
        self.client = _groq.Groq(api_key=raw_key)
        self.config.pop("api_key", None)

    @property
    def provider_name(self) -> str:
        return "groq_llama"

    def is_available(self) -> bool:
        return self.client is not None

    def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        **kwargs: Any,
    ) -> str:
        if not text or not text.strip():
            return ""
        if source_lang == target_lang:
            return text

        src_name = _LANG_NAMES.get(source_lang, source_lang)
        tgt_name = _LANG_NAMES.get(target_lang, target_lang)

        system_prompt = (
            f"You are a professional subtitle translator. "
            f"Translate the following {src_name} text into {tgt_name}. "
            f"Output ONLY the translated text with no introduction, explanation, or commentary. "
            f"Do NOT use markdown formatting. "
            f"If the text is already in {tgt_name}, output it unchanged."
        )

        try:
            import groq as _groq
            response = self.client.chat.completions.create(
                model=self.MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text.strip()},
                ],
                temperature=0.1,
                max_tokens=512,
            )
            return response.choices[0].message.content.strip()

        except _groq.RateLimitError:
            logger.warning("[groq_llama] 429 Too Many Requests from Groq")
            time.sleep(3)
            raise TranslationError("[groq_llama] Rate limited by Groq. Will retry next chunk.")
        except _groq.APIError as exc:
            raise TranslationError(f"[groq_llama] Groq API error: {exc}") from exc
        except Exception as exc:
            raise TranslationError(f"[groq_llama] Unexpected error: {exc}") from exc