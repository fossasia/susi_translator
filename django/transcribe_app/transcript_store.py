# transcribe_app/transcript_store.py
# (C) Michael Peter Christen 2024
# Licensed under Apache License Version 2.0

"""
Pluggable transcript storage backend.

Two implementations are provided:
  • InMemoryTranscriptStore  – the original dict-based storage (default)
  • RedisTranscriptStore     – Redis-backed storage required for Celery mode

When USE_CELERY=true the Redis store is used so that both the Django web
process **and** the Celery worker processes share the same transcript state.
When USE_CELERY=false (the default) the in-memory store is used, preserving
the original behaviour with zero additional dependencies.

Usage:
    from .transcript_store import store
    store.set_transcript(tenant_id, chunk_id, transcript_event)
    transcripts = store.get_transcripts(tenant_id)
"""

import json
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory backend (original behaviour)
# ---------------------------------------------------------------------------

class InMemoryTranscriptStore:
    """Thread-safe dictionary-backed transcript store."""

    def __init__(self):
        self._lock = threading.Lock()
        # {tenant_id: {chunk_id: {transcript event dict}}}
        self._transcripts = {}
        self._translation_cache = {}

    # -- transcripts --------------------------------------------------------

    def get_transcripts(self, tenant_id):
        """Return the transcript dict for *tenant_id* (may be empty)."""
        with self._lock:
            return self._transcripts.get(tenant_id, {})

    def set_transcript(self, tenant_id, chunk_id, transcript_event):
        """Create or overwrite a transcript event."""
        with self._lock:
            if tenant_id not in self._transcripts:
                self._transcripts[tenant_id] = {}
            self._transcripts[tenant_id][chunk_id] = transcript_event

    def get_transcript_event(self, tenant_id, chunk_id):
        """Return a single transcript event or *None*."""
        with self._lock:
            return self._transcripts.get(tenant_id, {}).get(chunk_id)

    def pop_transcript(self, tenant_id, chunk_id):
        """Remove and return a transcript event."""
        with self._lock:
            return self._transcripts.get(tenant_id, {}).pop(chunk_id, None)

    def get_chunk_ids(self, tenant_id):
        """Return the list of chunk_ids for a tenant."""
        with self._lock:
            return list(self._transcripts.get(tenant_id, {}).keys())

    def cleanup_old(self, max_age_ms=2 * 60 * 60 * 1000):
        """Remove transcript events older than *max_age_ms*."""
        current_time = int(time.time() * 1000)
        threshold = current_time - max_age_ms
        with self._lock:
            to_delete = []
            for tenant_id, transcripts in self._transcripts.items():
                old = [cid for cid in transcripts if cid.isdigit() and int(cid) < threshold]
                for cid in old:
                    del transcripts[cid]
                if not transcripts:
                    to_delete.append(tenant_id)
            for tid in to_delete:
                self._transcripts.pop(tid, None)

    # -- translation cache --------------------------------------------------

    def get_cached_translation(self, cache_key):
        return self._translation_cache.get(cache_key, '')

    def set_cached_translation(self, cache_key, value):
        self._translation_cache[cache_key] = value


# ---------------------------------------------------------------------------
# Redis backend (for Celery mode)
# ---------------------------------------------------------------------------

class RedisTranscriptStore:
    """
    Redis-backed transcript store.

    Layout:
        Hash   transcripts:{tenant_id}   field={chunk_id}  value=JSON
        String translation_cache:{key}   value=translated text
        Set    tenant_ids                 all known tenant ids
    """

    def __init__(self, redis_url=None):
        import redis
        url = redis_url or os.getenv('REDIS_URL', 'redis://localhost:6379/1')
        self._redis = redis.Redis.from_url(url, decode_responses=True)
        self._prefix = 'susi:'
        logger.info("RedisTranscriptStore connected to %s", url)

    def _tkey(self, tenant_id):
        return f"{self._prefix}transcripts:{tenant_id}"

    # -- transcripts --------------------------------------------------------

    def get_transcripts(self, tenant_id):
        raw = self._redis.hgetall(self._tkey(tenant_id))
        result = {}
        for chunk_id, val in raw.items():
            try:
                result[chunk_id] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
        return result

    def set_transcript(self, tenant_id, chunk_id, transcript_event):
        self._redis.hset(self._tkey(tenant_id), chunk_id, json.dumps(transcript_event))
        self._redis.sadd(f"{self._prefix}tenant_ids", tenant_id)

    def get_transcript_event(self, tenant_id, chunk_id):
        raw = self._redis.hget(self._tkey(tenant_id), chunk_id)
        if raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    def pop_transcript(self, tenant_id, chunk_id):
        raw = self._redis.hget(self._tkey(tenant_id), chunk_id)
        if raw:
            self._redis.hdel(self._tkey(tenant_id), chunk_id)
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    def get_chunk_ids(self, tenant_id):
        return list(self._redis.hkeys(self._tkey(tenant_id)))

    def cleanup_old(self, max_age_ms=2 * 60 * 60 * 1000):
        current_time = int(time.time() * 1000)
        threshold = current_time - max_age_ms
        tenant_ids = self._redis.smembers(f"{self._prefix}tenant_ids") or set()
        for tenant_id in tenant_ids:
            chunk_ids = self._redis.hkeys(self._tkey(tenant_id))
            old = [cid for cid in chunk_ids if cid.isdigit() and int(cid) < threshold]
            if old:
                self._redis.hdel(self._tkey(tenant_id), *old)
            # remove empty tenant
            if self._redis.hlen(self._tkey(tenant_id)) == 0:
                self._redis.srem(f"{self._prefix}tenant_ids", tenant_id)

    # -- translation cache --------------------------------------------------

    def get_cached_translation(self, cache_key):
        return self._redis.get(f"{self._prefix}translation_cache:{cache_key}") or ''

    def set_cached_translation(self, cache_key, value):
        # Cache translations for 24 hours
        self._redis.setex(f"{self._prefix}translation_cache:{cache_key}", 86400, value)


# ---------------------------------------------------------------------------
# Factory — select backend based on USE_CELERY environment variable
# ---------------------------------------------------------------------------

def _create_store():
    use_celery = os.getenv('USE_CELERY', 'false').lower() == 'true'
    if use_celery:
        try:
            return RedisTranscriptStore()
        except Exception as e:
            logger.warning("Failed to connect to Redis, falling back to in-memory store: %s", e)
            return InMemoryTranscriptStore()
    return InMemoryTranscriptStore()


store = _create_store()
