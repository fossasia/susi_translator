"""
provider registry for Translator
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from .base import TranslationProvider, ProviderConfigError

logger = logging.getLogger(__name__)

# Registry of provider factories
_PROVIDER_FACTORIES: Dict[str, Callable[[Dict[str, Any]], TranslationProvider]] = {}


def register_provider(
    name: str, 
    factory: Callable[[Dict[str, Any]], TranslationProvider]
) -> None:
    
    """Registers a provider factory under a canonical name"""
    
    _PROVIDER_FACTORIES[name] = factory
    logger.debug(f"Registered translation provider factory: {name}")


def available_providers() -> List[str]:
    """Return list of all registered provider names"""
    return list(_PROVIDER_FACTORIES.keys())


class ProviderRegistry:

    def __init__(self):
        self._tenants: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def configure(
        self,
        tenant_id: str,          
        provider_name: str,
        api_key: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        if provider_name not in _PROVIDER_FACTORIES:
            raise ValueError(
                f"Unknown provider '{provider_name}'. "
                f"Available: {available_providers()}"
            )

        config_dict = {"api_key": api_key, **kwargs}

        with self._lock:
            if tenant_id not in self._tenants:
                self._tenants[tenant_id] = {}

            self._tenants[tenant_id][provider_name] = {
                "config": config_dict,
                "factory": _PROVIDER_FACTORIES[provider_name],
                "instance": None,
            }

        logger.info(f"Configured lazy provider '{provider_name}' for tenant '{tenant_id}'")

    def translate(
        self,
        tenant_id: str,           
        provider_name: str,
        text: str,
        source_lang: str,
        target_lang: str,
        **kwargs: Any
    ) -> str:
        """
        lazily instantiating the provider with tenant isolation
        """

        tenant_providers = self._tenants.get(tenant_id)
        if not tenant_providers:
            raise ValueError(f"No providers configured for tenant '{tenant_id}'.")

        entry = tenant_providers.get(provider_name)
        if entry is None:
            raise ValueError(f"Provider '{provider_name}' has not been configured for tenant '{tenant_id}'.")

        # Lazy Instantiation with Double Checked Locking
        if entry["instance"] is None:
            with self._lock:
                if entry["instance"] is None:
                    factory = entry["factory"]
                    try:
                        instance = factory(entry["config"])
                        entry["instance"] = instance
                        logger.info(f"Lazily instantiated '{provider_name}' for tenant '{tenant_id}'")
                    except Exception as e:
                        logger.exception(f"Failed to instantiate '{provider_name}' for tenant '{tenant_id}': {e}")
                        raise ProviderConfigError(f"Provider initialization failed: {e}")

        provider: TranslationProvider = entry["instance"]

        if not provider.is_available():
            raise RuntimeError(f"Provider '{provider_name}' is currently unavailable.")

        return provider.translate(text, source_lang, target_lang, **kwargs)