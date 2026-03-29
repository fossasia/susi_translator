# #!/usr/bin/env python3
# """
# Simulate low-latency streaming: connect to ws://.../stt/stream and send ~1s PCM chunks.

# Requires: pip install websocket-client
# Server: python transcribe_server.py (port 5040)
# """
# import argparse
# import base64
# import json
# import struct
# import time

# try:
#     import websocket
# except ImportError:
#     raise SystemExit("Install websocket-client: pip install websocket-client")


# def build_pcm_chunk_ms(duration_ms: int, sample_rate: int = 16000, amplitude: int = 800) -> bytes:
#     """Mono int16 LE sine-ish pattern (not silent, to avoid is_valid rejection of empty-ish ASR)."""
#     n = sample_rate * duration_ms // 1000
#     out = bytearray()
#     for i in range(n):
#         v = int(amplitude * ((i % 200) / 100.0 - 1.0))
#         if v > 32767:
#             v = 32767
#         if v < -32768:
#             v = -32768
#         out.extend(struct.pack("<h", v))
#     return bytes(out)


# def drain(ws, timeout=0.3):
#     """Read all pending messages from server (non-blocking). Returns list of parsed dicts."""
#     msgs = []
#     ws.settimeout(timeout)
#     try:
#         while True:
#             raw = ws.recv()
#             try:
#                 msg = json.loads(raw)
#             except json.JSONDecodeError:
#                 msg = {"raw": raw}
#             msgs.append(msg)
#     except Exception:
#         pass
#     ws.settimeout(None)
#     return msgs


# def main():
#     p = argparse.ArgumentParser()
#     p.add_argument("--url", default="ws://127.0.0.1:5040/stt/stream?tenant_id=0000")
#     p.add_argument("--chunk-ms", type=int, default=1000, help="PCM duration per message (~1–2s recommended)")
#     p.add_argument("--rounds", type=int, default=3)
#     args = p.parse_args()

#     ws = websocket.create_connection(args.url)
#     session = json.loads(ws.recv())
#     print("from server:", session)
#     if session.get("type") != "session":
#         print("unexpected first message")

#     chunk_id = str(int(time.time() * 1000))
#     ws.send(json.dumps({"type": "set_chunk", "chunk_id": chunk_id}))
#     ws.settimeout(2.0)
#     try:
#         ack_raw = ws.recv()
#         ack = json.loads(ack_raw)
#         if ack.get("type") == "set_chunk_ack":
#             print(f"set_chunk_ack received for chunk_id={ack.get('chunk_id')}")
#         else:
#             print("unexpected message after set_chunk:", ack)
#     except Exception as e:
#         print("warning: did not receive set_chunk_ack:", e)
#     ws.settimeout(None)

#     for r in range(args.rounds):
#         pcm = build_pcm_chunk_ms(args.chunk_ms)
#         payload = {
#             "type": "audio_chunk",
#             "chunk_id": chunk_id,
#             "audio_b64": base64.b64encode(pcm).decode("ascii"),
#         }
#         ws.send(json.dumps(payload))
#         for m in drain(ws, timeout=0.5):
#             if m.get("type") == "error":
#                 print(f"  server error: {m.get('message')}")
#             else:
#                 text = m.get("text", "")
#                 is_final = m.get("is_final", False)
#                 print(f"  interim transcript (is_final={is_final}): {text!r}")
#         time.sleep(0.05)

#     ws.send(json.dumps({"type": "finalize_chunk", "chunk_id": chunk_id}))
#     ws.settimeout(5.0)
#     try:
#         while True:
#             raw = ws.recv()
#             m = json.loads(raw)
#             mtype = m.get("type", "")
#             if mtype == "finalize_ack":
#                 warning = m.get("warning", "")
#                 print(f"finalize_ack received.{(' WARNING: ' + warning) if warning else ''}")
#             elif mtype == "error":
#                 print(f"server error: {m.get('message')}")
#             else:
#                 text = m.get("text", "")
#                 is_final = m.get("is_final", False)
#                 print(f"final transcript (is_final={is_final}): {text!r}")
#                 if is_final:
#                     break
#     except Exception as e:
#         print("done waiting (timeout or closed):", e)
#     ws.close()
#     print("Connection closed.")


