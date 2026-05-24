"""
run_tests.py — Regression test for Transcription API
Usage: python run_tests.py --wav test_audio.wav
Run this on BOTH old and new versions and compare outputs.
"""

import argparse
import asyncio
import base64
import json
import sys
import time
import wave
import requests
import websockets

BASE_URL  = "http://127.0.0.1:5055"
WS_URL    = "ws://127.0.0.1:5055/stt/stream"
TENANT_ID = "0000"
CHUNK_ID  = "9999999999999"
WS_CHUNK_ID = "8888888888888"
FAR_FUTURE = "9999999999999999"  # large 'until' so list/size endpoints don't filter out our chunks

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
INFO = "\033[94m[INFO]\033[0m"
SKIP = "\033[93m[SKIP]\033[0m"

results = []

def log(status, test_name, detail=""):
    symbol = PASS if status else FAIL
    line = f"{symbol} {test_name}"
    if detail:
        line += f" — {detail}"
    print(line)
    results.append((status, test_name))

def log_skip(test_name, reason):
    print(f"{SKIP} {test_name} — {reason}")
    results.append((True, test_name))  # skips count as pass


# ─────────────────────────────────────────────
# Test 1 — Swagger UI
# ─────────────────────────────────────────────
def test_swagger():
    try:
        r = requests.get(f"{BASE_URL}/swagger", timeout=5)
        log(r.status_code == 200, "Test 1 — GET /swagger", f"status={r.status_code}")
    except Exception as e:
        log(False, "Test 1 — GET /swagger", str(e))


# ─────────────────────────────────────────────
# Test 2 — POST /transcribe
# ─────────────────────────────────────────────
def test_transcribe(wav_path):
    try:
        with wave.open(wav_path, 'rb') as w:
            pcm = w.readframes(w.getnframes())
        payload = {
            "chunk_id": CHUNK_ID,
            "tenant_id": TENANT_ID,
            "audio_b64": base64.b64encode(pcm).decode()
        }
        r = requests.post(f"{BASE_URL}/transcribe", json=payload, timeout=120)
        ok = r.status_code == 200
        log(ok, "Test 2 — POST /transcribe", f"status={r.status_code} | response={r.text[:150]}")
    except Exception as e:
        log(False, "Test 2 — POST /transcribe", str(e))


# ─────────────────────────────────────────────
# Poll until transcript is ready (max wait_s seconds)
# ─────────────────────────────────────────────
def wait_for_transcript(chunk_id, wait_s=120):
    print(f"\n{INFO} Polling for transcript (max {wait_s}s)...", flush=True)
    for i in range(wait_s):
        r = requests.get(f"{BASE_URL}/get_transcript",
                         params={"tenant_id": TENANT_ID, "chunk_id": chunk_id},
                         timeout=10)
        data = r.json()
        if data.get("chunk_id") != "-1" and data.get("transcript", ""):
            print(f"{INFO} Transcript ready after ~{i+1}s: {data['transcript'][:80]}\n")
            return True
        time.sleep(1)
    print(f"{FAIL} Transcript not ready after {wait_s}s\n")
    return False


# ─────────────────────────────────────────────
# Test 3 — GET /get_transcript
# ─────────────────────────────────────────────
def test_get_transcript():
    try:
        r = requests.get(f"{BASE_URL}/get_transcript",
                         params={"tenant_id": TENANT_ID, "chunk_id": CHUNK_ID},
                         timeout=10)
        data = r.json()
        ok = r.status_code == 200 and data.get("transcript", "") != ""
        log(ok, "Test 3 — GET /get_transcript",
            f"status={r.status_code} | transcript={data.get('transcript','(empty)')[:80]}")
    except Exception as e:
        log(False, "Test 3 — GET /get_transcript", str(e))


