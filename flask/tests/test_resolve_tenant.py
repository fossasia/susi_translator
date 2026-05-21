"""
Regression tests for `_resolve_tenant`:

- Explicit ``tenant_id`` wins over ``source``.
- Unknown ``source`` aborts with HTTP 400.
- Known source with no registered session -> ``None``.
- Known source with a fresh session -> the registered tenant_id.
- Known source whose session is older than ``SESSION_TTL_SECONDS`` is
  evicted on access and returns ``None`` (the bug fix).
"""

from __future__ import annotations

import time

import pytest


def _args(**kw):
    """Werkzeug-MultiDict-shaped stand-in (only `.get()` is used)."""
    return kw


def test_explicit_tenant_id_wins(ts):
    assert ts._resolve_tenant(_args(tenant_id="abc", source="mic")) == "abc"


def test_default_when_neither_given(ts):
    assert ts._resolve_tenant(_args(), default="0000") == "0000"


def test_unknown_source_aborts_400(ts):
    from werkzeug.exceptions import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        ts._resolve_tenant(_args(source="garbage"))
    assert exc_info.value.code == 400


def test_known_source_with_no_session_returns_none(ts):
    assert ts._resolve_tenant(_args(source="mic")) is None


def test_known_source_with_fresh_session_returns_tenant_id(ts):
    with ts.session_lock:
        ts.latest_session_by_source["mic"] = ("tenant-fresh", time.time())
    assert ts._resolve_tenant(_args(source="mic")) == "tenant-fresh"


def test_expired_session_is_evicted_and_returns_none(ts):
    """Regression: previously the session pointer never expired, so a stale
    grabber's tenant_id would be returned indefinitely."""
    stale_ts = time.time() - (ts.SESSION_TTL_SECONDS + 60)
    with ts.session_lock:
        ts.latest_session_by_source["mic"] = ("tenant-stale", stale_ts)

    assert ts._resolve_tenant(_args(source="mic")) is None
    # And the entry has been cleared out of the registry.
    with ts.session_lock:
        assert ts.latest_session_by_source["mic"] is None


def test_resolve_tenant_does_not_evict_fresh_session(ts):
    fresh_ts = time.time() - (ts.SESSION_TTL_SECONDS / 2)
    with ts.session_lock:
        ts.latest_session_by_source["url"] = ("tenant-fresh", fresh_ts)

    assert ts._resolve_tenant(_args(source="url")) == "tenant-fresh"
    with ts.session_lock:
        assert ts.latest_session_by_source["url"] == ("tenant-fresh", fresh_ts)
