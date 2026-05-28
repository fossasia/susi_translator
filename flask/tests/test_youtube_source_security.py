from __future__ import annotations

import pytest

from audio_sources import YouTubeSource


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/live/EXAMPLE_ID",
        "https://www.youtube-nocookie.com/embed/EXAMPLE_ID",
        # http (not https) is permitted at validation time; ffmpeg's
        # -protocol_whitelist still constrains what it will follow.
        "http://www.youtube.com/watch?v=dQw4w9WgXcQ",
    ],
)
def test_valid_youtube_urls_are_accepted(url):
    src = YouTubeSource(url)
    assert src._watch_url == url


@pytest.mark.parametrize(
    "bad_url, reason_substring",
    [
        ("", "non-empty"),
        ("file:///etc/passwd", "unsupported URL scheme"),
        ("concat:foo|bar", "unsupported URL scheme"),
        ("pipe:0", "unsupported URL scheme"),
        ("ftp://www.youtube.com/foo", "unsupported URL scheme"),
        ("-i evil", "must not start with '-'"),
        ("http://", "host"),
        # Non-YouTube hosts must be rejected even when otherwise valid.
        ("https://evil.example/watch?v=x", "not a recognised YouTube domain"),
        ("https://notyoutube.com/watch?v=x", "not a recognised YouTube domain"),
        # Look-alike host: youtube.com appears as a subdomain of an
        # attacker-controlled root. Exact-match allow-list rejects this.
        ("https://youtube.com.evil.example/watch?v=x", "not a recognised YouTube domain"),
    ],
)
def test_invalid_youtube_urls_are_rejected(bad_url, reason_substring):
    with pytest.raises(ValueError) as exc_info:
        YouTubeSource(bad_url)
    assert reason_substring in str(exc_info.value)


def test_non_string_input_is_rejected():
    with pytest.raises(ValueError):
        YouTubeSource(None)  # type: ignore[arg-type]


def test_validator_rejects_before_yt_dlp_or_ffmpeg_is_invoked():
    # Validator must run in __init__, not lazily in start(), so neither
    # yt-dlp nor ffmpeg are reached for bad input. (Asserted indirectly:
    # constructing the bad source raises before any side effect.)
    with pytest.raises(ValueError):
        YouTubeSource("https://evil.example/")


def test_cookies_options_are_mutually_exclusive():
    # Passing both cookies_path and cookies_from_browser is a caller
    # error: yt-dlp would silently honour only one, making misconfig
    # hard to debug. We surface it as ValueError at construct time.
    with pytest.raises(ValueError, match="at most one of"):
        YouTubeSource(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            cookies_path="/tmp/cookies.txt",
            cookies_from_browser="chrome",
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"cookies_path": "/tmp/cookies.txt"},
        {"cookies_from_browser": "chrome"},
        {},  # neither — current default, must still work
    ],
)
def test_cookies_either_or_neither_is_accepted(kwargs):
    # Each of the three valid configurations must construct without raising
    # (the file path is not validated in __init__; yt-dlp will raise at
    # start() time if it can't be read, matching FileSource's deferred
    # validation pattern).
    src = YouTubeSource("https://www.youtube.com/watch?v=dQw4w9WgXcQ", **kwargs)
    assert src._cookies_path == kwargs.get("cookies_path")
    assert src._cookies_from_browser == kwargs.get("cookies_from_browser")
