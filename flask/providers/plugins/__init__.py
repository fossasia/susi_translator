from providers.registry import register_provider
from .transcription_plugins.whisper_local import WhisperLocalProvider
from .translation_plugins.nllb_local import NLLBLocalProvider



# Transcription providers
register_provider(
    "whisper_local",
    factory=lambda config: WhisperLocalProvider(config)
)




# Translation providers
register_provider(
    "nllb_local",
    factory=lambda config: NLLBLocalProvider(config)
)

