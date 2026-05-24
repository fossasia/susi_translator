"""
Audio source abstractions for the SUSI Translator audio grabber.

This module defines an ``AudioSource`` abstract base class plus four concrete
implementations:

    - ``MicrophoneSource`` : live capture from a system microphone (PyAudio).
    - ``FileSource``       : decode a local audio file (pydub; requires ffmpeg).
    - ``URLSource``        : decode a remote HTTP(S) audio stream (ffmpeg).
    - ``StdinSource``      : read raw 16-bit / 16 kHz / mono PCM from stdin.

All sources MUST yield 16 kHz, 16-bit signed little-endian, mono PCM bytes.

System requirements
-------------------
- ``MicrophoneSource`` : PyAudio + a working input device.
- ``FileSource``       : the ``pydub`` Python package and the ``ffmpeg``
                         binary on PATH (pydub shells out to it for any
                         non-WAV input).
- ``URLSource``        : the ``ffmpeg`` binary on PATH.
- ``StdinSource``      : none beyond the standard library. The caller is
                         responsible for delivering audio in the required
                         raw PCM format.

Each source's ``read_chunk()`` yields ~1 second of audio per iteration
(``CHUNK_BYTES`` bytes) so the orchestrator can apply uniform silence
detection and buffering.
"""

from __future__ import annotations

import subprocess
import sys
import time
import queue
from abc import ABC, abstractmethod
from typing import Generator, Optional
from urllib.parse import urlparse


# Protocols ffmpeg is permitted to use when decoding a remote URL. Anything
# outside this set (notably ``file``, ``concat``, ``pipe``, ``subfile`` and
# friends) could be abused to read local resources, so it is rejected via
# ffmpeg's ``-protocol_whitelist`` option.
_ALLOWED_URL_SCHEMES: frozenset[str] = frozenset({"http", "https"})
_FFMPEG_PROTOCOL_WHITELIST: str = "http,https,tcp,tls,crypto"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_up_to(stream, n: int) -> bytes:
    """
    Read up to ``n`` bytes from a binary stream, looping over short reads.

    Returns fewer than ``n`` bytes only on EOF.
    """
    buf = bytearray()
    while len(buf) < n:
        piece = stream.read(n - len(buf))
        if not piece:
            break  # EOF
        buf.extend(piece)
    return bytes(buf)


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class AudioSource(ABC):
    """
    Abstract base class for an audio source.

    Output format (REQUIRED for every implementation)
    -------------------------------------------------
    All concrete sources MUST emit raw PCM with this exact format:

        sample rate    : 16 000 Hz
        sample width   : 2 bytes (16-bit signed little-endian)
        channels       : 1 (mono)

    Lifecycle
    ---------
    - ``start()`` opens the underlying resource (mic, file, network, ...).
    - ``read_chunk()`` is a generator yielding ~1 second of PCM bytes per
      iteration. It terminates when the source is exhausted or ``stop()``
      has been called.
    - ``stop()`` releases resources. It MUST be safe to call even if
      ``start()`` was never called, and safe to call multiple times.

    Conventions
    -----------
    1 chunk == ``SAMPLE_RATE`` samples == ``SAMPLE_RATE * SAMPLE_WIDTH``
    bytes. Implementations may yield a final partial chunk if the source
    ends mid-second.
    """

    SAMPLE_RATE: int = 16000
    SAMPLE_WIDTH: int = 2  # 16-bit
    CHANNELS: int = 1
    CHUNK_BYTES: int = SAMPLE_RATE * SAMPLE_WIDTH  # 1 second of audio

    @abstractmethod
    def start(self) -> None:
        """Open / initialize the underlying resource."""

    @abstractmethod
    def stop(self) -> None:
        """
        Release the underlying resource.

        MUST NOT raise even if ``start()`` was never called, and MUST be
        safe to call multiple times.
        """

    @abstractmethod
    def read_chunk(self) -> Generator[bytes, None, None]:
        """
        Yield raw PCM frames in ~1-second chunks (``CHUNK_BYTES`` bytes
        each, except possibly the last chunk for finite sources).
        """

    # Convenience context-manager support: ``with SomeSource(...) as src:``
    def __enter__(self) -> "AudioSource":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()


# ---------------------------------------------------------------------------
# MicrophoneSource
# ---------------------------------------------------------------------------

