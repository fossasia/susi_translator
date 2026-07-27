"""
This module manages the lifecycle of transcription and translation 
providers side-by-side using an isolated role-based slot pipeline.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import json
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

# Unified registry of provider factories.
# Each entry stores the factory callable AND memory metadata declared by the plugin author.
_PROVIDER_FACTORIES: Dict[str, Dict[str, Any]] = {}

MODEL_MEMORY_MB: Dict[str, int] = {}

# Placeholder budgets; to be tuned with real VRAM usage data
MAX_IDLE_MEMORY_MB = 5000
MAX_HOT_TIER_MB = 5000

# Parse hot tier models from environment variable, falling back to defaults
_default_hot_tier = [
    {"provider_name": "faster_whisper", "config": {"model_size": "medium"}},
    {"provider_name": "nllb_ctranslate2", "config": {}}
]
try:
    _env_hot_tier = os.getenv("HOT_TIER_MODELS")
    if _env_hot_tier:
        HOT_TIER_MODELS = json.loads(_env_hot_tier)
    else:
        HOT_TIER_MODELS = _default_hot_tier
except Exception as e:
    logger.error(f"[Registry] Failed to parse HOT_TIER_MODELS from environment, using defaults. Error: {e}")
    HOT_TIER_MODELS = _default_hot_tier


def _estimate_model_size(provider_name: str, config: Dict[str, Any]) -> int:
    """
    Look up the estimated memory footprint of a model using metadata registered
    by the plugin author
    """
    meta = _PROVIDER_FACTORIES.get(provider_name, {})
    config_key = meta.get("config_memory_key")  # e.g. "model_size", "model_id"
    memory_map = meta.get("memory_mb_map", {})  

    lookup_key = None
    if config_key and memory_map:
        raw_val = config.get(config_key)
        if raw_val is not None:
            # Normalize: strip leading path segments (e.g. "facebook/nllb-200-distilled-600M" -> "nllb-200-distilled-600M")
            short_val = str(raw_val).split("/")[-1]
            lookup_key = memory_map.get(short_val) or memory_map.get(raw_val)
        if lookup_key is None:
            # Fall back to the map's "default" key if the plugin declared one
            lookup_key = memory_map.get("default")

    if lookup_key is not None:
        return lookup_key

    # Global MODEL_MEMORY_MB table (coarse-grained, for external/legacy plugins)
    coarse_key = provider_name
    result = MODEL_MEMORY_MB.get(coarse_key)
    if result is not None:
        return result

    logger.warning(
        f"[Registry] No memory estimate registered for '{provider_name}' "
        f"(config_key={config_key!r}, config={config}). "
        "Using conservative fallback of 1000 MB"
    )
    return 1000

# Fallback used when a tenant skips configuration entirely
_DEFAULT_TRANSCRIPTION_FALLBACK: Dict[str, Any] = {
    "provider_name": "faster_whisper",
    "config": {},
}

_DEFAULT_TRANSLATION_FALLBACK: Dict[str, Any] = {
    "provider_name": "nllb_ctranslate2",
    "config": {},
    "source_lang": "en",
    "target_lang": "es",
}


def register_provider(
    name: str,
    factory: Callable[[Dict[str, Any]], BaseProvider],
    memory_mb_map: Optional[Dict[str, int]] = None,
    config_memory_key: Optional[str] = None,
) -> None:
    """
    Register a provider factory under a canonical name
    """
    _PROVIDER_FACTORIES[name] = {
        "factory": factory,
        "memory_mb_map": memory_mb_map or {},
        "config_memory_key": config_memory_key,
    }
    logger.debug(f"Registered plugin provider factory: {name}")


def available_providers() -> List[str]:
    """Return a list of all registered provider names."""
    return list(_PROVIDER_FACTORIES.keys())


class SharedModelRef:
    def __init__(self, instance: Optional[BaseProvider] = None):
        self.instance = instance
        self.refs = 0
        self.last_used = time.time()
        self.is_hot_tier = False

_shared_models: Dict[tuple, SharedModelRef] = {}
_shared_models_lock = threading.Lock()


def _make_cache_key(provider_name: str, config: Dict[str, Any]) -> tuple:
    return (provider_name, tuple(sorted(config.items())))


def _get_or_create_shared_model(provider_name: str, config: Dict[str, Any]) -> BaseProvider:
    """
    Creates and caches one on first call; subsequent calls return the same object.
    Thread-safe via double-checked locking.
    """
    cache_key = _make_cache_key(provider_name, config)

    # Fast path: check without lock
    ref = _shared_models.get(cache_key)
    if ref is not None and ref.instance is not None:
        ref.last_used = time.time()
        return ref.instance

    with _shared_models_lock:
        # Double-check inside lock
        ref = _shared_models.get(cache_key)
        if ref is not None and ref.instance is not None:
            ref.last_used = time.time()
            return ref.instance

        meta = _PROVIDER_FACTORIES.get(provider_name)
        if meta is None:
            raise ProviderConfigError(
                f"Unknown provider '{provider_name}'. Available: {available_providers()}"
            )
        factory = meta["factory"]
        try:
            instance = factory(config)
        except Exception as e:
            raise ProviderConfigError(
                f"Provider initialization failed for '{provider_name}': {e}"
            ) from e
            
        if ref is None:
            ref = SharedModelRef(instance=instance)
            _shared_models[cache_key] = ref
        else:
            ref.instance = instance
            
        ref.last_used = time.time()

        # Build a safe log key: mask api_key values so they never appear in logs.
        safe_config = {
            k: ("***" if "key" in k.lower() or "secret" in k.lower() or "token" in k.lower() else v)
            for k, v in config.items()
        }
        logger.info(
            f"[SharedModels] Loaded shared instance of '{provider_name}' "
            f"(config={safe_config})"
        )
        return instance


class ProviderRegistry:
    """
    Per tenant provider registry, One shared instance should be created
    at module load time in transcribe_server.py and used across all requests
    """

    def __init__(self):
        self._tenants: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        
        # Initialize Hot Tier Models unless we are in a testing environment
        if os.environ.get("FLASK_TESTING") != "true":
            hot_tier_size = 0
            for hot_model in HOT_TIER_MODELS:
                p_name = hot_model["provider_name"]
                p_config = hot_model.get("config", {})
                size = _estimate_model_size(p_name, p_config)
                hot_tier_size += size
                
            if hot_tier_size > MAX_HOT_TIER_MB:
                raise ValueError(f"[Registry] Hot Tier exceeds budget ({hot_tier_size} MB > {MAX_HOT_TIER_MB} MB). Refusing to start to prevent OOM.")
                
            for hot_model in HOT_TIER_MODELS:
                p_name = hot_model["provider_name"]
                p_config = hot_model.get("config", {})
                cache_key = _make_cache_key(p_name, p_config)
                
                ref = _shared_models.get(cache_key)
                if not ref:
                    # Eagerly create the ref
                    with _shared_models_lock:
                        if cache_key not in _shared_models:
                            _shared_models[cache_key] = SharedModelRef(instance=None)
                        ref = _shared_models[cache_key]
                
                ref.is_hot_tier = True
                
                # Start a daemon thread to load the hot model
                threading.Thread(
                    target=self._warmup_hot_tier,
                    args=(p_name, p_config),
                    name=f"warmup-hottier-{p_name}",
                    daemon=True
                ).start()
        
        threading.Thread(
            target=self._eviction_loop,
            name="registry-eviction-loop",
            daemon=True
        ).start()

    def _warmup_hot_tier(self, provider_name: str, config: Dict[str, Any]) -> None:
        try:
            provider = _get_or_create_shared_model(provider_name, config)
            size = _estimate_model_size(provider_name, config)
            logger.info(f"[Registry] Hot Tier Loading '{provider_name}' (Est {size}MB) into memory...")
            provider.load_model()
            logger.info(f"[Registry] Hot Tier Warmup complete for '{provider_name}'")
        except Exception as e:
            logger.error(f"[Registry] Hot Tier Warmup failed for '{provider_name}': {e}")

    def _increment_ref(self, cache_key: tuple) -> None:
        with _shared_models_lock:
            ref = _shared_models.get(cache_key)
            if ref is None:
                ref = SharedModelRef(instance=None)
                _shared_models[cache_key] = ref
            ref.refs += 1

    def _decrement_ref(self, cache_key: tuple) -> None:
        with _shared_models_lock:
            ref = _shared_models.get(cache_key)
            if ref is not None:
                ref.refs = max(0, ref.refs - 1)
                
    def _eviction_loop(self) -> None:
        while True:
            time.sleep(15)  # Check every 15 seconds
            now = time.time()
            models_to_unload = []
            
            with _shared_models_lock:
                # Debug logging of current models
                active_summary = []
                for cache_key, ref in _shared_models.items():
                    provider_name = cache_key[0]
                    state = "loading" if ref.instance is None else "ready"
                    tier = "HOT" if ref.is_hot_tier else "NORMAL"
                    active_summary.append(f"{provider_name} ({tier}, {state}, refs: {ref.refs})")
                
                if active_summary:
                    logger.debug(f"[Registry] Memory State: {', '.join(active_summary)}")
                
                total_idle_mb = 0
                idle_models = []
                
                # Calculate idle memory & Handle TTL
                keys_to_evict = []
                for cache_key, ref in list(_shared_models.items()):
                    if ref.refs > 0 or ref.is_hot_tier:
                        continue
                        
                    idle_time = now - ref.last_used
                    if idle_time <= 60:
                        continue  # Grace period immunity
                        
                    if idle_time > 3600:
                        keys_to_evict.append(cache_key)
                        continue
                        
                    size = _estimate_model_size(cache_key[0], dict(cache_key[1]))
                    total_idle_mb += size
                    idle_models.append((cache_key, ref, size))
                
                # Handle Memory Budgets
                if total_idle_mb > MAX_IDLE_MEMORY_MB:
                    # Sort oldest first
                    idle_models.sort(key=lambda item: item[1].last_used)
                    for cache_key, ref, size in idle_models:
                        keys_to_evict.append(cache_key)
                        total_idle_mb -= size
                        if total_idle_mb <= MAX_IDLE_MEMORY_MB:
                            break
                            
                # Pop evicted models from cache safely inside lock
                for key in keys_to_evict:
                    ref = _shared_models.pop(key, None)
                    if ref and ref.instance is not None:
                        models_to_unload.append((key, ref.instance))
                        
            # Perform unload_model outside the lock to avoid blocking other threads
            for key, instance in models_to_unload:
                size = _estimate_model_size(key[0], dict(key[1]))
                logger.info(f"[Registry] Evicting unused model {key[0]} (Est {size}MB) from memory.")
                try:
                    instance.unload_model()
                except Exception as e:
                    logger.error(f"[Registry] Error unloading model {key[0]}: {e}")

    def configure(
        self,
        tenant_id: str,
        transcription: Optional[Dict[str, Any]] = None,
        translation: Optional[Dict[str, Any]] = None,
        organizer_id: Optional[int] = None,
    ) -> None:

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

        #validating Translation Configuration outside the lock boundaries
        if translation:
            tx_name = translation.get("provider_name")
            if tx_name and tx_name not in _PROVIDER_FACTORIES:
                raise ValueError(
                    f"Unknown translation provider '{tx_name}'. "
                    f"Available: {available_providers()}"
                )

        #performing Atomic Writes to the registry with thread lock to avoid race conditions
        with self._lock:
            old_tenant = self._tenants.get(tenant_id)
            if old_tenant:
                old_t = old_tenant.get("transcription")
                if old_t and old_t.get("provider_name"):
                    self._decrement_ref(_make_cache_key(old_t["provider_name"], old_t.get("config", {})))
                old_tx = old_tenant.get("translation")
                if old_tx and old_tx.get("provider_name"):
                    self._decrement_ref(_make_cache_key(old_tx["provider_name"], old_tx.get("config", {})))

            # only fall back to the caller supplied value if no owner is set yet
            existing_owner = (self._tenants.get(tenant_id) or {}).get("organizer_id")
            resolved_owner = existing_owner if existing_owner is not None else organizer_id
            # always reset both slots on reconfigure to avoid stale provider bleedover
            self._tenants[tenant_id] = {"transcription": None, "translation": None, "organizer_id": resolved_owner}


            if transcription:
                t_config = dict(transcription)
                t_config.pop("provider_name", None)
                t_config.update(t_config.pop("config", {}))

                self._tenants[tenant_id]["transcription"] = {
                    "provider_name": t_name,
                    "config": t_config,
                    "instance": None,
                    "ready": False,
                }
                self._increment_ref(_make_cache_key(t_name, t_config))
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
                tx_config = dict(translation)
                tx_config.pop("provider_name", None)
                tx_config.pop("source_lang", None)
                tx_config.pop("target_lang", None)
                tx_config.update(tx_config.pop("config", {}))

                self._tenants[tenant_id]["translation"] = {
                    "provider_name": tx_name,
                    "config": tx_config,
                    "source_lang": translation.get("source_lang", "en"),
                    "target_lang": translation.get("target_lang", "es"),
                    "instance": None,
                    "ready": False,
                }
                self._increment_ref(_make_cache_key(tx_name, tx_config))

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

    def claim(self, tenant_id: str, organizer_id: int) -> None:
        """
        Stamp an organizer as the owner of a freshly-created tenant_id before
        any provider is configured
        """
        with self._lock:
            if tenant_id not in self._tenants:
                self._tenants[tenant_id] = {
                    "transcription": None,
                    "translation": None,
                    "organizer_id": organizer_id,
                }
                logger.info(
                    f"[Registry] Tenant '{tenant_id}' pre-claimed by organizer_id={organizer_id}"
                )
            else:
                # Already exists, only stamp if still unclaimed.
                existing = self._tenants[tenant_id]
                if existing.get("organizer_id") is None:
                    existing["organizer_id"] = organizer_id
                    logger.info(
                        f"[Registry] Tenant '{tenant_id}' late-claimed by organizer_id={organizer_id}"
                    )

    def check_ownership(self, tenant_id: str, organizer_id: int) -> bool:
        """Returns True if the tenant is owned by the given organizer_id or has not been claimed yet."""
        with self._lock:
            tenant = self._tenants.get(tenant_id)
            if not tenant:
                # If the tenant doesn't exist in the registry yet, it hasn't been claimed.
                # Allow the configuration to proceed so it can be claimed.
                return True
            # Allow operations if there's no owner recorded, but block mismatch
            owner = tenant.get("organizer_id")
            if owner is None:
                return True
            return owner == organizer_id

    def is_pipeline_ready(self, tenant_id: str) -> bool:
        """Checks if all configured background threads have fully loaded their models."""
        with self._lock:
            tenant = self._tenants.get(tenant_id)
            if not tenant:
                return False
            
            t_ready = True
            if tenant.get("transcription"):
                t_ready = tenant["transcription"].get("ready", False)
                
            tx_ready = True
            if tenant.get("translation"):
                tx_ready = tenant["translation"].get("ready", False)
                
            return t_ready and tx_ready

    def _resolve_instance(self, tenant_id: str, role: str) -> Optional[BaseProvider]:
        """
        Thread-safe lazy instantiation logic using the shared model singleton cache.
        All tenants that use the same provider and config will share one loaded model
        """
        with self._lock:
            tenant_entry = self._tenants.get(tenant_id)

            # Trigger fallback if the entry is missing OR if the provider_name is blank/None
            if not tenant_entry or not tenant_entry.get(role) or not tenant_entry[role].get("provider_name"):
                if role == "transcription":
                    fallback_name = _DEFAULT_TRANSCRIPTION_FALLBACK["provider_name"]
                    if fallback_name not in _PROVIDER_FACTORIES:
                        return None
                    if tenant_id not in self._tenants:
                        self._tenants[tenant_id] = {"transcription": None, "translation": None}
                    if not self._tenants[tenant_id].get("transcription") or not self._tenants[tenant_id]["transcription"].get("provider_name"):
                        logger.warning(
                            f"[Registry] Tenant '{tenant_id}' has no valid transcription config — "
                            f"falling back to default provider '{fallback_name}'."
                        )
                        self._tenants[tenant_id]["transcription"] = {
                            "provider_name": fallback_name,
                            "config": _DEFAULT_TRANSCRIPTION_FALLBACK["config"],
                        }
                        self._increment_ref(_make_cache_key(fallback_name, _DEFAULT_TRANSCRIPTION_FALLBACK["config"]))
                    role_entry = self._tenants[tenant_id]["transcription"]
                elif role == "translation":
                    fallback_name = _DEFAULT_TRANSLATION_FALLBACK["provider_name"]
                    if fallback_name not in _PROVIDER_FACTORIES:
                        return None
                    if tenant_id not in self._tenants:
                        self._tenants[tenant_id] = {"transcription": None, "translation": None}
                    if not self._tenants[tenant_id].get("translation") or not self._tenants[tenant_id]["translation"].get("provider_name"):
                        logger.warning(
                            f"[Registry] Tenant '{tenant_id}' has no valid translation config — "
                            f"falling back to default provider '{fallback_name}'."
                        )
                        self._tenants[tenant_id]["translation"] = {
                            "provider_name": fallback_name,
                            "config": _DEFAULT_TRANSLATION_FALLBACK["config"],
                            "source_lang": _DEFAULT_TRANSLATION_FALLBACK["source_lang"],
                            "target_lang": _DEFAULT_TRANSLATION_FALLBACK["target_lang"],
                        }
                        self._increment_ref(_make_cache_key(fallback_name, _DEFAULT_TRANSLATION_FALLBACK["config"]))
                    role_entry = self._tenants[tenant_id]["translation"]
                else:
                    return None
            else:
                role_entry = tenant_entry[role]

        # Use the shared singleton cache — no more per-tenant model duplication.
        provider_name = role_entry["provider_name"]
        config = role_entry.get("config", {})
        return _get_or_create_shared_model(provider_name, config)
    

    def _warmup(self, tenant_id: str, role: str) -> None:
        """
        resolve and load the model for a given role before starting the streaming
        """
        try:
            provider = self._resolve_instance(tenant_id, role)
            if provider is None:
                return
            
            size = _estimate_model_size(provider.provider_name, provider.config)
            logger.info(f"[Registry] Warmup Loading '{provider.provider_name}' (Est {size}MB) into memory...")
            # Trigger the actual model load by calling load_model directly
            provider.load_model()

            with self._lock:
                if tenant_id in self._tenants and self._tenants[tenant_id].get(role):
                    self._tenants[tenant_id][role]["ready"] = True
                    self._tenants[tenant_id][role].pop("warmup_error", None)

            logger.info(f"[Registry] Warmup complete for [{role}] provider '{provider.provider_name}' tenant '{tenant_id}'")
        except Exception as e:
            logger.error(f"[Registry] Warmup failed for [{role}] tenant '{tenant_id}': {e}")
            # Surface the failure so /status can return a meaningful error instead of
            # leaving the slot stuck in a permanent warming_up state.
            with self._lock:
                if tenant_id in self._tenants and self._tenants[tenant_id].get(role):
                    self._tenants[tenant_id][role]["warmup_error"] = str(e)



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
                old_t = removed.get("transcription")
                if old_t and old_t.get("provider_name"):
                    self._decrement_ref(_make_cache_key(old_t["provider_name"], old_t.get("config", {})))
                old_tx = removed.get("translation")
                if old_tx and old_tx.get("provider_name"):
                    self._decrement_ref(_make_cache_key(old_tx["provider_name"], old_tx.get("config", {})))
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