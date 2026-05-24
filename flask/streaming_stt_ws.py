"""
WebSocket handler for /stt/stream — optional real-time STT without changing HTTP APIs.
"""
import base64
import json
import logging
import queue as queue_mod
from typing import Any, Callable, Optional, Tuple

from websocket_manager import (
    create_session,
    remove_session,
    emit_stream_update,
    session_out_queue,
    set_current_chunk,
    get_current_chunk,
)

logger = logging.getLogger(__name__)

# Optional: bound in register_stt_stream_routes
_tenant_default = "0000"

# RMS energy threshold on int16 PCM (0–32768 scale); below this, chunk is treated as silence
VAD_SILENCE_THRESHOLD = 200


def _notify_queue_overload(session_id: str, err: Optional[str]) -> None:
    out = session_out_queue(session_id)
    if not out:
        return
    try:
        out.put_nowait(
            json.dumps(
                {
                    "type": "error",
                    "code": "queue_overload",
                    "message": err or "queue_full",
                }
            )
        )
    except queue_mod.Full:
        pass


def _handle_text_message(
    raw: str,
    session_id: str,
    tenant_id: str,
    enqueue_audio: Callable[[str, str, str, str], Tuple[bool, Optional[str]]],
    get_transcript: Callable[[str, str], str],
) -> None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON on /stt/stream")
        return

    msg_type = data.get("type", "audio")

    if msg_type == "ping":
        out = session_out_queue(session_id)
        if out:
            out.put_nowait(json.dumps({"type": "pong", "session_id": session_id}))
        return

    if msg_type == "finalize_chunk":
        chunk_id = data.get("chunk_id")
        if not chunk_id:
            return
        text = get_transcript(tenant_id, chunk_id)
        emit_stream_update(session_id, chunk_id, text, is_final=True)
        return

    if msg_type == "set_chunk":
        cid = data.get("chunk_id")
        if cid:
            set_current_chunk(session_id, cid)
        return

    # Default: audio (same fields as HTTP /transcribe)
    if "audio_b64" not in data or "chunk_id" not in data:
        logger.warning("Missing audio_b64 or chunk_id in WS message")
        return

    chunk_id = data["chunk_id"]
    audio_b64 = data["audio_b64"]
    set_current_chunk(session_id, chunk_id)
    pcm_bytes = base64.b64decode(audio_b64)
    n = len(pcm_bytes) // 2
    if n > 0:
        sum_sq = 0.0
        for i in range(n):
            v = int.from_bytes(pcm_bytes[2 * i : 2 * i + 2], "little", signed=True)
            sum_sq += float(v) * float(v)
        rms = (sum_sq / n) ** 0.5
        if rms < VAD_SILENCE_THRESHOLD:
            logger.debug("VAD: skipping silent chunk")
            return
    ok, err = enqueue_audio(tenant_id, chunk_id, audio_b64, session_id)
    if not ok:
        _notify_queue_overload(session_id, err)


def _handle_binary_message(
    pcm: bytes,
    session_id: str,
    tenant_id: str,
    enqueue_audio: Callable[[str, str, str, str], Tuple[bool, Optional[str]]],
) -> None:
    chunk_id = get_current_chunk(session_id)
    if not chunk_id:
        logger.warning("Binary PCM received but no chunk_id; send set_chunk first")
        return
    audio_b64 = base64.b64encode(pcm).decode("ascii")
    ok, err = enqueue_audio(tenant_id, chunk_id, audio_b64, session_id)
    if not ok:
        _notify_queue_overload(session_id, err)


def run_stt_stream(
    ws: Any,
    request: Any,
    *,
    enqueue_audio: Callable[[str, str, str, str], Tuple[bool, Optional[str]]],
    ensure_worker: Callable[[], None],
    get_transcript: Callable[[str, str], str],
) -> None:
    ensure_worker()
    tenant_id = request.args.get("tenant_id", _tenant_default)
    q_session = request.args.get("session_id")
    session_id, _ = create_session(tenant_id=tenant_id, session_id=q_session)
    out_q = session_out_queue(session_id)
    if not out_q:
        return

    # Tell client the assigned session_id (if auto-generated)
    try:
        ws.send(
            json.dumps(
                {
                    "type": "session",
                    "session_id": session_id,
                    "tenant_id": tenant_id,
                }
            )
        )
    except Exception:
        remove_session(session_id)
        return

    try:
        while True:
            # Flush outbound transcripts (worker thread enqueues here)
            try:
                while True:
                    msg = out_q.get_nowait()
                    ws.send(msg)
            except queue_mod.Empty:
                pass

            data = ws.receive(timeout=30)
            if data is None:
                break
            if isinstance(data, (bytes, bytearray)):
                _handle_binary_message(bytes(data), session_id, tenant_id, enqueue_audio)
            elif isinstance(data, str):
                _handle_text_message(data, session_id, tenant_id, enqueue_audio, get_transcript)
    finally:
        remove_session(session_id)
