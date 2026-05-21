"""
Higher-level transcript helpers consumed by Django views
"""

import time
import logging
from typing import Optional

from . import flask_client

logger = logging.getLogger(__name__)


POLL_INTERVAL: float = 1.0     # seconds between attempts in blocking poll
POLL_TIMEOUT: float  = 30.0    # give up after this many seconds



def _normalise(raw: dict) -> dict:

    return {
        "chunk_id"   : raw.get("chunk_id", ""),
        "transcript" : raw.get("original") or raw.get("transcript", ""),
        "translated" : raw.get("translated", ""),
        "source_lang": raw.get("source_lang", ""),
        "target_lang": raw.get("target_lang", ""),
    }


def _normalise_map(raw_map: dict) -> list[dict]:

    result = []
    for chunk_id, entry in sorted(raw_map.items(), key=lambda x: _safe_int(x[0])):
        normalised = _normalise(entry)
        normalised["chunk_id"] = chunk_id   # inject key as field
        result.append(normalised)
    return result


def _safe_int(value: str, fallback: int = 0) -> int:
    """Parse a string as int without raising — returns fallback on error."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return fallback


def poll_for_transcript(
    tenant_id: str,
    chunk_id: str,
    timeout: float = POLL_TIMEOUT,
) -> Optional[dict]:

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            raw = flask_client.get_transcript(tenant_id, chunk_id)
            entry = _normalise(raw)
            if entry["transcript"]:
                logger.debug(
                    "poll_for_transcript: got result | chunk=%s tenant=%s", chunk_id, tenant_id
                )
                return entry
        except Exception as exc:
            logger.warning(
                "poll_for_transcript: attempt failed | chunk=%s | %s", chunk_id, exc
            )
        time.sleep(POLL_INTERVAL)

    logger.warning(
        "poll_for_transcript: timed out after %.0fs | chunk=%s tenant=%s",
        timeout, chunk_id, tenant_id,
    )
    return None



def pop_latest_snapshot(tenant_id: str) -> dict:

    try:
        raw = flask_client.pop_latest_transcript(tenant_id)
        return _normalise(raw)
    except Exception as exc:
        logger.error("pop_latest_snapshot failed | tenant=%s | %s", tenant_id, exc)
        return {
            "chunk_id"   : "-1",
            "transcript" : "",
            "translated" : "",
            "source_lang": "",
            "target_lang": "",
        }


def get_latest_snapshot(tenant_id: str) -> dict:

    try:
        raw = flask_client.get_latest_transcript(tenant_id)
        return _normalise(raw)
    except Exception as exc:
        logger.error("get_latest_snapshot failed | tenant=%s | %s", tenant_id, exc)
        return {
            "chunk_id"   : "-1",
            "transcript" : "",
            "translated" : "",
            "source_lang": "",
            "target_lang": "",
        }

def get_all_transcripts(
    tenant_id: str,
    from_id: str = "0",
    until_id: str | None = None,
) -> list[dict]:

    try:
        raw_map = flask_client.list_transcripts(tenant_id, from_id=from_id, until_id=until_id)
        return _normalise_map(raw_map)
    except Exception as exc:
        logger.error("get_all_transcripts failed | tenant=%s | %s", tenant_id, exc)
        return []


def get_transcript_count(tenant_id: str) -> int:

    return flask_client.get_transcripts_size(tenant_id)


def reset_session(tenant_id: str) -> bool:

    success = flask_client.clear_all_transcripts(tenant_id)
    if success:
        logger.info("reset_session: cleared transcripts for tenant=%s", tenant_id)
    else:
        logger.warning("reset_session: partial failure for tenant=%s", tenant_id)
    return success


def configure_languages(
    tenant_id: str,
    source_lang: str,
    target_lang: str,
) -> bool:

    try:
        flask_client.set_language_config(tenant_id, source_lang, target_lang)
        logger.info(
            "configure_languages: tenant=%s src=%s tgt=%s", tenant_id, source_lang, target_lang
        )
        return True
    except Exception as exc:
        logger.error(
            "configure_languages failed | tenant=%s | %s", tenant_id, exc
        )
        return False