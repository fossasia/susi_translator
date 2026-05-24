from flask import Flask, request, jsonify, abort
from flask_restx import Api, Resource, fields
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
import numpy as np
import threading
import requests
import logging
import yaml
import base64
import queue
import time
import uuid
import wave
import io
import os
# added for translation pipeline
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
# added for Redis storage
import redis
# added for WAV header wrapping
from faster_whisper import WhisperModel
import soundfile as sf
from dotenv import load_dotenv

# torch and whisper are imported lazily below — only when we actually need
# to load local models. This keeps the module importable in environments
# (and test runs) that delegate to a remote whisper.cpp server, where those
# heavy deps are not installed.

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)



def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: str) -> list:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


#flask with CORS configuration
app = Flask(__name__)
api = Api(app, version='1.0', title='Transcription and Translation API',
          description='Transcription and Translation API', doc='/swagger')

# CORS_ALLOWED_ORIGINS is a comma-separated list
# Use "*" explicitly if (and only if) you really want to allow any origin.
_cors_origins = _env_csv(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:5040,http://127.0.0.1:5040",
)
CORS(app, resources={r"/*": {"origins": _cors_origins}})
logger.info(f"CORS allowed origins: {_cors_origins}")



#whisper backend configuration

# We either use a local in-code model or access a whisper.cpp server.
use_whisper_server = _env_bool('WHISPER_SERVER_USE', False)

# Two distinct env vars so a power user can pick a fast model for high load
# and a smart model for low load without collapsing them onto one variable.
# Backwards compat: if the legacy single WHISPER_MODEL is set, it is used as
# the default for both unless the more specific variables are also set.
_legacy_model = os.getenv('WHISPER_MODEL')
model_fast_name = os.getenv('WHISPER_MODEL_FAST', _legacy_model or 'small')    # 244M
model_smart_name = os.getenv('WHISPER_MODEL_SMART', _legacy_model or 'medium')  # 769M

# Detect hardware compatibility. We only need torch when loading local
# models, so device detection is deferred to the lazy-import branch below.
device = None

# Whisper.cpp server URL. We expose the BASE URL in env (no path), and append
# the endpoint path (e.g. /inference) at call time.
whisper_server = os.getenv('WHISPER_SERVER', 'http://localhost:8007').rstrip('/')

# Models are only loaded when we are NOT using the whisper.cpp server.
model_fast = None
model_smart = None

if use_whisper_server:
    logger.info(f"Whisper backend: server at {whisper_server}/inference")
else:
    # Lazy imports: torch and whisper are heavyweight optional deps. Only
    # import them when we actually need to load a local model.
    import torch  # noqa: WPS433

    device = os.getenv('WHISPER_DEVICE', 'cuda' if torch.cuda.is_available() else 'cpu')
    # faster-whisper/CTranslate2 uses 'cuda' not 'gpu'; normalize the alias so .env WHISPER_DEVICE=gpu works
    if device == 'gpu':
        device = 'cuda'
    logger.info(f"Hardware detection: using {device}")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    models_path = os.path.join(script_dir, 'models')
    # faster-whisper uses compute_type instead of in_memory; int8 for cpu, float16 for cuda
    compute_type = 'float16' if device == 'cuda' else 'int8'
    if os.path.exists(os.path.join(models_path, model_fast_name)):
        model_fast = WhisperModel(model_fast_name, device=device, compute_type=compute_type, download_root=models_path)
    else:
        model_fast = WhisperModel(model_fast_name, device=device, compute_type=compute_type)
    if os.path.exists(os.path.join(models_path, model_smart_name)):
        model_smart = WhisperModel(model_smart_name, device=device, compute_type=compute_type, download_root=models_path)
    else:
        model_smart = WhisperModel(model_smart_name, device=device, compute_type=compute_type)

# load NLLB-200 translation model for multilingual support
# facebook/nllb-200-distilled-600M is used as default
nllb_model_name = os.getenv('NLLB_MODEL', 'facebook/nllb-200-distilled-600M')
nllb_tokenizer = AutoTokenizer.from_pretrained(nllb_model_name)
# device may be None in whisper-server mode; fall back to cpu for NLLB
_nllb_device = device or 'cpu'
nllb_model = AutoModelForSeq2SeqLM.from_pretrained(nllb_model_name).to(_nllb_device)
nllb_model.eval()
logger.info(f"NLLB-200 translation model loaded: {nllb_model_name}")

# in-memory storage for transcripts
# transcriptd is kept as fallback in case Redis is unavailable
transcriptd = {}  # should be a dictionary of dictionaries; the key is the tenant_id and the value is a dictionary with the chunk_id as key and the transcript as value
audio_stack = queue.Queue()  # is this a fifo queue? yes, it is, a FILO queue would be LifoQueue

# Single shared lock guarding ALL reads and writes to transcriptd. Must NEVER
# be `threading.Lock()` re-instantiated inline (that pattern provides no
# mutual exclusion at all).
transcripts_lock = threading.Lock()

