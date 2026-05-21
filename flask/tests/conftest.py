"""
Pytest configuration for the Flask backend tests.

Goals
-----
1. Make ``flask/`` importable so tests can ``import transcribe_server`` and
   ``import audio_sources`` directly.
2. Avoid downloading or loading multi-hundred-megabyte whisper models when
   the test process imports ``transcribe_server``. We set
   ``WHISPER_SERVER_USE=true`` BEFORE the module is imported. The whisper
   server itself is never contacted in unit tests; integration tests that
   exercise the worker monkey-patch ``_whisper_server_transcribe``.
3. Reset module-level state (``transcriptd``, ``audio_stack``,
   ``latest_session_by_source``) between tests so they cannot leak into
   each other.
"""

from __future__ import annotations

import os
import sys

import pytest

# --- 1. Make `flask/` importable ------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_FLASK_DIR = os.path.abspath(os.path.join(_HERE, ".."))
if _FLASK_DIR not in sys.path:
    sys.path.insert(0, _FLASK_DIR)

# --- 2. Pin env vars BEFORE importing transcribe_server -------------------
# The module reads these at import time, so they must be set first.
# We OVERRIDE rather than setdefault so the test environment is hermetic
# (the developer's shell or local .env cannot accidentally pull in heavy
# whisper/torch deps or flip on debug mode).
os.environ["WHISPER_SERVER_USE"] = "true"
os.environ["FLASK_DEBUG"] = "false"
os.environ["FLASK_HOST"] = "127.0.0.1"
os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:5040"
os.environ["SESSION_TTL_SECONDS"] = "7200"
# Don't auto-start the audio worker thread during tests. The tests that
# enqueue payloads inspect the queue directly; a real worker would race
# with them and try to call out to a whisper.cpp server that isn't running.
os.environ["TRANSCRIBE_AUTOSTART_WORKER"] = "false"


@pytest.fixture
def ts():
    """
    Import (or re-use) the transcribe_server module and reset its
    module-level mutable state so each test starts from a clean slate.
    """
    import transcribe_server as ts_mod

    # Reset shared state.
    ts_mod.transcriptd.clear()
    with ts_mod.session_lock:
        for key in list(ts_mod.latest_session_by_source.keys()):
            ts_mod.latest_session_by_source[key] = None

    # Drain any leftover items from the audio_stack and reset task counters.
    while not ts_mod.audio_stack.empty():
        try:
            ts_mod.audio_stack.get_nowait()
            ts_mod.audio_stack.task_done()
        except Exception:
            break

    return ts_mod


@pytest.fixture
def client(ts):
    """A Flask test client bound to the live `app` from transcribe_server."""
    ts.app.config["TESTING"] = True
    with ts.app.test_client() as c:
        yield c
