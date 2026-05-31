"""
Per tenant provider registry for Susi Translator.
This module manages the lifecycle of transcription and translation 
providers side-by-side using an isolated role-based slot pipeline.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from .base import (
    BaseProvider,
    TranslationProvider,
    TranscriptionProvider,
    TranslationError,
    TranscriptionError,
    ProviderConfigError,
)

logger = logging.getLogger(__name__)

# Unified registry of provider factories. Each factory is a callable that takes a config dict
# and returns a concrete subclass of BaseProvider
_PROVIDER_FACTORIES: Dict[str, Callable[[Dict[str, Any]], BaseProvider]] = {}


def register_provider(
    name: str, 
    factory: Callable[[Dict[str, Any]], BaseProvider]
) -> None:
    """
    Register a provider factory under a canonical name.
    """
    _PROVIDER_FACTORIES[name] = factory
    logger.debug(f"Registered plugin provider factory: {name}")


def available_providers() -> List[str]:
    """Return a list of all registered provider names."""
    return list(_PROVIDER_FACTORIES.keys())


class ProviderRegistry:
    """
    Per-tenant provider registry. One shared instance should be created
    at module load time in transcribe_server.py and used across all requests
    """

    def __init__(self):
        self._tenants: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def configure(
        self,
        tenant_id: str,
        transcription: Optional[Dict[str, Any]] = None,
        translation: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        configures a flexible execution pipeline for a tenant session.
        accepts optional transcription and translation sub-configs.
        
        validations run outside the thread lock to avoid system deadlocks
        when configurations change mid stream.
        """
        t_name = None
        tx_name = None

        #validating Transcription Configuration outside the lock boundaries
        if transcription:
            t_name = transcription.get("provider_name")
            if t_name and t_name not in _PROVIDER_FACTORIES:
                raise ValueError(
                    f"Unknown transcription provider '{t_name}'. "
                    f"Available: {available_providers()}"
                )

        #validating Translation Configuration OUTSIDE the lock boundaries
        if translation:
            tx_name = translation.get("provider_name")
            if tx_name and tx_name not in _PROVIDER_FACTORIES:
                raise ValueError(
                    f"Unknown translation provider '{tx_name}'. "
                    f"Available: {available_providers()}"
                )

        #performing Atomic Writes to the registry with thread lock to avoid race conditions
        with self._lock:
            # always reset both slots on reconfigure to avoid stale provider bleedover
            self._tenants[tenant_id] = {"transcription": None, "translation": None}

            if transcription:
                self._tenants[tenant_id]["transcription"] = {
                    "provider_name": t_name,
                    "config": transcription.get("config", {}),
                    "instance": None,
                }
                logger.info(f"[Registry] Configured transcription module '{t_name}' for tenant '{tenant_id}'")

            #instantiate transcription model in a background thread
            # so it is warm and ready before the first /transcribe chunk arrives
            if transcription:
                threading.Thread(
                    target=self._warmup,
                    args=(tenant_id, "transcription"),
                    name=f"warmup-transcription-{tenant_id}",
                    daemon=True,
                ).start()

            if translation:
                self._tenants[tenant_id]["translation"] = {
                    "provider_name": tx_name,
                    "config": translation.get("config", {}),
                    "source_lang": translation.get("source_lang", "en"),
                    "target_lang": translation.get("target_lang", "es"),
                    "instance": None,
                }

                logger.info(f"[Registry] Configured translation module '{tx_name}' for tenant '{tenant_id}'")

            # Eagerly instantiate translation model in a background thread
            if translation:
                threading.Thread(
                    target=self._warmup,
                    args=(tenant_id, "translation"),
                    name=f"warmup-translation-{tenant_id}",
                    daemon=True,
                ).start()

        #Detect Unified Dual-Role Provider Allocations
        if transcription and translation and t_name == tx_name:
            logger.warning(
                f"[Registry] Tenant '{tenant_id}' configured the same provider '{t_name}' "
                "in both slots. Consider using a single TranscriptionTranslationProvider slot instead."
            )

    def _resolve_instance(self, tenant_id: str, role: str) -> Optional[BaseProvider]:
        """
        Thread-safe lazy-instantiation logic using Double-Checked Locking.
        Resolves the instance specifically assigned to a given role ('transcription' or 'translation').
        """
        # Fast, lock-free read
        tenant_entry = self._tenants.get(tenant_id)
        if not tenant_entry or not tenant_entry.get(role):
            return None

        role_entry = tenant_entry[role]

        # Lazy Instantiation with Double-Checked Locking block
        if role_entry["instance"] is None:
            with self._lock:
                # Re-verify inside the synchronized lock boundaries
                if role_entry["instance"] is None:
                    provider_name = role_entry["provider_name"]
                    factory = _PROVIDER_FACTORIES[provider_name]
                    try:
                        instance = factory(role_entry["config"])
                        role_entry["instance"] = instance
                        logger.info(f"Lazily instantiated '{provider_name}' as [{role}] for tenant '{tenant_id}'")
                    except Exception as e:
                        logger.error(f"Failed to instantiate '{provider_name}' for role '{role}': {e}")
                        raise ProviderConfigError(f"Provider initialization failed for {role}: {e}")

        return role_entry["instance"]
    

    def _warmup(self, tenant_id: str, role: str) -> None:
        """
        resolve and load the model for a given role
        Called in a background thread at /configure time so models
        are ready before the first /transcribe chunk arrives.
        """
        try:
            provider = self._resolve_instance(tenant_id, role)
            if provider is None:
                return
            # Trigger the actual model load by calling _load_model directly
            if hasattr(provider, '_load_model'):
                provider._load_model()
            elif hasattr(provider, '_lazy_load_model'):
                provider._lazy_load_model()
            logger.info(f"[Registry] Warmup complete for [{role}] provider '{provider.provider_name}' tenant '{tenant_id}'")
        except Exception as e:
            logger.error(f"[Registry] Warmup failed for [{role}] tenant '{tenant_id}': {e}")



    def transcribe(
        self,
        tenant_id: str,
        audio: Any,
        **kwargs: Any
    ) -> Optional[str]:
        """
        Generic entry point to transcribe audio vectors through the tenant's allocation slot.
        """
        provider = self._resolve_instance(tenant_id, "transcription")
        if provider is None:
            return None

        if not isinstance(provider, TranscriptionProvider):
            raise TypeError(
                f"Provider '{provider.provider_name}' loaded in transcription slot does not inherit from TranscriptionProvider. "
                f"Got type {type(provider).__name__}."
            )

        if not provider.is_available():
            logger.warning(f"Transcription provider '{provider.provider_name}' is currently unavailable for tenant '{tenant_id}'")
            return None

        return provider.transcribe(audio, **kwargs)

    def translate(
        self,
        tenant_id: str,
        text: str,
        source_lang: str,
        target_lang: str,
        **kwargs: Any
    ) -> Optional[str]:
        """
        Generic entry point to execute text translations through the tenant's allocation slot.
        """
        provider = self._resolve_instance(tenant_id, "translation")
        if provider is None:
            return None

        if not isinstance(provider, TranslationProvider):
            raise TypeError(
                f"Provider '{provider.provider_name}' loaded in translation slot does not inherit from TranslationProvider. "
                f"Got type {type(provider).__name__}."
            )

        if not provider.is_available():
            logger.warning(f"Translation provider '{provider.provider_name}' is currently unavailable for tenant '{tenant_id}'")
            return None

        return provider.translate(text, source_lang, target_lang, **kwargs)

    def remove(self, tenant_id: str) -> None:
        """Completely evict all memory footprints and pipeline layouts for a tenant session."""
        with self._lock:
            removed = self._tenants.pop(tenant_id, None)
            if removed:
                logger.info(f"Evicted active pipeline allocations from memory for tenant '{tenant_id}'")

    def get_provider_name(self, tenant_id: str, role: str = "transcription") -> Optional[str]:
        """Return the active engine model name for a specific execution layer role."""
        with self._lock:
            tenant_entry = self._tenants.get(tenant_id)
            if tenant_entry and tenant_entry.get(role):
                return tenant_entry[role]["provider_name"]
            return None
        
    def get_language_config(self, tenant_id: str) -> dict:
        """Return the source and target language configured for a tenant's translation slot."""
        with self._lock:
            tenant_entry = self._tenants.get(tenant_id)
            if tenant_entry and tenant_entry.get("translation"):
                return {
                    "source_lang": tenant_entry["translation"].get("source_lang", "en"),
                    "target_lang": tenant_entry["translation"].get("target_lang", "es"),
                }
            return {"source_lang": "en", "target_lang": "es"}