"""
provider registry for Translator.
This module manages the deferred instantiation of translation providers
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from .base import TranslationProvider, TranslationError, ProviderConfigError

logger = logging.getLogger(__name__)

# Registry of provider factories
_PROVIDER_FACTORIES: Dict[str, Callable[[Dict[str, Any]], TranslationProvider]] = {}


def register_provider(
    name: str, 
    factory: Callable[[Dict[str, Any]], TranslationProvider]
) -> None:
    """Register a provider factory under a canonical name"""
    _PROVIDER_FACTORIES[name] = factory
    logger.debug(f"Registered translation provider factory: {name}")


def available_providers() -> List[str]:
    """Return list of all registered provider names"""
    return list(_PROVIDER_FACTORIES.keys())


class ProviderRegistry:
    """
    A registry that defers translation provider instantiation until first use
    to minimize startup time and memory footprint.
    """
    def __init__(self):
        # Maps provider_name -> { "config": dict, "instance": Optional[TranslationProvider] }
        self._providers: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def configure(
        self,
        provider_name: str,
        api_key: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """
        Configure a provider's settings before instantiation.
        """
        if provider_name not in _PROVIDER_FACTORIES:
            raise ValueError(
                f"Unknown provider '{provider_name}'. "
                f"Available: {available_providers()}"
            )

        # Bundle the config as expected by base.py
        config_dict = {"api_key": api_key, **kwargs}
        
        with self._lock:
            self._providers[provider_name] = {
                "config": config_dict,
                "instance": None,  # Instantiated lazily on first use
            }
            
        logger.info(f"Configured lazy provider '{provider_name}'")

    def translate(
        self,
        provider_name: str,
        text: str,
        source_lang: str,
        target_lang: str,
        **kwargs: Any
    ) -> str:
        """
        Translates text, lazily instantiating the provider if necessary.
        """
        entry = self._providers.get(provider_name)
        
        if entry is None:
            raise ValueError(f"Provider '{provider_name}' has not been configured.")

        # Lazy Instantiation with Double-Checked Locking
        if entry["instance"] is None:
            with self._lock:
                # Check again inside the lock to prevent a race condition
                if entry["instance"] is None:
                    factory = _PROVIDER_FACTORIES[provider_name]
                    try:
                        instance = factory(entry["config"])
                        entry["instance"] = instance
                        logger.info(f"Lazily instantiated '{provider_name}'")
                    except Exception as e:
                        logger.error(f"Failed to instantiate '{provider_name}': {e}")
                        raise ProviderConfigError(f"Provider initialization failed: {e}")

        provider: TranslationProvider = entry["instance"]

        if not provider.is_available():
            raise RuntimeError(f"Provider '{provider_name}' is currently unavailable.")

        # Pass the extra kwargs down to support provider-specific settings
        return provider.translate(text, source_lang, target_lang, **kwargs)