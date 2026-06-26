from flask import Flask, request, jsonify, abort, Response, redirect, url_for, render_template
from flask_restx import Api, Resource, fields
from flask_cors import CORS
from flask_jwt_extended import JWTManager, verify_jwt_in_request
from flask_bcrypt import Bcrypt
from werkzeug.exceptions import HTTPException
import numpy as np
import threading
import requests
import logging
import base64
import json
import queue
import signal
import subprocess
import sys
import time
import uuid
import wave
import io
import os
import atexit
from datetime import timedelta
from dotenv import load_dotenv


from auth.routes import auth_bp, bcrypt
from auth.decorators import organizer_required
from flask_admin import Admin
from auth.admin_panel import SecureModelView, SecureAdminIndexView

from providers.registry import ProviderRegistry
import providers.plugins 
from dotenv import load_dotenv

from audio_sources import URLSource, YouTubeSource


# Load environment variables from .env file
load_dotenv()

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Known-weak placeholders that must never be used in production.
_KNOWN_WEAK_JWT_SECRETS: frozenset[str] = frozenset({
    "change-me",
    "changeme",
    "secret",
    "mysecret",
    "jwt_secret",
    "your_jwt_secret_key",
})


def _require_secret_key(env_var: str = "JWT_SECRET_KEY") -> str:
    """
    Return the value of env_var or abort startup with a clear error
    """
    value = os.getenv(env_var, "").strip()
    if not value:
        raise RuntimeError(
            f"[SECURITY] {env_var} is not set. "
            "Set a cryptographically random value (e.g. `openssl rand -hex 32`) "
            "in your .env file or environment before starting the server."
        )
    if value.lower() in _KNOWN_WEAK_JWT_SECRETS:
        raise RuntimeError(
            f"[SECURITY] {env_var} is set to a known placeholder ({value!r}). "
            "Replace it with a cryptographically random value "
            "(e.g. `openssl rand -hex 32`)."
        )
    if len(value) < 32:
        raise RuntimeError(
            f"[SECURITY] {env_var} is too short ({len(value)} chars; minimum 32). "
            "Use `openssl rand -hex 32` to generate a strong secret."
        )
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: str) -> list:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]

app = Flask(__name__)
api = Api(app, version='1.0', title='Transcription API',
          description='A simple Transcription API', doc='/swagger',
          decorators=[organizer_required])

# CORS configuration from .env file
_cors_origins = _env_csv(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:5040,http://127.0.0.1:5040",
)
if "*" in _cors_origins:
    logger.warning("CORS wildcard '*' is not allowed when supports_credentials=True. Falling back to localhost.")
    _cors_origins = ["http://localhost:5040", "http://127.0.0.1:5040"]

CORS(app, resources={r"/*": {"origins": _cors_origins}}, supports_credentials=True)
logger.info(f"CORS allowed origins: {_cors_origins}")

# Database, Auth, JWT 
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///susi.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = _require_secret_key("JWT_SECRET_KEY")
app.config["JWT_TOKEN_LOCATION"] = ["cookies", "headers"]



app.config["JWT_COOKIE_SECURE"] = _env_bool("JWT_COOKIE_SECURE", default=False)
app.config["JWT_COOKIE_SAMESITE"] = os.getenv("JWT_COOKIE_SAMESITE", "Lax")

# Default: match CSRF protection to whether HTTPS is enabled.
# Operators can override explicitly via JWT_COOKIE_CSRF_PROTECT=true/false.
_https_mode: bool = app.config["JWT_COOKIE_SECURE"]
app.config["JWT_COOKIE_CSRF_PROTECT"] = _env_bool(
    "JWT_COOKIE_CSRF_PROTECT", default=_https_mode
)

app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(days=7)

# Lifetime of the short-lived token issued to the audio_grabber subprocess.
# The grabber refreshes it proactively at 80% of this window.
# Must be greater than the longest possible audio chunk upload time (~30 s).
_INTERNAL_TOKEN_EXPIRY: timedelta = timedelta(
    minutes=int(os.getenv("INTERNAL_TOKEN_EXPIRY_MINUTES", "5"))
)

from auth.models import db
from flask_migrate import Migrate

db.init_app(app)
migrate = Migrate(app, db)
jwt = JWTManager(app)

@jwt.token_in_blocklist_loader
def check_if_token_revoked(jwt_header, jwt_payload: dict) -> bool:
    jti = jwt_payload["jti"]
    from auth.models import TokenBlocklist, db
    with app.app_context():
        token = db.session.query(TokenBlocklist.id).filter_by(jti=jti).scalar()
    return token is not None
bcrypt.init_app(app)

from auth.extensions import limiter
limiter.init_app(app)

# Register the auth blueprint (/auth/login, /auth/signup, /auth/api/*)
app.register_blueprint(auth_bp)

# Create DB tables if they don't exist yet (safe no-op if already created)
with app.app_context():
    db.create_all()

# Initialize Flask-Admin
from flask_admin.theme import Bootstrap4Theme
admin = Admin(app, name='SUSI Admin', theme=Bootstrap4Theme(swatch='flatly'), url='/admin', index_view=SecureAdminIndexView())
from auth.models import Organizer
admin.add_view(SecureModelView(Organizer, db, name="Users/Organizers"))


