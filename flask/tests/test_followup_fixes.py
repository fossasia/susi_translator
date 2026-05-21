"""
Regression tests for the three latest fixes:

#1  Range-filter endpoints must skip non-numeric chunk_ids instead of
    crashing with a 500 when ``int(k)`` raises ``ValueError``.

#4  The audio worker thread must auto-start at module-import time so the
    server works under WSGI servers (``gunicorn``, ``uwsgi``, ``flask
    run``), not only under the ``__main__`` entrypoint.

    The test conftest disables this with TRANSCRIBE_AUTOSTART_WORKER=false,
    so the test that proves the queue isn't being drained verifies that
    the off-switch actually works.

#7  Destructive endpoints (``/pop_first_transcript``,
    ``/pop_latest_transcript``, ``/delete_transcript``) must accept the
    correct HTTP method (DELETE) while keeping GET as a deprecated alias
    for backward compat with existing curl scripts.
"""

from __future__ import annotations

import time


# ---------------------------------------------------------------------------
# Helper: seed transcriptd directly through the shared lock.
# ---------------------------------------------------------------------------

def _seed(ts, tenant_id: str, items: dict):
    with ts.transcripts_lock:
        ts.transcriptd[tenant_id] = {k: {"transcript": v} for k, v in items.items()}


# ---------------------------------------------------------------------------
# #1  Non-numeric chunk_id in range filters
# ---------------------------------------------------------------------------

def test_list_transcripts_skips_non_numeric_chunk_ids(client, ts):
    """
    A non-numeric chunk_id sneaking into transcriptd (e.g. via a
    misbehaving direct API client) must NOT make /list_transcripts
    explode with a 500.
    """
    _seed(ts, "t1", {
        "100": "fresh",
        "non-numeric-id": "bogus",
        "500": "later",
    })
    resp = client.get("/list_transcripts?tenant_id=t1&from=0&until=1000")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "100" in body
    assert "500" in body
    assert "non-numeric-id" not in body  # silently skipped


def test_transcripts_size_skips_non_numeric_chunk_ids(client, ts):
    _seed(ts, "t1", {"100": "a", "junk": "b", "500": "c"})
    resp = client.get("/transcripts_size?tenant_id=t1&from=0&until=1000")
    assert resp.status_code == 200
    assert resp.get_json() == {"size": 2}


def test_get_first_transcript_skips_non_numeric(client, ts):
    _seed(ts, "t1", {"junk": "junk", "200": "real"})
    resp = client.get("/get_first_transcript?tenant_id=t1&from=0")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["chunk_id"] == "200"
    assert body["transcript"] == "real"


def test_get_latest_transcript_skips_non_numeric(client, ts):
    _seed(ts, "t1", {"junk": "junk", "200": "real", "500": "newer"})
    resp = client.get(f"/get_latest_transcript?tenant_id=t1&until={2 * 10**12}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["chunk_id"] == "500"


def test_pop_first_skips_non_numeric_then_pops_real(client, ts):
    _seed(ts, "t1", {"junk": "junk", "200": "real"})
    resp = client.delete("/pop_first_transcript?tenant_id=t1&from=0")
    assert resp.status_code == 200
    assert resp.get_json()["chunk_id"] == "200"
    # The non-numeric chunk_id is left untouched.
    with ts.transcripts_lock:
        assert "junk" in ts.transcriptd["t1"]


# ---------------------------------------------------------------------------
# #4  Worker auto-start (off switch verified)
# ---------------------------------------------------------------------------

def test_worker_does_not_drain_queue_during_tests(ts):
    """
    The test conftest sets TRANSCRIBE_AUTOSTART_WORKER=false. If that flag
    is being honoured, items we push onto the queue stay there until WE
    drain them; if a real worker is running it will race us and pop them.
    """
    assert ts._worker_thread is None, (
        "A worker thread is running during tests; conftest's "
        "TRANSCRIBE_AUTOSTART_WORKER=false is not being honoured."
    )

    # Confirm by pushing an item and then checking the queue still has it
    # after a beat. (No worker = no consumer = item still here.)
    ts.audio_stack.put(("test-tenant", "1", "AAAA"))
    time.sleep(0.05)
    assert ts.audio_stack.qsize() == 1
    # Drain manually so we don't leak state into other tests.
    ts.audio_stack.get_nowait()
    ts.audio_stack.task_done()


def test_start_worker_once_is_idempotent(ts):
    """
    If a developer flips the autostart flag back on at runtime, calling
    _start_worker_once() twice must not spawn a second consumer.
    """
    t1 = ts._start_worker_once()
    t2 = ts._start_worker_once()
    try:
        assert t1 is t2
        assert t1.is_alive()
    finally:
        # The worker is a daemon thread — it'll die when the test process
        # exits. We can't gracefully stop it from outside without a
        # cooperative shutdown signal, but we can at least drop our own
        # reference so subsequent tests' state-reset starts clean.
        with ts._worker_lock:
            ts._worker_thread = None


# ---------------------------------------------------------------------------
# #7  DELETE method on destructive endpoints (with GET kept deprecated)
# ---------------------------------------------------------------------------

def test_pop_first_transcript_via_delete(client, ts):
    _seed(ts, "t1", {"100": "first", "200": "second"})
    resp = client.delete("/pop_first_transcript?tenant_id=t1")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["chunk_id"] == "100"
    assert body["transcript"] == "first"
    # Removed from store.
    with ts.transcripts_lock:
        assert "100" not in ts.transcriptd["t1"]
        assert "200" in ts.transcriptd["t1"]


def test_pop_latest_transcript_via_delete(client, ts):
    _seed(ts, "t1", {"100": "first", "200": "second"})
    resp = client.delete(f"/pop_latest_transcript?tenant_id=t1&until={2 * 10**12}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["chunk_id"] == "200"
    assert body["transcript"] == "second"
    with ts.transcripts_lock:
        assert "200" not in ts.transcriptd["t1"]


def test_delete_transcript_via_delete(client, ts):
    _seed(ts, "t1", {"42": "to-be-deleted", "99": "kept"})
    resp = client.delete("/delete_transcript?tenant_id=t1&chunk_id=42")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"chunk_id": "42", "transcript": "to-be-deleted"}
    with ts.transcripts_lock:
        assert "42" not in ts.transcriptd["t1"]
        assert "99" in ts.transcriptd["t1"]


def test_delete_transcript_unknown_chunk_returns_empty(client, ts):
    _seed(ts, "t1", {"42": "exists"})
    resp = client.delete("/delete_transcript?tenant_id=t1&chunk_id=does-not-exist")
    assert resp.status_code == 200
    assert resp.get_json() == {"chunk_id": "does-not-exist", "transcript": ""}


def test_pop_first_transcript_via_get_still_works(client, ts):
    """Backward-compat: GET on the destructive endpoint must still work
    (with a deprecation log line) so existing curl scripts don't break."""
    _seed(ts, "t1", {"100": "first"})
    resp = client.get("/pop_first_transcript?tenant_id=t1")
    assert resp.status_code == 200
    assert resp.get_json()["chunk_id"] == "100"


def test_delete_transcript_via_get_still_works(client, ts):
    _seed(ts, "t1", {"42": "x"})
    resp = client.get("/delete_transcript?tenant_id=t1&chunk_id=42")
    assert resp.status_code == 200
    assert resp.get_json() == {"chunk_id": "42", "transcript": "x"}
