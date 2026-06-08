"""
Translation and LLM provider architecture for susi_translator
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

# Configure a base logger for the module
logger = logging.getLogger(__name__)


class TranslationError(Exception):
    """Base exception for all translation related failures"""


class ProviderConfigError(TranslationError):
    """Raised when a provider is initialized with missing or malformed configuration"""


class ProviderUnavailableError(TranslationError):
    """Raised when a provider is registered but currently unavailable"""
    pass


class TranslationProvider(ABC):

    def __init__(self, config: Optional[Dict[str, Any]] = None):

        # Create a shallow copy to prevent accidental mutation of the original dict
        self.config = dict(config) if config else {}

    @abstractmethod
    def translate(
        self, 
        text: str, 
        source_lang: str, 
        target_lang: str, 
        **kwargs: Any
    ) -> str:
       
        ...


    #health check
    @abstractmethod
    def is_available(self) -> bool:
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...