# Shared in-memory state
registry = ProviderRegistry()

transcriptd = {}
transcripts_lock = threading.Lock()

# Background audio grabber subprocesses, keyed by tenant_id.
grabber_processes = {}
 
grabber_lock = threading.Lock()

# FIFO queue of pending audio chunks awaiting transcription.
audio_stack = queue.Queue()
VALID_SOURCES = {"mic", "file", "url", "stdin", "youtube"}
latest_session_by_source = {s: None for s in VALID_SOURCES}
session_lock = threading.Lock()
SESSION_TTL_SECONDS = int(os.getenv('SESSION_TTL_SECONDS', '7200'))


# Small helper functions

def _parse_int_arg(args, name: str, default: int = None, required: bool = False) -> int:
    """
    Parses a query-string argument as an int
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
    Returns None for keys that cannot be interpreted as integers
    """
    try:
        return int(k)
    except (TypeError, ValueError):
        return None


def _numeric_sorted_keys(transcripts, reverse: bool = False) -> list:
    """
    Return the chunk_ids of transcripts sorted numerically, skipping
    any that can't be parsed as ints
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


def _assert_tenant_ownership(tenant_id: str) -> None:
    """
    Raises 403 Forbidden if the current user does not own the tenant_id.
    Admins bypass this check.
    """
    from flask_jwt_extended import get_jwt_identity
    from auth.models import Organizer
    email = get_jwt_identity()
    if not email:
        return
    organizer = Organizer.query.filter_by(email=email).first()
    if organizer and organizer.is_admin:
        return
    if organizer and not registry.check_ownership(tenant_id, organizer.id):
        abort(403, "You do not have permission to access or modify this tenant's stream.")


def _resolve_tenant(args, default='0000'):
    """
    Resolve which tenant_id a read request is targeting
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


def _next_payload():
    """
    Pull the next audio payload from audio stack, dropping any superseded
    duplicates so we only transcribe the latest version of each
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

        audio_stack.task_done()
        tenant_id, chunk_id, audiob64 = audio_stack.get()


def process_audio():
    while True:
        tenant_id, chunk_id, audiob64 = _next_payload()
        logger.debug(f"Queue length: {audio_stack.qsize()}")
        try:
            audio_data = base64.b64decode(audiob64)
            audio_int16 = np.frombuffer(audio_data, dtype=np.int16)

            if audio_int16.size == 0:
                logger.warning(f"Invalid audio data for chunk_id {chunk_id}")
                continue

            audio_float32 = audio_int16.astype(np.float32) / 32768.0
            if np.isnan(audio_float32).any():
                logger.warning(f"NaN values in audio array for chunk_id {chunk_id}")
                continue

            transcript = registry.transcribe(tenant_id, audio_float32)
            if transcript is None:
                logger.warning(f"Transcription provider unavailable for chunk_id {chunk_id}")
                continue

            if is_valid(transcript):
                logger.info(f"VALID transcript for chunk_id {chunk_id}: {transcript}")
                with transcripts_lock:
                    transcripts = transcriptd.get(tenant_id)
                    if not transcripts:
                        transcripts = {}
                        transcriptd[tenant_id] = transcripts

                    current_transcript = transcripts.get(chunk_id)
                    if current_transcript:
                        # buffer for the same chunk, so overwrite rather than concatenate.
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
            audio_stack.task_done()


def is_valid(transcript):
    """Check if the transcript is valid: contains at least one ASCII character and no forbidden words."""
    transcript_lower = transcript.lower()
    # Check for at least one ASCII character with a code < 128 and code > 32 (we omit space in this case)
    has_ascii_char = any(32 < ord(char) < 128 for char in transcript)

    # Check for forbidden words (case insensitive)
    forbidden_phrases = {"click, click", "click click", "cough cough", "뉴", "스", "김", "수", "근", "입", "니", "다"}
    contains_forbidden_phrases = any(word in transcript_lower for word in forbidden_phrases)
    forbidden_strings = {"eh.", "you", "it's fine"}
    is_forbidden_string = any(word == transcript_lower for word in forbidden_strings)

    # check if the transcript has words which are longer than 40 characters
    contains_long_words = any(len(word) > 40 for word in transcript.split())

    # Return true only if both conditions are met
    return has_ascii_char and not contains_forbidden_phrases and not is_forbidden_string and not contains_long_words


def clean_old_transcripts():
    """Remove all chunks older than two hours and any tenants that become empty."""
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

            stale_chunks = []
            for chunk_id in list(transcripts.keys()):
                try:
                    if int(chunk_id) < two_hours_ago_ms:
                        stale_chunks.append(chunk_id)
                except (TypeError, ValueError):
                    continue

            for chunk_id in stale_chunks:
                transcripts.pop(chunk_id, None)

            if not transcripts:
                empty_tenants.append(tenant_id)

        for tenant_id in empty_tenants:
            transcriptd.pop(tenant_id, None)

def merge_and_split_transcripts(transcripts):
    """
    smartly merge and split transcripts based on sentence boundaries
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

    # Any leftover text is attached to the final input key.
    if merged and keys:
        last_key = keys[-1]
        existing = result.get(last_key, {}).get('transcript')
        if existing:
            result[last_key] = {'transcript': existing + " " + merged}
        else:
            result[last_key] = {'transcript': merged}

    return result


