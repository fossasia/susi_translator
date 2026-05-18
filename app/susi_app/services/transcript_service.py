import time
import logging
from . import flask_client

logger = logging.getLogger(__name__)

POLL_INTERVAL= 1.0    #seconds between poll attempts for transcript availability
POLL_TIMEOUT= 30.0    #give up after this long


def poll_for_transcript(tenant_id: str, chunk_id: str, timeout: float = POLL_TIMEOUT) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = flask_client.get_transcript(tenant_id, chunk_id)
            # normalize field name before returning to the view
            transcript_text = result.get("original") or result.get("transcript", "")
            if transcript_text:
                result["transcript"] = transcript_text  # always expose as 'transcript'
                return result
        except Exception as exc:
            logger.warning(f"Poll attempt failed for chunk {chunk_id}: {exc}")
        time.sleep(POLL_INTERVAL)

    logger.warning(f"Timed out polling for chunk {chunk_id} (tenant {tenant_id})")
    return None


def get_all_transcripts(tenant_id: str, from_id: str = "0") -> list[dict]:
    try:
        results = flask_client.list_transcripts(tenant_id, from_id=from_id)
        return [
            {
                "chunk_id": k,
                # Redis returns 'original' but, in-memory fallback returns 'transcript'
                "transcript": v.get("original") or v.get("transcript", ""),
                "translated": v.get("translated", ""),
                "source_lang": v.get("source_lang", ""),
                "target_lang": v.get("target_lang", ""),
            }
            for k, v in sorted(results.items(), key=lambda x: int(x[0]))
        ]
    except Exception as exc:
        logger.error(f"get_all_transcripts failed for tenant {tenant_id}: {exc}")
        return []