# Redis replaces the clean_old_transcripts logic ,TTL is set per key instead
redis_client = None
try:
    redis_client = redis.Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        db=int(os.getenv('REDIS_DB', 0)),
        decode_responses=True
    )
    redis_client.ping()
    logger.info("Redis connection established")
except Exception:
    logger.warning("Redis unavailable; falling back to in-memory transcriptd dict")
    redis_client = None

# TTL for transcripts in Redis
REDIS_TRANSCRIPT_TTL = 2*60*60

# Per-source "latest session" registry.
# Each grabber run calls POST /session?source=<mic|file|url|stdin> at startup;
# the server mints a fresh tenant_id (uuid) and remembers it as the latest
# tenant_id for that source along with a creation timestamp. Read endpoints
# accept ?source=<name> as a convenience that resolves to the latest active
# tenant_id for that source, so the user never has to type or remember the
# uuid in curl commands. Stale sessions (older than SESSION_TTL_SECONDS)
# are evicted on resolve.
VALID_SOURCES = {"mic", "file", "url", "stdin"}
latest_session_by_source = {s: None for s in VALID_SOURCES}  # source -> (tenant_id, created_ts) or None
session_lock = threading.Lock()

# How long a per-source "latest session" pointer remains valid without
# anyone refreshing it. Two hours by default; matches the transcript TTL.
SESSION_TTL_SECONDS = int(os.getenv('SESSION_TTL_SECONDS', '7200'))

# whisper language code to NLLB-200 BCP-47 language tag mapping
# loaded once at startup from lang_map.yaml; the global is reused on every translation call
def _load_lang_map() -> dict:
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lang_map.yaml')
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    return config.get('whisper_to_nllb_lang', {})

WHISPER_TO_NLLB_LANG = _load_lang_map()

#Small helpers

def _parse_int_arg(args, name: str, default: int = None, required: bool = False) -> int:
    """
    Parse a query-string argument as an int. On invalid input, abort with HTTP
    400 instead of letting `int()` raise and be turned into a 500.

    Returns ``default`` if the argument is missing and not required.
    """
    raw = args.get(name)
    if raw is None or raw == "":
        if required:
            abort(400, f"Missing required query parameter: {name}")
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        abort(400, f"Query parameter {name!r} must be an integer, got {raw!r}")


def _chunk_id_int(k):
    """
    Best-effort int() of a chunk_id. Returns ``None`` for keys that cannot
    be interpreted as integers, so callers can defensively skip them
    rather than crashing the endpoint with a 500.

    The worker only ever stores numeric millisecond timestamps as
    chunk_ids, but the public ``POST /transcribe`` API does not validate
    that constraint; a misbehaving client can still slip a non-numeric
    id into ``transcriptd``.
    """
    try:
        return int(k)
    except (TypeError, ValueError):
        return None


def _numeric_sorted_keys(transcripts, reverse: bool = False) -> list:
    """
    Return the chunk_ids of ``transcripts`` sorted numerically, skipping
    any that can't be parsed as ints. Used by every endpoint that does
    "first" / "latest" / range-filtered lookups.
    """
    pairs = []
    for k in transcripts.keys():
        n = _chunk_id_int(k)
        if n is not None:
            pairs.append((n, k))
    pairs.sort(reverse=reverse)
    return [k for _, k in pairs]


def _in_chunk_range(k, fromid: int, untilid: int) -> bool:
    """``True`` iff ``k`` parses to an int and lies within [fromid, untilid]."""
    n = _chunk_id_int(k)
    return n is not None and fromid <= n <= untilid


def _resolve_tenant(args, default='0000'):
    """
    Resolve which tenant_id a read request is targeting.

    Priority:
      1. Explicit ?tenant_id=<id> wins (covers manual override / debugging).
      2. ?source=<mic|file|url|stdin> resolves to the most recently
         registered, non-expired session for that source. An unknown
         source value aborts with HTTP 400 so client typos surface
         loudly instead of masquerading as "no transcripts yet". A known
         source with no active session returns None so the caller can
         short-circuit with an empty response.
      3. Fall back to ``default`` (legacy behaviour).

    Note: a None return for a known source is intentionally
    indistinguishable from "session expired"; both result in an empty
    transcript response. If you need a hard 404 for "no session yet",
    add a separate endpoint rather than overloading this resolver.
    """
    explicit = args.get('tenant_id')
    if explicit:
        return explicit
    source = args.get('source')
    if source:
        if source not in VALID_SOURCES:
            abort(
                400,
                f"Invalid source '{source}'. "
                f"Must be one of: {sorted(VALID_SOURCES)}.",
            )
        now = time.time()
        with session_lock:
            entry = latest_session_by_source.get(source)
            if entry is None:
                return None
            tenant_id, created_ts = entry
            if now - created_ts > SESSION_TTL_SECONDS:
                # Expire stale session pointer.
                latest_session_by_source[source] = None
                return None
            return tenant_id
    return default


