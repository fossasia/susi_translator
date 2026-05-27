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


class ProviderConfigError(Exception):
    """Raised when a provider is initialized with missing or malformed configuration"""


class TranslationProvider(ABC):
    """
    Abstract base class for all translation and LLM providers.

    To ensure fast startup time are strictly deferred until a 
    translation is actually requested, rather than loading at import time.

    We also enforce tenant isolation by making sure each instance holds its own
    distinct configuration without relying on shared class-level state. 
    
    the translate method leverages kwargs to remain extensible, allowing you to easily pass 
    provider-specific settings like, an LLM's temperature or DeepL's formality—without ever having 
    to alter the base signature.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initializing the provider with tenant-specific configuration,
        this can include API keys, model paths, or any other settings required 
        for the provider to function.
        """
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
        """
        Translate text from source_lang to target_lang
        **kwargs: Optional provider specific parameters('temperature' for LLMs, 
        'formality' for DeepL)
        """
        ...

    #health check to ensure provider is ready to serve requests
    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if the provider is healthy and ready to serve requests
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """
        The canonical, machine-readable name of the provider (e.g., 'nllb', 'deepl', 'openai').
        Used heavily in logging, telemetry, and registry lookups
        """
        ...