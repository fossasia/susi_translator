

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# Helpers
_CONFIGURE_URL = "/api/v1/translate/configure"

_TRANSCRIPTION_BLOCK = {"provider_name": "dummy_stt"}


def _payload(stream_url=None, source_type=None, tenant_id="sec-test-tenant"):
    """Build a configure request payload."""
    body: dict = {
        "tenant_id": tenant_id,
        "transcription": _TRANSCRIPTION_BLOCK,
    }
    if stream_url is not None:
        body["stream_url"] = stream_url
    if source_type is not None:
        body["source_type"] = source_type
    return body


# Fixtures

@pytest.fixture(autouse=True)
def mock_registry(ts):
    """Stub out registry.configure so no real model is loaded."""
    with patch.object(ts.registry, "configure"):
        yield


# YouTube source(bad URLs must be rejected BEFORE Popen)

@pytest.mark.parametrize("bad_url, expected_fragment", [
    ("file:///etc/passwd",              "unsupported URL scheme"),
    ("concat:foo|bar",                  "unsupported URL scheme"),
    ("ftp://www.youtube.com/watch?v=x", "unsupported URL scheme"),
    ("pipe:0",                          "unsupported URL scheme"),
    ("-i evil_flag",                    "must not start with '-'"),
    ("http://",                         "host"),
    ("https://evil.example/watch?v=x",  "not a recognised YouTube domain"),
    ("https://notyoutube.com/live/abc", "not a recognised YouTube domain"),
    # Subdomain lookalike: youtube.com is a subdomain of attacker root.
    ("https://youtube.com.evil.example/watch?v=x", "not a recognised YouTube domain"),
])
def test_youtube_bad_stream_url_returns_400_without_spawning(
    client, bad_url, expected_fragment
):
    """Bad YouTube stream_url must fail at the API boundary (HTTP 400) without
    ever calling subprocess.Popen."""

    with patch("transcribe_server.subprocess.Popen") as mock_popen:
        resp = client.post(_CONFIGURE_URL, json=_payload(stream_url=bad_url))

    assert resp.status_code == 400, (
        f"Expected 400 for {bad_url!r}, got {resp.status_code}"
    )
    body = resp.get_json()
    assert body["status"] == "error"
    assert expected_fragment in body["message"], (
        f"Expected {expected_fragment!r} in message: {body['message']!r}"
    )
    mock_popen.assert_not_called(), "Popen must NOT be called for invalid URLs"


# YouTube source(good URLs must proceed to Popen)

@pytest.mark.parametrize("good_url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://m.youtube.com/live/EXAMPLE_ID",
    "https://music.youtube.com/watch?v=EXAMPLE_ID",
    "https://www.twitch.tv/somestream",
    "https://vimeo.com/123456789",
])
def test_youtube_good_stream_url_spawns_grabber(client, good_url):
    """Valid YouTube/allowlisted stream_url must reach subprocess.Popen exactly once."""
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    with patch("transcribe_server.subprocess.Popen", return_value=mock_proc) as mock_popen:
        resp = client.post(_CONFIGURE_URL, json=_payload(stream_url=good_url))

    assert resp.status_code == 200, (
        f"Expected 200 for {good_url!r}, got {resp.status_code}: {resp.get_json()}"
    )
    mock_popen.assert_called_once()
    cmd_args = mock_popen.call_args[0][0]  # first positional arg is the argv list
    assert good_url in cmd_args, (
        f"stream_url must be passed as a list element, not a shell string. "
        f"cmd was: {cmd_args!r}"
    )



# URL source(bad URLs must be rejected BEFORE Popen)

@pytest.mark.parametrize("bad_url, expected_fragment", [
    ("file:///etc/passwd",   "unsupported URL scheme"),
    ("ftp://example.com/f",  "unsupported URL scheme"),
    ("pipe:0",               "unsupported URL scheme"),
    ("-i evil.mp3",          "must not start with '-'"),
    ("http://",              "host"),
])
def test_url_source_bad_stream_url_returns_400_without_spawning(
    client, bad_url, expected_fragment
):
    """Bad stream_url for source_type='url' must fail at the API boundary without Popen."""
    with patch("transcribe_server.subprocess.Popen") as mock_popen:
        resp = client.post(
            _CONFIGURE_URL,
            json=_payload(stream_url=bad_url, source_type="url"),
        )

    assert resp.status_code == 400, (
        f"Expected 400 for url source {bad_url!r}, got {resp.status_code}"
    )
    body = resp.get_json()
    assert body["status"] == "error"
    assert expected_fragment in body["message"]
    mock_popen.assert_not_called()


# URL source(good URLs must proceed to Popen)

@pytest.mark.parametrize("good_url", [
    "https://example.com/stream.mp3",
    "http://radio.example.org:8080/live.m3u8",
    "https://cdn.example.com/hls/playlist.m3u8",
])
def test_url_source_good_stream_url_spawns_grabber(client, good_url):
    """Valid HTTP/HTTPS stream URL for source_type='url' must reach Popen."""
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    with patch("transcribe_server.subprocess.Popen", return_value=mock_proc) as mock_popen:
        resp = client.post(
            _CONFIGURE_URL,
            json=_payload(stream_url=good_url, source_type="url"),
        )

    assert resp.status_code == 200, (
        f"Expected 200 for {good_url!r}, got {resp.status_code}: {resp.get_json()}"
    )
    mock_popen.assert_called_once()


# source_type validation

def test_unknown_source_type_returns_400_without_spawning(client):
    """An unrecognised source_type must return HTTP 400 immediately."""
    with patch("transcribe_server.subprocess.Popen") as mock_popen:
        resp = client.post(
            _CONFIGURE_URL,
            json=_payload(
                stream_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                source_type="microphone",  # not a valid source_type for stream_url
            ),
        )

    assert resp.status_code == 400
    body = resp.get_json()
    assert body["status"] == "error"
    assert "source_type" in body["message"] or "Unknown" in body["message"]
    mock_popen.assert_not_called()


def test_default_source_type_is_youtube(client):
    """Omitting source_type must default to 'youtube' (backward compatibility)."""
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    with patch("transcribe_server.subprocess.Popen", return_value=mock_proc) as mock_popen:
        # Valid YouTube URL, no source_type field — must succeed with the YouTube validator.
        resp = client.post(
            _CONFIGURE_URL,
            json=_payload(stream_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        )

    assert resp.status_code == 200
    mock_popen.assert_called_once()
    # The subcommand passed to audio_grabber must be 'youtube'.
    cmd_args = mock_popen.call_args[0][0]
    assert "youtube" in cmd_args


def test_default_source_type_rejects_non_youtube_host(client):
    """Without source_type, a plain HTTPS URL to a non-YouTube host must be rejected
    (the youtube validator is the default)."""
    with patch("transcribe_server.subprocess.Popen") as mock_popen:
        resp = client.post(
            _CONFIGURE_URL,
            json=_payload(stream_url="https://example.com/stream.mp3"),
        )

    assert resp.status_code == 400
    mock_popen.assert_not_called()


# No stream_url(Popen must not be called)

def test_no_stream_url_does_not_spawn_grabber(client):
    """When stream_url is absent, configure_provider must NOT spawn any subprocess."""
    with patch("transcribe_server.subprocess.Popen") as mock_popen:
        resp = client.post(_CONFIGURE_URL, json=_payload())

    assert resp.status_code == 200
    mock_popen.assert_not_called()