def _pcm_int16_to_wav_bytes(pcm: np.ndarray, sample_rate: int = 16000) -> bytes:
    """
    Wrap a mono 16-bit PCM numpy array in a minimal RIFF/WAV container so it
    can be POSTed to whisper.cpp's /inference endpoint, which insists on a
    real audio file (raw PCM bytes will be rejected).
    """
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.astype(np.int16, copy=False).tobytes())
    return buf.getvalue()


def _whisper_server_transcribe(audio_int16: np.ndarray) -> dict:
    """
    POST a single chunk to whisper.cpp's /inference endpoint and return its
    JSON-decoded body. Raises requests.RequestException on transport errors.
    """
    wav_bytes = _pcm_int16_to_wav_bytes(audio_int16)
    files = {'file': ('audio.wav', wav_bytes, 'audio/wav')}
    data = {'response_format': 'json'}
    inference_url = whisper_server + '/inference'
    response = requests.post(inference_url, files=files, data=data, timeout=60)
    response.raise_for_status()
    return response.json()


def nllb_translate(text, src_lang_whisper, tgt_lang_nllb):
    # translate text from source language to target language using NLLB-200
    src_lang_nllb = WHISPER_TO_NLLB_LANG.get(src_lang_whisper, 'eng_Latn')
    if src_lang_nllb == tgt_lang_nllb:
        # no translation needed if source and target are the same language
        return text
    # reuse the already-loaded nllb_tokenizer; reinitializing per call adds 1-2s per chunk
    nllb_tokenizer.src_lang = src_lang_nllb
    inputs = nllb_tokenizer(text, return_tensors='pt', padding=True).to(_nllb_device)
    target_lang_id = nllb_tokenizer.convert_tokens_to_ids(tgt_lang_nllb)
    # reducing memory overhead and speeding up generation vs. no context manager
    import torch  # noqa: WPS433  (already imported above when use_whisper_server=False)
    with torch.inference_mode():
        translated_tokens = nllb_model.generate(
            **inputs,
            forced_bos_token_id=target_lang_id,
            max_length=512
        )
    return nllb_tokenizer.batch_decode(translated_tokens, skip_special_tokens=True)[0]


def redis_store_transcript(tenant_id, chunk_id, original, translated, source_lang, target_lang):
    # store both original and translated transcript in Redis as a hash
    # key format: transcript:{tenant_id}:{chunk_id}
    key = f"transcript:{tenant_id}:{chunk_id}"
    redis_client.hset(key, mapping={
        'original': original,
        'translated': translated,
        'source_lang': source_lang,
        'target_lang': target_lang
    })
    redis_client.expire(key, REDIS_TRANSCRIPT_TTL)


def redis_get_transcript(tenant_id, chunk_id):
    # retrieve transcript hash from Redis for a given tenant_id and chunk_id
    key = f"transcript:{tenant_id}:{chunk_id}"
    return redis_client.hgetall(key)


def redis_list_transcript_keys(tenant_id):
    # list all chunk_ids stored in Redis for a given tenant_id
    # uses pattern scan instead of keys to avoid blocking in production
    pattern = f"transcript:{tenant_id}:*"
    return [k.split(":")[-1] for k in redis_client.scan_iter(pattern)]


# ---------------------------------------------------------------------------
# Audio worker
# ---------------------------------------------------------------------------

def _next_payload():
    """
    Pull the next audio payload from ``audio_stack``, dropping any superseded
    duplicates so we only transcribe the latest version of each
    (tenant_id, chunk_id).

    Concurrency / accounting:
      - For every entry returned from this function the caller MUST eventually
        call ``audio_stack.task_done()`` exactly once (typically in a finally
        block). Entries that this function discards because a newer one is
        already queued are marked ``task_done()`` here so the queue's
        unfinished_tasks counter stays correct (``audio_stack.join()`` works).
      - The internal ``audio_stack.queue`` deque is scanned under
        ``audio_stack.mutex`` so concurrent ``put``/``get`` cannot mutate it
        while we iterate.
    """
    tenant_id, chunk_id, audiob64, source_type = audio_stack.get()
    while True:
        with audio_stack.mutex:
            has_newer = any(
                t == tenant_id and c == chunk_id
                for (t, c, _, _s) in audio_stack.queue
            )
        if not has_newer:
            return tenant_id, chunk_id, audiob64, source_type
        # Current entry is stale; discard it (correctly accounted) and grab
        # the next one from the head.
        audio_stack.task_done()
        tenant_id, chunk_id, audiob64, source_type = audio_stack.get()


