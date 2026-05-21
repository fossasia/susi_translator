# SUSI Translator

Real-time audio transcription + optional translation prototype with:

- a **Django API backend** (`django/`) - primary path
- a **Flask API backend** (`flask/`) - legacy/compat path
- browser/Python clients that capture audio chunks and push them to the API

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- pip (optional; only needed for the legacy fallback path)

## Setup (Primary: uv)

```bash
uv sync
```

This creates `.venv/` and installs dependencies from `pyproject.toml`.

## Run Django backend (recommended)

```bash
cd django
uv run python manage.py migrate
uv run python manage.py runserver 0.0.0.0:5040
```

Swagger:

- <http://localhost:5040/swagger/>

## Run Flask backend (legacy)

```bash
cd flask
uv run python transcribe_server.py
```

## Environment variables

Copy `.env.example` to `.env` and adjust values. Highlights:

Whisper / transcription:

- `WHISPER_SERVER_USE` (`true` to use whisper.cpp HTTP server, `false` for local models)
- `WHISPER_SERVER` (base URL of the whisper.cpp server, e.g. `http://localhost:8007`)
- `WHISPER_MODEL_FAST` / `WHISPER_MODEL_SMART` (model names for the local fast/smart paths; legacy single `WHISPER_MODEL` still honoured)
- `WHISPER_DEVICE`
- `TRANSCRIBE_SERVER_URL`

Flask backend bind / safety:

- `FLASK_HOST` (default `127.0.0.1` — loopback only)
- `FLASK_PORT` (default `5040`)
- `FLASK_DEBUG` (default `false`; never combine `true` with a non-loopback host — Werkzeug debugger is RCE)
- `CORS_ALLOWED_ORIGINS` (comma-separated; default localhost only; pass `*` only if you really mean it)
- `SESSION_TTL_SECONDS` (default `7200`; per-source `?source=…` session pointer expiry)

## Legacy pip fallback

`requirements.txt` is kept for compatibility, but `uv sync` is the supported install flow.

## Tests

A pytest suite for the Flask backend lives under `flask/tests/`.

```bash
uv sync --group dev      # one-time: install pytest into .venv
uv run pytest            # run the full suite
uv run pytest -v         # verbose
```

The tests pin `WHISPER_SERVER_USE=true` in `flask/tests/conftest.py` so they
do not download or load multi-hundred-megabyte whisper models. They exercise:

- env-var helpers and query-string parsing
- the `URLSource` security validator (rejects `file://`, `concat:`, leading `-`, etc.)
- `merge_and_split_transcripts` (sentence boundaries, empty input, dict shape)
- `_next_payload` queue dedup with correct `task_done()` accounting
- `clean_old_transcripts` (stale chunks, empty tenants, non-numeric ids)
- `_resolve_tenant` including session TTL expiry
- Flask test_client integration for `/session`, `/transcribe`, `/list_transcripts`,
  `/get_transcript`, `/transcripts_size` (including malformed input -> 400 not 500).
