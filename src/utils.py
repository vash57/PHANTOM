"""Small, dependency-free utilities shared across PHANTOM.exe."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, IO, TextIO

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


def configure_stdio() -> None:
    """Use UTF-8 where possible and enable ANSI on Windows terminals."""

    for stream_name in ("stdout", "stderr", "stdin"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
    enable_windows_ansi()


def enable_windows_ansi() -> None:
    """Enable virtual-terminal processing on Windows without colorama."""

    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        # A terminal without VT support still works in plain mode.
        return


def supports_unicode(stream: TextIO | None = None) -> bool:
    stream = stream or sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        "█╭╮─╰╯◈".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def visible_width(text: str) -> int:
    """Best-effort monospace width (without a wcwidth dependency)."""

    width = 0
    for char in strip_ansi(text):
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def truncate(text: str, width: int, suffix: str = "...") -> str:
    if width <= 0:
        return ""
    text = text.replace("\n", " ")
    if visible_width(text) <= width:
        return text
    if len(suffix) >= width:
        return text[:width]
    return text[: width - len(suffix)].rstrip() + suffix


def wrap_plain(text: str, width: int) -> list[str]:
    """Wrap text while preserving explicit newlines."""

    import textwrap

    lines: list[str] = []
    for raw in text.splitlines() or [""]:
        if not raw:
            lines.append("")
            continue
        lines.extend(
            textwrap.wrap(
                raw,
                width=max(10, width),
                break_long_words=True,
                break_on_hyphens=False,
                replace_whitespace=False,
            )
            or [""]
        )
    return lines


def hex_to_ansi(color: str, background: bool = False) -> str:
    match = _HEX_RE.match(color.strip())
    if not match:
        return "\x1b[48;2;0;0;0m" if background else "\x1b[38;2;255;255;255m"
    value = match.group(1)
    red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    layer = 48 if background else 38
    return f"\x1b[{layer};2;{red};{green};{blue}m"


def ansi(
    text: str,
    color: str,
    *,
    bold: bool = False,
    dim: bool = False,
    italic: bool = False,
    underline: bool = False,
) -> str:
    codes = [hex_to_ansi(color)]
    if bold:
        codes.append("\x1b[1m")
    if dim:
        codes.append("\x1b[2m")
    if italic:
        codes.append("\x1b[3m")
    if underline:
        codes.append("\x1b[4m")
    return "".join(codes) + text + "\x1b[0m"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_timestamp(value: str) -> str:
    parsed = parse_iso(value)
    if parsed is None:
        return value or "unknown"
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            path.chmod(0o700)
        except OSError:
            pass


def atomic_write_json(path: Path, payload: Any, mode: int = 0o600) -> None:
    """Write JSON atomically, so an interrupted séance never corrupts memory."""

    ensure_private_dir(path.parent)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            try:
                temporary_path.chmod(mode)
            except OSError:
                pass
        os.replace(temporary_path, path)
    except BaseException:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def safe_session_id(value: str) -> str:
    """Reject path traversal and odd identifiers before touching the disk."""

    value = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError("Session ids may contain letters, digits, '-' and '_' only.")
    return value


def is_tty(stream: IO[Any] | None = None) -> bool:
    stream = stream or sys.stdout
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def is_wsl() -> bool:
    if os.name == "nt":
        return False
    try:
        return "microsoft" in Path("/proc/version").read_text(
            encoding="utf-8", errors="ignore"
        ).lower()
    except OSError:
        return False


def platform_label() -> str:
    if os.name == "nt":
        return "Windows"
    if sys.platform == "darwin":
        return "macOS"
    if is_wsl():
        return "Linux (WSL)"
    return "Linux"


def terminal_width(default: int = 80) -> int:
    try:
        return max(40, os.get_terminal_size().columns)
    except OSError:
        return default


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    return singular if count == 1 else (plural_form or singular + "s")


__all__ = [
    "configure_stdio",
    "enable_windows_ansi",
    "supports_unicode",
    "strip_ansi",
    "visible_width",
    "truncate",
    "wrap_plain",
    "hex_to_ansi",
    "ansi",
    "now_iso",
    "parse_iso",
    "format_timestamp",
    "ensure_private_dir",
    "atomic_write_json",
    "read_json",
    "safe_session_id",
    "is_tty",
    "is_wsl",
    "platform_label",
    "terminal_width",
    "plural",
]
