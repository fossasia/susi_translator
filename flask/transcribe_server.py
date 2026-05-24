from flask import Flask, request, jsonify, abort
from flask_restx import Api, Resource, fields
from flask_cors import CORS
from flask_sock import Sock
from werkzeug.exceptions import HTTPException
import numpy as np
import threading
import requests
import logging
import base64
import queue
import time
import uuid
import wave
import io
import os
from dotenv import load_dotenv

# torch and whisper are imported lazily below — only when we actually need
# to load local models. This keeps the module importable in environments
# (and test runs) that delegate to a remote whisper.cpp server, where those
# heavy deps are not installed.

# Load environment variables from .env file
load_dotenv()

from websocket_manager import emit_stream_update

from stt_config import STT_NUM_WORKERS, STT_MAX_QUEUE_SIZE, STT_QUEUE_OVERFLOW_POLICY
from stt_ingest import try_enqueue

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers for env-var parsing
# ---------------------------------------------------------------------------

def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: str) -> list:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Flask + CORS configuration (env-driven)
# ---------------------------------------------------------------------------

app = Flask(__name__)
api = Api(app, version='1.0', title='Transcription API',
          description='A simple Transcription API', doc='/swagger')
CORS(app, resources={r"/*": {"origins": "*"}})
sock = Sock(app)

_worker_started = False
_worker_lock = threading.Lock()


def ensure_process_audio_thread():
    """Start the STT worker pool once (HTTP + WebSocket ingestion)."""
    global _worker_started
    if _worker_started:
        return
    with _worker_lock:
        if _worker_started:
            return
        for i in range(STT_NUM_WORKERS):
            threading.Thread(
                target=process_audio,
                name=f"stt-worker-{i}",
                daemon=True,
            ).start()
        _worker_started = True
        logger.info(
            "STT workers started: num=%s max_queue=%s overflow_policy=%s "
            "(set STT_NUM_WORKERS=1 if your Whisper backend is not thread-safe)",
            STT_NUM_WORKERS,
            STT_MAX_QUEUE_SIZE,
            STT_QUEUE_OVERFLOW_POLICY,
        )


@app.before_request
def _ensure_stt_worker():
    ensure_process_audio_thread()


# CORS_ALLOWED_ORIGINS is a comma-separated list. Default is local-dev only.
# Use "*" explicitly if (and only if) you really want to allow any origin.
_cors_origins = _env_csv(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:5040,http://127.0.0.1:5040",
)
CORS(app, resources={r"/*": {"origins": _cors_origins}})
logger.info(f"CORS allowed origins: {_cors_origins}")


# ---------------------------------------------------------------------------
# Whisper backend configuration
# ---------------------------------------------------------------------------

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
    import torch  # noqa: WPS433  (deferred import is intentional)
    import whisper  # noqa: WPS433  (deferred import is intentional)

    device = os.getenv('WHISPER_DEVICE', 'cuda' if torch.cuda.is_available() else 'cpu')
    logger.info(f"Hardware detection: using {device}")

    # Download (or load) two whisper models. If the download via the whisper
    # library is not possible (offline / firewalled), prefer locally stored
    # models from <script_dir>/models/<name>.pt.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    models_path = os.path.join(script_dir, 'models')
    if os.path.exists(os.path.join(models_path, model_fast_name + ".pt")):
        model_fast = whisper.load_model(model_fast_name, device=device, in_memory=True, download_root=models_path)
    else:
        model_fast = whisper.load_model(model_fast_name, device=device, in_memory=True)
    if os.path.exists(os.path.join(models_path, model_smart_name + ".pt")):
        model_smart = whisper.load_model(model_smart_name, device=device, in_memory=True, download_root=models_path)
    else:
        model_smart = whisper.load_model(model_smart_name, device=device, in_memory=True)

# In-memory storage for transcripts
transcriptd = {}  # key: tenant_id -> dict of chunk_id -> {"transcript": str}
audio_stack = queue.Queue(maxsize=STT_MAX_QUEUE_SIZE)

_transcript_lock = threading.Lock()
_dequeue_coalesce_lock = threading.Lock()


