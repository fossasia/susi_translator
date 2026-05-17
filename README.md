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

Copy `.env.example` to `.env` and adjust values:

- `WHISPER_SERVER_USE` (`true` to use whisper server, `false` for local models)
- `WHISPER_SERVER`
- `WHISPER_MODEL`
- `WHISPER_DEVICE`
- `TRANSCRIBE_SERVER_URL`

## Legacy pip fallback

`requirements.txt` is kept for compatibility, but `uv sync` is the supported install flow.