# Swagger and flask-restx models

configure_input_model = api.model('ConfigureRequest', {
    'tenant_id': fields.String(required=True, description='Tenant ID for the session'),
    'transcription': fields.Raw(
        required=False,
        description=(
            'Transcription provider config, e.g. {"provider_name": "whisper_local", "model_size": "small"}.'
        ),
    ),
    'translation': fields.Raw(
        required=False,
        description=(
            'Translation provider config, e.g. {"provider_name": "nllb_local"}.'
        ),
    ),
    'stream_url': fields.String(
        required=False,
        description=(
            'Optional stream URL. Validated in the parent process before spawning audio_grabber.py. '
            'Rejected with HTTP 400 for invalid scheme, missing host, or (for youtube) non-allowlisted domain.'
        ),
    ),
    'source_type': fields.String(
        required=False,
        enum=['youtube', 'url'],
        description=(
            'Audio source type for stream_url. '
            '"youtube" (default) enforces a recognised YouTube/Twitch/Vimeo host allowlist. '
            '"url" allows any HTTP/HTTPS URL with a non-empty host.'
        ),
    ),
})

configure_response_model = api.model('ConfigureResponse', {
    'status': fields.String(description='Success or error status'),
    'message': fields.String(description='Status details')
})

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
        description='Input source name; one of: mic, file, url, stdin, youtube',
        enum=sorted(VALID_SOURCES),
    ),
})

session_response_model = api.model('SessionResponse', {
    'tenant_id': fields.String(description='Server-minted tenant ID for this run'),
    'source': fields.String(description='Source name this session is registered under'),
})