# Process audio data
def process_audio():
    while True:
        tenant_id, chunk_id, audiob64, source_type = _next_payload()
        logger.debug(f"Queue length: {audio_stack.qsize()}")
        try:
            # Convert audio bytes to a writable NumPy array
            audio_data = base64.b64decode(audiob64)
            audio_int16 = np.frombuffer(audio_data, dtype=np.int16)

            if audio_int16.size == 0:
                logger.warning(f"Invalid audio data for chunk_id {chunk_id}")
                continue

            audio_float32 = audio_int16.astype(np.float32) / 32768.0
            if np.isnan(audio_float32).any():
                logger.warning(f"NaN values in audio array for chunk_id {chunk_id}")
                continue

            #Run transcription via the configured backend
            qsize = audio_stack.qsize()
            if use_whisper_server:
                # Whisper.cpp server doesn't expose a fast/smart distinction;
                # send everything to /inference. The server itself decides
                # how to schedule it.
                try:
                    server_json = _whisper_server_transcribe(audio_int16)
                    result = {
                        'text': server_json.get('text', ''),
                        # whisper.cpp /inference returns detected language in the 'language' field
                        'language': server_json.get('language', 'en')
                    }
                except requests.RequestException as exc:
                    logger.error(f"Whisper server error for chunk_id {chunk_id}: {exc}")
                    continue
            else:
                # faster-whisper transcribe returns (segments, info); join segments for full text
                if qsize > 20:
                    segments, info = model_fast.transcribe(audio_float32, temperature=0, beam_size=5)
                else:
                    segments, info = model_smart.transcribe(audio_float32, temperature=0, beam_size=5)
                result = {'text': ' '.join(s.text for s in segments), 'language': info.language}

            transcript = (result.get('text') or '').strip()
            # detected_lang is provided by Whisper; used for NLLB-200 translation
            detected_lang = result.get('language', 'en')

            #Validate and store
            if is_valid(transcript):

                # full translated text to DEBUG to avoid leaking sensitive content in production
                # logs. Set LOG_TRANSLATED_AT_INFO=true in .env to restore INFO-level logging.
                log_translated_at_info = os.getenv('LOG_TRANSLATED_AT_INFO', 'false') == 'true'
                logger.info(f"VALID transcript for chunk_id {chunk_id}: {transcript}")

                # translate the transcript using NLLB-200
                # target language is read per tenant from Redis config if available, else defaults to English
                target_lang_nllb = 'eng_Latn'
                if redis_client:
                    tenant_config = redis_client.hgetall(f"tenant:{tenant_id}:config")
                    target_lang_nllb = tenant_config.get('target_lang', 'eng_Latn')
                translated_transcript = nllb_translate(transcript, detected_lang, target_lang_nllb)
                if log_translated_at_info:
                    logger.info(f"TRANSLATED transcript for chunk_id {chunk_id}: {translated_transcript}")
                else:
                    logger.debug(f"TRANSLATED transcript for chunk_id {chunk_id}: {translated_transcript}")

                # lock instance inline — a new lock() object is never shared across threads
                with transcripts_lock:
                    # we must distinguish between the case where the chunk_id is already in the transcripts
                    # this can happen quite often because the client will generate a new chunk_id only when
                    # the recorded audio has silence. So all chunks are those pieces with speech without a pause.

                    if redis_client:
                        # store both original and translated transcript in Redis with auto-expiry
                        redis_store_transcript(tenant_id, chunk_id, transcript, translated_transcript, detected_lang, target_lang_nllb)
                    else:
                        # store in in-memory transcriptd dict if Redis is unavailable
                        # get the current transcripts for the tenant_id
                        transcripts = transcriptd.get(tenant_id, None)
                        # if the current transcripts are None, we create a new dictionary for the tenant_id
                        if not transcripts:
                            transcripts = {}
                            transcriptd[tenant_id] = transcripts

                        # get the current transcript for the chunk_id
                        current_transcript = transcripts.get(chunk_id, None)
                        # if the current transcript is not None, we append the new transcript to the current one
                        if current_transcript:
                            # here we do NOT append the new transcript to the current one becuase it is transcripted
                            # from the same audio data that has been transcripted before.
                            # The audio was appended by the client
                            # We just overwrite the current transcript with the new one.
                            current_transcript['transcript'] = transcript
                            current_transcript['translated'] = translated_transcript
                        else:
                            # if the current transcript is None, we create a new entry with the new transcript
                            transcripts[chunk_id] = {'transcript': transcript, 'translated': translated_transcript}
            else:
                logger.warning(f"INVALID transcript for chunk_id {chunk_id}: {transcript}")

            # clean old transcripts
            # note: when Redis is active this is a no-op since Redis TTL handles expiry automatically
            clean_old_transcripts()

            # Mark the task as done
        except Exception:
            logger.error(f"Error processing audio chunk {chunk_id}", exc_info=True)
        finally:
            audio_stack.task_done()


# Check if the transcript is valid: Contains at least one ASCII character and no forbidden words
def is_valid(transcript):
    transcript_lower = transcript.lower()
    # Check for at least one ASCII character with a code < 128 and code > 32 (we omit space in this case)
    has_ascii_char = any(32 < ord(char) < 128 for char in transcript)

    # Check for forbidden words (case insensitive)
    forbidden_phrases = {"thank you", "bye!", "thanks for watching", "click, click", "click click", "cough cough", "뉴", "스", "김", "수", "근", "입", "니", "다"}
    contains_forbidden_phrases = any(word in transcript_lower for word in forbidden_phrases)
    forbidden_strings = {"eh.", "you", "bye.", "it's fine"}
    is_forbidden_string = any(word == transcript_lower for word in forbidden_strings)

    # check if the transcript has words which are longer than 40 characters
    contains_long_words = any(len(word) > 40 for word in transcript.split())

    # Return true only if both conditions are met
    return has_ascii_char and not contains_forbidden_phrases and not is_forbidden_string and not contains_long_words


