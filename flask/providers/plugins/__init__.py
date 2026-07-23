from providers.registry import register_provider
from .transcription_plugins.faster_whisper_local import FasterWhisperLocalProvider
from .translation_plugins.nllb_ctranslate2 import NLLBCTranslate2Provider


# Transcription providers
register_provider(
    "faster_whisper",
    factory=lambda config: FasterWhisperLocalProvider(config),
    memory_mb_map={
        "tiny": 150,
        "base": 300,
        "small": 1000,
        "medium": 3000,
        "large-v2": 6000,
        "large-v3": 6000,
        "default": 3000,  # same as medium (the system default)
    },
    config_memory_key="model_size",
)


# Translation providers
register_provider(
    "nllb_ctranslate2",
    factory=lambda config: NLLBCTranslate2Provider(config),
    memory_mb_map={
        "nllb-200-distilled-600M": 1500,
        "nllb-200-distilled-1.3B": 3000,
        "nllb-200-1.3B": 3000,
        "default": 1500,  # same as nllb-200-distilled-600M (the system default)
    },
    config_memory_key="model_id",
)
