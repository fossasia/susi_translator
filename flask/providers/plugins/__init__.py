from providers.registry import register_provider
from .transcription_plugins.whisper_local import WhisperLocalProvider
from .translation_plugins.nllb_local import NLLBLocalProvider
from .transcription_plugins.groq_whisper import GroqWhisperProvider
from .translation_plugins.groq_llama import GroqLlamaProvider


# Transcription providers
register_provider(
    "whisper_local",
    factory=lambda config: WhisperLocalProvider(config)
)

register_provider(
    "groq_whisper",
    factory=lambda config: GroqWhisperProvider(config)
)


# Translation providers
register_provider(
    "nllb_local",
    factory=lambda config: NLLBLocalProvider(config)
)

register_provider(
    "groq_llama",
    factory=lambda config: GroqLlamaProvider(config)
)