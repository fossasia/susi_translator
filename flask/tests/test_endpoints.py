from __future__ import annotations

import time


def _seed(ts, tenant_id: str, items: dict):
    with ts.transcripts_lock:
        ts.transcriptd[tenant_id] = {k: {"transcript": v} for k, v in items.items()}


def test_session_post_mints_tenant_for_valid_source(client, ts):
    resp = client.post("/session", json={"source": "mic"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["source"] == "mic"
    assert isinstance(body["tenant_id"], str) and len(body["tenant_id"]) > 0

    with ts.session_lock:
        entry = ts.latest_session_by_source["mic"]
    assert entry is not None
    tenant_id, created_ts = entry
    assert tenant_id == body["tenant_id"]
    assert abs(created_ts - time.time()) < 5


def test_session_post_rejects_unknown_source(client):
    resp = client.post("/session", json={"source": "totally-bogus"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert "source must be one of" in body.get("error", "")


def test_transcribe_enqueues_and_returns_processing(client, ts):
    payload = {
        "audio_b64": "AAAA",
        "chunk_id": "12345",
        "tenant_id": "tenant-x",
    }
    resp = client.post("/transcribe", json=payload)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"chunk_id": "12345", "tenant_id": "tenant-x", "status": "processing"}

    # Worker is disabled in tests; the item should still be on the queue.
    assert ts.audio_stack.qsize() == 1
    queued = ts.audio_stack.get_nowait()
    ts.audio_stack.task_done()
    assert queued == ("tenant-x", "12345", "AAAA")


def test_transcribe_rejects_missing_fields(client):
    resp = client.post("/transcribe", json={"chunk_id": "1"})
    assert resp.status_code == 400
    assert "Missing required fields" in resp.get_json().get("error", "")


def test_transcribe_rejects_empty_payload(client):
    resp = client.post("/transcribe", data="", content_type="application/json")
    assert resp.status_code in (400, 415)


def test_list_transcripts_filters_by_from_until(client, ts):
    _seed(ts, "t1", {"100": "a", "500": "b", "900": "c"})

    resp = client.get("/list_transcripts?tenant_id=t1&from=200&until=800")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "500" in body
    assert "100" not in body
    assert "900" not in body


def test_list_transcripts_rejects_non_integer_from(client, ts):
    _seed(ts, "t1", {"100": "a"})
    resp = client.get("/list_transcripts?tenant_id=t1&from=notanint")
    assert resp.status_code == 400


def test_get_transcript_returns_empty_when_no_session(client):
    resp = client.get("/get_transcript?source=mic")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"chunk_id": "-1", "transcript": ""}


def test_get_transcript_rejects_unknown_source(client):
    resp = client.get("/get_transcript?source=microphone")
    assert resp.status_code == 400


def test_get_transcript_finds_seeded_entry(client, ts):
    _seed(ts, "t1", {"42": "hello world"})
    resp = client.get("/get_transcript?tenant_id=t1&chunk_id=42")
    assert resp.status_code == 200
    assert resp.get_json() == {"chunk_id": "42", "transcript": "hello world"}


def test_transcripts_size_counts_within_range(client, ts):
    _seed(ts, "t1", {"100": "a", "500": "b", "900": "c"})
    resp = client.get("/transcripts_size?tenant_id=t1&from=0&until=1000")
    assert resp.status_code == 200
    assert resp.get_json() == {"size": 3}

    resp = client.get("/transcripts_size?tenant_id=t1&from=200&until=800")
    assert resp.get_json() == {"size": 1}


def test_swagger_has_distinct_models(client):
    resp = client.get("/swagger.json")
    assert resp.status_code == 200
    spec = resp.get_json()
    definitions = spec.get("definitions") or spec.get("components", {}).get("schemas") or {}
    assert "Transcript" in definitions
    assert "TranscribeAck" in definitions