def _unpack_audio_item(item):
    """Normalize to (tenant_id, chunk_id, audio_b64, session_id, enqueue_monotonic_ts)."""
    if isinstance(item, tuple) and len(item) == 5:
        return item[0], item[1], item[2], item[3], float(item[4])
    if isinstance(item, tuple) and len(item) == 4:
        t, c, a, s = item
        return t, c, a, s, time.monotonic()
    tenant_id, chunk_id, audiob64 = item
    return tenant_id, chunk_id, audiob64, None, time.monotonic()


def _queue_coalesce_key(entry):
    ln = len(entry)
    if ln >= 5:
        return entry[0], entry[1], entry[3]
    if ln == 4:
        return entry[0], entry[1], entry[3]
    return entry[0], entry[1], None


# Process audio data
def process_audio():
    while True:
        coalesced_gets = 0
        chunk_id = "-"
        session_id = None
        try:
            with _dequeue_coalesce_lock:
                item = audio_stack.get()
                coalesced_gets += 1
                tenant_id, chunk_id, audiob64, session_id, enqueue_ts = _unpack_audio_item(item)
                key = (tenant_id, chunk_id, session_id)
                logger.debug("STT dequeue qsize=%s key=%s", audio_stack.qsize(), key)
                # Drop superseded payloads: if a newer entry for the same key exists, advance to it.
                # Scan from the tail — duplicates from live streaming are usually near the end (O(1) typical).
                while audio_stack.qsize() > 0:
                    found_same = False
                    try:
                        n = audio_stack.qsize()
                        for i in range(n - 1, -1, -1):
                            next_entry = audio_stack.queue[i]
                            if _queue_coalesce_key(next_entry) == key:
                                found_same = True
                                break
                    except (IndexError, ValueError):
                        break
                    if not found_same:
                        break
                    tenant_id, chunk_id, audiob64, session_id, enqueue_ts = _unpack_audio_item(
                        audio_stack.get()
                    )
                    coalesced_gets += 1
                    key = (tenant_id, chunk_id, session_id)

            # Convert audio bytes to a writable NumPy array

    def _load_whisper_model(name: str):
        local_pt = os.path.join(models_path, name + ".pt")
        if os.path.exists(local_pt):
            return whisper.load_model(name, device=device, in_memory=True, download_root=models_path)
        return whisper.load_model(name, device=device, in_memory=True)

    logger.info(f"Whisper backend: local models fast={model_fast_name}, smart={model_smart_name}")
    model_fast = _load_whisper_model(model_fast_name)
    model_smart = _load_whisper_model(model_smart_name)


# ---------------------------------------------------------------------------
# Shared in-memory state
# ---------------------------------------------------------------------------

# transcripts:  tenant_id -> { chunk_id -> {'transcript': str} }
transcriptd = {}
# Single shared lock guarding ALL reads and writes to transcriptd. Must NEVER
# be `threading.Lock()` re-instantiated inline (that pattern provides no
# mutual exclusion at all).
transcripts_lock = threading.Lock()

# FIFO queue of pending audio chunks awaiting transcription.
audio_stack = queue.Queue()

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


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

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
    tenant_id, chunk_id, audiob64 = audio_stack.get()
    while True:
        with audio_stack.mutex:
            has_newer = any(
                t == tenant_id and c == chunk_id
                for (t, c, _) in audio_stack.queue
            )
        if not has_newer:
            return tenant_id, chunk_id, audiob64
        # Current entry is stale; discard it (correctly accounted) and grab
        # the next one from the head.
        audio_stack.task_done()
        tenant_id, chunk_id, audiob64 = audio_stack.get()


