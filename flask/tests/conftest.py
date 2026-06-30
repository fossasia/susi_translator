from __future__ import annotations

import os
import sys

import pytest
from flask_jwt_extended import create_access_token

# Make `flask/` importable so tests can `import transcribe_server`.
_HERE = os.path.dirname(os.path.abspath(__file__))
_FLASK_DIR = os.path.abspath(os.path.join(_HERE, ".."))
if _FLASK_DIR not in sys.path:
    sys.path.insert(0, _FLASK_DIR)

os.environ["WHISPER_SERVER_USE"] = "true"
os.environ["FLASK_DEBUG"] = "false"
os.environ["FLASK_HOST"] = "127.0.0.1"
os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:5040"
os.environ["SESSION_TTL_SECONDS"] = "7200"
os.environ["TRANSCRIBE_AUTOSTART_WORKER"] = "false"
os.environ["JWT_SECRET_KEY"] = "testing-secret-key-that-is-long-enough"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"


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

    with ts_mod.grabber_lock:
        ts_mod.grabber_processes.clear()

    return ts_mod


@pytest.fixture(autouse=True)
def setup_db(ts):
    """Ensure every test runs on a fresh, isolated in-memory database."""
    ts.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with ts.app.app_context():
        ts.db.create_all()
        yield
        ts.db.session.remove()
        ts.db.drop_all()


@pytest.fixture
def unauth_client(ts):
    """An unauthenticated test client."""
    ts.app.config["TESTING"] = True
    with ts.app.test_client() as c:
        yield c


@pytest.fixture
def client(ts):
    """An automatically authenticated test client acting as an admin."""
    ts.app.config["TESTING"] = True
    with ts.app.test_client() as c:
        with ts.app.app_context():
            from auth.models import Organizer
            user = Organizer(email="testadmin@localhost.com", password_hash="dummy", is_admin=True)
            ts.db.session.add(user)
            ts.db.session.commit()
            
            token = create_access_token(identity=user.email)
            c.set_cookie('access_token_cookie', token)
        yield c
