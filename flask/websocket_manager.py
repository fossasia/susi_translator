"""
WebSocket session registry and outbound message queues for streaming STT.

All sends to clients happen from the WebSocket handler thread by draining
per-session queues; the Whisper worker thread only enqueues JSON strings.
"""
import json
import queue
import threading
import uuid
from typing import Any, Dict, Optional, Tuple

_sessions_lock = threading.Lock()
# session_id -> { "tenant_id", "out_q": Queue[str], "current_chunk_id": Optional[str] }
_sessions: Dict[str, Dict[str, Any]] = {}


def create_session(tenant_id: str = "0000", session_id: Optional[str] = None) -> Tuple[str, queue.Queue]:
    sid = session_id or uuid.uuid4().hex
    out_q: queue.Queue[str] = queue.Queue(maxsize=256)
    with _sessions_lock:
        _sessions[sid] = {"tenant_id": tenant_id, "out_q": out_q, "current_chunk_id": None}
    return sid, out_q


def remove_session(session_id: str) -> None:
    with _sessions_lock:
        _sessions.pop(session_id, None)


def get_session_tenant(session_id: str) -> Optional[str]:
    with _sessions_lock:
        s = _sessions.get(session_id)
        return s["tenant_id"] if s else None


def set_current_chunk(session_id: str, chunk_id: Optional[str]) -> None:
    with _sessions_lock:
        s = _sessions.get(session_id)
        if s:
            s["current_chunk_id"] = chunk_id


def get_current_chunk(session_id: str) -> Optional[str]:
    with _sessions_lock:
        s = _sessions.get(session_id)
        return s.get("current_chunk_id") if s else None


def emit_stream_update(session_id: str, chunk_id: str, text: str, is_final: bool) -> None:
    """Called from the STT worker thread; never blocks on WebSocket I/O."""
    payload = {
        "session_id": session_id,
        "chunk_id": chunk_id,
        "text": text,
        "is_final": is_final,
    }
    msg = json.dumps(payload, ensure_ascii=False)
    with _sessions_lock:
        s = _sessions.get(session_id)
        if not s:
            return
        out_q = s["out_q"]
    try:
        out_q.put_nowait(msg)
    except queue.Full:
        pass


def session_out_queue(session_id: str) -> Optional[queue.Queue]:
    with _sessions_lock:
        s = _sessions.get(session_id)
        return s["out_q"] if s else None
