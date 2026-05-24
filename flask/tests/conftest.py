from __future__ import annotations

import os
import sys

import pytest

# Make `flask/` importable so tests can `import transcribe_server`.
_HERE = os.path.dirname(os.path.abspath(__file__))
_FLASK_DIR = os.path.abspath(os.path.join(_HERE, ".."))
if _FLASK_DIR not in sys.path:
    sys.path.insert(0, _FLASK_DIR)

# Pin env BEFORE importing transcribe_server (it reads these at import time).
# Override (not setdefault) so a developer's shell can't pull in heavy deps
# or flip on debug mode.
os.environ["WHISPER_SERVER_USE"] = "true"
os.environ["FLASK_DEBUG"] = "false"
os.environ["FLASK_HOST"] = "127.0.0.1"
os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:5040"
os.environ["SESSION_TTL_SECONDS"] = "7200"
os.environ["TRANSCRIBE_AUTOSTART_WORKER"] = "false"


@pytest.fixture
def ts():
    import transcribe_server as ts_mod

    ts_mod.transcriptd.clear()
    with ts_mod.session_lock:
        for key in list(ts_mod.latest_session_by_source.keys()):
            ts_mod.latest_session_by_source[key] = None

    while not ts_mod.audio_stack.empty():
        try:
            ts_mod.audio_stack.get_nowait()
            ts_mod.audio_stack.task_done()
        except Exception:
            break

    return ts_mod


@pytest.fixture
def client(ts):
    ts.app.config["TESTING"] = True
    with ts.app.test_client() as c:
        yield c
