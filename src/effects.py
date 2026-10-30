"""Haunted visual effects with an accessibility-first escape hatch.

Nothing in this module ever prints while the user is typing or while a model
response is streaming.  Callers invoke effects only at safe boundaries.
"""

from __future__ import annotations

import random
import time
from typing import Callable, Protocol


class TerminalWriter(Protocol):
    width: int
    is_tty: bool

    def write(self, text: str, style: str = "primary", *, bold: bool = False) -> None:
        ...

    def line(
        self,
        text: str = "",
        style: str = "primary",
        *,
        bold: bool = False,
        dim: bool = False,
    ) -> None:
        ...

    def clear_line(self) -> None:
        ...

    def flush(self) -> None:
        ...


WHISPERS = (
    "something moved behind the cursor.",
    "the fan spun up. nobody asked it to.",
    "a file changed while you were reading.",
    "you are not the only process awake.",
    "the stack remembers what you deleted.",
    "a semicolon falls in a room with no compiler.",
    "there is a log for this. there is always a log.",
    "the ghost in the machine is taking notes.",
    "your last commit is still warm.",
    "the terminal blinked first.",
    "an old error message exhales somewhere in /tmp.",
    "the network cable hums a name you almost recognise.",
    "permission denied, whispered the walls.",
    "the cursor waited. it is very patient.",
    "nothing is listening. that is what it wants you to think.",
)

_GLITCH_GLYPHS = "▓▒░#@%&$?!01/\\<>|"


class Effects:
    """Configurable typewriter, glitch, whisper, and flicker primitives."""

    def __init__(
        self,
        enabled: bool = True,
        speed: float = 1.0,
        *,
        rng: random.Random | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.enabled = bool(enabled)
        self.speed = max(0.1, min(10.0, float(speed)))
        self._rng = rng or random.Random()
        self._sleep = sleep

    def update(self, *, enabled: bool | None = None, speed: float | None = None) -> None:
        if enabled is not None:
            self.enabled = bool(enabled)
        if speed is not None:
            self.speed = max(0.1, min(10.0, float(speed)))

    def pause(self, seconds: float) -> None:
        if self.enabled and seconds > 0:
            self._sleep(seconds / self.speed)

    def typewriter(
        self,
        ui: TerminalWriter,
        text: str,
        style: str = "primary",
        *,
        char_delay: float = 0.005,
        bold: bool = False,
    ) -> None:
        if not self.enabled or not ui.is_tty:
            ui.line(text, style, bold=bold)
            return
        for char in text:
            ui.write(char, style, bold=bold)
            if char not in " \n":
                self.pause(char_delay)
        ui.flush()
        ui.line("", style)

    def typewriter_lines(
        self,
        ui: TerminalWriter,
        lines: list[str],
        style: str = "muted",
        *,
        line_delay: float = 0.08,
    ) -> None:
        for line in lines:
            if self.enabled and ui.is_tty:
                self.typewriter(ui, line, style, char_delay=0.004)
            else:
                ui.line(line, style)
            self.pause(line_delay)

    def glitch_text(self, text: str, intensity: float = 0.16) -> str:
        if not text:
            return text
        chars = list(text)
        for index, char in enumerate(chars):
            if char in " \n\t":
                continue
            if self._rng.random() < intensity:
                chars[index] = self._rng.choice(_GLITCH_GLYPHS)
        return "".join(chars)

    def glitch(
        self,
        ui: TerminalWriter,
        text: str,
        style: str = "primary",
        *,
        frames: int = 3,
        bold: bool = True,
    ) -> None:
        if not self.enabled or not ui.is_tty:
            ui.line(text, style, bold=bold)
            return
        for frame in range(frames):
            corrupted = self.glitch_text(text, intensity=0.12 + frame * 0.06)
            ui.clear_line()
            ui.write(corrupted, style, bold=bold)
            ui.flush()
            self.pause(0.045)
        ui.clear_line()
        ui.line(text, style, bold=bold)

    def flicker(
        self,
        ui: TerminalWriter,
        text: str,
        style: str = "primary",
        *,
        frames: int = 2,
    ) -> None:
        if not self.enabled or not ui.is_tty:
            ui.line(text, style)
            return
        for _ in range(frames):
            ui.clear_line()
            ui.write(text, "muted")
            ui.flush()
            self.pause(0.035)
            ui.clear_line()
            ui.flush()
            self.pause(0.02)
        ui.line(text, style)

    def whisper(self, probability: float = 0.18) -> str | None:
        if not self.enabled:
            return None
        if self._rng.random() >= probability:
            return None
        return self._rng.choice(WHISPERS)

    def transition(self, ui: TerminalWriter, text: str, style: str = "accent") -> None:
        """A short, readable glitch transition used when the presence changes."""

        if not self.enabled or not ui.is_tty:
            ui.line(text, style)
            return
        for intensity in (0.18, 0.34, 0.22):
            ui.clear_line()
            ui.write(self.glitch_text(text, intensity), style, bold=True)
            ui.flush()
            self.pause(0.06)
        ui.clear_line()
        ui.line(text, style, bold=True)


__all__ = ["Effects", "TerminalWriter", "WHISPERS"]