# if __name__ == "__main__":
#     main()

#!/usr/bin/env python3
# """
# Simulate low-latency streaming: connect to ws://.../stt/stream and send ~1s PCM chunks.

# Requires: pip install websocket-client
# Server: python transcribe_server.py (port 5055)

# Real server protocol (streaming_stt_ws.py):
#   Client → server:
#     {"type": "set_chunk",      "chunk_id": "<id>"}          ← no ack sent back
#     {"chunk_id": "<id>", "audio_b64": "<base64 PCM>"}       ← type field optional
#     {"type": "finalize_chunk", "chunk_id": "<id>"}           ← triggers final transcript

#   Server → client:
#     {"type": "session", "session_id": "...", "tenant_id": "..."}   ← on connect
#     {"session_id":…, "chunk_id":…, "text":…, "is_final": false}   ← interim
#     {"session_id":…, "chunk_id":…, "text":…, "is_final": true}    ← on finalize
# """
# import argparse
# import base64
# import json
# import struct
# import time

# try:
#     import websocket
# except ImportError:
#     raise SystemExit("Install websocket-client: pip install websocket-client")


# def build_pcm_chunk_ms(duration_ms: int, sample_rate: int = 16000, amplitude: int = 800) -> bytes:
#     """Mono int16 LE sine-ish pattern (not silent, to avoid is_valid rejection of empty-ish ASR)."""
#     n = sample_rate * duration_ms // 1000
#     out = bytearray()
#     for i in range(n):
#         v = int(amplitude * ((i % 200) / 100.0 - 1.0))
#         if v > 32767:
#             v = 32767
#         if v < -32768:
#             v = -32768
#         out.extend(struct.pack("<h", v))
#     return bytes(out)


# def drain(ws, timeout=0.3):
#     """Read all pending messages from server (non-blocking best-effort). Returns list of parsed msgs."""
#     msgs = []
#     ws.settimeout(timeout)
#     try:
#         while True:
#             raw = ws.recv()
#             try:
#                 msg = json.loads(raw)
#             except json.JSONDecodeError:
#                 msg = {"raw": raw}
#             msgs.append(msg)
#     except Exception:
#         pass
#     ws.settimeout(None)
#     return msgs


# def main():
#     p = argparse.ArgumentParser()
#     p.add_argument("--url", default="ws://127.0.0.1:5055/stt/stream?tenant_id=0000")
#     p.add_argument("--chunk-ms", type=int, default=1000)
#     p.add_argument("--rounds", type=int, default=3)
#     args = p.parse_args()

#     ws = websocket.create_connection(args.url)

#     # 1. Session greeting
#     session = json.loads(ws.recv())
#     print("from server:", session)

#     # 2. Set chunk
#     chunk_id = str(int(time.time() * 1000))
#     ws.send(json.dumps({"type": "set_chunk", "chunk_id": chunk_id}))
#     print(f"set_chunk sent (chunk_id={chunk_id})")

#     # 3. Send all audio chunks with NO waiting between them
#     #    Server closes connection after 50ms of silence so we must
#     #    keep sending without any blocking reads in between.
#     for r in range(args.rounds):
#         print(f"\n--- round {r + 1}/{args.rounds} ---")
#         pcm = build_pcm_chunk_ms(args.chunk_ms)
#         payload = {
#             "chunk_id": chunk_id,
#             "audio_b64": base64.b64encode(pcm).decode("ascii"),
#         }
#         ws.send(json.dumps(payload))
#         print(f"  sent {len(pcm)} bytes PCM (~{args.chunk_ms}ms)")
#         # NO drain() here — server drops connection after 50ms of silence

#     # 4. Send finalize immediately after last chunk
#     print("\n--- finalizing ---")
#     ws.send(json.dumps({"type": "finalize_chunk", "chunk_id": chunk_id}))
#     print("finalize_chunk sent, waiting for transcript...")

