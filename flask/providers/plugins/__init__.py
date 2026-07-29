from providers.registry import register_provider
from .transcription_plugins.faster_whisper_local import FasterWhisperLocalProvider
from .translation_plugins.nllb_ctranslate2 import NLLBCTranslate2Provider


# Transcription providers — CTranslate2 optimized backend
register_provider(
    "faster_whisper",
    factory=lambda config: FasterWhisperLocalProvider(config)
)


# Translation providers — CTranslate2 optimized backend
register_provider(
    "nllb_ctranslate2",
    factory=lambda config: NLLBCTranslate2Provider(config)
)
