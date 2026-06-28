"""
Tests for the WebSocket streaming endpoint for _translate_stream_ws_handler()

flask-sock does not ship a WebSocket test client and its @sock.route decorator
returns None. We call the raw inner function directly
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest
from flask_jwt_extended import create_access_token



# Helpers

def _make_ws(max_connected: int = 1):
    """Return a MagicMock WS whose .connected attribute returns True exactly
    `max_connected` times before switching to False."""
    ws = MagicMock()
    sent: list[str] = []
    ws.send.side_effect = sent.append

    counter = [0]
    def _connected(self):
        counter[0] += 1
        return counter[0] <= max_connected
    type(ws).connected = property(_connected)
    return ws, sent



# Auth rejection 

class TestWebSocketAuth:
    def test_unauthenticated_sends_error_frame(self, ts):
        """Handler with no JWT cookie → error frame, no further frames."""
        from transcribe_server import _translate_stream_ws_handler as handler

        ws, sent = _make_ws(max_connected=0)

        with ts.app.test_request_context("/ws/v1/translate/stream?tenant_id=0000"):
            handler(ws)

        assert len(sent) == 1, f"Expected exactly 1 error frame, got: {sent}"
        frame = json.loads(sent[0])
        assert frame["status"] == "error"
        assert "authentication" in frame.get("message", "").lower()



# Authenticated handshake 

class TestWebSocketHandshake:
    def test_connected_frame_on_open(self, ts):
        """Valid admin JWT + known tenant → first frame is 'connected'.
        _assert_tenant_ownership is mocked — it is tested by its own dedicated tests.
        """
        from transcribe_server import _translate_stream_ws_handler as handler

        tenant_id = "ws-handshake-test"
        with ts.app.app_context():
            from auth.models import Organizer
            user = Organizer(email="wshandshake@localhost.com",
                             password_hash="dummy", is_admin=True)
            ts.db.session.add(user)
            ts.db.session.commit()
            token = create_access_token(identity=user.email)

        with ts.session_lock:
            ts.latest_session_by_source["mic"] = (tenant_id, time.time())

        ws, sent = _make_ws(max_connected=1)

        with ts.app.test_request_context(
            f"/ws/v1/translate/stream?tenant_id={tenant_id}&source=mic&last_chunk_id=0",
            headers={"Cookie": f"access_token_cookie={token}"},
        ):
            with patch("time.sleep"), \
                 patch("transcribe_server._assert_tenant_ownership"):  # ownership tested separately
                handler(ws)

        assert len(sent) >= 1, f"No frames sent at all: {sent}"
        first = json.loads(sent[0])
        assert first["status"] == "connected", f"Got {first} instead of connected frame"



    def test_missing_tenant_sends_error(self, ts):
        """Known source but no active session → error frame about missing tenant."""
        from transcribe_server import _translate_stream_ws_handler as handler

        # Ensure no session for 'stdin'
        with ts.session_lock:
            ts.latest_session_by_source["stdin"] = None

        with ts.app.app_context():
            from auth.models import Organizer
            user = Organizer(email="wsmissing@localhost.com",
                             password_hash="dummy", is_admin=True)
            ts.db.session.add(user)
            ts.db.session.commit()
            token = create_access_token(identity=user.email)

        ws, sent = _make_ws(max_connected=0)

        with ts.app.test_request_context(
            "/ws/v1/translate/stream?source=stdin",
            headers={"Cookie": f"access_token_cookie={token}"},
        ):
            handler(ws)

        assert len(sent) == 1
        frame = json.loads(sent[0])
        assert frame["status"] == "error"


# Transcript delivery

class TestWebSocketTranscriptDelivery:
    def test_transcript_delivered_in_first_poll(self, ts):
        """Seeded transcript appears as the second frame (after 'connected').
        _assert_tenant_ownership is mocked — it is tested by its own dedicated tests.
        """
        from transcribe_server import _translate_stream_ws_handler as handler

        tenant_id = "ws-tx-test"
        chunk_id = str(int(time.time() * 1000))

        with ts.app.app_context():
            from auth.models import Organizer
            user = Organizer(email="wstx2@localhost.com",
                             password_hash="dummy", is_admin=True)
            ts.db.session.add(user)
            ts.db.session.commit()
            token = create_access_token(identity=user.email)

        with ts.session_lock:
            ts.latest_session_by_source["mic"] = (tenant_id, time.time())
        with ts.transcripts_lock:
            ts.transcriptd[tenant_id] = {chunk_id: {"transcript": "WebSocket works!"}}

        ws, sent = _make_ws(max_connected=1)

        with ts.app.test_request_context(
            f"/ws/v1/translate/stream?tenant_id={tenant_id}&source=mic&last_chunk_id=0",
            headers={"Cookie": f"access_token_cookie={token}"},
        ):
            with patch("time.sleep"), \
                 patch("transcribe_server._assert_tenant_ownership"):  # ownership tested separately
                handler(ws)

        assert len(sent) >= 2, f"Expected ≥2 frames, got: {sent}"
        frames = [json.loads(s) for s in sent]
        assert frames[0]["status"] == "connected"

        transcript_frames = [f for f in frames if "chunk_id" in f]
        assert len(transcript_frames) >= 1
        assert transcript_frames[0]["chunk_id"] == chunk_id
        assert transcript_frames[0]["transcript"] == "WebSocket works!"
