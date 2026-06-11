"""
NLLBLocalProvider TranslationProvider implementation using
Meta NLLB-200 via HF transformers loaded into RAM
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from providers.base import TranslationProvider, TranslationError, ProviderConfigError

logger = logging.getLogger(__name__)


#TODO: will move this mapping to a config file
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
    """Resolve short BCP-47 code to NLLB format Returns as-is if already in NLLB format or unknown"""
    return LANG_CODE_MAP.get(lang, lang)


class NLLBLocalProvider(TranslationProvider):
    """
    wraps NLLB-200 loaded locally into RAM via the HuggingFace transformers library
    torch and transformers are imported lazily to keep server boot instantly
    """

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        self._model = None
        self._tokenizer = None
        
        # 600M is a great balance of speed/quality for real-time local CPU/GPU inference

        self._model_id = self.config.get("model_id", "facebook/nllb-200-distilled-600M")
        self._device_config = self.config.get("device", None)
        self._num_beams = int(self.config.get("num_beams", 1))
        self.device = "cpu"  # Set dynamically

    @property
    def provider_name(self) -> str:
        return "nllb_local"

    def is_available(self) -> bool:
            
        try:
            import torch 
            import transformers  
            return True
        except ImportError:
            return False

    def _load_model(self):
        """
        Loads the NLLB tokenizer and model into RAM
        auto hardware detection with safe fallback to CPU 
        """
        import torch
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

        # Device hardware detection and safety fallback
        self.device = self._device_config or ("cuda" if torch.cuda.is_available() else "cpu")
        
        if self.device == "cuda" and not torch.cuda.is_available():
            logger.warning(
                f"[{self.provider_name}] CUDA requested, but no GPU available. "
                "Safely falling back to CPU."
            )
            self.device = "cpu"

        logger.info(f"[{self.provider_name}] Loading '{self._model_id}' on '{self.device}'...")
        
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(self._model_id)
            self._model = AutoModelForSeq2SeqLM.from_pretrained(self._model_id).to(self.device)
            logger.info(f"[{self.provider_name}] Model '{self._model_id}' loaded successfully.")
        except Exception as e:
            raise ProviderConfigError(f"[{self.provider_name}] Failed to load NLLB model: {e}")

    def translate(
        self, 
        text: str, 
        source_lang: str, 
        target_lang: str, 
        **kwargs: Any
    ) -> str:
        """
        translate text from source lang to target lang using the loaded model
        """
        if not text or not text.strip():
            return ""
        

        source_lang = _resolve_lang_code(source_lang)
        target_lang = _resolve_lang_code(target_lang)

        if self._model is None or self._tokenizer is None:
            self._load_model()

        max_length = kwargs.get("max_length", 512)

        try:
            
            self._tokenizer.src_lang = source_lang
            
            # Map the target language to its specific token 
            target_lang_id = self._tokenizer.convert_tokens_to_ids(target_lang)
            if target_lang_id == self._tokenizer.unk_token_id:
                raise TranslationError(
                    f"[{self.provider_name}] Unsupported target language code: '{target_lang}'. "
                    "Ensure you are using NLLB BCP-47 codes"
                )

            # Tokenize and push to the correct hardware device
            inputs = self._tokenizer(text, return_tensors="pt").to(self.device)
            
            # Generate translation (greedy by default for real-time speed)
            translated_tokens = self._model.generate(
                **inputs, 
                forced_bos_token_id=target_lang_id, 
                max_new_tokens=max_length,
                max_length=None,
                num_beams=self._num_beams,
                repetition_penalty=1.2,
                no_repeat_ngram_size=3,
            )
            
            # Decode back to a clean string
            result = self._tokenizer.batch_decode(translated_tokens, skip_special_tokens=True)[0]
            return result.strip()
            
        except TranslationError:
            raise
        except Exception as e:
            raise TranslationError(f"[{self.provider_name}] Inference failed: {e}")