class MicrophoneSource(AudioSource):
    """
    Capture live audio from a microphone via PyAudio.

    System requirements
    -------------------
    - PyAudio installed (``pip install pyaudio``).
    - A working input device.

    Yields 1-second chunks of 16 kHz / 16-bit / mono PCM bytes. PyAudio is
    callback-driven, so internally we push frames into a queue and
    ``read_chunk()`` drains the queue. This decouples the audio thread from
    the orchestrator and gives the same pull-style generator interface as
    the other sources.
    """

    def __init__(self, input_device_index: Optional[int] = None) -> None:
        self._input_device_index: Optional[int] = input_device_index
        self._audio = None  # type: ignore[assignment]
        self._stream = None  # type: ignore[assignment]
        self._queue: "queue.Queue[bytes]" = queue.Queue()
        self._running: bool = False
        self._pa_continue: int = 0  # set on start() to pyaudio.paContinue

    def start(self) -> None:
        # Imported lazily so that other sources work even if PyAudio is
        # unavailable on the host (e.g. headless server with no audio libs).
        import pyaudio

        self._pa_continue = pyaudio.paContinue
        self._audio = pyaudio.PyAudio()
        self._stream = self._audio.open(
            format=pyaudio.paInt16,
            channels=self.CHANNELS,
            rate=self.SAMPLE_RATE,
            input=True,
            input_device_index=self._input_device_index,
            frames_per_buffer=self.SAMPLE_RATE,  # 1 second per callback
            stream_callback=self._callback,
        )
        self._running = True
        self._stream.start_stream()

    def _callback(self, in_data, frame_count, time_info, status):  # type: ignore[no-untyped-def]
        # PyAudio callback signature is fixed; we just enqueue and continue.
        if self._running and in_data:
            self._queue.put(in_data)
        return (None, self._pa_continue)

    def read_chunk(self) -> Generator[bytes, None, None]:
        # Block on the queue with a small timeout so stop() is responsive.
        while self._running:
            try:
                chunk = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if chunk:
                yield chunk

    def stop(self) -> None:
        # Idempotent and exception-safe: must not raise even if start() was
        # never called.
        self._running = False
        stream = self._stream
        audio = self._audio
        self._stream = None
        self._audio = None
        if stream is not None:
            try:
                stream.stop_stream()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        if audio is not None:
            try:
                audio.terminate()
            except Exception:
                pass
        # Drain the queue so a fresh start() starts clean.
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass


# ---------------------------------------------------------------------------
# FileSource
# ---------------------------------------------------------------------------

class FileSource(AudioSource):
    """
    Read audio from a local file (any format pydub/ffmpeg can decode).

    System requirements
    -------------------
    - The ``pydub`` Python package (``pip install pydub``).
    - The ``ffmpeg`` binary on PATH (pydub shells out to it for any
      format other than WAV).

    The file is decoded once on ``start()``, downmixed to mono, resampled
    to 16 kHz, and converted to 16-bit signed PCM in memory.
    ``read_chunk()`` then yields 1-second slices of that PCM buffer.

    Args
    ----
    path
        Path to the audio file.
    realtime
        If True, throttle yields so playback runs at wall-clock speed
        (useful to simulate a live microphone for testing). If False,
        yields as fast as the consumer reads.
    """

    def __init__(self, path: str, realtime: bool = False) -> None:
        self._path: str = path
        self._realtime: bool = realtime
        self._pcm: bytes = b""
        self._running: bool = False

    def start(self) -> None:
        from pydub import AudioSegment  # imported lazily

        seg = AudioSegment.from_file(self._path)
        seg = (
            seg.set_frame_rate(self.SAMPLE_RATE)
               .set_channels(self.CHANNELS)
               .set_sample_width(self.SAMPLE_WIDTH)
        )
        self._pcm = seg.raw_data
        self._running = True

    def read_chunk(self) -> Generator[bytes, None, None]:
        offset: int = 0
        chunk_bytes: int = self.CHUNK_BYTES
        total: int = len(self._pcm)
        while self._running and offset < total:
            chunk = self._pcm[offset:offset + chunk_bytes]
            offset += len(chunk)
            yield chunk
            if self._realtime:
                # 1 chunk ~= 1 second; sleep proportional to actual length.
                time.sleep(len(chunk) / float(chunk_bytes))
        self._running = False

    def stop(self) -> None:
        # No external resources to release; just clear state.
        self._running = False
        self._pcm = b""


# ---------------------------------------------------------------------------
# URLSource
# ---------------------------------------------------------------------------

