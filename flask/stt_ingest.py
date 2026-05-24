"""
Bounded ingestion for the shared STT queue: timestamps, backpressure, normalized tuples.
"""
import queue
import threading
import time
from typing import Any, Optional, Tuple, Union

from stt_config import STT_QUEUE_OVERFLOW_POLICY

IngestItem = Union[
    Tuple[str, str, str],
    Tuple[str, str, str, Optional[str]],
    Tuple[str, str, str, Optional[str], float],
]

_ingest_lock = threading.Lock()


def normalize_stt_item(item: IngestItem) -> Tuple[str, str, str, Optional[str], float]:
    """Canonical queue item: (tenant_id, chunk_id, audio_b64, session_id, enqueue_monotonic_ts)."""
    ts = time.monotonic()
    if isinstance(item, tuple) and len(item) == 5:
        t, c, a, s, old_ts = item
        return (t, c, a, s, float(old_ts))
    if isinstance(item, tuple) and len(item) == 4:
        t, c, a, s = item
        return (t, c, a, s, ts)
    if isinstance(item, tuple) and len(item) == 3:
        t, c, a = item
        return (t, c, a, None, ts)
    raise ValueError("ingest item must be a 3-, 4-, or 5-tuple")


def try_enqueue(audio_stack: "queue.Queue", item: IngestItem) -> Tuple[bool, Optional[str]]:
    """
    Enqueue one STT job. Returns (ok, error_code).
    Uses policy STT_QUEUE_OVERFLOW_POLICY when the queue is at capacity.
    """
    normalized = normalize_stt_item(item)
    if STT_QUEUE_OVERFLOW_POLICY == "drop_oldest":
        with _ingest_lock:
            while True:
                try:
                    audio_stack.put(normalized, block=False)
                    return True, None
                except queue.Full:
                    try:
                        audio_stack.get_nowait()
                        audio_stack.task_done()
                    except queue.Empty:
                        return False, "queue_full"
    try:
        audio_stack.put(normalized, block=False)
        return True, None
    except queue.Full:
        return False, "queue_full"
