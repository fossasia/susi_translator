# Susi Translator Flask App

A real-time speech-to-text (transcription) HTTP API built with Flask + flask-restx. It accepts streamed audio chunks, transcribes them via Whisper, and exposes REST endpoints for clients to poll/consume the resulting text.

---

## High-Level Architecture

```text
┌─────────────┐  POST /session    ┌──────────────────────────────────────┐
│ audio_      │  POST /transcribe │  transcribe_server.py                │
│ grabber.py  │ ────────────────> │  (Flask + flask-restx)               │
│ (mic/file/  │                   │                                      │
│  url/stdin  │                   │  ┌────────────────────┐              │
│  /youtube)  │                   │  │ audio_stack queue  │              │
└─────────────┘                   │  └─────────┬──────────┘              │
                                  │            ▼                         │
                                  │  ┌────────────────────┐              │
                                  │  │ process_audio()    │──> ProviderRegistry
                                  │  │ worker thread      │       ↓            │
                                  │  └─────────┬──────────┘  FasterWhisperLocal│
                                  │            ▼             (CTranslate2)     │
                                  │  transcriptd (in-memory) NLLBCTranslate2   │
                                  │   tenant -> chunk -> txt (CTranslate2)     │
                                  └──────────────────────────────────────┘
                                               ▲
                  GET /transcripts, /transcripts/first, etc.
```

---

## How It Works

**1. Producer side (`audio_grabber.py` / `audio_sources.py`)**

Grabs ~1s frames of 16 kHz / 16-bit / mono PCM from a mic, file, URL, stdin, or YouTube. Accumulates up to ~10s buffers (resets on silence) and POSTs each as base64 to `/transcripts`.

**2. Server side (`transcribe_server.py`)**

- `POST /transcripts` only enqueues `(tenant_id, chunk_id, audio_b64)` onto an in-memory `queue.Queue` (`audio_stack`) and returns `202 Accepted` immediately — non-blocking.
- A background worker thread (`process_audio`) pulls items, decodes base64 → int16 numpy → float32, then either runs Whisper locally (small/medium model selected by queue depth) or POSTs WAV bytes to whisper.cpp's `/inference` HTTP server.
- Results land in an in-memory dict `transcriptd[tenant_id][chunk_id] = {'transcript': ...}`, guarded by a single `threading.Lock`.

---

## Key Design Pieces

**Sessions and source aliases.**
Instead of forcing clients to track UUIDs, `POST /session?source=mic|file|url|stdin|youtube` mints a tenant UUID and registers it as "the latest session for that source." Read endpoints accept `?source=mic`, which resolves to that current tenant ID. Sessions expire after `SESSION_TTL_SECONDS` (default 7200s).

**Pluggable provider architecture.**
`POST /api/v1/translate/configure` selects per-tenant transcription and translation backends via the `ProviderRegistry`. Available providers: `faster_whisper` (CTranslate2-accelerated Whisper) for transcription and `nllb_ctranslate2` (Facebook NLLB-200 via CTranslate2) for translation. Providers are loaded lazily in background warmup threads and shared across tenants with identical configs to avoid duplicate model copies in RAM.

**Queue dedup.**
`_next_payload()` peeks ahead in the queue and drops superseded duplicates of the same `(tenant_id, chunk_id)` (with proper `task_done()` accounting) so only the most recent version of an extending chunk gets transcribed.

**Validation filter.**
`is_valid()` discards Whisper hallucinations like "thank you", "bye!", "thanks for watching", certain Korean fragments, transcripts with 40+ char "words," or pure non-ASCII output.

**Sentence reflow.**
`merge_and_split_transcripts()` re-flows chunked text onto sentence boundaries (`.!?`), redistributing the merged output back onto `chunk_id`s.

**Garbage collection.**
`clean_old_transcripts()` runs after every chunk and evicts chunks older than 2 hours and any tenants that become empty.

**Safe defaults.**
Binds `127.0.0.1` only by default; `FLASK_DEBUG=false` (the Werkzeug debugger over network = RCE — explicit warning if misconfigured). CORS origins are env-driven, defaulting to localhost only.

**Authentication.**
All API endpoints now require JWT authentication. The app requires `JWT_SECRET_KEY` (≥32 chars) to start. Create a first admin user using `uv run python auth/create_superuser.py`. In production, use `JWT_COOKIE_SECURE=true`, `DATABASE_URL` (PostgreSQL), and `RATELIMIT_STORAGE_URI` (Redis).

---

## REST Endpoints

All endpoints are available under `/swagger`.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/session` | Mint a tenant UUID for a source (`mic`/`file`/`url`/`stdin`/`youtube`) — returns `201 Created` |
| `POST` | `/transcripts` | Submit a base64 audio chunk for async processing — returns `202 Accepted` |
| `GET` | `/transcripts` | All transcripts in `[from, until]` |
| `GET` | `/transcripts/count` | Count of transcripts in `[from, until]` |
| `GET` | `/transcripts/first` | First transcript ≥ `from` |
| `GET` | `/transcripts/latest` | Latest transcript < `until` |
| `GET` | `/transcripts/{chunk_id}` | Fetch transcript for a specific `chunk_id` |
| `DELETE` | `/transcripts/first` | Read + remove first |
| `DELETE` | `/transcripts/latest` | Read + remove latest |
| `DELETE` | `/transcripts/{chunk_id}` | Delete by `chunk_id` |

All read endpoints accept either `?tenant_id=<uuid>` or `?source=<name>`, plus `?sentences=true` to return text re-flowed at sentence boundaries.

### Deprecated aliases

The previous RPC-style paths still work for one release but are hidden from
Swagger and log a deprecation warning. Migrate to the REST paths above.

| Deprecated | Replacement |
| --- | --- |
| `POST /transcribe` (200) | `POST /transcripts` (202) |
| `GET /list_transcripts` | `GET /transcripts` |
| `GET /transcripts_size` | `GET /transcripts/count` |
| `GET /get_transcript?chunk_id=X` | `GET /transcripts/{chunk_id}` |
| `GET /get_first_transcript` | `GET /transcripts/first` |
| `GET /get_latest_transcript` | `GET /transcripts/latest` |
| `DELETE`/`GET /pop_first_transcript` | `DELETE /transcripts/first` |
| `DELETE`/`GET /pop_latest_transcript` | `DELETE /transcripts/latest` |
| `DELETE`/`GET /delete_transcript?chunk_id=X` | `DELETE /transcripts/{chunk_id}` |

---

## Other Files in `flask/`

- **`audio_grabber.py`** — CLI client orchestrator (subcommands `mic`, `file`, `url`, `stdin`, `youtube`).
- **`audio_sources.py`** — `AudioSource` ABC + four concrete implementations; `URLSource` has explicit security validation (rejects `file://`, `concat:`, leading `-` to block ffmpeg arg injection).
- **`transcribe_listener.html`, `transcribe_evaluation.html`, `audio_grabber.html`** — browser UIs that hit the same API.
- **`tests/`** — pytest suite (`conftest.py` pins `WHISPER_SERVER_USE=true` so tests don't download multi-hundred-MB models).
- **`speech.pcm`, `speech.mp3`, `tone.pcm`** — sample audio for manual smoke testing.
