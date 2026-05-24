from __future__ import annotations

import pytest

from audio_sources import URLSource


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/stream.mp3",
        "https://example.com/live.m3u8",
        "https://user:pass@example.com:8080/path?query=1",
    ],
)
def test_valid_urls_are_accepted(url):
    src = URLSource(url)
    assert src._url == url


@pytest.mark.parametrize(
    "bad_url, reason_substring",
    [
        ("", "non-empty"),
        ("file:///etc/passwd", "unsupported URL scheme"),
        ("concat:foo|bar", "unsupported URL scheme"),
        ("pipe:0", "unsupported URL scheme"),
        ("ftp://example.com/file", "unsupported URL scheme"),
        ("subfile:foo", "unsupported URL scheme"),
        ("-i evil.mp3", "must not start with '-'"),
        ("http://", "host"),
    ],
)
def test_invalid_urls_are_rejected(bad_url, reason_substring):
    with pytest.raises(ValueError) as exc_info:
        URLSource(bad_url)
    assert reason_substring in str(exc_info.value)


def test_non_string_input_is_rejected():
    with pytest.raises(ValueError):
        URLSource(None)  # type: ignore[arg-type]


def test_validator_rejects_before_subprocess_is_started():
    # Validator must run in __init__, not lazily in start(), so Popen is
    # never reached for bad input.
    with pytest.raises(ValueError):
        URLSource("file:///etc/passwd")
