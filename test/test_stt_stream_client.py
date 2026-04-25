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