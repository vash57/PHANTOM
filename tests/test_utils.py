from __future__ import annotations

import os
from io import StringIO

from src.utils import (
    ansi,
    atomic_write_json,
    ensure_private_dir,
    format_timestamp,
    hex_to_ansi,
    is_tty,
    parse_iso,
    plural,
    read_json,
    safe_session_id,
    strip_ansi,
    terminal_width,
    truncate,
    visible_width,
    wrap_plain,
)


def test_strip_ansi_and_visible_width():
    coloured = ansi("ghost", "#39ff14", bold=True)

    assert strip_ansi(coloured) == "ghost"
    assert visible_width(coloured) == 5
    assert visible_width("界") == 2


def test_truncate_handles_narrow_widths_and_newlines():
    assert truncate("hello\nworld", 8) == "hello..."
    assert truncate("hello", 0) == ""
    assert truncate("hello", 2, suffix="..") == "he"


def test_wrap_plain_preserves_blank_lines():
    assert wrap_plain("one\n\ntwo", 20) == ["one", "", "two"]
    assert wrap_plain("a" * 30, 10)[0] == "a" * 10


def test_ansi_helpers_validate_hex_colours():
    assert hex_to_ansi("#39ff14") == "\x1b[38;2;57;255;20m"
    assert hex_to_ansi("not-a-colour") == "\x1b[38;2;255;255;255m"
    assert hex_to_ansi("#000000", background=True) == "\x1b[48;2;0;0;0m"


def test_iso_helpers_are_lenient():
    assert parse_iso("2026-01-01T00:00:00+00:00") is not None
    assert parse_iso("not a date") is None
    assert format_timestamp("not a date") == "not a date"
    assert format_timestamp("") == "unknown"


def test_safe_session_id_rejects_traversal():
    assert safe_session_id("  abc-123  ") == "abc-123"
    for value in ("", "../x", "a b", "a/b", "-leading"):
        try:
            safe_session_id(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted unsafe id: {value!r}")


def test_atomic_write_json_writes_private_file(tmp_path):
    path = tmp_path / "nested" / "session.json"

    atomic_write_json(path, {"message": "séance"})

    assert read_json(path) == {"message": "séance"}
    assert not list(path.parent.glob(".*.tmp"))
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


def test_ensure_private_dir_creates_directory(tmp_path):
    directory = tmp_path / "a" / "b"

    ensure_private_dir(directory)

    assert directory.is_dir()


def test_is_tty_and_terminal_width(monkeypatch):
    assert is_tty(StringIO()) is False

    monkeypatch.setattr(
        os, "get_terminal_size", lambda: os.terminal_size((120, 40))
    )
    assert terminal_width() == 120

    def broken():
        raise OSError("no terminal")

    monkeypatch.setattr(os, "get_terminal_size", broken)
    assert terminal_width(default=72) == 72


def test_plural():
    assert plural(1, "session") == "session"
    assert plural(0, "session") == "sessions"
    assert plural(2, "echo", "echoes") == "echoes"