def process_audio():
    while True:
        tenant_id, chunk_id, audiob64 = _next_payload()
        logger.debug(f"Queue length: {audio_stack.qsize()}")
        try:
            # --- Decode + sanity-check the incoming audio ------------------
            audio_data = base64.b64decode(audiob64)
            audio_int16 = np.frombuffer(audio_data, dtype=np.int16)

            # Convert audio bytes to a writable NumPy array with int16 dtype
            audio_array = np.frombuffer(audio_data, dtype=np.int16)

            # Convert int16 to float32 and normalize
            audio_array = audio_array.astype(np.float32) / 32768.0

            # Ensure the array is not empty
            if audio_array.size == 0:
                logger.warning(f"Invalid audio data for chunk_id {chunk_id}")
                continue

            # Ensure no NaN values in audio array
            if np.isnan(audio_array).any():
                logger.warning(f"NaN values in audio array for chunk_id {chunk_id}")
                continue

            # Convert to PyTorch tensor
            audio_tensor = torch.from_numpy(audio_array)

            if use_whisper_server:
                files = {'file': ('audio.wav', audio_array, 'application/octet-stream')}
                data = {'response_format': 'json'}
                response = requests.post(whisper_server, files=files, data=data)
                if response.status_code != 200:
                    logger.error(
                        "Whisper server error %s: %s",
                        response.status_code,
                        (response.text or "")[:200],
                    )
                    continue
                result = response.json()
                if not isinstance(result, dict) or "text" not in result:
                    logger.error("Unexpected whisper server JSON shape")
                    continue
            elif audio_stack.qsize() > 20:
                result = model_fast.transcribe(audio_tensor, temperature=0)
            else:
                result = model_smart.transcribe(audio_tensor, temperature=0)

            transcript = result["text"].strip()
            done_ts = time.monotonic()
            latency_ms = (done_ts - enqueue_ts) * 1000.0
            logger.info(
                "stt_latency_ms=%.1f chunk_id=%s session_id=%s qsize=%s workers=%s",
                latency_ms,
                chunk_id,
                session_id or "-",
                audio_stack.qsize(),
                STT_NUM_WORKERS,
            )
            if is_valid(transcript):
                logger.info(f"VALID transcript for chunk_id {chunk_id}: {transcript}")
                with _transcript_lock:
                    # we must distinguish between the case where the chunk_id is already in the transcripts
                    # this can happen quite often because the client will generate a new chunk_id only when
                    # the recorded audio has silence. So all chunks are those pieces with speech without a pause.

                    # get the current transcripts for the tenant_id
                    transcripts = transcriptd.get(tenant_id, None)
                    # if the current transcripts are None, we create a new dictionary for the tenant_id
            if audio_int16.size == 0:
                logger.warning(f"Invalid audio data for chunk_id {chunk_id}")
                continue

            audio_float32 = audio_int16.astype(np.float32) / 32768.0
            if np.isnan(audio_float32).any():
                logger.warning(f"NaN values in audio array for chunk_id {chunk_id}")
                continue

            # --- Run transcription via the configured backend --------------
            qsize = audio_stack.qsize()
            if use_whisper_server:
                # Whisper.cpp server doesn't expose a fast/smart distinction;
                # send everything to /inference. The server itself decides
                # how to schedule it.
                try:
                    result = _whisper_server_transcribe(audio_int16)
                except requests.RequestException as exc:
                    logger.error(f"Whisper server error for chunk_id {chunk_id}: {exc}")
                    continue
            else:
                # Local-model branch: torch was already imported at module
                # load time when use_whisper_server=False, so this is cheap.
                import torch  # noqa: WPS433  (already imported above)
                model = model_fast if qsize > 20 else model_smart
                audio_tensor = torch.from_numpy(audio_float32)
                result = model.transcribe(audio_tensor, temperature=0)

            transcript = (result.get('text') or '').strip()

            # --- Validate + store ----------------------------------------
            if is_valid(transcript):
                logger.info(f"VALID transcript for chunk_id {chunk_id}: {transcript}")
                with transcripts_lock:
                    transcripts = transcriptd.get(tenant_id)
                    if not transcripts:
                        transcripts = {}
                        transcriptd[tenant_id] = transcripts

                    current_transcript = transcripts.get(chunk_id)
                    if current_transcript:
                        # here we do NOT append the new transcript to the current one because it is transcribed
                        # from the same audio data that has been transcribed before.
                        # The audio was appended by the client!
                        # We just overwrite the current transcript with the new one.
                        current_transcript["transcript"] = transcript
                    else:
                        # if the current transcript is None, we create a new entry with the new transcript
                        transcripts[chunk_id] = {"transcript": transcript}
                if session_id:
                    emit_stream_update(session_id, chunk_id, transcript, False)
            else:
                logger.warning(f"INVALID transcript for chunk_id {chunk_id}: {transcript}")

            # clean old transcripts
            clean_old_transcripts()

        except Exception as e:
                        # Same chunk_id already exists: this audio is the
                        # client's appended/extended version of the prior
                        # buffer for the same chunk, so overwrite rather
                        # than concatenate.
                        current_transcript['transcript'] = transcript
                    else:
                        transcripts[chunk_id] = {'transcript': transcript}
            else:
                logger.warning(f"INVALID transcript for chunk_id {chunk_id}: {transcript}")

            # Periodic GC of stale tenants/chunks.
            clean_old_transcripts()

        except Exception:
            logger.error(f"Error processing audio chunk {chunk_id}", exc_info=True)
        finally:
            for _ in range(coalesced_gets):
                audio_stack.task_done()


