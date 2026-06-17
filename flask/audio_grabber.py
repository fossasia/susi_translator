"""
SUSI Translator audio grabber

Reads audio from one of five sources (microphone, file, URL, stdin,
YouTube), buffers up to ~10 seconds while resetting on silence, and POSTs
base64-encoded chunks to the transcription server's ``/transcripts``
endpoint
"""

from __future__ import annotations

import argparse
import base64
import os
import struct
import sys
import threading
import time
import uuid
import http.cookiejar
from typing import List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib3.exceptions import MaxRetryError
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from audio_sources import (
    AudioSource,
    FileSource,
    MicrophoneSource,
    StdinSource,
    URLSource,
    YouTubeSource,
)


RATE: int = 16000
SAMPLE_WIDTH: int = 2  # 16-bit
BUFFER_SIZE: int = 2 * 10 * RATE  # bytes -> 10 seconds of audio
SILENCE_THRESHOLD: int = 500

DEFAULT_SERVER: str = "http://localhost:5040"
VALID_SOURCES = ("mic", "file", "url", "stdin", "youtube")



def _is_silent(pcm_bytes: bytes) -> bool: # Return True if the loudest sample in ``pcm_bytes`` is below ``SILENCE_THRESHOLD``.
    if not pcm_bytes:
        return True
    n_samples = len(pcm_bytes) // SAMPLE_WIDTH
    if n_samples == 0:
        return True
    samples = struct.unpack("<%dh" % n_samples, pcm_bytes[: n_samples * SAMPLE_WIDTH])
    peak = max(abs(s) for s in samples)
    return peak < SILENCE_THRESHOLD

def _build_session(auth_cookie_path: Optional[str] = None, auth_token: Optional[str] = None) -> requests.Session: # Build a requests Session with retry/backoff for transient 5xx errors.
    retry_policy = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=frozenset(["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE", "POST"]),
    )
    adapter = HTTPAdapter(max_retries=retry_policy)
    session = requests.Session()
    session.verify = False
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    if auth_cookie_path:
        cj = http.cookiejar.MozillaCookieJar(auth_cookie_path)
        try:
            cj.load(ignore_discard=True, ignore_expires=True)
            session.cookies.update(cj)
        except Exception as e:
            print(f"Warning: could not load auth cookies from {auth_cookie_path}: {e}")
            
    if auth_token:
        print(f"DEBUG: Adding Authorization header with token: {auth_token[:10]}...")
        session.headers.update({"Authorization": f"Bearer {auth_token}"})
    else:
        print("DEBUG: NO auth_token provided to _build_session!")

    return session


class TranscribeUploader:
    """
    POSTs accumulated audio buffers to the transcription server
    """

    _EXPIRY_MINUTES: int = int(os.environ.get("INTERNAL_TOKEN_EXPIRY_MINUTES", "5"))
    # Refresh at 80% of the expiry window to give plenty of margin.
    _REFRESH_INTERVAL: float = _EXPIRY_MINUTES * 60 * 0.80

    def __init__(
        self,
        server: str,
        tenant_id: str,
        auth_cookie_path: Optional[str] = None,
        auth_token: Optional[str] = None,
    ) -> None:
        self._url: str = server.rstrip("/") + "/transcripts"
        self._refresh_url: str = server.rstrip("/") + "/internal/token-refresh"
        self._tenant_id: str = tenant_id
        self._session: requests.Session = _build_session(auth_cookie_path, auth_token)
        # Mutable token slot protected by a lock so the refresh thread and
        # the main upload thread don't race on cookie updates.
        self._token_lock = threading.Lock()
        self._current_token: Optional[str] = auth_token

        if auth_token:
            # Start the background refresh thread only when we have an
            # internal token to manage .
            self._start_refresh_thread()

    # Token refresh helpers
    def _update_token(self, new_token: str) -> None:
        """Thread-safe cookie slot update."""
        with self._token_lock:
            self._current_token = new_token
            self._session.headers.update({"Authorization": f"Bearer {new_token}"})

    def _refresh_token(self) -> bool:
        """
        Call /internal/token-refresh with the current token.
        Returns True on success, False on any failure.
        """
        with self._token_lock:
            current = self._current_token
        if not current:
            return False
        try:
            resp = requests.post(
                self._refresh_url,
                headers={"Authorization": f"Bearer {current}"},
                timeout=10,
                verify=False,
            )
            if resp.status_code == 200:
                new_token = resp.json().get("token")
                if new_token:
                    self._update_token(new_token)
                    print("[token-refresh] Internal token refreshed successfully.")
                    return True
            print(f"[token-refresh] Unexpected response {resp.status_code}: {resp.text}")
        except requests.exceptions.RequestException as exc:
            print(f"[token-refresh] Could not reach server: {exc}")
        return False

    def _refresh_loop(self) -> None:
        """Proactively refresh the token at 80% of its lifetime."""
        while True:
            time.sleep(self._REFRESH_INTERVAL)
            self._refresh_token()

    def _start_refresh_thread(self) -> None:
        t = threading.Thread(
            target=self._refresh_loop,
            name="token-refresh",
            daemon=True,  # dies automatically when the main process exits
        )
        t.start()

    # Chunk upload
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
            # New REST endpoint returns 202 Accepted, transcription is async;
            # older servers returned 200. Treat both as success.
            if response.status_code in (200, 202):
                print(f"Sent chunk {chunk_id} with {len(buffer)} bytes")
            elif response.status_code == 401 and self._current_token:
                # Defence-in-depth: token expired despite proactive refresh
                # Refresh immediately and retry once.
                print(f"[token-refresh] 401 on chunk {chunk_id} — refreshing token and retrying.")
                if self._refresh_token():
                    retry = self._session.post(
                        self._url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=30,
                    )
                    if retry.status_code in (200, 202):
                        print(f"Sent chunk {chunk_id} (after token refresh).")
                    else:
                        print(f"Error sending chunk after refresh: {retry.status_code}: {retry.text}")
                else:
                    print(f"Error: could not refresh token. Chunk {chunk_id} dropped.")
            else:
                print(f"Error sending chunk: {response.status_code}: {response.text}")
        except MaxRetryError:
            print("Error: Maximum retries exceeded. Could not connect to the endpoint.")
        except requests.exceptions.RequestException as exc:
            print(f"Error sending chunk: {exc}")


