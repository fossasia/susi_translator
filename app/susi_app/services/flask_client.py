import logging
import time
import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

FLASK_URL = getattr(settings, 'FLASK_SERVICE_URL', 'http://localhost:5040').rstrip('/')

def _get_session() -> requests.Session:
    retry_policy = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[500,502,503,504],
    )
    adapter = HTTPAdapter(max_retries=retry_policy)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

#a single global session to reuse connection pools across all requests
_session = _get_session()

def post_audio_chunk(audio_b64: str, chunk_id: str, tenant_id: str, audio_type: str = "mic") -> dict:
   
    url = f"{FLASK_URL}/transcribe"
    payload = {
        "audio_b64": audio_b64,
        "chunk_id": chunk_id,
        "tenant_id": tenant_id,
        "source_type": audio_type
    }
    
    try:
        response = _session.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        response.raise_for_status() 
        
        #return the json response from flask server
        return response.json() 
        
    except requests.exceptions.RequestException as exc:
        logger.error(f"Failed to send chunk {chunk_id} to Flask server at {url}. Error: {exc}")
        raise

def get_transcript(tenant_id: str, chunk_id: str) -> dict:
    url = f"{FLASK_URL}/get_transcript"
    try:
        response = _session.get(
            url, 
            params={
                "tenant_id": tenant_id, 
                "chunk_id": chunk_id}, 
                 timeout=10
                 )
        response.raise_for_status()
        return response.json()
    
    except requests.exceptions.RequestException as exc:
        logger.error(f"Failed to get transcript {chunk_id}: {exc}")
        raise

def list_transcripts(tenant_id: str, from_id: str = "0", until_id: str = None) -> dict:
    import time
    url = f"{FLASK_URL}/list_transcripts"
    params = {
        "tenant_id": tenant_id,
        "from": from_id,
        "until": until_id or str(int(time.time() * 1000)),
    }
    try:
        response = _session.get(
            url, 
            params=params, 
            timeout=10
            )
        response.raise_for_status()
        return response.json()
    
    except requests.exceptions.RequestException as exc:
        logger.error(f"Failed to list transcripts for tenant {tenant_id}: {exc}")
        raise

def set_language_config(tenant_id: str, source_lang: str, target_lang: str) -> dict:
    url = f"{FLASK_URL}/set_language_config"
    try:
        response = _session.post(
            url,
            params={
                "tenant_id": tenant_id, 
                "source_lang": source_lang, 
                "target_lang": target_lang},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    
    except requests.exceptions.RequestException as exc:
        logger.error(f"Failed to set language config for tenant {tenant_id}: {exc}")
        raise