# Check if the transcript is valid: no known hallucination phrases and no forbidden strings
def is_valid(transcript):
    transcript_lower = transcript.lower()

    forbidden_phrases = {"thanks for watching", "click, click", "click click", "cough cough"}

# Check if the transcript is valid: Contains at least one ASCII character and no forbidden words
def is_valid(transcript):
    transcript_lower = transcript.lower()
    # Check for at least one ASCII character with a code < 128 and code > 32 (we omit space in this case)
    has_ascii_char = any(32 < ord(char) < 128 for char in transcript)

    # Check for forbidden words (case insensitive)
    forbidden_phrases = {"thank you", "bye!", "thanks for watching", "click, click", "click click", "cough cough", "뉴", "스", "김", "수", "근", "입", "니", "다"}
    contains_forbidden_phrases = any(word in transcript_lower for word in forbidden_phrases)
    forbidden_strings = {"eh.", "bye.", "it's fine"}
    is_forbidden_string = any(word == transcript_lower for word in forbidden_strings)

    # check if the transcript has words which are longer than 40 characters
    contains_long_words = any(len(word) > 40 for word in transcript.split())

    return not contains_forbidden_phrases and not is_forbidden_string and not contains_long_words
    # Return true only if both conditions are met
    return has_ascii_char and not contains_forbidden_phrases and not is_forbidden_string and not contains_long_words


# Clean old transcripts: remove all chunks older than two hours and any tenants
# that become empty as a result. Concurrency-safe: takes the shared
# transcripts_lock and iterates over a snapshot so concurrent mutation in
# process_audio cannot raise "dictionary changed size during iteration".
def clean_old_transcripts():
    current_time = int(time.time() * 1000)  # Current time in milliseconds
    two_hours_ago = current_time - (2 * 60 * 60 * 1000)  # Two hours ago in milliseconds
    with _transcript_lock:
        tenants_to_remove = []
        for tenant_id in list(transcriptd.keys()):
            transcripts = transcriptd[tenant_id]
            old_chunks = [
                chunk_id
                for chunk_id in transcripts
                if (isinstance(chunk_id, int) or (isinstance(chunk_id, str) and chunk_id.isdigit()))
                and int(chunk_id) < two_hours_ago
            ]
            for chunk_id in old_chunks:
                del transcripts[chunk_id]
            if len(transcripts) == 0:
                tenants_to_remove.append(tenant_id)
        for tenant_id in tenants_to_remove:
            del transcriptd[tenant_id]
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
            # Append the transcript to the merged string with a space and lowercase the following first character.
            t = transcripts[key].strip()
            if len(t) > 1:
                merged_transcripts += " " + t[0].lower() + t[1:]
            else:
                merged_transcripts += " " + t

        # find first appearance of a sentence-ending character
        while any(char in sec for char in merged_transcripts):
            # split the merged transcript after the first sentence-ending character
            index = next(i for i, char in enumerate(merged_transcripts) if char in sec)
            # get head with sentence-ending character included
            head = merged_transcripts[:index + 1].strip()
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
                result[key] = head

            # get tail without sentence-ending character
            merged_transcripts = merged_transcripts[index + 1:].strip()

    # add the last part of the merged transcript
    if merged_transcripts:
        # dict.keys() returns a view in Python 3, not a list. so we wrap with list() to allow index access
        last_key = list(transcripts.keys())[-1]
        p = result.get(last_key)
        if p:
            result[last_key] = p + " " + merged_transcripts
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
# ---------------------------------------------------------------------------
# Swagger / flask-restx models
# ---------------------------------------------------------------------------

# NOTE: api.model() registrations must use unique names. The original code
# used 'Transcript' for both the /transcribe ack and the transcript-payload
# schema, which made flask-restx silently overwrite the first registration
# and produce a wrong Swagger doc for /transcribe.
transcribe_input_model = api.model('Transcribe', {
    'audio_b64': fields.String(required=True, description='Base64 encoded audio data'),
    'chunk_id': fields.String(required=True, description='ID of the audio chunk'),
    'tenant_id': fields.String(required=False, description='Tenant ID', default='0000')
})

