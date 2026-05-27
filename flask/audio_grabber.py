"""
SUSI Translator audio grabber (refactored orchestrator).

Reads audio from one of five sources (microphone, file, URL, stdin,
YouTube), buffers up to ~10 seconds while resetting on silence, and POSTs
base64-encoded chunks to the transcription server's ``/transcribe``
endpoint.

The POST body shape is unchanged from the original implementation::

    { "chunk_id": str, "audio_b64": str, "tenant_id": str }

System requirements
-------------------
- ``mic``     : pyaudio (live capture).
- ``file``    : pydub Python package + the ``ffmpeg`` binary on PATH.
- ``url``     : the ``ffmpeg`` binary on PATH.
- ``stdin``   : none beyond the standard library.
- ``youtube`` : the ``yt-dlp`` Python package + the ``ffmpeg`` binary on
                PATH.

Tenant IDs (auto-managed)
-------------------------
The grabber never asks the user for a tenant id. On startup it calls
``POST /session`` with the chosen subcommand (``mic``/``file``/``url``/
``stdin``/``youtube``); the server mints a fresh tenant_id (uuid) and
records it as the latest session for that source.

To fetch transcripts, curl with ``?source=<name>`` instead of
``?tenant_id=...``::

    curl "http://localhost:5040/pop_first_transcript?source=mic"
    curl "http://localhost:5040/pop_first_transcript?source=youtube"

The server resolves ``source=mic`` to "the most recent mic session", so
each fresh run gives you a clean bucket of transcripts under that fixed
curl command. ``--tenant <id>`` is still accepted as an explicit
override (e.g. for reconnecting to a known session id).

Examples
--------
::

    python audio_grabber.py mic --server http://localhost:5040
    python audio_grabber.py file --path talk.mp3 --realtime
    python audio_grabber.py url  --url https://example.com/stream.mp3
    python audio_grabber.py youtube --url https://www.youtube.com/live/EXAMPLE_ID
    ffmpeg -i input.wav -f s16le -ac 1 -ar 16000 - | \\
        python audio_grabber.py stdin
"""

from __future__ import annotations

import argparse
import base64
import struct
import sys
import time
import uuid
from typing import List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib3.exceptions import MaxRetryError

from audio_sources import (
    AudioSource,
    FileSource,
    MicrophoneSource,
    StdinSource,
    URLSource,
    YouTubeSource,
)


# --- Audio / chunking constants (kept identical to the original grabber) ---
RATE: int = 16000
SAMPLE_WIDTH: int = 2  # 16-bit
BUFFER_SIZE: int = 2 * 10 * RATE  # bytes -> 10 seconds of audio
SILENCE_THRESHOLD: int = 500

DEFAULT_SERVER: str = "http://localhost:5040"
VALID_SOURCES = ("mic", "file", "url", "stdin", "youtube")


# ---------------------------------------------------------------------------
# Silence detection (absolute-peak variant of the original is_silent)
# ---------------------------------------------------------------------------

def _is_silent(pcm_bytes: bytes) -> bool:
    """
    Return True if the loudest sample in ``pcm_bytes`` is below
    ``SILENCE_THRESHOLD``.

    Behaviour note
    --------------
    The original ``AudioGrabber.is_silent`` (see ``audio_grabber.html``) used
    ``Math.max(...data)``, i.e. the signed maximum, which would mis-classify
    buffers whose loudest excursions are negative as "silent". This
    implementation intentionally uses ``max(abs(s) for s in samples)`` so
    that loud negative excursions count too. Callers that depend on strict
    bit-for-bit parity with the JS check should be aware of this difference.
    """
    if not pcm_bytes:
        return True
    n_samples = len(pcm_bytes) // SAMPLE_WIDTH
    if n_samples == 0:
        return True
    samples = struct.unpack("<%dh" % n_samples, pcm_bytes[: n_samples * SAMPLE_WIDTH])
    peak = max(abs(s) for s in samples)
    return peak < SILENCE_THRESHOLD


# ---------------------------------------------------------------------------
# Uploader
# ---------------------------------------------------------------------------

