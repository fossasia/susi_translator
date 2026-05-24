#!/usr/bin/env python3
"""
Quick ingest stress helper (no Whisper needed for queue behavior if server mocks fail fast).

Example:
  STT_MAX_QUEUE_SIZE=5 STT_QUEUE_OVERFLOW_POLICY=reject python transcribe_server.py
  python stress_ingest_test.py --requests 20

Uses SSE /transcribe body: repeated JSON lines in one POST is not supported by this client;
sends one JSON per POST (non-streaming) — if your client only supports stream, use curl loop.

This script POSTs application/json as a single object (compatible with many proxies);
if transcribe_server only accepts raw stream, adapt accordingly.
"""
import argparse
import base64
import json
import time
import urllib.request
import urllib.error


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:5040")
    p.add_argument("--requests", type=int, default=30)
    p.add_argument("--tenant", default="0000")
    args = p.parse_args()

    silent_pcm = b"\x00\x00" * 800  # tiny
    b64 = base64.b64encode(silent_pcm).decode("ascii")
    url = args.base.rstrip("/") + "/transcribe"
    rejected = 0
    ok = 0
    for i in range(args.requests):
        body = json.dumps(
            {"tenant_id": args.tenant, "chunk_id": str(int(time.time() * 1000) + i), "audio_b64": b64}
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                if "rejected" in raw.lower():
                    rejected += 1
                else:
                    ok += 1
        except urllib.error.HTTPError as e:
            print("HTTP", e.code, e.read()[:200])
        time.sleep(0.01)
    print(f"done ok-ish={ok} rejected_hint={rejected} (stream response parsing is approximate)")


if __name__ == "__main__":
    main()
