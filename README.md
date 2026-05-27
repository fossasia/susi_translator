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

## Audio grabber (client-side ingestion)

The grabber under `flask/audio_grabber.py` captures audio from one of five
sources and streams it to the transcription server. Each source runs
client-side; the server only ever receives already-decoded base64 PCM via
`POST /transcribe`.

| Source    | Backend                 | Extra requirements                |
| --------- | ----------------------- | --------------------------------- |
| `mic`     | PyAudio                 | a working input device            |
| `file`    | pydub + ffmpeg          | ffmpeg on PATH                    |
| `url`     | ffmpeg                  | ffmpeg on PATH                    |
| `stdin`   | raw PCM passthrough     | none                              |
| `youtube` | yt-dlp + ffmpeg         | ffmpeg on PATH (yt-dlp via `uv sync`) |

Examples:

```bash
uv run python flask/audio_grabber.py mic
uv run python flask/audio_grabber.py file --path talk.mp3 --realtime
uv run python flask/audio_grabber.py url --url https://example.com/live.m3u8
uv run python flask/audio_grabber.py youtube --url https://www.youtube.com/live/EXAMPLE_ID
ffmpeg -i input.wav -f s16le -ac 1 -ar 16000 - | \
    uv run python flask/audio_grabber.py stdin
```

Read the resulting transcripts back via `?source=<name>`:

```bash
curl "http://localhost:5040/list_transcripts?source=youtube"
curl "http://localhost:5040/pop_first_transcript?source=youtube"
```

The `youtube` source resolves the supplied URL via yt-dlp (default format
selector `bestaudio/best`, override with `--format`), pipes the resulting
direct media URL through ffmpeg, and auto-reconnects on transient stream
interruptions with capped exponential backoff. The host must be a
recognised YouTube domain; arbitrary `https://...` URLs are rejected.

### YouTube authentication ("Sign in to confirm you're not a bot")

YouTube increasingly returns

```
ERROR: [youtube] <id>: Sign in to confirm you're not a bot.
       Use --cookies-from-browser or --cookies for the authentication.
```

for requests from data-center IPs, VPNs, or WSL. This is a YouTube
policy, not a bug; yt-dlp itself can't bypass it. Pass cookies from a
logged-in YouTube session using one of these mutually exclusive flags:

```bash
# Option A: read cookies straight from your browser (does NOT work
# reliably on WSL because the Windows browser's cookie store sits
# outside the WSL filesystem):
uv run python flask/audio_grabber.py youtube \
    --url https://www.youtube.com/watch?v=EXAMPLE_ID \
    --cookies-from-browser chrome

# Option B: export cookies.txt from your browser (Netscape format,
# via a 'Get cookies.txt LOCALLY' or similar extension while logged
# into youtube.com), then point --cookies at the file. This is the
# reliable path on WSL:
uv run python flask/audio_grabber.py youtube \
    --url https://www.youtube.com/watch?v=EXAMPLE_ID \
    --cookies /path/to/youtube-cookies.txt
```

Treat the cookies file like a credential — it grants access to your
YouTube account. Do not commit it to git.

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