#     # 5. NOW we can wait — Whisper takes ~40s on CPU
#     print("(Whisper runs on CPU, this may take up to 60 seconds...)")
#     ws.settimeout(60.0)
#     try:
#         while True:
#             raw = ws.recv()
#             if not raw:
#                 continue
#             try:
#                 m = json.loads(raw)
#             except json.JSONDecodeError:
#                 continue
#             if m.get("type") == "error":
#                 print(f"server error [{m.get('code','?')}]: {m.get('message')}")
#             elif "text" in m:
#                 print(f"transcript (is_final={m.get('is_final')}): {m.get('text')!r}")
#                 if m.get("is_final"):
#                     break
#             else:
#                 print("message:", m)
#     except Exception as e:
#         print("done waiting:", e)

#     ws.close()
#     print("\nConnection closed.")


# if __name__ == "__main__":
#     main()

#!/usr/bin/env python3
"""
Simulate low-latency streaming: connect to ws://.../stt/stream and send ~1s PCM chunks.

Requires: pip install websocket-client
Server: python transcribe_server.py (port 5055)

Real server protocol (streaming_stt_ws.py):
  Client → server:
    {"type": "set_chunk",      "chunk_id": "<id>"}          ← no ack sent back
    {"chunk_id": "<id>", "audio_b64": "<base64 PCM>"}       ← type field optional
    {"type": "finalize_chunk", "chunk_id": "<id>"}           ← triggers final transcript

  Server → client:
    {"type": "session", "session_id": "...", "tenant_id": "..."}   ← on connect
    {"session_id":…, "chunk_id":…, "text":…, "is_final": false}   ← interim
    {"session_id":…, "chunk_id":…, "text":…, "is_final": true}    ← on finalize

Usage:
  # Fake sine wave (protocol test only):
  python test_stt_stream_client.py --url ws://127.0.0.1:5055/stt/stream

  # Real WAV file (must be 16kHz mono 16-bit PCM):
  python test_stt_stream_client.py --url ws://127.0.0.1:5055/stt/stream --wav test_audio.wav
"""
import argparse
import base64
import json
import struct
import time
import wave

try:
    import websocket
except ImportError:
    raise SystemExit("Install websocket-client: pip install websocket-client")


SAMPLE_RATE = 16000
BYTES_PER_CHUNK = SAMPLE_RATE * 2  # 1 second of 16-bit mono = 32000 bytes


def build_fake_pcm_chunk(duration_ms: int = 1000, amplitude: int = 800) -> bytes:
    """Mono int16 LE sine-ish pattern — for protocol testing only, not real speech."""
    n = SAMPLE_RATE * duration_ms // 1000
    out = bytearray()
    for i in range(n):
        v = int(amplitude * ((i % 200) / 100.0 - 1.0))
        v = max(-32768, min(32767, v))
        out.extend(struct.pack("<h", v))
    return bytes(out)