def _build_session() -> requests.Session:
    """Build a requests Session with retry/backoff for transient 5xx errors."""
    retry_policy = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        # urllib3's default allowed_methods does NOT include POST, so the
        # /transcribe upload would otherwise never be retried. POST retries
        # are safe here because the server contract is idempotent on
        # ``chunk_id`` (a re-sent body for the same chunk_id simply
        # overwrites the previous one).
        allowed_methods=frozenset(["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE", "POST"]),
    )
    adapter = HTTPAdapter(max_retries=retry_policy)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class TranscribeUploader:
    """
    POSTs accumulated audio buffers to the transcription server.

    Body shape (do NOT change, server contract):
        { "audio_b64": str, "chunk_id": str, "tenant_id": str }
    """

    def __init__(self, server: str, tenant_id: str) -> None:
        self._url: str = server.rstrip("/") + "/transcribe"
        self._tenant_id: str = tenant_id
        self._session: requests.Session = _build_session()

    def send(self, buffer: bytes, chunk_id: str) -> None:
        if not buffer:
            return
        payload = {
            "audio_b64": base64.b64encode(buffer).decode("utf-8"),
            "chunk_id": chunk_id,
            "tenant_id": self._tenant_id,
        }
        try:
            response = self._session.post(
                self._url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            if response.status_code == 200:
                print(f"Sent chunk {chunk_id} with {len(buffer)} bytes")
            else:
                print(
                    f"Error sending chunk: {response.status_code}: {response.text}"
                )
        except MaxRetryError:
            print(
                "Error: Maximum retries exceeded. Could not connect to the endpoint."
            )
        except requests.exceptions.RequestException as exc:
            print(f"Error sending chunk: {exc}")


def _new_chunk_id() -> str:
    """Return a fresh chunk_id (milliseconds since epoch)."""
    return str(int(time.time() * 1000))


def _register_session(server: str, source: str) -> str:
    """
    Ask the server for a fresh tenant_id for this run.

    Calls ``POST /session`` with ``{"source": <name>}``. The server mints
    a uuid and records it as the latest session for that source, so curl
    with ``?source=<name>`` will resolve to this run's transcripts.

    Falls back to a locally-generated uuid if the server does not yet
    implement ``/session`` (older builds), so the grabber still works,
    just without the per-source ``?source=...`` resolution.
    """
    url = server.rstrip("/") + "/session"
    try:
        response = requests.post(url, json={"source": source}, timeout=10)
        if response.status_code == 200:
            payload = response.json()
            tenant_id = payload.get("tenant_id")
            if tenant_id:
                return tenant_id
        print(
            f"Warning: /session returned HTTP {response.status_code}; "
            f"falling back to a local uuid (curl with ?source={source} "
            f"will not work for this run)."
        )
    except requests.exceptions.RequestException as exc:
        print(
            f"Warning: could not reach {url} ({exc}); falling back to a "
            f"local uuid (curl with ?source={source} will not work for "
            f"this run)."
        )
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run(source: AudioSource, server: str, tenant_id: str) -> None:
    """
    Drive one of the ``AudioSource`` implementations: read PCM in
    ~1-second chunks, apply silence-based buffering, and upload each
    running buffer to ``/transcribe``.

    Logic mirrors the original ``audio_grabber.py``:

    - On silence : drop the working buffer and rotate ``chunk_id`` (the
      buffer most recently sent under the old chunk_id is treated as that
      chunk's final state on the server).
    - On speech  : extend the buffer and POST the running buffer under the
      current chunk_id. The server overwrites prior versions of the same
      chunk_id with this newer (longer) audio.
    - When the buffer reaches ``BUFFER_SIZE`` : the chunk just sent is
      considered final; rotate ``chunk_id`` and start fresh.

    ``stop()`` on the source is invoked in a ``finally`` block, so partial
    starts and mid-stream interrupts are safe.
    """
    uploader = TranscribeUploader(server=server, tenant_id=tenant_id)
    buffer = bytearray()
    chunk_id: str = _new_chunk_id()

    try:
        source.start()
        for pcm in source.read_chunk():
            if _is_silent(pcm):
                # The buffer last sent is now the final state of this
                # chunk on the server; reset locally and rotate.
                buffer = bytearray()
                chunk_id = _new_chunk_id()
                continue

            buffer.extend(pcm)

            # Always send the running buffer so the server has the latest.
            if buffer:
                uploader.send(bytes(buffer), chunk_id)

            # If the buffer is full, the chunk we just sent is final;
            # start a new one on the next non-silent input.
            if len(buffer) >= BUFFER_SIZE:
                buffer = bytearray()
                chunk_id = _new_chunk_id()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        # Flush a final tail if a finite source ended mid-buffer, so the
        # server has the complete final state of that chunk.
        if buffer:
            try:
                uploader.send(bytes(buffer), chunk_id)
            except Exception as exc:
                print(f"Error flushing final buffer: {exc}")
        # ``stop()`` is required to be safe to call even if start() never
        # completed; we call it unconditionally here.
        try:
            source.stop()
        except Exception as exc:
            print(f"Error stopping source: {exc}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="audio_grabber",
        description=(
            "Capture audio from various sources (microphone, file, URL, "
            "stdin, YouTube) and stream it to the SUSI transcription server."
        ),
    )
    parser.add_argument(
        "--server",
        default=DEFAULT_SERVER,
        help=f"Transcribe server URL (default: {DEFAULT_SERVER}).",
    )
    parser.add_argument(
        "--tenant",
        default=None,
        help=(
            "Explicit tenant ID override. By default the grabber asks "
            "the server for a fresh tenant ID per run via POST /session."
        ),
    )

    sub = parser.add_subparsers(
        dest="source",
        required=True,
        metavar="{mic,file,url,stdin,youtube}",
        help="Audio source to use.",
    )

    p_mic = sub.add_parser("mic", help="Live microphone capture (PyAudio).")
    p_mic.add_argument(
        "--device-index",
        type=int,
        default=None,
        help="PyAudio input device index (default: system default).",
    )

    p_file = sub.add_parser(
        "file",
        help="Decode a local audio file (pydub + ffmpeg).",
    )
    p_file.add_argument(
        "--path",
        required=True,
        help="Path to the audio file.",
    )
    p_file.add_argument(
        "--realtime",
        action="store_true",
        help="Throttle to wall-clock playback speed (simulate a live source).",
    )

    p_url = sub.add_parser(
        "url",
        help="Decode an HTTP(S) audio stream (ffmpeg).",
    )
    p_url.add_argument(
        "--url",
        required=True,
        help="URL of the audio stream.",
    )

    sub.add_parser(
        "stdin",
        help="Read raw 16 kHz / 16-bit / mono PCM from stdin.",
    )

    p_yt = sub.add_parser(
        "youtube",
        help="Decode a YouTube (Live or VOD) URL via yt-dlp + ffmpeg.",
    )
    p_yt.add_argument(
        "--url",
        required=True,
        help="YouTube watch / live URL.",
    )
    p_yt.add_argument(
        "--format",
        default="bestaudio/best",
        help="yt-dlp format selector (default: bestaudio/best).",
    )
    # YouTube increasingly returns "Sign in to confirm you're not a bot"
    # for data-center / VPN / WSL IPs. Pass cookies via one of these two
    # mutually exclusive channels to authenticate.
    yt_auth = p_yt.add_mutually_exclusive_group()
    yt_auth.add_argument(
        "--cookies",
        dest="cookies_path",
        default=None,
        help=(
            "Path to a Netscape-format cookies.txt file (export from your "
            "browser via a 'Get cookies.txt' extension while logged into "
            "YouTube). Bypasses YouTube's bot challenge."
        ),
    )
    yt_auth.add_argument(
        "--cookies-from-browser",
        dest="cookies_from_browser",
        default=None,
        help=(
            "Browser to read YouTube cookies from directly "
            "(e.g. chrome, firefox, edge, brave). Note: on WSL this often "
            "fails because the Windows browser's cookie store is outside "
            "the WSL filesystem; prefer --cookies on WSL."
        ),
    )

    return parser


def _build_source(args: argparse.Namespace) -> AudioSource:
    if args.source == "mic":
        return MicrophoneSource(input_device_index=args.device_index)
    if args.source == "file":
        return FileSource(path=args.path, realtime=args.realtime)
    if args.source == "url":
        return URLSource(url=args.url)
    if args.source == "stdin":
        return StdinSource()
    if args.source == "youtube":
        return YouTubeSource(
            url=args.url,
            format_selector=args.format,
            cookies_path=args.cookies_path,
            cookies_from_browser=args.cookies_from_browser,
        )
    raise ValueError(f"Unknown source: {args.source}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    source = _build_source(args)

    # Resolve the tenant_id for this run. If the user passed --tenant,
    # honour it; otherwise ask the server to mint one and register it
    # under this source name so `curl ...?source=<name>` will work.
    if args.tenant:
        tenant_id = args.tenant
        registered = False
    else:
        tenant_id = _register_session(server=args.server, source=args.source)
        registered = True

    print("=" * 60)
    print(f"  source:    {args.source}")
    print(f"  tenant_id: {tenant_id}")
    print(f"  server:    {args.server}")
    if registered:
        print(f"  curl:      curl \"{args.server.rstrip('/')}"
              f"/pop_first_transcript?source={args.source}\"")
    else:
        print(f"  curl:      curl \"{args.server.rstrip('/')}"
              f"/pop_first_transcript?tenant_id={tenant_id}\"")
    print("=" * 60)

    run(source=source, server=args.server, tenant_id=tenant_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