# Clean old transcripts: remove all chunks older than two hours and any tenants
# that become empty as a result. Concurrency-safe: takes the shared
# transcripts_lock and iterates over a snapshot so concurrent mutation in
# process_audio cannot raise "dictionary changed size during iteration".
def clean_old_transcripts():
    # when Redis is active, TTL handles expiry automatically so this function is skipped
    if redis_client:
        return
    current_time_ms = int(time.time() * 1000)
    two_hours_ago_ms = current_time_ms - (2 * 60 * 60 * 1000)

    with transcripts_lock:
        empty_tenants = []
        # Snapshot the tenant ids before iterating; we mutate inside the loop.
        for tenant_id in list(transcriptd.keys()):
            transcripts = transcriptd.get(tenant_id)
            if not transcripts:
                empty_tenants.append(tenant_id)
                continue

            # Snapshot chunk ids; some chunk_ids may be non-numeric in
            # principle, so we defensively skip those rather than crashing
            # the worker thread.
            stale_chunks = []
            for chunk_id in list(transcripts.keys()):
                try:
                    if int(chunk_id) < two_hours_ago_ms:
                        stale_chunks.append(chunk_id)
                except (TypeError, ValueError):
                    # Unknown id format -> leave it alone.
                    continue

            for chunk_id in stale_chunks:
                transcripts.pop(chunk_id, None)

            if not transcripts:
                empty_tenants.append(tenant_id)

        for tenant_id in empty_tenants:
            transcriptd.pop(tenant_id, None)


# merge all transcripts into one and split them into sentences
def merge_and_split_transcripts(transcripts):
    """
    Take a ``{chunk_id: {'transcript': str}}`` mapping and produce a new
    mapping of the same shape where text has been re-flowed onto sentence
    boundaries (``.``, ``!``, ``?``).

    The output preserves chunk_ids from the input (a subset of them: only
    the chunk_ids at which a sentence boundary actually falls, plus the
    last chunk for any trailing fragment). Values are dicts with a
    ``'transcript'`` key so callers can use the same access pattern as
    the underlying ``transcriptd`` store.

    The previous implementation called ``.strip()`` directly on values,
    which crashed at runtime because values are dicts, not strings; this
    rewrite handles the dict shape correctly.
    """
    sec = ".!?"
    merged = ""
    result = {}
    keys = list(transcripts.keys())
    for key in keys:
        raw = transcripts[key]
        text = (raw.get('transcript') if isinstance(raw, dict) else str(raw or '')).strip()

        if not merged:
            merged += text
        else:
            if len(text) > 1:
                merged += " " + text[0].lower() + text[1:]
            elif text:
                merged += " " + text

        # Drain every complete sentence currently in `merged` onto this key.
        while any(char in sec for char in merged):
            index = next(i for i, c in enumerate(merged) if c in sec)
            head = merged[:index + 1].strip()
            head = head[0].capitalize() + head[1:] if len(head) > 1 else head
            existing = result.get(key, {}).get('transcript')
            if existing:
                result[key] = {'transcript': existing + " " + head}
            else:
                result[key] = {'transcript': head}
            merged = merged[index + 1:].strip()

    # Any leftover (no terminal punctuation) attaches to the final input key.
    if merged and keys:
        last_key = keys[-1]
        existing = result.get(last_key, {}).get('transcript')
        if existing:
            result[last_key] = {'transcript': existing + " " + merged}
        else:
            result[last_key] = {'transcript': merged}

    return result


# Define models for API documentation
transcribe_input_model = api.model('TranscribeInput', {
    'audio_b64': fields.String(required=True, description='Base64 encoded audio data'),
    'chunk_id': fields.String(required=True, description='ID of the audio chunk'),
    'tenant_id': fields.String(required=False, description='Tenant ID', default='0000'),
    # source_type is sent by the new AudioGrabber to indicate which AudioSource produced this chunk
    'source_type': fields.String(required=False, description='Audio source type: mic, file, or url', default='mic')
})

transcribe_response_model = api.model('TranscribeResponse', {
    'chunk_id': fields.String(description='ID of the audio chunk'),
    'tenant_id': fields.String(description='Tenant ID'),
    'status': fields.String(description='processing flag')
})

get_transcript_response_model = api.model('GetTranscriptResponse', {
    'chunk_id': fields.String(description='ID of the audio chunk'),
    'transcript': fields.String(description='The transcribed text'),
    # translated field is returned alongside transcript when NLLB-200 translation is available
    'translated': fields.String(description='The translated text')
})