# Shared Swagger parameter blocks
_TENANT_PARAM = {'description': 'Tenant ID', 'default': '0000'}
_SOURCE_PARAM = {
    'description': 'Resolve to the latest session for a source (mic|file|url|stdin|youtube). '
                   'Ignored if tenant_id is given. Unknown values return HTTP 400.',
    'type': 'string',
    'enum': ['mic', 'file', 'url', 'stdin', 'youtube'],
}
_SENTENCES_PARAM = {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False}
_FROM_PARAM = {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'}
_UNTIL_PARAM = {'description': 'End chunk ID (defaults to "now" in ms)', 'type': 'string'}

_EMPTY_TRANSCRIPT = {'chunk_id': '-1', 'transcript': ''}


def _wants_sentences() -> bool:
    return request.args.get('sentences', default='false').strip().lower() == 'true'


def _session_logic(success_status: int = 200):
    data = request.get_json(force=True, silent=True) or {}
    source = data.get('source') or request.args.get('source')
    if source not in VALID_SOURCES:
        return {"error": f"source must be one of {sorted(VALID_SOURCES)}"}, 400

    new_tenant_id = uuid.uuid4().hex
    with session_lock:
        latest_session_by_source[source] = (new_tenant_id, time.time())

    # Opportunistically bind the caller as owner at session creation so that no
    # other authenticated user can claim this tenant_id via POST /configure
    try:
        from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
        from flask_jwt_extended.exceptions import JWTExtendedException
        from jwt.exceptions import PyJWTError
        from auth.models import Organizer
        verify_jwt_in_request(optional=True)
        email = get_jwt_identity()
        if email:
            organizer = Organizer.query.filter_by(email=email).first()
            if organizer:
                registry.claim(new_tenant_id, organizer.id)
    except (JWTExtendedException, PyJWTError):
        pass  

    logger.info(f"New session for source={source}: tenant_id={new_tenant_id}")
    return {"tenant_id": new_tenant_id, "source": source}, success_status


def _transcribe_logic(success_status: int = 202):
    data = request.get_json(force=True, silent=True)
    if not data:
        return {"error": "No JSON payload received"}, 400

    audio_b64 = data.get('audio_b64')
    chunk_id = data.get('chunk_id')
    tenant_id = data.get('tenant_id', '0000')

    if not audio_b64 or not chunk_id:
        return {"error": "Missing required fields"}, 400

    from flask_jwt_extended import verify_jwt_in_request, get_jwt
    from flask_jwt_extended.exceptions import JWTExtendedException
    from jwt.exceptions import PyJWTError
    try:
        verify_jwt_in_request(locations=["headers"])
        claims = get_jwt()
    except (JWTExtendedException, PyJWTError) as exc:
        logger.warning(f"Auth failed for /transcripts: {exc.__class__.__name__}: {exc}")
        return {"error": "Authentication required.", "status": "error"}, 401

    if claims.get("role") != "internal" or claims.get("tenant_id") != tenant_id:
        return {"error": "Forbidden or invalid tenant scope.", "status": "error"}, 403

    # push to processing queue
    audio_stack.put((tenant_id, chunk_id, audio_b64))
    return {"chunk_id": chunk_id, "tenant_id": tenant_id, "status": "processing"}, success_status


def _kill_grabber(proc, tenant_id: str) -> None:
    """Send SIGTERM to the grabber's entire process group, then wait."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=3)
        logger.info(f"Stopped grabber for tenant {tenant_id}")
    except Exception as e:
        logger.error(f"Error stopping grabber for {tenant_id}: {e}")


def cleanup_grabbers():
    """Ensure no audio_grabber subprocesses are left orphaned on server shutdown."""
    with grabber_lock:
        for tenant_id, proc in list(grabber_processes.items()):
            _kill_grabber(proc, tenant_id)
        grabber_processes.clear()


atexit.register(cleanup_grabbers)


def _get_transcript_logic(chunk_id):
    tenant_id = _resolve_tenant(request.args)
    _assert_tenant_ownership(tenant_id)
    with transcripts_lock:
        t = dict(transcriptd.get(tenant_id, {}))
    if len(t) == 0:
        return dict(_EMPTY_TRANSCRIPT)
    if _wants_sentences():
        t = merge_and_split_transcripts(t)
    chunk_id = None if chunk_id is None else str(chunk_id)
    if chunk_id in t:
        return {'chunk_id': chunk_id, 'transcript': t[chunk_id]['transcript']}
    return {'chunk_id': chunk_id, 'transcript': ''}


def _first_transcript_logic():
    tenant_id = _resolve_tenant(request.args)
    _assert_tenant_ownership(tenant_id)
    with transcripts_lock:
        t = dict(transcriptd.get(tenant_id, {}))
    if len(t) == 0:
        return dict(_EMPTY_TRANSCRIPT)
    if _wants_sentences():
        t = merge_and_split_transcripts(t)
    fromid = _parse_int_arg(request.args, 'from', default=0)
    first_chunk_id = next(
        (k for k in _numeric_sorted_keys(t) if _chunk_id_int(k) >= fromid),
        None,
    )
    if first_chunk_id is None:
        return dict(_EMPTY_TRANSCRIPT)
    return {'chunk_id': first_chunk_id, 'transcript': t[first_chunk_id]['transcript']}


def _pop_first_logic():
    tenant_id = _resolve_tenant(request.args)
    _assert_tenant_ownership(tenant_id)
    sentences = _wants_sentences()
    fromid = _parse_int_arg(request.args, 'from', default=0)

    with transcripts_lock:
        stored = transcriptd.get(tenant_id)
        if not stored:
            return dict(_EMPTY_TRANSCRIPT)

        view = merge_and_split_transcripts(stored) if sentences else stored
        first_chunk_id = next(
            (k for k in _numeric_sorted_keys(view) if _chunk_id_int(k) >= fromid),
            None,
        )
        if first_chunk_id is None:
            return dict(_EMPTY_TRANSCRIPT)

        entry = stored.pop(first_chunk_id, None)
        if sentences:
            first_transcript = view[first_chunk_id]['transcript']
        else:
            first_transcript = entry['transcript'] if entry else ''
    return {'chunk_id': first_chunk_id, 'transcript': first_transcript}


def _latest_transcript_logic():
    tenant_id = _resolve_tenant(request.args)
    _assert_tenant_ownership(tenant_id)
    with transcripts_lock:
        t = dict(transcriptd.get(tenant_id, {}))
    if len(t) == 0:
        return dict(_EMPTY_TRANSCRIPT)
    if _wants_sentences():
        t = merge_and_split_transcripts(t)
    untilid = _parse_int_arg(request.args, 'until', default=int(time.time() * 1000))
    latest_chunk_id = next(
        (k for k in _numeric_sorted_keys(t, reverse=True) if _chunk_id_int(k) < untilid),
        None,
    )
    if latest_chunk_id is None:
        return dict(_EMPTY_TRANSCRIPT)
    return {'chunk_id': latest_chunk_id, 'transcript': t[latest_chunk_id]['transcript']}


def _pop_latest_logic():
    tenant_id = _resolve_tenant(request.args)
    _assert_tenant_ownership(tenant_id)
    sentences = _wants_sentences()
    untilid = _parse_int_arg(request.args, 'until', default=int(time.time() * 1000))

    with transcripts_lock:
        stored = transcriptd.get(tenant_id)
        if not stored:
            return dict(_EMPTY_TRANSCRIPT)

        view = merge_and_split_transcripts(stored) if sentences else stored
        latest_chunk_id = next(
            (k for k in _numeric_sorted_keys(view, reverse=True) if _chunk_id_int(k) < untilid),
            None,
        )
        if latest_chunk_id is None:
            return dict(_EMPTY_TRANSCRIPT)

        entry = stored.pop(latest_chunk_id, None)
        if sentences:
            latest_transcript = view[latest_chunk_id]['transcript']
        else:
            latest_transcript = entry['transcript'] if entry else ''
    return {'chunk_id': latest_chunk_id, 'transcript': latest_transcript}


def _delete_transcript_logic(chunk_id):
    tenant_id = _resolve_tenant(request.args)
    _assert_tenant_ownership(tenant_id)
    chunk_id = None if chunk_id is None else str(chunk_id)
    with transcripts_lock:
        stored = transcriptd.get(tenant_id, {})
        if chunk_id in stored:
            entry = stored.pop(chunk_id, None)
            return {'chunk_id': chunk_id, 'transcript': entry['transcript']}
    return {'chunk_id': chunk_id, 'transcript': ''}


def _list_transcripts_logic():
    tenant_id = _resolve_tenant(request.args)
    _assert_tenant_ownership(tenant_id)
    sentences = _wants_sentences()
    fromid = _parse_int_arg(request.args, 'from', default=0)
    untilid = _parse_int_arg(request.args, 'until', default=int(time.time() * 1000))
    with transcripts_lock:
        t = dict(transcriptd.get(tenant_id, {}))
    if sentences:
        t = merge_and_split_transcripts(t)
    return {k: v for k, v in t.items() if _in_chunk_range(k, fromid, untilid)}


def _transcripts_size_logic():
    tenant_id = _resolve_tenant(request.args)
    _assert_tenant_ownership(tenant_id)
    sentences = _wants_sentences()
    fromid = _parse_int_arg(request.args, 'from', default=0)
    untilid = _parse_int_arg(request.args, 'until', default=int(time.time() * 1000))
    with transcripts_lock:
        t = dict(transcriptd.get(tenant_id, {}))
    if sentences:
        t = merge_and_split_transcripts(t)
    t = {k: v for k, v in t.items() if _in_chunk_range(k, fromid, untilid)}
    return {'size': len(t)}

#Provider configuration endpoint
@app.route('/api/v1/translate/configure', methods=['POST'])
@organizer_required
def configure_provider():
    """
    Configure transcription and/or translation providers for a tenant
    """
    data = request.get_json(silent=True) or {}

    tenant_id = data.get("tenant_id")
    if not tenant_id:
        return jsonify({"status": "error", "message": "Missing 'tenant_id'"}), 400

    transcription = data.get("transcription")
    translation = data.get("translation")

    if not transcription and not translation:
        return jsonify({
            "status": "error",
            "message": "At least one of 'transcription' or 'translation' must be provided.",
        }), 400

    _assert_tenant_ownership(tenant_id)

    try:
        from flask_jwt_extended import get_jwt_identity
        from auth.models import Organizer
        email = get_jwt_identity()
        organizer = None
        if email:
            organizer = Organizer.query.filter_by(email=email).first()

        registry.configure(
            tenant_id=tenant_id,
            transcription=transcription,
            translation=translation,
            organizer_id=organizer.id if organizer else None,
        )
        configured = []
        if transcription:
            configured.append(f"transcription='{transcription.get('provider_name')}'")
        if translation:
            configured.append(f"translation='{translation.get('provider_name')}'")

        stream_url = data.get("stream_url")
        if stream_url:
            logger.info(f"Spawning audio_grabber for tenant {tenant_id} on url {stream_url}")
            from flask_jwt_extended import create_access_token

            internal_token = create_access_token(
                identity="internal_grabber",
                expires_delta=_INTERNAL_TOKEN_EXPIRY,
                additional_claims={"role": "internal", "tenant_id": tenant_id},
            )
        
            source_type = data.get("source_type", "youtube")

            if source_type == "youtube":
                YouTubeSource._validate_url(stream_url)
            elif source_type == "url":
                if not organizer or not organizer.is_admin:
                    return jsonify({"status": "error", "message": "Only admins can provide direct stream URLs."}), 403
                URLSource._validate_url(stream_url)
            else:
                return jsonify({
                    "status": "error",
                    "message": (
                        f"Unknown source_type {source_type!r}. "
                        "Must be 'youtube' or 'url'."
                    ),
                }), 400

            logger.info(
                f"Spawning audio_grabber for tenant {tenant_id} "
                f"on {source_type} url {stream_url}"
            )
            cmd = [
                sys.executable,
                "audio_grabber.py",
                "--tenant", tenant_id,
                source_type,
                "--url", stream_url,
            ]
            # Pass the auth token via environment variable
            # Explicitly construct a minimal environment to avoid leaking
            # sensitive parent vars to the subprocess.
            safe_env_keys = {"PATH", "LANG", "LC_ALL", "USER", "HOME", "PYTHONPATH", "VIRTUAL_ENV"}
            grabber_env = {k: os.environ[k] for k in safe_env_keys if k in os.environ}
            grabber_env["GRABBER_AUTH_TOKEN"] = internal_token

            # Only applicable for the youtube source.
            if source_type == "youtube":
                cookies_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "instance", "youtubecookies.txt"
                )
                if os.path.exists(cookies_path):
                    logger.info(f"Using YouTube cookies file at {cookies_path}")
                    cmd.extend(["--cookies", cookies_path])

            # Kill any existing grabber for this tenant before replacing it.
            # Without this, the old yt-dlp/ffmpeg process group is leaked.
            with grabber_lock:
                old_proc = grabber_processes.pop(tenant_id, None)
            if old_proc:
                _kill_grabber(old_proc, tenant_id)

            proc = subprocess.Popen(
                cmd,
                cwd=os.path.dirname(os.path.abspath(__file__)),
                preexec_fn=os.setsid,
                env=grabber_env,
            )
            with grabber_lock:
                grabber_processes[tenant_id] = proc


        return jsonify({
            "status": "success",
            "message": f"Configured {', '.join(configured)} for tenant '{tenant_id}'.",
        }), 200
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Configuration failed: {str(e)}"}), 500


# SSE streaming endpoint

@app.route('/api/v1/translate/stream', methods=['GET'])
@organizer_required
def translate_stream():
    """
    Server-sent events endpoint for real-time captions
    """
    tenant_id = _resolve_tenant(request.args)
    if not tenant_id:
        return jsonify({"status": "error", "message": "Missing 'tenant_id'"}), 400

    _assert_tenant_ownership(tenant_id)

    target_lang = request.args.get('target_lang')
    if not target_lang:
        target_lang = registry.get_language_config(tenant_id).get('target_lang')
    last_chunk_id = _parse_int_arg(request.args, 'last_chunk_id', default=0)

    def event_stream():
        sent_transcripts = {}
        translated_transcripts = {}
        last_translations = {}
        last_translation_time = 0.0

        yield f"data: {json.dumps({'status': 'connected'})}\n\n"

        try:
            while True:
                with transcripts_lock:
                    tenant_transcripts = dict(transcriptd.get(tenant_id, {}))

                now = time.time()
                provider_name = registry.get_provider_name(tenant_id, "translation")
                # Default throttle interval (can be increased for rate-limited providers)
                throttle_interval = 0.0
                can_translate = (now - last_translation_time) >= throttle_interval

                events_to_send = []

                for cid in _numeric_sorted_keys(tenant_transcripts):
                    cid_int = _chunk_id_int(cid)
                    if cid_int >= last_chunk_id:
                        text = tenant_transcripts[cid]['transcript']

                        needs_tx_update = sent_transcripts.get(cid) != text
                        needs_tl_update = target_lang and (translated_transcripts.get(cid) != text)

                        if needs_tx_update or needs_tl_update:
                            translation = last_translations.get(cid, "")

                            if needs_tl_update and can_translate:
                                try:
                                    lang_config = registry.get_language_config(tenant_id)
                                    source_lang = lang_config.get('source_lang', 'en')
                                    new_tl = registry.translate(tenant_id, text, source_lang, target_lang)
                                    if new_tl:
                                        translation = new_tl
                                    last_translations[cid] = translation
                                    translated_transcripts[cid] = text
                                    last_translation_time = time.time()
                                    can_translate = False  # Only 1 translation per loop to spread load
                                except Exception as e:
                                    logger.error(f"Stream translation error for {tenant_id}: {e}")

                            # Send an event if the transcription changed, or if we just
                            # successfully translated it to match the current transcription.
                            if needs_tx_update or (needs_tl_update and translated_transcripts.get(cid) == text):
                                events_to_send.append({
                                    "chunk_id": cid,
                                    "transcript": text,
                                    "translation": translation,
                                })
                                sent_transcripts[cid] = text

                for payload in events_to_send:
                    yield f"data: {json.dumps(payload)}\n\n"

                time.sleep(0.2)
        except GeneratorExit:
            logger.info(f"SSE Client disconnected for tenant {tenant_id}")

    return Response(event_stream(), mimetype="text/event-stream")


# Tenant lifecycle endpoints

@app.route('/stop_event/<tenant_id>', methods=['POST'])
@organizer_required
def stop_event(tenant_id):
    """
    Kills the background audio grabber, releases provider slots, and
    deletes all in-memory transcripts for tenant_id.
    """
    _assert_tenant_ownership(tenant_id)

    with grabber_lock:
        proc = grabber_processes.pop(tenant_id, None)
    if proc:
        _kill_grabber(proc, tenant_id)

    registry.remove(tenant_id)

    with transcripts_lock:
        transcriptd.pop(tenant_id, None)

    return jsonify({"status": "success", "message": f"Event {tenant_id} stopped"}), 200


@app.route('/internal/token-refresh', methods=['POST'])
def internal_token_refresh():
    """
    Issues a fresh short-lived internal token to a running audio_grabber
    """
    from flask_jwt_extended import verify_jwt_in_request, get_jwt, create_access_token
    from flask_jwt_extended.exceptions import JWTExtendedException
    from jwt.exceptions import PyJWTError
    try:
        verify_jwt_in_request(locations=["headers"])
        claims = get_jwt()
    except (JWTExtendedException, PyJWTError) as exc:
        logger.warning(f"token-refresh rejected: {exc}")
        return jsonify({"status": "error", "message": "Authentication required."}), 401

    if claims.get("role") != "internal" or "tenant_id" not in claims:
        # Organiser tokens must not be able to use this endpoint to extend themselves.
        return jsonify({"status": "error", "message": "Forbidden."}), 403

    tenant_id = claims["tenant_id"]

    new_token = create_access_token(
        identity="internal_grabber",
        expires_delta=_INTERNAL_TOKEN_EXPIRY,
        additional_claims={"role": "internal", "tenant_id": tenant_id},
    )
    logger.debug("Issued refreshed internal token to audio_grabber")
    return jsonify({"token": new_token}), 200


@app.route('/api/v1/translate/status/<tenant_id>', methods=['GET'])
@organizer_required
def provider_status(tenant_id):
    """
    Check whether the models for a given tenant are fully loaded and ready.
    The frontend polls this during the loading screen.
    """
    _assert_tenant_ownership(tenant_id)

    if registry.is_pipeline_ready(tenant_id):
        return jsonify({"status": "ready"}), 200
    return jsonify({"status": "warming_up"}), 200


# REST transcript endpoints

@api.route('/session')
class Session(Resource):
    @api.expect(session_input_model)
    @api.response(200, 'Success', session_response_model)
    @api.response(400, 'Invalid source')
    def post(self):
        '''
        Start a new transcription session for an input source
        '''
        try:
            return _session_logic(success_status=200)
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Error in POST /session", exc_info=True)
            return {"error": str(e)}, 500


@api.route('/transcripts')
class Transcripts(Resource):
    @api.expect(transcribe_input_model)
    @api.response(202, 'Accepted', transcribe_response_model)
    @api.response(400, 'Bad Request')
    def post(self):
        '''
        Submit an audio chunk for transcription
        '''
        try:
            return _transcribe_logic(success_status=202)
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Error in POST /transcripts", exc_info=True)
            return {"error": str(e)}, 500

    @api.doc(params={
        'tenant_id': _TENANT_PARAM,
        'source': _SOURCE_PARAM,
        'sentences': _SENTENCES_PARAM,
        'from': _FROM_PARAM,
        'until': _UNTIL_PARAM,
    })
    @api.response(200, 'Success', list_transcripts_response_model)
    @organizer_required
    def get(self):
        '''List all transcripts for a tenant, filtered by the from/until chunk range.'''
        return jsonify(_list_transcripts_logic())


@api.route('/transcripts/count')
class TranscriptsCount(Resource):
    method_decorators = [organizer_required]

    @api.doc(params={
        'tenant_id': _TENANT_PARAM,
        'source': _SOURCE_PARAM,
        'sentences': _SENTENCES_PARAM,
        'from': _FROM_PARAM,
        'until': _UNTIL_PARAM,
    })
    @api.response(200, 'Success', size_response_model)
    def get(self):
        '''Get the number of transcripts for a tenant'''
        return jsonify(_transcripts_size_logic())


@api.route('/transcripts/first')
class TranscriptsFirst(Resource):
    method_decorators = [organizer_required]

    @api.doc(params={
        'tenant_id': _TENANT_PARAM,
        'source': _SOURCE_PARAM,
        'sentences': _SENTENCES_PARAM,
        'from': _FROM_PARAM,
    })
    @api.response(200, 'Success', transcript_response_model)
    def get(self):
        '''Retrieve the first transcript for a tenant (non-destructive).'''
        return jsonify(_first_transcript_logic())

    @api.doc(params={
        'tenant_id': _TENANT_PARAM,
        'source': _SOURCE_PARAM,
        'sentences': _SENTENCES_PARAM,
        'from': _FROM_PARAM,
    })
    @api.response(200, 'Success', transcript_response_model)
    def delete(self):
        '''Retrieve and remove (pop) the first transcript for a tenant.'''
        return jsonify(_pop_first_logic())


@api.route('/transcripts/latest')
class TranscriptsLatest(Resource):
    method_decorators = [organizer_required]

    @api.doc(params={
        'tenant_id': _TENANT_PARAM,
        'source': _SOURCE_PARAM,
        'sentences': _SENTENCES_PARAM,
        'until': _UNTIL_PARAM,
    })
    @api.response(200, 'Success', transcript_response_model)
    def get(self):
        '''Retrieve the latest transcript for a tenant (non-destructive).'''
        return jsonify(_latest_transcript_logic())

    @api.doc(params={
        'tenant_id': _TENANT_PARAM,
        'source': _SOURCE_PARAM,
        'sentences': _SENTENCES_PARAM,
        'until': _UNTIL_PARAM,
    })
    @api.response(200, 'Success', transcript_response_model)
    def delete(self):
        '''Retrieve and remove (pop) the latest transcript for a tenant.'''
        return jsonify(_pop_latest_logic())


@api.route('/transcripts/<int:chunk_id>')
class TranscriptByID(Resource):
    method_decorators = [organizer_required]

    @api.doc(params={
        'tenant_id': _TENANT_PARAM,
        'source': _SOURCE_PARAM,
        'sentences': _SENTENCES_PARAM,
    })
    @api.response(200, 'Success', transcript_response_model)
    def get(self, chunk_id):
        '''Retrieve the transcript for a specific chunk_id.'''
        return jsonify(_get_transcript_logic(chunk_id))

    @api.doc(params={
        'tenant_id': _TENANT_PARAM,
        'source': _SOURCE_PARAM,
    })
    @api.response(200, 'Success', transcript_response_model)
    def delete(self, chunk_id):
        '''Delete the transcript for a specific chunk_id.'''
        return jsonify(_delete_transcript_logic(chunk_id))


# Deprecated RPC-style aliases.

@api.route('/transcribe', doc=False)
class TranscribeLegacy(Resource):
    def post(self):
        '''DEPRECATED: use POST /transcripts.'''
        logger.warning("Deprecated POST /transcribe called; use POST /transcripts.")
        try:
            return _transcribe_logic(success_status=200)
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Error in /transcribe (deprecated)", exc_info=True)
            return {"error": str(e)}, 500


@api.route('/list_transcripts', doc=False)
class ListTranscriptsLegacy(Resource):
    method_decorators = [organizer_required]

    def get(self):
        '''DEPRECATED: use GET /transcripts.'''
        return jsonify(_list_transcripts_logic())


@api.route('/transcripts_size', doc=False)
class TranscriptsSizeLegacy(Resource):
    method_decorators = [organizer_required]

    def get(self):
        '''DEPRECATED: use GET /transcripts/count.'''
        return jsonify(_transcripts_size_logic())


@api.route('/get_transcript', doc=False)
class GetTranscriptLegacy(Resource):
    method_decorators = [organizer_required]

    def get(self):
        '''DEPRECATED: use GET /transcripts/<chunk_id>.'''
        return jsonify(_get_transcript_logic(request.args.get('chunk_id')))


@api.route('/get_first_transcript', doc=False)
class GetFirstTranscriptLegacy(Resource):
    method_decorators = [organizer_required]

    def get(self):
        '''DEPRECATED: use GET /transcripts/first.'''
        return jsonify(_first_transcript_logic())


@api.route('/pop_first_transcript', doc=False)
class PopFirstTranscriptLegacy(Resource):
    method_decorators = [organizer_required]

    def delete(self):
        '''DEPRECATED: use DELETE /transcripts/first.'''
        return jsonify(_pop_first_logic())

    def get(self):
        '''DEPRECATED (and destructive): use DELETE /transcripts/first.'''
        logger.warning("Deprecated GET /pop_first_transcript called; use DELETE /transcripts/first.")
        return jsonify(_pop_first_logic())


@api.route('/get_latest_transcript', doc=False)
class GetLatestTranscriptLegacy(Resource):
    method_decorators = [organizer_required]

    def get(self):
        '''DEPRECATED: use GET /transcripts/latest.'''
        return jsonify(_latest_transcript_logic())


@api.route('/pop_latest_transcript', doc=False)
class PopLatestTranscriptLegacy(Resource):
    method_decorators = [organizer_required]

    def delete(self):
        '''DEPRECATED: use DELETE /transcripts/latest.'''
        return jsonify(_pop_latest_logic())

    def get(self):
        '''DEPRECATED (and destructive): use DELETE /transcripts/latest.'''
        logger.warning("Deprecated GET /pop_latest_transcript called; use DELETE /transcripts/latest.")
        return jsonify(_pop_latest_logic())


@api.route('/delete_transcript', doc=False)
class DeleteTranscriptLegacy(Resource):
    method_decorators = [organizer_required]

    def delete(self):
        '''DEPRECATED: use DELETE /transcripts/<chunk_id>.'''
        return jsonify(_delete_transcript_logic(request.args.get('chunk_id')))

    def get(self):
        '''DEPRECATED (and destructive): use DELETE /transcripts/<chunk_id>.'''
        logger.warning("Deprecated GET /delete_transcript called; use DELETE /transcripts/<chunk_id>.")
        return jsonify(_delete_transcript_logic(request.args.get('chunk_id')))


# Audio worker thread

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


# Page routes all require a valid JWT cookie

def _require_login():
    """Return a redirect to /auth/login if the request has no valid JWT cookie."""
    try:
        verify_jwt_in_request(locations=["cookies"])
        return None  # authenticated — let the view proceed
    except Exception:
        return redirect(url_for("auth.login_page"))


@app.before_request
def redirect_root():
    """Intercept bare root URL and redirect to home."""
    if request.path == "/":
        return redirect(url_for("home"))


@app.route("/home")
def home():
    """Dashboard / lobby — requires login."""
    redir = _require_login()
    if redir:
        return redir
    return render_template("create-room.html")


@app.route("/config/<tenant_id>")
def config_page(tenant_id: str):
    """Room configuration page — requires login."""
    redir = _require_login()
    if redir:
        return redir
    _assert_tenant_ownership(tenant_id)
    return render_template("config.html", tenant_id=tenant_id)


@app.route("/stream/<tenant_id>")
def stream_page(tenant_id: str):
    """Live stream / caption viewer page — requires login."""
    redir = _require_login()
    if redir:
        return redir
    _assert_tenant_ownership(tenant_id)
    video_url = request.args.get("url", "")
    return render_template("stream.html", tenant_id=tenant_id, video_url=video_url)


if __name__ == '__main__':
    # Server bind config is env-driven so the defaults are SAFE:
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

    # use_reloader=False because the audio-worker thread above must not be spawned twice
    app.run(host=host, port=port, debug=debug, use_reloader=False)