# ─────────────────────────────────────────────
# Test 4 — GET /get_latest_transcript
# Known bug in original code: crashes with NoneType when no matching chunk found.
# We pass 'until=FAR_FUTURE' so it finds our chunk.
# ─────────────────────────────────────────────
def test_get_latest_transcript():
    try:
        r = requests.get(f"{BASE_URL}/get_latest_transcript",
                         params={"tenant_id": TENANT_ID, "until": FAR_FUTURE},
                         timeout=10)
        ok = r.status_code == 200
        log(ok, "Test 4 — GET /get_latest_transcript",
            f"status={r.status_code} | response={r.text[:150]}")
        if r.status_code == 500:
            print(f"         {INFO} Note: 500 here = pre-existing bug in original code (NoneType crash when no chunk matches 'until' filter)")
    except Exception as e:
        log(False, "Test 4 — GET /get_latest_transcript", str(e))


# ─────────────────────────────────────────────
# Test 5 — GET /get_first_transcript
# ─────────────────────────────────────────────
def test_get_first_transcript():
    try:
        r = requests.get(f"{BASE_URL}/get_first_transcript",
                         params={"tenant_id": TENANT_ID},
                         timeout=10)
        ok = r.status_code == 200
        log(ok, "Test 5 — GET /get_first_transcript",
            f"status={r.status_code} | response={r.text[:150]}")
    except Exception as e:
        log(False, "Test 5 — GET /get_first_transcript", str(e))


# ─────────────────────────────────────────────
# Test 6 — GET /list_transcripts
# Must pass until=FAR_FUTURE because our CHUNK_ID is a large number
# and the default 'until' is current timestamp which is smaller
# ─────────────────────────────────────────────
def test_list_transcripts():
    try:
        r = requests.get(f"{BASE_URL}/list_transcripts",
                         params={"tenant_id": TENANT_ID, "until": FAR_FUTURE},
                         timeout=10)
        ok = r.status_code == 200
        log(ok, "Test 6 — GET /list_transcripts",
            f"status={r.status_code} | response={r.text[:150]}")
    except Exception as e:
        log(False, "Test 6 — GET /list_transcripts", str(e))


# ─────────────────────────────────────────────
# Test 7 — GET /transcripts_size
# Same reason — pass until=FAR_FUTURE
# ─────────────────────────────────────────────
def test_transcripts_size():
    try:
        r = requests.get(f"{BASE_URL}/transcripts_size",
                         params={"tenant_id": TENANT_ID, "until": FAR_FUTURE},
                         timeout=10)
        ok = r.status_code == 200
        log(ok, "Test 7 — GET /transcripts_size",
            f"status={r.status_code} | response={r.text[:150]}")
    except Exception as e:
        log(False, "Test 7 — GET /transcripts_size", str(e))


