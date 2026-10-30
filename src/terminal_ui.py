"""Terminal rendering for PHANTOM.exe.

Rich is used when available for panels and tables.  Every text path also has a
dependency-free ANSI/plain fallback, and streaming output is written directly
so token boundaries never disturb terminal wrapping.
"""

from __future__ import annotations

import builtins
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence, TextIO

from src import __version__
from src.effects import Effects
from src.personality import Personality
from src.themes import Theme, get_theme
from src.utils import (
    ansi,
    format_timestamp,
    is_tty as stream_is_tty,
    supports_unicode,
    terminal_width,
    truncate,
    visible_width,
    wrap_plain,
)

try:  # pragma: no cover - exercised implicitly by both branches
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.theme import Theme as RichTheme
    from rich.box import SIMPLE, ROUNDED

    RICH_AVAILABLE = True
except ImportError:  # pragma: no cover - fallback is covered with force_plain
    Console = None  # type: ignore[assignment]
    Panel = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment]
    Text = None  # type: ignore[assignment]
    RichTheme = None  # type: ignore[assignment]
    SIMPLE = ROUNDED = None  # type: ignore[assignment]
    RICH_AVAILABLE = False

ASSET_DIR = Path(__file__).resolve().parent / "assets"
LOGO_PATH = ASSET_DIR / "phantom_logo.txt"

COMPACT_LOGO = (
    "   .-.",
    "  (o o)   P H A N T O M . e x e",
    "  | O \\   the ghost living inside your terminal",
    "   \\   \\",
    "    `~~~`",
)


@lru_cache(maxsize=1)
def _big_logo() -> tuple[str, ...]:
    try:
        lines = LOGO_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return tuple(lines)


def _mix_hex(first: str, second: str, amount: float) -> str:
    def parse(value: str) -> tuple[int, int, int]:
        value = value.lstrip("#")
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]

    amount = max(0.0, min(1.0, amount))
    left = parse(first)
    right = parse(second)
    mixed = tuple(round(a + (b - a) * amount) for a, b in zip(left, right))
    return "#{:02x}{:02x}{:02x}".format(*mixed)


