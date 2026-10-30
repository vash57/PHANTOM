"""Application orchestration for PHANTOM.exe.

This module wires configuration, rendering, memory, Ollama and commands into a
single interactive loop.  It deliberately contains no model logic and no
command implementations: those live in their own modules so they can be tested
without a terminal.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from config import Config
from src.commands import CommandProcessor, CommandResult, CommandServices
from src.effects import Effects
from src.engine import ChatEngine
from src.memory import MemoryStore, MemoryStoreError
from src.ollama_client import (
    OllamaClient,
    OllamaError,
    OllamaModelNotFound,
    OllamaUnavailable,
)
from src.terminal_ui import TerminalUI
from src.themes import find_theme, get_theme
from src.utils import plural


class PhantomApp:
    """The interactive shell around the engine and command processor."""

    def __init__(
        self,
        config: Config,
        *,
        theme: str = "phosphor",
        plain: bool = False,
        color: bool | None = None,
        debug: bool = False,
    ) -> None:
        self.config = config
        self.debug = debug

        chosen_theme = find_theme(theme)
        if chosen_theme is None:
            self.config.warnings.append(
                f"Unknown theme {theme!r}; using phosphor."
            )
            chosen_theme = get_theme("phosphor")

        self.effects = Effects(
            enabled=self.config.animation,
            speed=self.config.animation_speed,
        )
        self.ui = TerminalUI(
            theme=chosen_theme,
            effects=self.effects,
            force_plain=plain,
            force_color=color,
        )

        self.memory = self._open_memory(self.config.memory_dir)
        self.client = OllamaClient(
            self.config.base_url,
            self.config.model,
            timeout=self.config.request_timeout,
            status_timeout=self.config.status_timeout,
        )
        self.engine = ChatEngine(
            self.config,
            self.client,
            self.memory,
            personality=self.config.personality,
        )
        self.processor = CommandProcessor(
            CommandServices(
                config=self.config,
                engine=self.engine,
                memory=self.memory,
                client=self.client,
                ui=self.ui,
                effects=self.effects,
            )
        )

    # ------------------------------------------------------------------ setup
    def _open_memory(self, directory: Path) -> MemoryStore:
        try:
            return MemoryStore(directory)
        except MemoryStoreError as exc:
            fallback = Path(tempfile.mkdtemp(prefix="phantom-sessions-"))
            self.config.warnings.append(
                f"{exc} Sessions will be kept in {fallback} for this run."
            )
            self.config.memory_dir = fallback
            return MemoryStore(fallback)

    def _open_session(self, *, resume: bool, session_id: str | None) -> None:
        if session_id:
            try:
                summary = self.memory.resolve(session_id)
                self.engine.load_session(summary.id)
                self.ui.info(f"Restored {summary.id} · {summary.title}")
                return
            except (MemoryStoreError, ValueError) as exc:
                self.ui.error(str(exc), title="MEMORY FAULT")
                self.ui.info("Starting a new session instead.")
        elif resume:
            latest = self.memory.latest()
            if latest is not None:
                try:
                    self.engine.load_session(latest.id)
                    self.ui.info(f"Resumed {latest.id} · {latest.title}")
                    return
                except (MemoryStoreError, ValueError) as exc:
                    self.ui.error(str(exc), title="MEMORY FAULT")
                    self.ui.info("Starting a new session instead.")
            else:
                self.ui.info("No saved sessions to resume. A new room opens.")
        self.engine.start_new_session()

    # -------------------------------------------------------------- reporting
    def status(self) -> int:
        """Print the same status panel used by ``/status`` without a session."""

        self.processor.handle("/status")
        for warning in self.config.warnings:
            self.ui.warning(warning)
        return 0

    def list_sessions(self) -> int:
        """Print saved sessions without opening one."""

        self.processor.handle("/memory list")
        return 0

    # ------------------------------------------------------------------- run
    def run(
        self,
        *,
        resume: bool = False,
        session_id: str | None = None,
        show_boot: bool = True,
    ) -> int:
        if show_boot:
            self.ui.boot(animate=self.config.animation)
        self._open_session(resume=resume, session_id=session_id)

        status = self.client.status(self.engine.model)
        session = self.engine.session
        self.ui.logo()
        self.ui.intro(
            model=self.engine.model,
            personality=self.engine.personality,
            signal=(
                status.summary
                if status.reachable
                else "offline — local rituals only"
            ),
            memory=(
                f"{self.memory.count()} saved "
                f"{plural(self.memory.count(), 'session')}"
            ),
            session=session.id if session is not None else "none",
        )
        self._report_startup(status)
        self.ui.greeting(self.engine.personality)

        try:
            self._loop()
        except KeyboardInterrupt:
            self.ui.blank(1)
            self.ui.info("Signal interrupted. Any messages are saved.")
        finally:
            self._safe_save()
            self.ui.farewell(self.engine.personality.farewell)
            self.ui.flush()
        return 0

    def _report_startup(self, status) -> None:
        for warning in self.config.warnings:
            self.ui.warning(warning)
        if not status.reachable:
            self.ui.warning(status.error or "Ollama is offline.")
            self.ui.info(
                "Local rituals still work: /help, /status, /scan, /memory, "
                "/theme, /ghost and /effects."
            )
            return
        if not status.model_available:
            self.ui.warning(
                f"Model {self.engine.model!r} is not installed. "
                f"Run: ollama pull {self.engine.model}"
            )
            if status.models:
                self.ui.info(
                    "Installed models: " + ", ".join(status.models[:8])
                )

    # ------------------------------------------------------------------ loop
    def _loop(self) -> None:
        while True:
            self._maybe_whisper()
            try:
                raw = self.ui.prompt(self.engine.personality)
            except EOFError:
                self.ui.blank(1)
                self.ui.info("End of input. Any messages are saved.")
                return
            except KeyboardInterrupt:
                self.ui.blank(1)
                self.ui.info("Signal interrupted. Any messages are saved.")
                return

            text = raw.strip()
            if not text:
                continue

            if text.endswith("\\"):
                head = text[:-1].rstrip()
                try:
                    tail = self.ui.read_multiline("continued message")
                except (EOFError, KeyboardInterrupt):
                    self.ui.blank(1)
                    self.ui.info("Continuation cancelled.")
                    continue
                text = (head + "\n" + tail).strip()
                if not text:
                    continue

            try:
                result = self.processor.handle(text)
            except KeyboardInterrupt:
                self.ui.interrupted()
                continue

            if result is None:
                self._chat(text)
                continue
            if result.should_exit:
                return
            if result.send_text is not None:
                self._chat(
                    result.send_text,
                    prompt_text=result.prompt_text,
                    display=result.display,
                )

    def _chat(
        self,
        text: str,
        *,
        prompt_text: str | None = None,
        display: str | None = None,
    ) -> None:
        self.ui.user_label(display or "you")
        self.ui.assistant_header(self.engine.personality)
        try:
            self.engine.send(
                text,
                prompt_text=prompt_text,
                on_token=self.ui.stream,
            )
        except KeyboardInterrupt:
            self.ui.interrupted()
            self._safe_save()
            return
        except OllamaModelNotFound as exc:
            self.ui.end_response()
            self.ui.error(str(exc), title="VESSEL MISSING")
            return
        except OllamaUnavailable as exc:
            self.ui.end_response()
            self.ui.error(str(exc), title="NO SIGNAL")
            return
        except OllamaError as exc:
            self.ui.end_response()
            self.ui.error(str(exc), title="SIGNAL LOST")
            return
        except MemoryStoreError as exc:
            self.ui.end_response()
            self.ui.error(str(exc), title="MEMORY FAULT")
            return
        except ValueError as exc:
            self.ui.end_response()
            self.ui.error(str(exc), title="EMPTY SIGNAL")
            return
        self.ui.end_response()

    def _maybe_whisper(self) -> None:
        line = self.effects.whisper(0.12)
        if line:
            self.ui.ghost_note(line)

    def _safe_save(self) -> None:
        try:
            self.engine.save()
        except MemoryStoreError as exc:
            self.ui.error(str(exc), title="MEMORY FAULT")


__all__ = ["PhantomApp"]
