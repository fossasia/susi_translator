"""Environment-based STT scaling configuration (Flask server)."""
import os

STT_NUM_WORKERS = max(1, int(os.getenv("STT_NUM_WORKERS", "1")))
STT_MAX_QUEUE_SIZE = max(1, int(os.getenv("STT_MAX_QUEUE_SIZE", "1000")))
# reject: put fails when full; drop_oldest: drop head tasks until there is space
STT_QUEUE_OVERFLOW_POLICY = os.getenv("STT_QUEUE_OVERFLOW_POLICY", "reject").strip().lower()
if STT_QUEUE_OVERFLOW_POLICY not in ("reject", "drop_oldest"):
    STT_QUEUE_OVERFLOW_POLICY = "reject"