class URLSource(AudioSource):
    """
    Decode a remote audio stream (HTTP/HTTPS URL, including live streams)
    by piping it through ``ffmpeg``.

    System requirements
    -------------------
    - The ``ffmpeg`` binary on PATH.

    ``ffmpeg`` is invoked once on ``start()`` and produces a continuous
    stream of 16 kHz / 16-bit / mono PCM on stdout. ``read_chunk()`` reads
    1 second per iteration until ffmpeg exits or ``stop()`` is called.
    """

    def __init__(self, url: str) -> None:
        self._url: str = self._validate_url(url)
        self._proc: Optional[subprocess.Popen] = None
        self._running: bool = False

    @staticmethod
    def _validate_url(url: str) -> str:
        """
        Enforce that ``url`` is a well-formed HTTP(S) URL before it is ever
        handed to ffmpeg.

        This is the first line of defence against the security audit
        finding on the ``subprocess.Popen`` call below: by the time the
        URL reaches ffmpeg we have already guaranteed it is not an option
        flag (e.g. ``-something``) and not a non-network scheme such as
        ``file://`` or ``concat:`` that could be used to read local
        resources.
        """
        if not isinstance(url, str) or not url:
            raise ValueError("URLSource: url must be a non-empty string")
        # Reject anything that could be parsed as an option flag by ffmpeg
        # before the scheme check, just to be explicit.
        if url.startswith("-"):
            raise ValueError("URLSource: url must not start with '-'")
        parsed = urlparse(url)
        if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES:
            raise ValueError(
                f"URLSource: unsupported URL scheme {parsed.scheme!r}; "
                f"allowed schemes are {sorted(_ALLOWED_URL_SCHEMES)}"
            )
        if not parsed.netloc:
            raise ValueError("URLSource: url must include a host")
        return url

    def start(self) -> None:
        # SECURITY: ``self._url`` has been validated by ``_validate_url`` to
        # be an http(s) URL with a host and no leading ``-``. We invoke
        # ffmpeg with a fixed argv list (``shell=False``) and additionally
        # pass ``-protocol_whitelist`` so ffmpeg itself refuses any nested
        # redirect to a non-network protocol. This addresses the static
        # analysis warning about a non-static argument to ``subprocess.Popen``.
        cmd = [
            "ffmpeg",
            "-loglevel", "error",
            "-protocol_whitelist", _FFMPEG_PROTOCOL_WHITELIST,
            "-i", self._url,
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ac", str(self.CHANNELS),
            "-ar", str(self.SAMPLE_RATE),
            "-",  # write to stdout
        ]
        self._proc = subprocess.Popen(  # noqa: S603  # validated argv, shell=False
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        self._running = True

    def read_chunk(self) -> Generator[bytes, None, None]:
        if self._proc is None or self._proc.stdout is None:
            return
        chunk_bytes: int = self.CHUNK_BYTES
        stream = self._proc.stdout
        while self._running:
            buf = _read_up_to(stream, chunk_bytes)
            if not buf:
                break  # ffmpeg exited / stream ended
            yield buf
        self._running = False

    def stop(self) -> None:
        self._running = False
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=2.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# StdinSource
# ---------------------------------------------------------------------------

class StdinSource(AudioSource):
    """
    Read raw 16 kHz / 16-bit / mono PCM from standard input.

    Useful for piping arbitrary tools into the grabber, e.g.::

        ffmpeg -i input.flac -f s16le -ac 1 -ar 16000 - | \\
            python audio_grabber.py stdin --server http://localhost:5040

    System requirements
    -------------------
    None beyond the standard library. The caller is responsible for
    delivering audio in the required raw PCM format; this source does no
    decoding or resampling of its own.
    """

    def __init__(self) -> None:
        self._running: bool = False
        self._stream = None  # type: ignore[assignment]

    def start(self) -> None:
        # Use the underlying binary buffer to avoid newline translation
        # on Windows.
        self._stream = sys.stdin.buffer
        self._running = True

    def read_chunk(self) -> Generator[bytes, None, None]:
        if self._stream is None:
            return
        chunk_bytes: int = self.CHUNK_BYTES
        while self._running:
            buf = _read_up_to(self._stream, chunk_bytes)
            if not buf:
                break  # EOF
            yield buf
        self._running = False

    def stop(self) -> None:
        # We never own stdin; just clear state.
        self._running = False
        self._stream = None