transcribe_response_model = api.model('TranscribeAck', {
    'chunk_id': fields.String(description='ID of the audio chunk'),
    'tenant_id': fields.String(description='Tenant ID'),
    'status': fields.String(description='processing flag')
})

transcript_response_model = api.model('Transcript', {
    'chunk_id': fields.String(description='ID of the audio chunk'),
    'transcript': fields.String(description='The transcribed text')
})

list_transcripts_response_model = api.model('ListTranscriptsResponse', {
    'transcripts': fields.List(fields.Nested(transcript_response_model), description='List of transcripts')
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
        the user never has to know or type the uuid.
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
        try:
            # `silent=True` makes get_json() return None on a malformed body
            # instead of raising werkzeug.BadRequest. We then translate the
            # missing/invalid body into a clean 400 ourselves rather than
            # letting the broad `except Exception` below convert it into 500.
            data = request.get_json(force=True, silent=True)

            if not data:
                return {"error": "No JSON payload received"}, 400

            audio_b64 = data.get('audio_b64')
            chunk_id = data.get('chunk_id')
            tenant_id = data.get('tenant_id', '0000')

            if not audio_b64 or not chunk_id:
                return {"error": "Missing required fields"}, 400

            # push to processing queue
            audio_stack.put((tenant_id, chunk_id, audio_b64))

            response_data = {
                "chunk_id": chunk_id,
                "tenant_id": tenant_id,
                "status": "processing"
            }

            return response_data, 200

        except HTTPException:
            # Let abort()/HTTPException-derived errors keep their status code.
            raise
        except Exception as e:
            logger.error("Error in /transcribe", exc_info=True)
            return {"error": str(e)}, 500


@api.route('/get_transcript')
class GetTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin']},
        'chunk_id' : {'description': 'Chunk ID'},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.response(404, 'Transcript Not Found')
    def get(self):
        '''
        The /get_transcript endpoint allows clients to retrieve the transcript for a given chunk_id.
        If the chunk_id is not found, an empty transcript is returned.
        '''
        tenant_id = request.args.get('tenant_id', '0000')
        with _transcript_lock:
            t = transcriptd.get(tenant_id, {})
            if len(t) == 0:
                return jsonify({'chunk_id': '-1', 'transcript': ''})
            sentences = request.args.get('sentences', default='false').lower() == 'true'
            if sentences:
                t = merge_and_split_transcripts(t)
        tenant_id = _resolve_tenant(request.args)
        with transcripts_lock:
            t = dict(transcriptd.get(tenant_id, {}))
        if len(t) == 0:
            return jsonify({'chunk_id': '-1', 'transcript': ''})
        else:
            sentences = request.args.get('sentences', default='false').strip().lower() == 'true'
            if sentences: t = merge_and_split_transcripts(t)
            chunk_id = request.args.get('chunk_id')
            if chunk_id in t:
                return jsonify({'chunk_id': chunk_id, 'transcript': t[chunk_id]['transcript']})
            return jsonify({'chunk_id': chunk_id, 'transcript': ''})


@api.route('/get_first_transcript')
class GetFirstTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin']},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'from'     : {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.response(404, 'Transcript Not Found')
    def get(self):
        '''
        Get first transcript endpoint: Retrieve the first transcript for a given tenant_id
        '''
        tenant_id = request.args.get('tenant_id', '0000')
        with _transcript_lock:
            t = transcriptd.get(tenant_id, {})
            if len(t) == 0:
                return jsonify({'chunk_id': '-1', 'transcript': ''})
            sentences = request.args.get('sentences', default='false').lower() == 'true'
            if sentences:
                t = merge_and_split_transcripts(t)
            fromid = request.args.get('from', default='0')
            first_chunk_id = next((k for k in sorted(t.keys()) if int(k) >= int(fromid)), None)
        tenant_id = _resolve_tenant(request.args)
        with transcripts_lock:
            t = dict(transcriptd.get(tenant_id, {}))
        if len(t) == 0:
            return jsonify({'chunk_id': '-1', 'transcript': ''})
        else:
            sentences = request.args.get('sentences', default='false').strip().lower() == 'true'
            if sentences: t = merge_and_split_transcripts(t)
            fromid = _parse_int_arg(request.args, 'from', default=0)
            first_chunk_id = next(
                (k for k in _numeric_sorted_keys(t) if _chunk_id_int(k) >= fromid),
                None,
            )
            if first_chunk_id is None:
                return jsonify({'chunk_id': '-1', 'transcript': ''})
            first_transcript = t[first_chunk_id]['transcript']
            return jsonify({'chunk_id': first_chunk_id, 'transcript': first_transcript})


@api.route('/pop_first_transcript')
class PopFirstTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin']},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'from'     : {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.response(404, 'Transcript Not Found')
    def delete(self):
        '''
        Pop first transcript: retrieve and remove the first transcript for a given tenant_id.

        DELETE is the canonical method for this destructive operation.
        '''
        return self._pop_first()

    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin']},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'from'     : {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.deprecated
    def get(self):
        '''
        DEPRECATED: use DELETE /pop_first_transcript instead. GET on a
        destructive endpoint violates the HTTP "GET is safe" contract and
        is incompatible with caching proxies. Kept for backward compat.
        '''
        tenant_id = request.args.get('tenant_id', '0000')
        with _transcript_lock:
            t = transcriptd.get(tenant_id, {})
            if len(t) == 0:
                return jsonify({'chunk_id': '-1', 'transcript': ''})
            sentences = request.args.get('sentences', default='false').lower() == 'true'
            if sentences:
                t = merge_and_split_transcripts(t)
            fromid = request.args.get('from', default='0')
            first_chunk_id = next((k for k in sorted(t.keys()) if int(k) >= int(fromid)), None)
            first_transcript = t.pop(first_chunk_id)['transcript']
            return jsonify({'chunk_id': first_chunk_id, 'transcript': first_transcript})
        logger.warning("Deprecated GET /pop_first_transcript called; use DELETE.")
        return self._pop_first()

    def _pop_first(self):
        tenant_id = _resolve_tenant(request.args)
        sentences = request.args.get('sentences', default='false').strip().lower() == 'true'
        fromid = _parse_int_arg(request.args, 'from', default=0)

        with transcripts_lock:
            stored = transcriptd.get(tenant_id)
            if not stored:
                return jsonify({'chunk_id': '-1', 'transcript': ''})

            view = merge_and_split_transcripts(stored) if sentences else stored
            first_chunk_id = next(
                (k for k in _numeric_sorted_keys(view) if _chunk_id_int(k) >= fromid),
                None,
            )
            if first_chunk_id is None:
                return jsonify({'chunk_id': '-1', 'transcript': ''})

            entry = stored.pop(first_chunk_id, None)
            if sentences:
                first_transcript = view[first_chunk_id]['transcript']
            else:
                first_transcript = entry['transcript'] if entry else ''
        return jsonify({'chunk_id': first_chunk_id, 'transcript': first_transcript})


@api.route('/get_latest_transcript')
class GetLatestTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin']},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'until': {'description': 'End chunk ID (defaults to "now" in ms)', 'type': 'string'}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.response(404, 'Transcript Not Found')
    def get(self):
        '''
        Get latest transcript endpoint: Retrieve the latest transcript for a given tenant_id
        '''
        tenant_id = request.args.get('tenant_id', '0000')
        with _transcript_lock:
            t = transcriptd.get(tenant_id, {})
            if len(t) == 0:
                return jsonify({'chunk_id': '-1', 'transcript': ''})
            sentences = request.args.get('sentences', default='false').lower() == 'true'
            if sentences:
                t = merge_and_split_transcripts(t)
            untilid = request.args.get('until', default=str(int(time.time() * 1000)))
            latest_chunk_id = next((k for k in sorted(t.keys(), reverse=True) if int(k) < int(untilid)), None)
        tenant_id = _resolve_tenant(request.args)
        with transcripts_lock:
            t = dict(transcriptd.get(tenant_id, {}))
        if len(t) == 0:
            return jsonify({'chunk_id': '-1', 'transcript': ''})
        else:
            sentences = request.args.get('sentences', default='false').strip().lower() == 'true'
            if sentences: t = merge_and_split_transcripts(t)
            untilid = _parse_int_arg(request.args, 'until', default=int(time.time() * 1000))
            latest_chunk_id = next(
                (k for k in _numeric_sorted_keys(t, reverse=True) if _chunk_id_int(k) < untilid),
                None,
            )
            if latest_chunk_id is None:
                return jsonify({'chunk_id': '-1', 'transcript': ''})
            latest_transcript = t[latest_chunk_id]['transcript']
            return jsonify({'chunk_id': latest_chunk_id, 'transcript': latest_transcript})


@api.route('/pop_latest_transcript')
class PopLatestTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin']},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'until': {'description': 'End chunk ID (defaults to "now" in ms)', 'type': 'string'}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.response(404, 'Transcript Not Found')
    def delete(self):
        '''
        Pop latest transcript: retrieve and remove the latest transcript for a given tenant_id.

        DELETE is the canonical method for this destructive operation.
        '''
        return self._pop_latest()

    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin']},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'until': {'description': 'End chunk ID (defaults to "now" in ms)', 'type': 'string'}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.deprecated
    def get(self):
        '''
        Pop latest transcript endpoint: Retrieve and remove the latest transcript for a given tenant_id
        '''
        tenant_id = request.args.get('tenant_id', '0000')
        with _transcript_lock:
            t = transcriptd.get(tenant_id, {})
            if len(t) == 0:
                return jsonify({'chunk_id': '-1', 'transcript': ''})
            sentences = request.args.get('sentences', default='false').lower() == 'true'
            if sentences:
                t = merge_and_split_transcripts(t)
            untilid = request.args.get('until', default=str(int(time.time() * 1000)))
            latest_chunk_id = next((k for k in sorted(t.keys(), reverse=True) if int(k) < int(untilid)), None)
            latest_transcript = t.pop(latest_chunk_id)['transcript']
            return jsonify({'chunk_id': latest_chunk_id, 'transcript': latest_transcript})

        DEPRECATED: use DELETE /pop_latest_transcript instead. GET on a
        destructive endpoint violates the HTTP "GET is safe" contract and
        is incompatible with caching proxies. Kept for backward compat.
        '''
        logger.warning("Deprecated GET /pop_latest_transcript called; use DELETE.")
        return self._pop_latest()

    def _pop_latest(self):
        tenant_id = _resolve_tenant(request.args)
        sentences = request.args.get('sentences', default='false').strip().lower() == 'true'
        untilid = _parse_int_arg(request.args, 'until', default=int(time.time() * 1000))

        with transcripts_lock:
            stored = transcriptd.get(tenant_id)
            if not stored:
                return jsonify({'chunk_id': '-1', 'transcript': ''})

            view = merge_and_split_transcripts(stored) if sentences else stored
            latest_chunk_id = next(
                (k for k in _numeric_sorted_keys(view, reverse=True) if _chunk_id_int(k) < untilid),
                None,
            )
            if latest_chunk_id is None:
                return jsonify({'chunk_id': '-1', 'transcript': ''})

            entry = stored.pop(latest_chunk_id, None)
            if sentences:
                latest_transcript = view[latest_chunk_id]['transcript']
            else:
                latest_transcript = entry['transcript'] if entry else ''
        return jsonify({'chunk_id': latest_chunk_id, 'transcript': latest_transcript})

@api.route('/delete_transcript')
class DeleteTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin']},
        'chunk_id' : {'description': 'Chunk ID', 'type': 'string'}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.response(404, 'Transcript Not Found')
    def delete(self):
        '''
        Delete a transcript for a given tenant_id and chunk_id.

        DELETE is the canonical method for this destructive operation.
        '''
        return self._delete()

    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin']},
        'chunk_id' : {'description': 'Chunk ID', 'type': 'string'}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.deprecated
    def get(self):
        '''
        delete a transcript for a given tenant_id and chunk_id
        '''
        tenant_id = request.args.get('tenant_id', '0000')
        with _transcript_lock:
            t = transcriptd.get(tenant_id, {})
            sentences = request.args.get('sentences', default='false').lower() == 'true'
            if sentences:
                t = merge_and_split_transcripts(t)
            chunk_id = request.args.get('chunk_id')
            if chunk_id in t:
                entry = t.pop(chunk_id, None)
                return jsonify({'chunk_id': chunk_id, 'transcript': entry['transcript']})
            return jsonify({'chunk_id': chunk_id, 'transcript': ''})
        DEPRECATED: use DELETE /delete_transcript instead. GET on a
        destructive endpoint violates the HTTP "GET is safe" contract and
        is incompatible with caching proxies. Kept for backward compat.
        '''
        logger.warning("Deprecated GET /delete_transcript called; use DELETE.")
        return self._delete()

    def _delete(self):
        tenant_id = _resolve_tenant(request.args)
        chunk_id = request.args.get('chunk_id')
        with transcripts_lock:
            stored = transcriptd.get(tenant_id, {})
            if chunk_id in stored:
                entry = stored.pop(chunk_id, None)
                return jsonify({'chunk_id': chunk_id, 'transcript': entry['transcript']})
        return jsonify({'chunk_id': chunk_id, 'transcript': ''})


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
        tenant_id = request.args.get('tenant_id', '0000')
        with _transcript_lock:
            t = transcriptd.get(tenant_id, {})
            sentences = request.args.get('sentences', default='false').lower() == 'true'
            if sentences:
                t = merge_and_split_transcripts(t)
            fromid = request.args.get('from', default='0')
            untilid = request.args.get('until', default=str(int(time.time() * 1000)))
            transcripts_filtered = {k: v for k, v in t.items() if int(fromid) <= int(k) <= int(untilid)}
            return jsonify(transcripts_filtered)

        tenant_id = _resolve_tenant(request.args)
        sentences = request.args.get('sentences', default='false').strip().lower() == 'true'
        fromid = _parse_int_arg(request.args, 'from', default=0)
        untilid = _parse_int_arg(request.args, 'until', default=int(time.time() * 1000))
        with transcripts_lock:
            t = dict(transcriptd.get(tenant_id, {}))
        if sentences: t = merge_and_split_transcripts(t)
        result = {k: v for k, v in t.items() if _in_chunk_range(k, fromid, untilid)}
        return jsonify(result)

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
        tenant_id = request.args.get('tenant_id', '0000')
        with _transcript_lock:
            t = transcriptd.get(tenant_id, {})
            sentences = request.args.get('sentences', default='false').lower() == 'true'
            if sentences:
                t = merge_and_split_transcripts(t)
            fromid = request.args.get('from', default='0')
            untilid = request.args.get('until', default=str(int(time.time() * 1000)))
            t = {k: v for k, v in t.items() if int(fromid) <= int(k) <= int(untilid)}
            return jsonify({'size': len(t)})


def get_transcript_for_ws(tenant_id: str, chunk_id: str) -> str:
    """Read current transcript text for finalize_chunk WebSocket control messages."""
    with _transcript_lock:
        row = transcriptd.get(tenant_id, {}).get(chunk_id)
    if isinstance(row, dict):
        return row.get("transcript", "") or ""
    return ""


@sock.route("/stt/stream")
def stt_stream(ws):
    """Real-time STT: send JSON audio messages; receive transcript events (see streaming_stt_ws)."""
    from streaming_stt_ws import run_stt_stream

    run_stt_stream(
        ws,
        request,
        enqueue_audio=lambda t, c, a, s: try_enqueue(audio_stack, (t, c, a, s)),
        ensure_worker=ensure_process_audio_thread,
        get_transcript=get_transcript_for_ws,
    )


if __name__ == '__main__':
    ensure_process_audio_thread()
    app.run(host='0.0.0.0', port=5040, debug=False)
        tenant_id = _resolve_tenant(request.args)
        sentences = request.args.get('sentences', default='false').strip().lower() == 'true'
        fromid = _parse_int_arg(request.args, 'from', default=0)
        untilid = _parse_int_arg(request.args, 'until', default=int(time.time() * 1000))
        with transcripts_lock:
            t = dict(transcriptd.get(tenant_id, {}))
        if sentences: t = merge_and_split_transcripts(t)
        t = {k: v for k, v in t.items() if _in_chunk_range(k, fromid, untilid)}
        return jsonify({'size': len(t)})


# ---------------------------------------------------------------------------
# Audio worker auto-start
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    # Server bind config is env-driven so the defaults are SAFE:
    #   - host defaults to 127.0.0.1 (loopback only)
    #   - debug defaults to False (NEVER bind the Werkzeug debugger on a
    #     network-reachable port; doing so is remote-code-execution).
    # Override via FLASK_HOST / FLASK_PORT / FLASK_DEBUG when you really
    # mean it (e.g. inside a private VM you fully control).
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

    # use_reloader=False because the audio-worker thread above must not be
    # spawned twice (the reloader runs the module twice, which would
    # otherwise create a duplicate consumer on the queue).
    app.run(host=host, port=port, debug=debug, use_reloader=False)
