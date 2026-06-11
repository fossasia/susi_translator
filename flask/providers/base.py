"""
Translation and Transcription provider architecture for susi_translator
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class TranslationError(Exception):
    """Base exception for all translation related failures"""


class TranscriptionError(Exception):
    """Base exception for all transcription related failures"""


class ProviderConfigError(Exception):
    """Raised when a provider is initialized with missing or malformed configuration"""


class BaseProvider(ABC):
    """
    Common root for all providers
    holds config, health-check, and identity contracts
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = dict(config) if config else {}

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is healthy and ready to serve requests"""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """
        Canonical machine-readable name for this provider
        """
        ...


class TranscriptionProvider(BaseProvider):
    """
    ABC for providers that convert transcriptions from audio
    """
    @abstractmethod
    def transcribe(
        self,
        audio,          
        **kwargs: Any
    ) -> str:
        """
        Transcribe raw audio to text with provider specific options 
        """
        ...


class TranslationProvider(BaseProvider):
    """
    ABC for providers for translating text between languages
    """
    @abstractmethod
    def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        **kwargs: Any
    ) -> str:
        """
        Translate text from source lang to target lang with provider-specific options 
        """
        ...