transcript_response_model = api.model('TranscriptResponse', {
    'chunk_id': fields.String(description='ID of the audio chunk'),
    'transcript': fields.String(description='The transcribed text'),
})

list_transcripts_response_model = api.model('ListTranscriptsResponse', {
    'transcripts': fields.List(fields.Nested(get_transcript_response_model), description='List of transcripts')
})

size_response_model = api.model('SizeResponse', {
    'size': fields.Integer(description='The number of transcripts')
})

session_input_model = api.model('SessionRequest', {
    'source': fields.String(
        required=True,
        description='Input source name; one of: mic, file, url, stdin',
        enum=sorted(VALID_SOURCES),
    ),
})

session_response_model = api.model('SessionResponse', {
    'tenant_id': fields.String(description='Server-minted tenant ID for this run'),
    'source': fields.String(description='Source name this session is registered under'),
})


@api.route('/session')
class Session(Resource):
    @api.expect(session_input_model)
    @api.response(200, 'Success', session_response_model)
    @api.response(400, 'Invalid source')
    def post(self):
        '''
        Start a new transcription session for an input source.

        The grabber calls this once per run, passing its source name
        (mic/file/url/stdin). The server mints a fresh tenant_id (uuid)
        and records it as the latest session for that source. Subsequent
        read requests using ?source=<name> resolve to this tenant_id, so
        the user never has to know or type the uuid in curl commands.
        '''
        try:
            data = request.get_json(force=True, silent=True) or {}
            source = data.get('source') or request.args.get('source')
            if source not in VALID_SOURCES:
                return {
                    "error": f"source must be one of {sorted(VALID_SOURCES)}",
                }, 400

            new_tenant_id = uuid.uuid4().hex
            with session_lock:
                latest_session_by_source[source] = (new_tenant_id, time.time())

            logger.info(f"New session for source={source}: tenant_id={new_tenant_id}")
            return {"tenant_id": new_tenant_id, "source": source}, 200
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Error in /session", exc_info=True)
            return {"error": str(e)}, 500


@api.route('/transcribe')
class Transcribe(Resource):
    @api.expect(transcribe_input_model)
    @api.response(200, 'Success', transcribe_response_model)
    @api.response(404, 'Transcript Not Found')
    def post(self):
        '''Transcribe endpoint: Accepts base64-encoded audio data and queues it for transcription,
            the source_type specified as a query parameter or in the JSON body'''
        try:
            data = request.get_json(force=True, silent=True)
            if not data:
                return {"error": "No JSON payload received"}, 400

            audio_b64 = data.get('audio_b64')
            chunk_id = data.get('chunk_id')
            tenant_id = data.get('tenant_id', '0000')
            source_type = (
                request.args.get('source_type')
                or data.get('source_type')
                or 'mic'
            )

            if not audio_b64 or not chunk_id:
                return {"error": "Missing required fields"}, 400

            # push to processing queue with source_type so process_audio can log the origin
            audio_stack.put((tenant_id, chunk_id, audio_b64, source_type))

            return {
                "chunk_id": chunk_id,
                "tenant_id": tenant_id,
                "status": "processing",
                "source_type": source_type
            }, 200
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Error in /transcribe", exc_info=True)
            return {"error": str(e)}, 500


# source_type is passed as a query param, POST /transcribe?source_type=mic,file,url
@api.route('/get_transcript')
class GetTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin']},
        'chunk_id' : {'description': 'Chunk ID'},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False}
    })
    @api.response(200, 'Success', get_transcript_response_model)
    @api.response(404, 'Transcript Not Found')
    def get(self):
        '''Get transcript endpoint: Retrieve the transcript with translation for a given tenant_id and chunk_id'''
        tenant_id = _resolve_tenant(request.args)
        chunk_id = request.args.get('chunk_id')

        # fetch from Redis if available; fall back to in-memory transcriptd
        if redis_client:
            entry = redis_get_transcript(tenant_id, chunk_id)
            if entry:
                return jsonify({'chunk_id': chunk_id, 'transcript': entry.get('original', ''), 'translated': entry.get('translated', '')})
            else:
                return jsonify({'chunk_id': chunk_id, 'transcript': '', 'translated': ''})

        with transcripts_lock:
            t = dict(transcriptd.get(tenant_id, {}))
        if len(t) == 0:
            return jsonify({'chunk_id': '-1', 'transcript': '', 'translated': ''})
        else:
            sentences = request.args.get('sentences', default='false').strip().lower() == 'true'
            if sentences:
                t = merge_and_split_transcripts(t)
            if chunk_id in t:
                return jsonify({'chunk_id': chunk_id, 'transcript': t[chunk_id]['transcript'], 'translated': t[chunk_id].get('translated', '')})
            else:
                return jsonify({'chunk_id': chunk_id, 'transcript': '', 'translated': ''})


