"""Tests for the env-var helper functions and _parse_int_arg."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# _env_bool
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("off", False),
        ("garbage", False),
        ("", False),
    ],
)
def test_env_bool_parses_truthy_and_falsy(monkeypatch, ts, raw, expected):
    monkeypatch.setenv("X_TEST", raw)
    assert ts._env_bool("X_TEST", default=False) is expected


def test_env_bool_uses_default_when_missing(monkeypatch, ts):
    monkeypatch.delenv("X_TEST_MISSING", raising=False)
    assert ts._env_bool("X_TEST_MISSING", default=True) is True
    assert ts._env_bool("X_TEST_MISSING", default=False) is False


# ---------------------------------------------------------------------------
# _env_csv
# ---------------------------------------------------------------------------

def test_env_csv_strips_whitespace_and_drops_empty(monkeypatch, ts):
    monkeypatch.setenv("X_CSV", " a , b ,, c ")
    assert ts._env_csv("X_CSV", "x") == ["a", "b", "c"]


def test_env_csv_uses_default_when_missing(monkeypatch, ts):
    monkeypatch.delenv("X_CSV_MISSING", raising=False)
    assert ts._env_csv("X_CSV_MISSING", "alpha,beta") == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# _parse_int_arg
# ---------------------------------------------------------------------------

class _Args(dict):
    """Stand-in for werkzeug's MultiDict (only `.get()` is exercised)."""


def test_parse_int_arg_returns_default_when_missing(ts):
    assert ts._parse_int_arg(_Args(), "from", default=0) == 0


def test_parse_int_arg_parses_valid_int(ts):
    assert ts._parse_int_arg(_Args(**{"from": "42"}), "from") == 42


def test_parse_int_arg_aborts_400_on_invalid(ts):
    # `abort(400, ...)` raises a werkzeug HTTPException.
    from werkzeug.exceptions import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        ts._parse_int_arg(_Args(**{"from": "notanint"}), "from")
    assert exc_info.value.code == 400


def test_parse_int_arg_aborts_400_when_required_and_missing(ts):
    from werkzeug.exceptions import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        ts._parse_int_arg(_Args(), "from", required=True)
    assert exc_info.value.code == 400