def load_wav_chunks(path: str, chunk_ms: int = 1000):
    """
    Read a WAV file and yield raw PCM chunks of chunk_ms duration.
    File must be 16kHz, mono, 16-bit. Raises ValueError if not.
    """
    with wave.open(path, 'rb') as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        if sr != SAMPLE_RATE:
            raise ValueError(
                f"WAV must be {SAMPLE_RATE}Hz, got {sr}Hz.\n"
                f"Convert with: ffmpeg -i {path} -ar 16000 -ac 1 -sample_fmt s16 test_audio.wav"
            )
        if ch != 1:
            raise ValueError(f"WAV must be mono, got {ch} channels.")
        if sw != 2:
            raise ValueError(f"WAV must be 16-bit, got {sw*8}-bit.")

        frames_per_chunk = SAMPLE_RATE * chunk_ms // 1000
        total = w.getnframes()
        print(f"WAV loaded: {path} | {sr}Hz mono 16-bit | {total/sr:.2f}s")

        while True:
            frames = w.readframes(frames_per_chunk)
            if not frames:
                break
            yield frames


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="ws://127.0.0.1:5055/stt/stream?tenant_id=0000")
    p.add_argument("--chunk-ms", type=int, default=1000, help="PCM duration per message in ms")
    p.add_argument("--rounds", type=int, default=3, help="Rounds of fake audio (ignored if --wav is set)")
    p.add_argument("--wav", type=str, default=None, help="Path to a 16kHz mono 16-bit WAV file")
    args = p.parse_args()

    # Build list of PCM chunks to send
    if args.wav:
        print(f"Mode: real WAV file ({args.wav})")
        try:
            chunks = list(load_wav_chunks(args.wav, args.chunk_ms))
        except (ValueError, FileNotFoundError) as e:
            raise SystemExit(f"ERROR: {e}")
    else:
        print("Mode: fake sine wave (protocol test only — transcript will be empty)")
        chunks = [build_fake_pcm_chunk(args.chunk_ms) for _ in range(args.rounds)]

    # ── Connect ──────────────────────────────────────────────────────────────
    ws = websocket.create_connection(args.url)

    # ── 1. Session greeting ──────────────────────────────────────────────────
    session = json.loads(ws.recv())
    print("from server:", session)
    if session.get("type") != "session":
        print("WARNING: unexpected first message:", session)

    # ── 2. Set chunk ─────────────────────────────────────────────────────────
    # Server (streaming_stt_ws.py) does NOT send an ack — just registers silently.
    chunk_id = str(int(time.time() * 1000))
    ws.send(json.dumps({"type": "set_chunk", "chunk_id": chunk_id}))
    print(f"set_chunk sent (chunk_id={chunk_id})")

    # # ── 3. Send all audio chunks with NO blocking reads between sends ─────────
    # # CRITICAL: server closes connection after 50ms of silence (ws.receive timeout=0.05).
    # # Any blocking recv() between sends will kill the connection. Send everything
    # # first, then read responses after finalize.
    # for i, pcm in enumerate(chunks):
    #     print(f"\n--- chunk {i + 1}/{len(chunks)} ---")
    #     payload = {
    #         "chunk_id": chunk_id,
    #         "audio_b64": base64.b64encode(pcm).decode("ascii"),
    #     }
    #     ws.send(json.dumps(payload))
    #     print(f"  sent {len(pcm)} bytes (~{args.chunk_ms}ms)")
    
    # ── 3. Send entire audio as ONE payload ──────────────────────────────────
    # Sending as multiple chunks causes each to be transcribed separately,
    # overwriting previous results. One payload = one full transcription.
    print("\n--- sending full audio as single payload ---")
    full_pcm = b"".join(chunks)
    payload = {
        "chunk_id": chunk_id,
        "audio_b64": base64.b64encode(full_pcm).decode("ascii"),
    }
    ws.send(json.dumps(payload))
    print(f"  sent {len(full_pcm)} bytes ({len(full_pcm)/32000:.2f}s of audio)")

    # ── 4. Keep connection alive while Whisper processes, then finalize ───────
    print("\n--- keeping connection alive while Whisper processes (~40s on CPU) ---")
    wait_total = 55  # seconds to wait
    interval = 0.03  # ping every 30ms — faster than server's 50ms timeout
    steps = int(wait_total / interval)
    for i in range(steps):
        time.sleep(interval)
        ws.send(json.dumps({"type": "ping"}))
        if i % 33 == 0:  # print progress every ~1 second
            print(f"  waiting... {int(i * interval)+1}/{wait_total}s", end="\r")

    print("\n--- finalizing ---")
    ws.send(json.dumps({"type": "finalize_chunk", "chunk_id": chunk_id}))
    print("finalize_chunk sent — reading transcript...")

    # ── 5. Wait for final transcript ─────────────────────────────────────────
    ws.settimeout(60.0)
    try:
        while True:
            raw = ws.recv()
            if not raw:
                continue
            try:
                m = json.loads(raw)
            except json.JSONDecodeError:
                print("non-JSON from server:", raw)
                continue

            if m.get("type") == "error":
                print(f"server error [{m.get('code', '?')}]: {m.get('message')}")
            elif "text" in m:
                print(f"transcript (is_final={m.get('is_final')}): {m.get('text')!r}")
                if m.get("is_final"):
                    break
            else:
                print("message:", m)
    except Exception as e:
        print("done waiting:", e)

    ws.close()
    print("\nConnection closed.")


if __name__ == "__main__":
    main()