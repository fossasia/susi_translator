"""
Basic provider registry for Translator,
This manages the registration and retrieval of translation providers
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from .base import TranslationProvider, TranslationError

logger = logging.getLogger(__name__)

class ProviderRegistry:
    """
    A simple registry to hold instantiated translation providers.
    """

    def __init__(self):
        self._providers: Dict[str, TranslationProvider] = {}

    def register(self, provider: TranslationProvider) -> None:
        """
        Registers an already-instantiated translation provider
        """
        self._providers[provider.provider_name] = provider
        logger.info(f"Registered translation provider: {provider.provider_name}")

    def get_provider(self, provider_name: str) -> TranslationProvider:
        """
        Retrieves a provider by name, Raises ValueError if the provider is not registered.
        """
        if provider_name not in self._providers:
            raise ValueError(f"Provider '{provider_name}' is not registered.")
        return self._providers[provider_name]

    def translate(
        self, 
        provider_name: str, 
        text: str, 
        source_lang: str, 
        target_lang: str, 
        **kwargs: Any
    ) -> str:
        """
        Translates text using the specified provider
        """
        provider = self.get_provider(provider_name)
        
        if not provider.is_available():
            raise RuntimeError(f"Provider '{provider_name}' is currently unavailable.")
            
        # Pass the extra kwargs down to support provider-specific settings
        return provider.translate(text, source_lang, target_lang, **kwargs)