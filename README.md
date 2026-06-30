# SUSI Translator

A production-ready, real-time speech-to-text (transcription) and translation HTTP API built with Flask. It accepts streamed audio chunks, processes them asynchronously using a pluggable provider architecture (e.g., OpenAI, Deepgram, Whisper.cpp), and exposes REST endpoints and a modern web dashboard for clients to consume the resulting text.

## High-Level Architecture

1. **Audio Sources**: Clients capture audio from a microphone, local file, live URL, `stdin`, or YouTube, and continuously `POST` base64 encoded chunks to the API.
2. **REST API**: A Flask application queues the incoming chunks safely.
3. **Pluggable Providers**: A background worker pulls chunks from the queue and routes them to configurable external or internal AI providers for transcription and optional translation.
4. **Consumption**: Clients or web dashboards poll the REST endpoints to receive live, sentence-reflowed text.

## Features

- **Provider Registry**: Dynamically configure the transcription and translation AI models per-session. Support for OpenAI, Deepgram, and local Whisper models out-of-the-box.
- **Secure by Default**: Strict JWT-based authentication, IDOR (Insecure Direct Object Reference) prevention, and tenant isolation. No anonymous access is permitted.
- **Rate Limiting**: Built-in endpoints are protected against abuse via Redis-backed rate limiters in production.
- **Queue Deduplication**: Intelligently deduplicates overlapping audio chunks to optimize API utilization and lower provider costs.
- **Modern Dashboard**: A fully featured dashboard to configure providers, view active streams, and manage credentials.

---

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) for fast dependency management
- ffmpeg (must be installed on your `PATH` if using `file`, `url`, or `youtube` audio sources)

## Setup

**Note on Supertonic TTS**: The server uses Supertonic 3 for text-to-speech audio generation. On the first run, it will automatically download ~250MB of ONNX models to `~/.cache/supertonic3`. If you encounter rate limits or slow downloads, export a free Hugging Face token (`HF_TOKEN`) to your environment.

Use `uv` to automatically create a virtual environment (`.venv/`) and install all required dependencies:

```bash
uv sync
```

---

## Running the Server

### 1. Configure the Environment

Copy `.env.example` to `.env` in the `flask/` directory.

### 2. Create the First Admin

Before you can log into the dashboard or configure providers, you must create a superuser:

```bash
uv run python flask/auth/create_superuser.py
```

### 3. Start the Flask Backend

```bash
uv run python flask/transcribe_server.py
```

The Web Dashboard and Swagger API documentation will now be available at `http://127.0.0.1:5040`.

---

## Environment Variables & Production Defaults

**BREAKING CHANGE**: All API clients (including transcription viewing and audio grabbing) now strictly require authentication.

### Authentication

- `JWT_SECRET_KEY` (**REQUIRED**): Must be a strong, unpredictable string of ≥32 characters. The server will safely refuse to start without this set.

### Production Readiness

For a production deployment, ensure the following are configured in your environment:

- `JWT_COOKIE_SECURE=true` (Requires the server to run over HTTPS)
- `JWT_COOKIE_CSRF_PROTECT=true`
- `DATABASE_URL` (Use PostgreSQL, not the default SQLite in production. e.g., `postgresql://user:pass@localhost:5432/susi`)
- `RATELIMIT_STORAGE_URI` (Use a Redis backend, e.g., `redis://localhost:6379`, not `memory://`)
- `CORS_ALLOWED_ORIGINS` (Pass explicit origins, e.g., `https://yourdomain.com`. Default is localhost only)
- `FLASK_DEBUG=false` (Never combine `true` with a non-loopback host — Werkzeug debugger is RCE)
- `FLASK_HOST` (Bind to `0.0.0.0` to expose externally, but default `127.0.0.1` is recommended if running behind a reverse proxy like Nginx)

---

## Database Migrations

This project uses Flask-Migrate and Alembic to handle database schema upgrades. To ensure your database has the latest tables (such as `rooms`), run the following commands **from the `flask/` directory**:

```bash
cd flask
uv run python -m flask --app transcribe_server.py db upgrade
```

**Existing deployments:** If you have an existing `susi.db` that was created before migrations were added, the `rooms` table may be missing. Running `db upgrade` will add it without affecting your existing `organizers` or `token_blocklist` data.

**Fresh installs:** `db upgrade` must be run **before** starting the server for the first time, or the server will fail when attempting to write room records to the database.

## Audio Grabber (Client-Side Ingestion)

The grabber script (`flask/audio_grabber.py`) captures audio from one of five sources and streams it to the transcription server.

| Source    | Backend                 | Extra Requirements                    |

| --------- | ----------------------- | ------------------------------------- |
| `mic`     | PyAudio                 | a working input device                |
| `file`    | pydub + ffmpeg          | ffmpeg on PATH                        |
| `url`     | ffmpeg                  | ffmpeg on PATH                        |
| `stdin`   | raw PCM passthrough     | none                                  |
| `youtube` | yt-dlp + ffmpeg         | ffmpeg on PATH (yt-dlp via `uv sync`) |

**Authentication Note:** `audio_grabber.py` requires an authentication token to push data. Provide it via the `GRABBER_AUTH_TOKEN` environment variable or the `--auth-token` CLI flag. (You can generate a long-lived internal token or grab a session token from the dashboard).

### Usage Examples

```bash
export GRABBER_AUTH_TOKEN="your_internal_or_session_token"

uv run python flask/audio_grabber.py mic
uv run python flask/audio_grabber.py file --path talk.mp3 --realtime
uv run python flask/audio_grabber.py url --url https://example.com/live.m3u8
uv run python flask/audio_grabber.py youtube --url https://www.youtube.com/live/EXAMPLE_ID
ffmpeg -i input.wav -f s16le -ac 1 -ar 16000 - | \
    uv run python flask/audio_grabber.py stdin
```

### YouTube Authentication

YouTube increasingly returns:

```text
ERROR: [youtube] <id>: Sign in to confirm you're not a bot.
       Use --cookies-from-browser or --cookies for the authentication.
```

This applies particularly for requests from data-center IPs, VPNs, or WSL. To bypass it, pass cookies from a logged-in YouTube session using one of these mutually exclusive flags:

```bash
# Option A: Read cookies directly from your local browser:
uv run python flask/audio_grabber.py youtube \
    --url https://www.youtube.com/watch?v=EXAMPLE_ID \
    --cookies-from-browser chrome

# Option B: Export cookies.txt (Netscape format) using a browser extension,
# then point --cookies at the file. This is required for WSL:
uv run python flask/audio_grabber.py youtube \
    --url https://www.youtube.com/watch?v=EXAMPLE_ID \
    --cookies /path/to/youtube-cookies.txt
```

> **Warning:** Treat the `cookies.txt` file like a credential — it grants access to your YouTube account. Do not commit it to version control.

---

## Tests

A pytest suite for the Flask backend lives under `flask/tests/`.

```bash
uv sync --group dev      # one-time: install pytest into .venv
uv run pytest            # run the full suite
uv run pytest -v         # verbose
```
