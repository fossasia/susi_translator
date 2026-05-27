"""
Per-tenant provider registry for Susi Translator,
This module manages the lifecycle of translation 
providers
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from .base import TranslationProvider, TranslationError, ProviderConfigError

logger = logging.getLogger(__name__)

# Registry of provider factories. Each factory is a callable that takes a config dict
# and returns a TranslationProvider instance
_PROVIDER_FACTORIES: Dict[str, Callable[[Dict[str, Any]], TranslationProvider]] = {}


def register_provider(
    name: str, 
    factory: Callable[[Dict[str, Any]], TranslationProvider]
) -> None:
    """
    Register a provider factory under a canonical name
    """
    _PROVIDER_FACTORIES[name] = factory
    logger.debug(f"Registered translation provider: {name}")


def available_providers() -> List[str]:
    """Return list of all registered provider names"""
    return list(_PROVIDER_FACTORIES.keys())


class ProviderRegistry:
    """
    Per-tenant provider registry. One shared instance should be created
    at module load time in transcribe_server.py and used across all requests
    """

    def __init__(self):
        # tenant_id -> { "provider_name": str, "config": dict, "instance": Optional[TranslationProvider] }
        self._tenants: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def configure(
        self,
        tenant_id: str,
        provider_name: str,
        api_key: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """
        Configure a provider for a tenant session.
        """
        if provider_name not in _PROVIDER_FACTORIES:
            raise ValueError(
                f"Unknown provider '{provider_name}'. "
                f"Available: {available_providers()}"
            )

        # Bundle the config as expected by base.py
        config_dict = {"api_key": api_key, **kwargs}

        with self._lock:
            self._tenants[tenant_id] = {
                "provider_name": provider_name,
                "config": config_dict,
                "instance": None,  # instantiated lazily on first use
            }
            
        logger.info(
            f"Configured provider '{provider_name}' for tenant '{tenant_id}'"
        )

    def translate(
        self,
        tenant_id: str,
        text: str,
        source_lang: str,
        target_lang: str,
        **kwargs: Any
    ) -> Optional[str]:
        """
        Translate text for a given tenant using their configured provider.
        """
        #Fast, lock-free read to get the tenant entry
        entry = self._tenants.get(tenant_id)
        if entry is None:
            return None  # no translation configured for this tenant

        #Lazy Instantiation with Double-Checked Locking
        if entry["instance"] is None:
            with self._lock:
                
                if entry["instance"] is None:
                    provider_name = entry["provider_name"]
                    factory = _PROVIDER_FACTORIES[provider_name]
                    
                    try:
                        # Pass the bundled config dict to match base.py
                        instance = factory(entry["config"])
                        entry["instance"] = instance
                        logger.info(f"Lazily instantiated '{provider_name}' for tenant '{tenant_id}'")
                    except Exception as e:
                        logger.error(f"Failed to instantiate '{provider_name}': {e}")
                        raise ProviderConfigError(f"Provider initialization failed: {e}")

        provider: TranslationProvider = entry["instance"]

        if not provider.is_available():
            logger.warning(
                f"Provider '{provider.provider_name}' is not available "
                f"for tenant '{tenant_id}'"
            )
            return None

        # Pass the extra kwargs down to support provider-specific settings
        return provider.translate(text, source_lang, target_lang, **kwargs)

    def remove(self, tenant_id: str) -> None:
        """Remove provider config for a tenant"""
        with self._lock:
            self._tenants.pop(tenant_id, None)

    def get_provider_name(self, tenant_id: str) -> Optional[str]:
        """Return the configured provider name for a tenant, or None."""
        with self._lock:
            entry = self._tenants.get(tenant_id)
            return entry["provider_name"] if entry else None