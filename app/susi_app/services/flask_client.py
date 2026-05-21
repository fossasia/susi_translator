import time
import logging

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


FLASK_URL: str = getattr(settings, "FLASK_SERVICE_URL", "http://localhost:5040").rstrip("/")


def _build_session() -> requests.Session:

    retry_policy = Retry(
        total=5,
        backoff_factor=1,                       
        status_forcelist=[500, 502, 503, 504],  
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry_policy)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


# One global session shared by the whole Django process
_session: requests.Session = _build_session()


def _until_now() -> str:
    return str(int(time.time() * 1000))



#Core API Endpoints

def post_audio_chunk(
    audio_b64: str,
    chunk_id: str,
    tenant_id: str,
    source_type: str = "mic",           # "mic" | "file" | "url"

) -> dict:

    url = f"{FLASK_URL}/transcribe"
    payload: dict = {
        "audio_b64"  : audio_b64,
        "chunk_id"   : chunk_id,
        "tenant_id"  : tenant_id,
        "source_type": source_type,     
    }

    try:
        response = _session.post(url, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        logger.error(
            "post_audio_chunk failed | chunk=%s tenant=%s source=%s | %s",
            chunk_id, tenant_id, source_type, exc,
        )
        raise


def get_transcript(tenant_id: str, chunk_id: str) -> dict:

    url = f"{FLASK_URL}/get_transcript"
    try:
        response = _session.get(
            url,
            params={"tenant_id": tenant_id, "chunk_id": chunk_id},
            timeout=5,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        logger.error("get_transcript failed | chunk=%s tenant=%s | %s", chunk_id, tenant_id, exc)
        raise


# This will be used to set the language for a tenant, which can be used by the Flask service to perform language-specific processing 
def set_language_config(
    tenant_id: str,
    source_lang: str,
    target_lang: str,
) -> dict:

    url = f"{FLASK_URL}/set_language_config"
    try:
        response = _session.post(
            url,
            json={
                "tenant_id": tenant_id,
                "source_lang": source_lang,
                "target_lang": target_lang,
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        logger.error(
            "set_language_config failed | tenant=%s src=%s tgt=%s | %s",
            tenant_id, source_lang, target_lang, exc,
        )
        raise





#Management & Diagnostic Endpoints

# This will be used to list transcripts for a tenant, which can be used by the Flask service to perform language-specific processing
def list_transcripts(
    tenant_id: str,
    from_id: str = "0",
    until_id: str | None = None,
) -> dict:

    url = f"{FLASK_URL}/list_transcripts"
    try:
        response = _session.get(
            url,
            params={
                "tenant_id": tenant_id,
                "from": from_id,
                "until": until_id or _until_now(),
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        logger.error("list_transcripts failed | tenant=%s | %s", tenant_id, exc)
        raise


#can be used as health check or to monitor the growth of stored transcripts for a tenant
def get_transcripts_size(
    tenant_id: str,
    from_id: str = "0",
    until_id: str | None = None,
) -> int:
   
    url = f"{FLASK_URL}/transcripts_size"
    try:
        response = _session.get(
            url,
            params={
                "tenant_id": tenant_id,
                "from": from_id,
                "until": until_id or _until_now(),
            },
            timeout=10,
        )
        response.raise_for_status()
        return int(response.json().get("size", 0))
    except requests.exceptions.RequestException as exc:
        logger.error("get_transcripts_size failed | tenant=%s | %s", tenant_id, exc)
        return 0