# @api.route('/get_first_transcript')
# class GetFirstTranscript(Resource):
#     @api.doc(params={
#         'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
#         'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin']},
#         'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
#         'from'     : {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'}
#     })
#     @api.response(200, 'Success', transcript_response_model)
#     @api.response(404, 'Transcript Not Found')
#     def get(self):
#         '''
#         Get first transcript endpoint: Retrieve the first transcript for a given tenant_id
#         '''
#         tenant_id = _resolve_tenant(request.args)
#         with transcripts_lock:
#             t = dict(transcriptd.get(tenant_id, {}))
#         if len(t) == 0:
#             return jsonify({'chunk_id': '-1', 'transcript': ''})
#         else:
#             sentences = request.args.get('sentences', default='false').strip().lower() == 'true'
#             if sentences:
#                 t = merge_and_split_transcripts(t)
#             fromid = _parse_int_arg(request.args, 'from', default=0)
#             first_chunk_id = next(
#                 (k for k in _numeric_sorted_keys(t) if _chunk_id_int(k) >= fromid),
#                 None,
#             )
#             if first_chunk_id is None:
#                 return jsonify({'chunk_id': '-1', 'transcript': ''})
#             first_transcript = t[first_chunk_id]['transcript']
#             return jsonify({'chunk_id': first_chunk_id, 'transcript': first_transcript})




# @api.route('/get_latest_transcript')
# class GetLatestTranscript(Resource):
#     @api.doc(params={
#         'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
#         'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin']},
#         'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
#         'until': {'description': 'End chunk ID (defaults to "now" in ms)', 'type': 'string'}
#     })
#     @api.response(200, 'Success', transcript_response_model)
#     @api.response(404, 'Transcript Not Found')
#     def get(self):
#         '''
#         Get latest transcript endpoint: Retrieve the latest transcript for a given tenant_id
#         '''
#         tenant_id = _resolve_tenant(request.args)
#         with transcripts_lock:
#             t = dict(transcriptd.get(tenant_id, {}))
#         if len(t) == 0:
#             return jsonify({'chunk_id': '-1', 'transcript': ''})
#         else:
#             sentences = request.args.get('sentences', default='false').strip().lower() == 'true'
#             if sentences:
#                 t = merge_and_split_transcripts(t)
#             untilid = _parse_int_arg(request.args, 'until', default=int(time.time() * 1000))
#             latest_chunk_id = next(
#                 (k for k in _numeric_sorted_keys(t, reverse=True) if _chunk_id_int(k) < untilid),
#                 None,
#             )
#             if latest_chunk_id is None:
#                 return jsonify({'chunk_id': '-1', 'transcript': ''})
#             latest_transcript = t[latest_chunk_id]['transcript']
#             return jsonify({'chunk_id': latest_chunk_id, 'transcript': latest_transcript})



# @api.route('/delete_transcript')
# class DeleteTranscript(Resource):
#     @api.doc(params={
#         'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
#         'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin']},
#         'chunk_id' : {'description': 'Chunk ID', 'type': 'string'}
#     })
#     @api.response(200, 'Success', transcript_response_model)
#     @api.response(404, 'Transcript Not Found')
#     def delete(self):
#         '''
#         Delete a transcript for a given tenant_id and chunk_id.

#         DELETE is the canonical method for this destructive operation.
#         '''
#         return self._delete()

#     @api.doc(params={
#         'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
#         'source':    {'description': 'Resolve to the latest session for a source.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin']},
#         'chunk_id' : {'description': 'Chunk ID', 'type': 'string'}
#     })
#     @api.response(200, 'Success', transcript_response_model)
#     @api.deprecated
#     def get(self):
#         '''
#         DEPRECATED: use DELETE /delete_transcript instead. GET on a
#         destructive endpoint violates the HTTP "GET is safe" contract and
#         is incompatible with caching proxies. Kept for backward compat.
#         '''
#         logger.warning("Deprecated GET /delete_transcript called; use DELETE.")
#         return self._delete()

#     def _delete(self):
#         tenant_id = _resolve_tenant(request.args)
#         chunk_id = request.args.get('chunk_id')
#         with transcripts_lock:
#             stored = transcriptd.get(tenant_id, {})
#             if chunk_id in stored:
#                 entry = stored.pop(chunk_id, None)
#                 return jsonify({'chunk_id': chunk_id, 'transcript': entry['transcript']})
#         return jsonify({'chunk_id': chunk_id, 'transcript': ''})


@api.route('/list_transcripts')
class ListTranscripts(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin']},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'from'     : {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'},
        'until'    : {'description': 'End chunk ID (defaults to "now" in ms)', 'type': 'string'}
    })
    @api.response(200, 'Success', list_transcripts_response_model)
    @api.response(404, 'Transcript Not Found')
    def get(self):
        '''
        list all transcripts for a given tenant_id
        '''
        tenant_id = _resolve_tenant(request.args)
        sentences = request.args.get('sentences', default='false').strip().lower() == 'true'
        fromid = _parse_int_arg(request.args, 'from', default=0)
        untilid = _parse_int_arg(request.args, 'until', default=int(time.time() * 1000))

        # fetch all chunk_ids from Redis and filter by from/until range
        if redis_client:
            chunk_ids = redis_list_transcript_keys(tenant_id)
            result = {}
            for chunk_id in chunk_ids:
                if _in_chunk_range(chunk_id, fromid, untilid):
                    result[chunk_id] = redis_get_transcript(tenant_id, chunk_id)
            return jsonify(result)

        with transcripts_lock:
            t = dict(transcriptd.get(tenant_id, {}))
        if sentences:
            t = merge_and_split_transcripts(t)
        result = {k: v for k, v in t.items() if _in_chunk_range(k, fromid, untilid)}
        return jsonify(result)