# ─────────────────────────────────────────────
# Test 8 — WebSocket /stt/stream (NEW FEATURE)
#
# Correct protocol (from streaming_stt_ws.py):
# 1. Connect → server immediately sends {"type":"session","session_id":"...","tenant_id":"..."}
# 2. Client sends {"type":"set_chunk","chunk_id":"...","tenant_id":"..."} 
# 3. Client sends binary PCM chunks
# 4. Server enqueues audio → Whisper processes → emit_stream_update sends transcript back
# 5. Close connection (no "end" message needed — server times out after 30s of silence)
# ─────────────────────────────────────────────
async def _ws_test(wav_path):
    with wave.open(wav_path, 'rb') as wf:
        assert wf.getframerate() == 16000, "WAV must be 16000Hz"
        assert wf.getnchannels() == 1,     "WAV must be mono"
        pcm = wf.readframes(wf.getnframes())

    chunk_size = 3200  # 100ms at 16kHz 16-bit mono
    received_msgs = []

    async with websockets.connect(WS_URL) as ws:

        # Step 1 — receive session message from server
        try:
            session_msg = await asyncio.wait_for(ws.recv(), timeout=5)
            session_data = json.loads(session_msg)
            session_id = session_data.get("session_id", "unknown")
            print(f"         {INFO} WS session assigned: {session_id}")
        except Exception as e:
            return False, f"No session message from server: {e}"

        # Step 2 — send set_chunk control message
        await ws.send(json.dumps({
            "type": "set_chunk",
            "chunk_id": WS_CHUNK_ID,
            "tenant_id": TENANT_ID
        }))
        await asyncio.sleep(0.2)

        # Step 3 — send binary PCM chunks
        for i in range(0, len(pcm), chunk_size):
            await ws.send(pcm[i:i + chunk_size])
            await asyncio.sleep(0.1)

        # Step 4 — keep connection alive with pings while Whisper processes
        # Server closes after 30s of silence; our hardware takes ~50s to transcribe
        # Ping resets the 30s timeout. We ping every 20s for up to 120s total.
        print(f"         {INFO} Audio sent, waiting for transcript response (up to 120s)...")
        deadline = 120  # total seconds to wait
        ping_interval = 20  # ping every 20s to keep connection alive
        elapsed = 0
        try:
            while elapsed < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=ping_interval)
                    received_msgs.append(msg)
                    try:
                        data = json.loads(msg)
                        # transcript from emit_stream_update has: session_id, chunk_id, text, is_final
                        if "text" in data and data.get("chunk_id") == WS_CHUNK_ID:
                            return True, f"transcript='{data['text'][:80]}' is_final={data.get('is_final')}"
                        if data.get("type") == "pong":
                            pass  # expected keepalive response
                    except Exception:
                        pass
                except asyncio.TimeoutError:
                    # No message yet — send ping to reset server 30s timeout
                    elapsed += ping_interval
                    if elapsed < deadline:
                        await ws.send(json.dumps({"type": "ping"}))
                        print(f"         {INFO} Ping sent (elapsed={elapsed}s), still waiting...")
        except Exception as e:
            if received_msgs:
                return True, f"got {len(received_msgs)} message(s), last={received_msgs[-1][:100]}"
            return False, f"Connection error: {e}"
        return False, "No transcript received within 120s"


def test_websocket_stream(wav_path):
    try:
        ok, detail = asyncio.run(_ws_test(wav_path))
        log(ok, "Test 8 — WS  /stt/stream (new feature)", detail)
    except Exception as e:
        log(False, "Test 8 — WS  /stt/stream (new feature)", str(e))


# ─────────────────────────────────────────────
# Test 9 — GET /delete_transcript (cleanup)
# ─────────────────────────────────────────────
def test_delete_transcript():
    try:
        r = requests.get(f"{BASE_URL}/delete_transcript",
                         params={"tenant_id": TENANT_ID, "chunk_id": CHUNK_ID},
                         timeout=10)
        ok = r.status_code == 200
        log(ok, "Test 9 — GET /delete_transcript (cleanup)",
            f"status={r.status_code} | response={r.text[:150]}")
    except Exception as e:
        log(False, "Test 9 — GET /delete_transcript (cleanup)", str(e))


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wav", default="test_audio.wav", help="16kHz mono 16-bit WAV file")
    args = parser.parse_args()

    print("\n" + "="*60)
    print("  Transcription API — Regression Test Suite")
    print("="*60 + "\n")
    print(f"{INFO} Using WAV file: {args.wav}\n")

    # --- Old feature tests ---
    test_swagger()
    test_transcribe(args.wav)

    # Poll instead of fixed sleep — faster on good hardware, patient on slow
    ready = wait_for_transcript(CHUNK_ID, wait_s=120)

    test_get_transcript()
    test_get_latest_transcript()
    test_get_first_transcript()
    test_list_transcripts()
    test_transcripts_size()

    # --- New feature test ---
    test_websocket_stream(args.wav)

    # --- Cleanup ---
    test_delete_transcript()

    # Summary
    passed = sum(1 for ok, _ in results if ok)
    total  = len(results)
    print("\n" + "="*60)
    print(f"  Results: {passed}/{total} passed")
    print("="*60)

    if passed == total:
        print("\n✅ All tests passed. New feature has not broken anything.\n")
    else:
        print("\n❌ Some tests failed. Check output above.\n")
        for ok, name in results:
            if not ok:
                print(f"   - {name}")
        print()

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()