def _new_chunk_id() -> str: #Return a fresh chunk_id (milliseconds since epoch).
    return str(int(time.time() * 1000))


def _register_session(server: str, source: str, auth_cookie_path: Optional[str] = None, auth_token: Optional[str] = None) -> str:
    """
    Request a new tenant_id from the server.

    Calls POST /session with the source name and returns the generated
    tenant_id. Falls back to a local UUID if the server does not support
    the endpoint.
    """
    url = server.rstrip("/") + "/session"
    cookies = None
    if auth_cookie_path:
        cj = http.cookiejar.MozillaCookieJar(auth_cookie_path)
        try:
            cj.load(ignore_discard=True, ignore_expires=True)
            cookies = requests.cookies.RequestsCookieJar()
            cookies.update(cj)
        except Exception:
            pass
            
    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    try:
        response = requests.post(url, json={"source": source}, cookies=cookies, headers=headers, timeout=10, verify=False)
        # /session returns 201 Created on the REST server; older servers returned 200. Accept both.
        if response.status_code in (200, 201):
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


def run(source: AudioSource, server: str, tenant_id: str, auth_cookie_path: Optional[str] = None, auth_token: Optional[str] = None) -> None:
    """
    Drive one of the ``AudioSource`` implementations: read PCM in
    ~1-second chunks, apply silence-based buffering, and upload each
    running buffer to ``/transcripts``.
    """
    uploader = TranscribeUploader(server=server, tenant_id=tenant_id, auth_cookie_path=auth_cookie_path, auth_token=auth_token)
    buffer = bytearray()
    chunk_id: str = _new_chunk_id()

    try:
        source.start()
        for pcm in source.read_chunk():
            if _is_silent(pcm):
                # The buffer last sent is now the final state of this chunk on the server; reset locally and rotate.
                buffer = bytearray()
                chunk_id = _new_chunk_id()
                continue

            buffer.extend(pcm)

            # Always send the running buffer so the server has the latest.
            if buffer:
                uploader.send(bytes(buffer), chunk_id)

            # If the buffer is full, the chunk we just sent is final; start a new one on the next non-silent input.
            if len(buffer) >= BUFFER_SIZE:
                buffer = bytearray()
                chunk_id = _new_chunk_id()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        # Flush a final tail if a finite source ended mid-buffer, so the server has the complete final state of that chunk.
        if buffer:
            try:
                uploader.send(bytes(buffer), chunk_id)
            except Exception as exc:
                print(f"Error flushing final buffer: {exc}")
        try:
            source.stop()
        except Exception as exc:
            print(f"Error stopping source: {exc}")

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
    parser.add_argument(
        "--auth-cookie",
        default=None,
        help="Path to cookies.txt containing backend JWT auth cookie.",
    )
    parser.add_argument(
        "--auth-token",
        default=None,
        help="Raw JWT token to use for backend authentication.",
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
    # YouTube increasingly returns "Sign in to confirm you're not a bot" for data-center / VPN / WSL IPs. Pass cookies via one of these two mutually exclusive channels to authenticate.
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
    auth_token: Optional[str] = os.environ.get("GRABBER_AUTH_TOKEN") or args.auth_token

    # Resolve the tenant_id for this run.
    if args.tenant:
        tenant_id = args.tenant
        registered = False
    else:
        tenant_id = _register_session(
            server=args.server,
            source=args.source,
            auth_cookie_path=args.auth_cookie,
            auth_token=auth_token,
        )
        registered = True

    print("=" * 60)
    print(f"  source:    {args.source}")
    print(f"  tenant_id: {tenant_id}")
    print(f"  server:    {args.server}")
    if registered:
        print(f"  curl:      curl -X DELETE \"{args.server.rstrip('/')}"
              f"/transcripts/first?source={args.source}\"")
    else:
        print(f"  curl:      curl -X DELETE \"{args.server.rstrip('/')}"
              f"/transcripts/first?tenant_id={tenant_id}\"")
    print("=" * 60)

    run(
        source=source,
        server=args.server,
        tenant_id=tenant_id,
        auth_cookie_path=args.auth_cookie,
        auth_token=auth_token,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