#Healthcheck endpoint
@api.route('/transcripts_size')
class TranscriptsSize(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin']},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'from'     : {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'},
        'until'    : {'description': 'End chunk ID (defaults to "now" in ms)', 'type': 'string'}
    })
    @api.response(200, 'Success', size_response_model)
    @api.response(404, 'Transcript Not Found')
    def get(self):
        '''
        get the size of the transcripts for a given tenant_id
        '''
        tenant_id = _resolve_tenant(request.args)
        sentences = request.args.get('sentences', default='false').strip().lower() == 'true'
        fromid = _parse_int_arg(request.args, 'from', default=0)
        untilid = _parse_int_arg(request.args, 'until', default=int(time.time() * 1000))

        # count matching chunk_ids from Redis if available
        if redis_client:
            chunk_ids = redis_list_transcript_keys(tenant_id)
            count = sum(1 for k in chunk_ids if _in_chunk_range(k, fromid, untilid))
            return jsonify({'size': count})

        with transcripts_lock:
            t = dict(transcriptd.get(tenant_id, {}))
        if sentences:
            t = merge_and_split_transcripts(t)
        t = {k: v for k, v in t.items() if _in_chunk_range(k, fromid, untilid)}
        return jsonify({'size': len(t)})


# set language config endpoint
# source_lang should be a Whisper language code e.g. 'de'; target_lang should be NLLB BCP-47 e.g. 'eng_Latn'
@api.route('/set_language_config')
class SetLanguageConfig(Resource):
    @api.doc(params={
        'tenant_id'  : {'description': 'Tenant ID', 'default': '0000'},
        'source_lang': {'description': 'Source language code (Whisper format e.g. de, fr)', 'default': 'en'},
        'target_lang': {'description': 'Target language NLLB BCP-47 tag e.g. eng_Latn', 'default': 'eng_Latn'}
    })
    @api.response(200, 'Success')
    def post(self):
        '''
        set source and target language for a given tenant_id; used by NLLB-200 translation pipeline
        '''
        body = request.get_json(silent=True) or {}
        tenant_id   = body.get('tenant_id')   or request.args.get('tenant_id',   '0000')
        source_lang = body.get('source_lang') or request.args.get('source_lang', 'en')
        target_lang = body.get('target_lang') or request.args.get('target_lang', 'eng_Latn')
        if redis_client:
            redis_client.hset(f"tenant:{tenant_id}:config", mapping={
                'source_lang': source_lang,
                'target_lang': target_lang
            })
            return jsonify({'tenant_id': tenant_id, 'source_lang': source_lang, 'target_lang': target_lang})
        return {"error": "Redis unavailable; language config requires Redis"}, 503



# Audio worker auto-start
# The worker thread MUST be started at module-import time, not in
# ``if __name__ == '__main__':``. Otherwise running under any WSGI server
# (gunicorn, uwsgi, ``flask run``) leaves the queue with no consumer and
# ``POST /transcribe`` requests pile up forever.
#
# The TRANSCRIBE_AUTOSTART_WORKER env var is honoured for the test suite,
# which sets it to "false" so a real worker doesn't try to drain queued
# items (and call out to whisper.cpp) during ``test_transcribe_*``.
_worker_thread = None
_worker_lock = threading.Lock()


def _start_worker_once():
    """Start the audio-worker thread exactly once per process. Idempotent."""
    global _worker_thread
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return _worker_thread
        _worker_thread = threading.Thread(
            target=process_audio,
            name="audio-worker",
            daemon=True,
        )
        _worker_thread.start()
        logger.info("Audio worker thread started")
        return _worker_thread


if _env_bool('TRANSCRIBE_AUTOSTART_WORKER', True):
    _start_worker_once()



#Entrypoint


if __name__ == '__main__':
    # Server bind config is env-driven so the defaults are SAFE
    host = os.getenv('FLASK_HOST', '127.0.0.1')
    port = int(os.getenv('FLASK_PORT', '5040'))
    debug = _env_bool('FLASK_DEBUG', False)

    if debug and host not in ('127.0.0.1', 'localhost'):
        logger.warning(
            "FLASK_DEBUG=true with host=%s exposes the Werkzeug debugger to "
            "the network. This is remote-code-execution. Set FLASK_HOST=127.0.0.1 "
            "or disable debug.",
            host,
        )

    app.run(host=host, port=port, debug=debug, use_reloader=False)