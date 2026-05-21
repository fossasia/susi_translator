"""
Concurrency regression tests:
- `_next_payload`: queue dedup + correct task_done accounting.
- `clean_old_transcripts`: prunes stale chunks/tenants, doesn't crash on
  non-numeric chunk_ids, doesn't mix chunk_ids and tenant_ids in the
  delete list (the original bug).
"""

from __future__ import annotations

import time


# ---------------------------------------------------------------------------
# _next_payload
# ---------------------------------------------------------------------------

def test_next_payload_returns_singleton_when_no_dups(ts):
    ts.audio_stack.put(("t1", "c1", "data-c1"))
    got = ts._next_payload()
    assert got == ("t1", "c1", "data-c1")
    assert ts.audio_stack.unfinished_tasks == 1
    ts.audio_stack.task_done()
    assert ts.audio_stack.unfinished_tasks == 0


def test_next_payload_collapses_duplicate_chunks(ts):
    ts.audio_stack.put(("t1", "c1", "old1"))
    ts.audio_stack.put(("t1", "c1", "old2"))
    ts.audio_stack.put(("t1", "c1", "newest"))
    got = ts._next_payload()
    assert got == ("t1", "c1", "newest")
    # Only the returned entry should remain unfinished; older duplicates were
    # task_done'd inside _next_payload so queue.join() would not hang.
    assert ts.audio_stack.unfinished_tasks == 1
    ts.audio_stack.task_done()
    ts.audio_stack.join()  # would hang on accounting bugs


def test_next_payload_only_dedups_same_tenant_and_chunk(ts):
    ts.audio_stack.put(("t1", "c1", "v1"))
    ts.audio_stack.put(("t2", "c1", "x"))      # different tenant
    ts.audio_stack.put(("t1", "c2", "y"))      # different chunk
    ts.audio_stack.put(("t1", "c1", "v2"))     # newer dup of the head

    got = ts._next_payload()
    # The head ("t1","c1","v1") sees a newer dup (v2), so we discard the head
    # and pull the next one, which is ("t2","c1","x") (no dup).
    assert got == ("t2", "c1", "x")
    # v1 was task_done'd; v2 + (t1,c2,y) still queued + the returned one =
    # 3 unfinished tasks total.
    assert ts.audio_stack.unfinished_tasks == 3
    ts.audio_stack.task_done()

    assert ts._next_payload() == ("t1", "c2", "y")
    ts.audio_stack.task_done()
    assert ts._next_payload() == ("t1", "c1", "v2")
    ts.audio_stack.task_done()
    ts.audio_stack.join()


# ---------------------------------------------------------------------------
# clean_old_transcripts
# ---------------------------------------------------------------------------

def test_clean_prunes_stale_chunks_and_keeps_fresh(ts):
    now_ms = int(time.time() * 1000)
    hour_ms = 60 * 60 * 1000

    ts.transcriptd["tenant-A"] = {
        str(now_ms - 30 * 60 * 1000): {"transcript": "fresh"},
        str(now_ms - 3 * hour_ms):    {"transcript": "stale"},
    }
    ts.clean_old_transcripts()

    chunks = ts.transcriptd["tenant-A"]
    assert len(chunks) == 1
    assert next(iter(chunks.values()))["transcript"] == "fresh"


def test_clean_removes_tenant_when_all_chunks_stale(ts):
    now_ms = int(time.time() * 1000)
    hour_ms = 60 * 60 * 1000

    ts.transcriptd["tenant-B"] = {
        str(now_ms - 4 * hour_ms): {"transcript": "stale"},
        str(now_ms - 5 * hour_ms): {"transcript": "stale"},
    }
    ts.clean_old_transcripts()
    assert "tenant-B" not in ts.transcriptd


def test_clean_removes_already_empty_tenants(ts):
    ts.transcriptd["tenant-D"] = {}
    ts.clean_old_transcripts()
    assert "tenant-D" not in ts.transcriptd


def test_clean_does_not_crash_on_non_numeric_chunk_ids(ts):
    """Regression: the original int() call would propagate ValueError up
    out of the worker thread."""
    ts.transcriptd["tenant-E"] = {"non-numeric-id": {"transcript": "weird"}}
    ts.clean_old_transcripts()  # must not raise
    assert "tenant-E" in ts.transcriptd
    assert "non-numeric-id" in ts.transcriptd["tenant-E"]


def test_clean_does_not_mix_chunk_ids_and_tenant_ids(ts):
    """
    Regression: original code reused the `to_delete` list across iterations
    and ended up calling ``del transcriptd[<chunk_id>]``. With multiple
    fresh tenants AND a fresh chunk in each, the cleanup must be a no-op
    rather than a KeyError.
    """
    now_ms = int(time.time() * 1000)
    ts.transcriptd["tenant-X"] = {str(now_ms - 100): {"transcript": "fresh-X"}}
    ts.transcriptd["tenant-Y"] = {str(now_ms - 200): {"transcript": "fresh-Y"}}

    ts.clean_old_transcripts()  # must not raise

    assert "tenant-X" in ts.transcriptd
    assert "tenant-Y" in ts.transcriptd