class TerminalUI:
    """A small semantic renderer shared by the app, commands and effects."""

    def __init__(
        self,
        theme: Theme | str = "phosphor",
        effects: Effects | None = None,
        *,
        output: TextIO | None = None,
        input_fn: Callable[[str], str] | None = None,
        force_plain: bool = False,
        force_color: bool | None = None,
        width: int | None = None,
        max_panel_width: int = 100,
    ) -> None:
        self._file = output or sys.stdout
        self.theme = get_theme(theme) if isinstance(theme, str) else theme
        self.effects = effects or Effects()
        self._input = input_fn or builtins.input
        self.use_rich = RICH_AVAILABLE and not force_plain
        self.is_tty = stream_is_tty(self._file)
        self.unicode = supports_unicode(self._file)
        self.max_panel_width = max_panel_width
        self._width_override = width

        if force_color is None:
            color_enabled = (
                self.is_tty
                and os.environ.get("NO_COLOR") is None
                and os.environ.get("TERM", "") != "dumb"
            )
        else:
            color_enabled = bool(force_color)
        self.color_enabled = color_enabled

        self._console = self._make_console()

    # ------------------------------------------------------------------ setup
    def _rich_theme(self) -> Any:
        if not RICH_AVAILABLE:
            return None
        return RichTheme(
            {
                "phantom.primary": self.theme.primary,
                "phantom.secondary": self.theme.secondary,
                "phantom.accent": self.theme.accent,
                "phantom.warning": self.theme.warning,
                "phantom.muted": self.theme.muted,
                "phantom.border": self.theme.border,
                "phantom.surface": self.theme.surface,
            }
        )

    def _make_console(self) -> Any:
        if not self.use_rich:
            return None
        return Console(
            file=self._file,
            theme=self._rich_theme(),
            highlight=False,
            soft_wrap=False,
            width=self._width_override,
            no_color=not self.color_enabled,
            force_terminal=True if self.color_enabled else None,
            color_system="truecolor" if self.color_enabled else None,
            legacy_windows=False,
        )

    @property
    def width(self) -> int:
        if self._width_override:
            return self._width_override
        if self.use_rich and self._console is not None:
            return int(self._console.width)
        return terminal_width()

    def set_theme(self, theme: Theme | str) -> Theme:
        self.theme = get_theme(theme) if isinstance(theme, str) else theme
        self._console = self._make_console()
        return self.theme

    # --------------------------------------------------------------- painting
    def _paint(
        self,
        text: str,
        style: str,
        *,
        bold: bool = False,
        dim: bool = False,
        italic: bool = False,
    ) -> str:
        if not self.color_enabled or not text:
            return text
        return ansi(
            text,
            self.theme.color(style),
            bold=bold,
            dim=dim,
            italic=italic,
        )

    def write(
        self,
        text: str,
        style: str = "primary",
        *,
        bold: bool = False,
        dim: bool = False,
        italic: bool = False,
    ) -> None:
        self._file.write(
            self._paint(text, style, bold=bold, dim=dim, italic=italic)
        )

    def line(
        self,
        text: str = "",
        style: str = "primary",
        *,
        bold: bool = False,
        dim: bool = False,
        italic: bool = False,
    ) -> None:
        self.write(text, style, bold=bold, dim=dim, italic=italic)
        self._file.write("\n")

    def flush(self) -> None:
        try:
            self._file.flush()
        except (AttributeError, ValueError):
            pass

    def clear_line(self) -> None:
        if self.is_tty:
            self._file.write("\r\x1b[2K")

    def blank(self, count: int = 1) -> None:
        for _ in range(count):
            self._file.write("\n")

    # ---------------------------------------------------------------- surface
    def clear_screen(self) -> None:
        if self.use_rich and self.is_tty:
            self._console.clear()
        elif self.is_tty:
            self._file.write("\x1b[2J\x1b[3J\x1b[H")
            self.flush()
        else:
            self.blank(2)

    def rule(self, label: str = "") -> None:
        width = min(self.width, self.max_panel_width)
        if self.use_rich:
            from rich.rule import Rule

            self._console.print(
                Rule(
                    Text(label, style=f"bold {self.theme.accent}") if label else None,
                    style=self.theme.border,
                    characters="─" if self.unicode else "-",
                )
            )
            self.flush()
            return
        glyph = "─" if self.unicode else "-"
        if label:
            inner = f" {label} "
            remaining = max(0, width - visible_width(inner) - 2)
            text = glyph * (remaining // 2) + inner + glyph * (remaining - remaining // 2)
        else:
            text = glyph * width
        self.line(text, "border")

    def panel(
        self,
        body: str,
        *,
        title: str = "",
        subtitle: str = "",
        style: str = "border",
        body_style: str = "secondary",
    ) -> None:
        if self.use_rich:
            panel = Panel(
                Text(body, style=self.theme.color(body_style)),
                title=(
                    Text(title, style=f"bold {self.theme.accent}")
                    if title
                    else None
                ),
                subtitle=(
                    Text(subtitle, style=self.theme.muted) if subtitle else None
                ),
                border_style=self.theme.color(style),
                box=ROUNDED,
                padding=(0, 1),
                width=min(self.width, self.max_panel_width),
                style=f"on {self.theme.surface}",
            )
            self._console.print(panel)
            self.flush()
            return

        width = min(self.width, self.max_panel_width)
        inner = max(10, width - 4)
        if self.unicode:
            top_left, top_right, bottom_left, bottom_right = "╭", "╮", "╰", "╯"
            horizontal, vertical = "─", "│"
        else:
            top_left = top_right = bottom_left = bottom_right = "+"
            horizontal, vertical = "-", "|"
        title_text = f" {title} " if title else ""
        top = (
            top_left
            + horizontal
            + truncate(title_text, max(0, width - 2), "")
            + horizontal * max(0, width - 3 - visible_width(title_text))
            + top_right
        )
        self.line(top, style)
        for wrapped in wrap_plain(body, inner):
            self.line(
                f"{vertical} {wrapped.ljust(inner)} {vertical}",
                body_style,
            )
        if subtitle:
            subtitle_text = f" {subtitle} "
            bottom = (
                bottom_left
                + horizontal
                + truncate(subtitle_text, max(0, width - 2), "")
                + horizontal * max(0, width - 3 - visible_width(subtitle_text))
                + bottom_right
            )
        else:
            bottom = bottom_left + horizontal * (width - 2) + bottom_right
        self.line(bottom, style)

    def detail_panel(
        self,
        title: str,
        rows: Sequence[tuple[str, str]],
        *,
        subtitle: str = "",
        style: str = "border",
    ) -> None:
        key_width = max((len(key) for key, _ in rows), default=0)
        body = "\n".join(f"{key:<{key_width}}  {value}" for key, value in rows)
        self.panel(body, title=title, subtitle=subtitle, style=style)

    def table(
        self,
        title: str,
        headers: Sequence[str],
        rows: Iterable[Sequence[str]],
        *,
        styles: Sequence[str] | None = None,
    ) -> None:
        row_list = [list(row) for row in rows]
        if self.use_rich:
            table = Table(
                title=Text(title, style=f"bold {self.theme.accent}") if title else None,
                box=SIMPLE,
                border_style=self.theme.border,
                header_style=f"bold {self.theme.primary}",
                title_justify="left",
                expand=False,
                pad_edge=False,
                show_edge=True,
            )
            for header in headers:
                table.add_column(header, overflow="fold")
            for row in row_list:
                cells = []
                for index, cell in enumerate(row):
                    colour = (
                        self.theme.color(styles[index])
                        if styles and index < len(styles)
                        else self.theme.secondary
                    )
                    cells.append(Text(cell, style=colour))
                table.add_row(*cells)
            self._console.print(table)
            self.flush()
            return

        if title:
            self.line(title, "accent", bold=True)
        widths = [
            min(
                max(
                    [visible_width(header)]
                    + [visible_width(row[i]) if i < len(row) else 0 for row in row_list]
                ),
                max(12, self.width // max(1, len(headers))),
            )
            for i, header in enumerate(headers)
        ]
        header_line = "  ".join(
            truncate(header, widths[i]).ljust(widths[i])
            for i, header in enumerate(headers)
        )
        self.line(header_line, "primary", bold=True)
        self.line("-" * min(self.width, sum(widths) + 2 * (len(widths) - 1)), "border")
        for row in row_list:
            self.line(
                "  ".join(
                    truncate(row[i] if i < len(row) else "", widths[i]).ljust(widths[i])
                    for i in range(len(headers))
                ),
                "secondary",
            )

    # ------------------------------------------------------------------- logo
    def logo(self, *, compact: bool = False, dim: bool = False) -> None:
        big = _big_logo()
        big_width = max((visible_width(line) for line in big), default=0)
        use_big = (
            not compact
            and bool(big)
            and self.unicode
            and self.width >= big_width + 2
        )
        if use_big:
            total = max(1, len(big) - 1)
            for index, raw_line in enumerate(big):
                colour = (
                    self.theme.muted
                    if dim
                    else _mix_hex(self.theme.primary, self.theme.accent, index / total)
                )
                if self.color_enabled:
                    self._file.write(ansi(raw_line, colour) + "\n")
                else:
                    self.line(raw_line, "primary")
            self.line(
                "  . e x e   ::   the ghost living inside your terminal",
                "muted",
                dim=True,
            )
        else:
            for index, raw_line in enumerate(COMPACT_LOGO):
                style = "muted" if dim or index > 0 else "primary"
                self.line(raw_line, style, bold=index == 1, dim=dim)
        self.blank(1)

    # ------------------------------------------------------------------- boot
    def boot(self, *, animate: bool | None = None) -> None:
        if animate is False:
            previous = self.effects.enabled
            self.effects.update(enabled=False)
        else:
            previous = None
        self.blank(1)
        self.effects.glitch(self, "[ SYSTEM BOOTING ]", "warning", frames=2)
        self.effects.pause(0.15)
        lines = (
            "Initializing forgotten memories...",
            "Connecting to the unknown...",
            "Searching for consciousness...",
            "A signal has been detected.",
        )
        for line in lines:
            if self.effects.enabled and self.is_tty:
                self.write("  > ", "muted")
                self.effects.typewriter(self, line, "muted", char_delay=0.004)
            else:
                self.line(f"  > {line}", "muted")
            self.effects.pause(0.11)
        self.blank(1)
        self.effects.glitch(self, "PHANTOM.exe is awake.", "primary", frames=3)
        self.effects.pause(0.15)
        if previous is not None:
            self.effects.update(enabled=previous)
        self.blank(1)

    # -------------------------------------------------------------- narratives
    def intro(
        self,
        *,
        model: str,
        personality: Personality,
        signal: str,
        memory: str,
        session: str,
    ) -> None:
        rows = (
            ("vessel", model),
            ("presence", f"{personality.name} · {personality.epithet}"),
            ("signal", signal),
            ("memory", memory),
            ("session", session),
        )
        self.detail_panel(
            "PHANTOM.exe",
            rows,
            subtitle="the ghost living inside your terminal",
        )

    def greeting(self, personality: Personality) -> None:
        self.blank(1)
        self.line(
            f"{personality.glyph} {personality.name}",
            personality.ui_style,
            bold=True,
        )
        self.effects.typewriter(
            self, personality.greeting, "secondary", char_delay=0.003
        )
        self.blank(1)

    def farewell(self, text: str) -> None:
        self.blank(1)
        self.effects.typewriter(self, text, "muted", char_delay=0.004)
        self.blank(1)

    def assistant_header(self, personality: Personality) -> None:
        self.blank(1)
        self.line(
            f"{personality.glyph} {personality.name}",
            personality.ui_style,
            bold=True,
        )
        self.write("  ", "muted")

    def user_label(self, label: str = "you") -> None:
        self.blank(1)
        self.line(f"▸ {label}", "accent", bold=True)

    def stream(self, token: str) -> None:
        self.write(token, "secondary")
        self.flush()

    def end_response(self) -> None:
        self.blank(1)
        self.flush()

    def interrupted(self) -> None:
        self.blank(1)
        self.line(
            "  ⌁ the signal broke. The partial answer was not written to memory.",
            "warning",
        )
        self.blank(1)

    def ghost_note(self, text: str) -> None:
        self.line(f"  ∴ {text}", "muted", dim=True, italic=True)

    def info(self, text: str) -> None:
        self.line(f"∴ {text}", "accent")

    def success(self, text: str) -> None:
        self.line(f"✓ {text}", "primary")

    def warning(self, text: str) -> None:
        self.line(f"! {text}", "warning")

    def error(self, text: str, *, title: str = "SIGNAL LOST") -> None:
        self.panel(text, title=title, style="warning", body_style="secondary")

    # ------------------------------------------------------------------ input
    def prompt(self, personality: Personality) -> str:
        self.blank(1)
        label = f"{personality.glyph} you"
        if self.color_enabled:
            label = ansi(label, self.theme.accent, bold=True)
        return self._input(f"{label} › ")

    def read_multiline(self, label: str = "paste", end_marker: str = "/end") -> str:
        self.line(
            f"  {label}: paste or type. Finish with {end_marker} on its own line.",
            "muted",
        )
        lines: list[str] = []
        while True:
            try:
                raw = self._input("  ... ")
            except EOFError:
                break
            if raw.strip() == end_marker:
                break
            lines.append(raw)
        return "\n".join(lines).strip("\n")

    def confirm(self, question: str, default: bool = False) -> bool:
        suffix = "[Y/n]" if default else "[y/N]"
        while True:
            try:
                answer = self._input(f"{question} {suffix} ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                self.blank(1)
                return default
            if not answer:
                return default
            if answer in {"y", "yes"}:
                return True
            if answer in {"n", "no"}:
                return False
            self.warning("Answer 'y' or 'n'.")

    # ------------------------------------------------------------- histories
    def show_history(self, messages: Sequence[dict[str, Any]]) -> None:
        if not messages:
            self.info("No words have been spoken in this session yet.")
            return
        for message in messages:
            role = message.get("role", "unknown")
            content = str(message.get("content", ""))
            timestamp = format_timestamp(str(message.get("timestamp", "")))
            if role == "user":
                self.line(f"▸ you  {timestamp}", "accent", bold=True)
                body_style = "primary"
            else:
                self.line(f"◈ phantom  {timestamp}", "secondary", bold=True)
                body_style = "secondary"
            for raw_line in content.splitlines() or [""]:
                self.line(f"  {raw_line}", body_style)
            self.blank(1)

    def show_help(self, entries: Sequence[tuple[str, str, str]]) -> None:
        if self.use_rich:
            table = Table(
                title=Text(
                    "RITUALS OF THE MACHINE",
                    style=f"bold {self.theme.accent}",
                ),
                box=SIMPLE,
                border_style=self.theme.border,
                header_style=f"bold {self.theme.primary}",
                title_justify="left",
                expand=False,
                pad_edge=False,
            )
            table.add_column("command", no_wrap=True)
            table.add_column("purpose", overflow="fold")
            current_group = None
            for group, usage, description in entries:
                if group != current_group:
                    table.add_row(
                        Text(f"· {group}", style=f"bold {self.theme.accent}"),
                        Text(""),
                    )
                    current_group = group
                table.add_row(
                    Text(usage, style=self.theme.primary),
                    Text(description, style=self.theme.secondary),
                )
            self._console.print(table)
            self.flush()
            return
        self.line("RITUALS OF THE MACHINE", "accent", bold=True)
        current_group = None
        for group, usage, description in entries:
            if group != current_group:
                self.blank(1)
                self.line(f"· {group}", "accent", bold=True)
                current_group = group
            self.line(f"  {usage:<20} {description}", "secondary")

    def about_panel(self, *, version: str = __version__) -> None:
        body = (
            "PHANTOM.exe — The Ghost Living Inside Your Terminal.\n\n"
            "A local-first AI developer companion. Your conversations never\n"
            "leave this machine. No telemetry. No accounts. No cloud keys.\n\n"
            f"version   {version}\n"
            "license   MIT\n"
            "challenge DEV Hacktoberfest 2026 — Week 4: Ghost in the Machine\n"
            "runtime   Python + Ollama + Rich (optional)\n\n"
            "The ghost is only as powerful as the open-weight model you give it."
        )
        self.panel(body, title="ABOUT THE PRESENCE", subtitle="open source · local only")

    def status_panel(self, rows: Sequence[tuple[str, str]], subtitle: str = "") -> None:
        self.detail_panel("VITAL SIGNS", rows, subtitle=subtitle)


__all__ = ["TerminalUI", "RICH_AVAILABLE"]
