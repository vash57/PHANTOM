"""The command system for PHANTOM.exe.

Commands are local-only.  None of them execute shell commands, and none of
them touch the network except the explicit Ollama status/model checks.
"""

from __future__ import annotations

import difflib
import os
import platform
import sys
from dataclasses import dataclass
from typing import Any, Callable

from config import Config
from src import __challenge__, __license__, __tagline__, __version__
from src.effects import Effects
from src.engine import ChatEngine
from src.memory import (
    MemoryStore,
    MemoryStoreError,
    SessionCorruptError,
    SessionNotFoundError,
)
from src.ollama_client import OllamaClient, OllamaError, OllamaStatus
from src.personality import PERSONALITIES, get_personality, personality_slugs
from src.terminal_ui import RICH_AVAILABLE
from src.themes import THEMES, find_theme
from src.toolkit import (
    ALIASES as TOOL_ALIASES,
    TOOLS,
    UnknownToolError,
    build_prompt,
    resolve_tool,
    tool_entries,
)
from src.utils import format_timestamp, platform_label, truncate


class CommandParseError(ValueError):
    """Raised when a slash command cannot be parsed."""


@dataclass(frozen=True)
class CommandSpec:
    name: str
    usage: str
    description: str
    group: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandInvocation:
    name: str
    args: str
    raw: str


@dataclass
class CommandResult:
    should_exit: bool = False
    send_text: str | None = None
    prompt_text: str | None = None
    display: str | None = None


@dataclass
class CommandServices:
    config: Config
    engine: ChatEngine
    memory: MemoryStore
    client: OllamaClient
    ui: Any
    effects: Effects
    confirm: Callable[[str, bool], bool] | None = None
    read_multiline: Callable[[str], str] | None = None


COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("help", "/help", "Show every ritual.", "System"),
    CommandSpec("clear", "/clear", "Clear the screen, keep the memory.", "System"),
    CommandSpec(
        "status", "/status", "Check Ollama, the model, and the séance.", "System"
    ),
    CommandSpec("scan", "/scan", "Inspect local configuration and health.", "System"),
    CommandSpec("about", "/about", "Project, licence, and privacy.", "System"),
    CommandSpec(
        "exit", "/exit", "Save the session and leave safely.", "System", ("quit", "q")
    ),
    CommandSpec(
        "ghost",
        "/ghost [name]",
        "Show or switch the active presence.",
        "Presence",
        ("persona",),
    ),
    CommandSpec(
        "model",
        "/model [name|list]",
        "Show, list, or change the Ollama model.",
        "Presence",
    ),
    CommandSpec(
        "dev",
        "/dev <ritual> [material]",
        "explain · debug · review · generate · command · trace · "
        "concept · ideas · summarize · optimize",
        "Developer",
        ("tools",),
    ),
    CommandSpec("new", "/new", "Begin a fresh session.", "Session"),
    CommandSpec("save", "/save", "Write the current session to disk.", "Session"),
    CommandSpec("rename", "/rename <title>", "Name the current session.", "Session"),
    CommandSpec(
        "paste",
        "/paste",
        "Paste multi-line text; finish with /end.",
        "Session",
    ),
    CommandSpec(
        "memory",
        "/memory [list|load|delete|clear|save|rename]",
        "Manage local sessions.",
        "Memory",
        ("sessions",),
    ),
    CommandSpec("history", "/history [n]", "Show this session's messages.", "Memory"),
    CommandSpec(
        "theme", "/theme [name]", "Show or change the colour palette.", "Appearance"
    ),
    CommandSpec(
        "effects",
        "/effects [on|off|speed N|status]",
        "Control animation, glitches, and whispers.",
        "Appearance",
    ),
)

_COMMAND_ALIASES: dict[str, str] = {}
for _spec in COMMANDS:
    for _alias in _spec.aliases:
        _COMMAND_ALIASES[_alias] = _spec.name

_TOOL_NAMES = set(TOOLS) | set(TOOL_ALIASES)


def parse_command(text: str) -> CommandInvocation | None:
    """Parse a slash command.  Returns ``None`` for ordinary chat text."""

    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    if stripped == "/":
        raise CommandParseError("A command needs a name after '/'.")
    head, _, remainder = stripped.partition(" ")
    name = head[1:].strip().lower()
    if not name:
        raise CommandParseError("A command needs a name after '/'.")
    return CommandInvocation(name=name, args=remainder.strip(), raw=stripped)


def _all_command_names() -> list[str]:
    names = [spec.name for spec in COMMANDS]
    names.extend(_COMMAND_ALIASES)
    names.extend(TOOLS)
    names.extend(TOOL_ALIASES)
    return names


def _short_session_ids(summaries) -> dict[str, str]:
    """Show the shortest unambiguous id prefix that still fits the table."""

    ids = [summary.id for summary in summaries]
    short: dict[str, str] = {}
    for session_id in ids:
        for length in range(15, len(session_id) + 1):
            prefix = session_id[:length]
            if sum(other.startswith(prefix) for other in ids) == 1:
                short[session_id] = prefix
                break
        else:
            short[session_id] = session_id
    return short


class CommandProcessor:
    def __init__(self, services: CommandServices) -> None:
        self.services = services
        self._confirm = services.confirm or services.ui.confirm
        self._read_multiline = services.read_multiline or services.ui.read_multiline

    # ------------------------------------------------------------------ public
    def handle(self, text: str) -> CommandResult | None:
        try:
            invocation = parse_command(text)
        except CommandParseError as exc:
            self.services.ui.error(str(exc))
            return CommandResult()
        if invocation is None:
            return None
        return self.execute(invocation)

    def execute(self, invocation: CommandInvocation) -> CommandResult:
        name = _COMMAND_ALIASES.get(invocation.name, invocation.name)
        try:
            if name == "help":
                return self._help(invocation.args)
            if name == "clear":
                return self._clear()
            if name == "status":
                return self._status()
            if name == "scan":
                return self._scan()
            if name == "about":
                return self._about()
            if name == "exit":
                self.services.engine.save()
                return CommandResult(should_exit=True)
            if name == "ghost":
                return self._ghost(invocation.args)
            if name == "model":
                return self._model(invocation.args)
            if name == "dev":
                return self._dev(invocation.args)
            if name == "new":
                return self._new()
            if name == "save":
                return self._save()
            if name == "rename":
                return self._rename(invocation.args)
            if name == "paste":
                return self._paste()
            if name == "memory":
                return self._memory(invocation.args)
            if name == "history":
                return self._history(invocation.args)
            if name == "theme":
                return self._theme(invocation.args)
            if name == "effects":
                return self._effects(invocation.args)
            if name in _TOOL_NAMES:
                return self._run_tool(name, invocation.args)
        except (MemoryStoreError, SessionNotFoundError, SessionCorruptError, OllamaError) as exc:
            self.services.ui.error(str(exc))
            return CommandResult()
        except (ValueError, OSError) as exc:
            self.services.ui.error(f"{exc}")
            return CommandResult()
        return self._unknown(invocation.name)

    # -------------------------------------------------------------------- help
    def _help(self, args: str) -> CommandResult:
        ui = self.services.ui
        ui.show_help(_help_entries())
        ui.info(
            "Shortcuts work too: /explain, /debug, /review, /generate, /cmd, "
            "/trace, /concept, /ideas, /summarize, /optimize."
        )
        return CommandResult()

    # ------------------------------------------------------------------ system
    def _clear(self) -> CommandResult:
        ui = self.services.ui
        ui.clear_screen()
        ui.logo(compact=True)
        ui.ghost_note("The screen forgets. The session does not.")
        return CommandResult()

    def _status(self) -> CommandResult:
        ui = self.services.ui
        engine = self.services.engine
        status = self.services.client.status(engine.model)
        session = engine.session
        memory_health = self.services.memory.health()
        rows: list[tuple[str, str]] = [
            ("presence", f"{engine.personality.name} · {engine.personality.epithet}"),
            ("model", engine.model),
            ("ollama", status.base_url),
            ("signal", "online" if status.reachable else "offline"),
        ]
        if status.reachable:
            rows.append(("version", status.version or "unknown"))
            rows.append(("models", str(len(status.models))))
            rows.append(
                (
                    "vessel",
                    "installed" if status.model_available else "missing",
                )
            )
            if status.latency_ms is not None:
                rows.append(("latency", f"{status.latency_ms} ms"))
        if session is not None:
            rows.append(
                (
                    "session",
                    f"{session.id} · {session.message_count} messages",
                )
            )
            rows.append(("title", session.title))
        rows.append(
            (
                "memory",
                f"{memory_health.directory} · {memory_health.valid_sessions} saved",
            )
        )
        rows.append(
            (
                "effects",
                f"{'on' if self.services.effects.enabled else 'off'} · "
                f"speed {self.services.effects.speed:g}",
            )
        )
        rows.append(("theme", ui.theme.label))
        rows.append(("runtime", f"Python {platform.python_version()} · {platform_label()}"))
        ui.status_panel(rows, subtitle=status.summary)
        if not status.reachable and status.error:
            ui.error(status.error, title="NO SIGNAL")
        elif status.reachable and not status.model_available:
            ui.warning(
                f"Model {engine.model!r} is not installed. "
                f"Run: ollama pull {engine.model}"
            )
        return CommandResult()

    def _scan(self) -> CommandResult:
        ui = self.services.ui
        config = self.services.config
        status = self.services.client.status(self.services.engine.model)
        health = self.services.memory.health()
        rows: list[tuple[str, str, str]] = []

        python_ok = sys.version_info >= (3, 11)
        rows.append(
            (
                "python",
                "OK" if python_ok else "FAIL",
                f"{platform.python_version()} (3.11+ required)",
            )
        )
        rows.append(
            (
                "renderer",
                "OK" if RICH_AVAILABLE else "WARN",
                "Rich available" if RICH_AVAILABLE else "ANSI fallback active",
            )
        )
        rows.append(
            (
                "terminal",
                "OK" if ui.is_tty else "WARN",
                f"{ui.width} cols · {'tty' if ui.is_tty else 'non-tty'} · "
                f"{'unicode' if ui.unicode else 'ascii'}",
            )
        )
        rows.append(("platform", "OK", platform_label()))
        env_ok = bool(config.env_file and config.env_file.is_file())
        rows.append(
            (
                ".env",
                "OK" if env_ok else "WARN",
                str(config.env_file) if config.env_file else "disabled",
            )
        )
        writable = os.access(health.directory, os.W_OK)
        rows.append(
            (
                "memory",
                "OK" if writable else "FAIL",
                f"{health.directory} · {health.valid_sessions} valid · "
                f"{len(health.corrupt_files)} corrupt",
            )
        )
        if health.corrupt_files:
            rows.append(
                (
                    "corrupt files",
                    "WARN",
                    ", ".join(health.corrupt_files[:3]),
                )
            )
        rows.append(
            (
                "ollama",
                "OK" if status.reachable else "WARN",
                status.base_url if status.reachable else "offline; local rituals still work",
            )
        )
        if status.reachable:
            rows.append(
                (
                    "model",
                    "OK" if status.model_available else "FAIL",
                    self.services.engine.model
                    if status.model_available
                    else f"{self.services.engine.model} missing",
                )
            )
        else:
            rows.append(
                (
                    "model",
                    "WARN",
                    f"{self.services.engine.model} (cannot verify offline)",
                )
            )
        rows.append(
            (
                "effects",
                "OK",
                f"{'on' if self.services.effects.enabled else 'off'} · "
                f"speed {self.services.effects.speed:g}",
            )
        )
        rows.append(("privacy", "OK", "local memory · no telemetry · no API keys"))
        rows.append(("auto-exec", "OK", "AI commands are never executed"))
        ui.table(
            "LOCAL CONFIGURATION SCAN",
            ["check", "state", "detail"],
            rows,
            styles=["primary", "accent", "secondary"],
        )
        for warning in config.warnings:
            ui.warning(warning)
        return CommandResult()

    def _about(self) -> CommandResult:
        self.services.ui.about_panel()
        self.services.ui.line(
            f"  {__tagline__}", "muted", dim=True
        )
        self.services.ui.line(
            f"  {__challenge__}", "muted", dim=True
        )
        self.services.ui.line(
            f"  licence: {__license__}  ·  version: {__version__}",
            "muted",
            dim=True,
        )
        return CommandResult()

    # -------------------------------------------------------------- personality
    def _ghost(self, args: str) -> CommandResult:
        ui = self.services.ui
        engine = self.services.engine
        if not args:
            rows = [
                (
                    spec.name,
                    spec.slug,
                    spec.description,
                    "← current" if spec.slug == engine.personality.slug else "",
                )
                for spec in PERSONALITIES.values()
            ]
            ui.table(
                "PRESENCES",
                ["name", "slug", "nature", "state"],
                rows,
                styles=["accent", "muted", "secondary", "primary"],
            )
            ui.info("Switch with /ghost <name>.")
            return CommandResult()
        slug = args.split()[0].lower()
        try:
            personality = get_personality(slug)
        except ValueError:
            suggestions = difflib.get_close_matches(
                slug, personality_slugs(), n=3, cutoff=0.4
            )
            hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
            ui.error(f"Unknown presence {slug!r}.{hint}")
            return CommandResult()
        if personality.slug == engine.personality.slug:
            ui.info(f"{personality.name} is already here.")
            return CommandResult()
        engine.set_personality(personality.slug)
        self.services.effects.transition(
            ui, f"the presence shifts → {personality.name}", personality.ui_style
        )
        ui.line(
            f"  {personality.glyph} {personality.name} · {personality.epithet}",
            personality.ui_style,
            bold=True,
        )
        ui.line(f"  {personality.description}", "muted")
        return CommandResult()

    def _model(self, args: str) -> CommandResult:
        ui = self.services.ui
        engine = self.services.engine
        status = self.services.client.status(engine.model)
        if not args:
            ui.detail_panel(
                "VESSEL",
                [
                    ("current", engine.model),
                    ("ollama", status.base_url),
                    ("signal", "online" if status.reachable else "offline"),
                    (
                        "installed",
                        "yes"
                        if status.model_available
                        else ("unknown" if not status.reachable else "no"),
                    ),
                    ("available", ", ".join(status.models) if status.models else "none"),
                ],
            )
            ui.info("Use /model <name> to switch, or /model list.")
            return CommandResult()
        if args.strip().lower() == "list":
            if not status.reachable:
                ui.error(
                    "Ollama is offline, so the model list cannot be read.\n\n"
                    "Start it with: ollama serve"
                )
                return CommandResult()
            if not status.models:
                ui.warning("No models are installed. Run: ollama pull gemma4:e2b")
                return CommandResult()
            rows = [
                (
                    name,
                    "← current" if name == engine.model else "",
                    "installed" if name in status.models else "",
                )
                for name in status.models
            ]
            ui.table(
                "INSTALLED MODELS",
                ["model", "state", ""],
                rows,
                styles=["primary", "accent", "muted"],
            )
            return CommandResult()
        requested = args.split()[0].strip()
        if not requested:
            ui.error("Usage: /model <name> or /model list")
            return CommandResult()
        if status.reachable:
            from src.ollama_client import model_is_installed

            if not model_is_installed(requested, status.models):
                ui.error(
                    f"Model {requested!r} is not installed.\n\n"
                    f"Run: ollama pull {requested}\n\n"
                    "Then try /model again, or use /model list."
                )
                return CommandResult()
        engine.set_model(requested)
        if status.reachable:
            ui.success(f"The vessel is now {requested}.")
        else:
            ui.warning(
                f"Model set to {requested!r}, but Ollama is offline and the "
                "model could not be verified."
            )
        return CommandResult()

    # ------------------------------------------------------------------ session
    def _new(self) -> CommandResult:
        previous = self.services.engine.session
        had_messages = bool(previous is not None and previous.messages)
        session = self.services.engine.start_new_session()
        suffix = " The previous one was saved." if had_messages else ""
        self.services.ui.success(f"A new séance begins: {session.id}.{suffix}")
        return CommandResult()

    def _save(self) -> CommandResult:
        if not self.services.engine.history():
            self.services.ui.info("Nothing to save yet. Send a message first.")
            return CommandResult()
        self.services.engine.save()
        self.services.ui.success("The session is written to local memory.")
        return CommandResult()

    def _rename(self, args: str) -> CommandResult:
        if not args.strip():
            self.services.ui.error("Usage: /rename <new title>")
            return CommandResult()
        self.services.engine.set_title(args)
        self.services.ui.success("The session has a new name.")
        return CommandResult()

    def _paste(self) -> CommandResult:
        material = self._read_multiline("material")
        if not material.strip():
            self.services.ui.info("Nothing was pasted.")
            return CommandResult()
        return CommandResult(send_text=material, display="paste")

    def _memory(self, args: str) -> CommandResult:
        ui = self.services.ui
        memory = self.services.memory
        engine = self.services.engine
        parts = args.split(maxsplit=1)
        action = parts[0].lower() if parts else "list"
        rest = parts[1].strip() if len(parts) > 1 else ""

        if action in {"list", "ls"}:
            summaries = memory.list_sessions()
            if not summaries:
                ui.info("No saved sessions. The room is empty.")
                return CommandResult()
            short_ids = _short_session_ids(summaries)
            rows = []
            for summary in summaries:
                marker = "›" if engine.session and summary.id == engine.session.id else " "
                rows.append(
                    (
                        f"{marker}{short_ids[summary.id]}",
                        summary.title,
                        summary.personality,
                        str(summary.message_count),
                        format_timestamp(summary.updated_at),
                    )
                )
            ui.table(
                "SAVED ECHOES",
                ["id", "title", "presence", "msgs", "updated"],
                rows,
                styles=["primary", "secondary", "accent", "muted", "muted"],
            )
            ui.info("Load with /memory load <id>, delete with /memory delete <id>.")
            return CommandResult()

        if action in {"load", "restore"}:
            if not rest:
                ui.error("Usage: /memory load <id or prefix>")
                return CommandResult()
            summary = memory.resolve(rest)
            session = engine.load_session(summary.id)
            self.services.effects.transition(
                ui, f"restoring → {session.title}", "accent"
            )
            ui.success(
                f"Restored {session.id} · {session.message_count} messages · "
                f"{session.personality} · {session.model or engine.model}"
            )
            return CommandResult()

        if action in {"delete", "rm"}:
            if not rest:
                ui.error("Usage: /memory delete <id or prefix>")
                return CommandResult()
            summary = memory.resolve(rest)
            if not self._confirm(
                f"Delete session {summary.id} ({summary.title})? This cannot be undone.",
                False,
            ):
                ui.info("The echo remains.")
                return CommandResult()
            is_current = bool(engine.session and engine.session.id == summary.id)
            if is_current:
                engine.session = None
            memory.delete(summary.id)
            if is_current:
                engine.start_new_session()
                ui.info("The current session was deleted; a new one is open.")
            else:
                ui.success(f"Deleted {summary.id}.")
            return CommandResult()

        if action in {"clear", "purge"}:
            count = memory.count()
            if count == 0:
                ui.info("There is nothing to erase.")
                return CommandResult()
            if not self._confirm(
                f"Erase all {count} saved session(s)? This cannot be undone.", False
            ):
                ui.info("Nothing was erased.")
                return CommandResult()
            engine.session = None
            removed = memory.clear_all()
            engine.start_new_session()
            ui.success(f"Erased {removed} session(s). A new séance begins.")
            return CommandResult()

        if action == "save":
            if not engine.history():
                ui.info("Nothing to save yet. Send a message first.")
                return CommandResult()
            engine.save()
            ui.success("The session is written to local memory.")
            return CommandResult()

        if action in {"rename", "title"}:
            if not rest:
                ui.error("Usage: /memory rename <new title>")
                return CommandResult()
            engine.set_title(rest)
            ui.success("The session has a new name.")
            return CommandResult()

        ui.error(
            "Unknown memory action. Use list, load, delete, clear, save, or rename."
        )
        return CommandResult()

    def _history(self, args: str) -> CommandResult:
        ui = self.services.ui
        history = self.services.engine.history()
        if not history:
            ui.info("This session has no messages yet.")
            return CommandResult()
        count = 20
        if args:
            if args.lower() == "all":
                count = len(history)
            else:
                try:
                    count = int(args.split()[0])
                except ValueError:
                    ui.error("Usage: /history [n|all]")
                    return CommandResult()
                if count <= 0:
                    ui.error("History count must be positive.")
                    return CommandResult()
        selected = history[-count:]
        ui.show_history(selected)
        if len(selected) < len(history):
            ui.info(f"Showing the last {len(selected)} of {len(history)} messages.")
        return CommandResult()

    # ---------------------------------------------------------------- developer
    def _dev(self, args: str) -> CommandResult:
        ui = self.services.ui
        if not args:
            rows = [
                (slug, name, description)
                for slug, name, description in tool_entries()
            ]
            ui.table(
                "DEVELOPER RITUALS",
                ["ritual", "name", "purpose"],
                rows,
                styles=["primary", "accent", "secondary"],
            )
            ui.info(
                "Use /dev <ritual>, then paste material. Shortcuts like /explain "
                "also work."
            )
            return CommandResult()
        parts = args.split(maxsplit=1)
        slug = parts[0]
        material = parts[1].strip() if len(parts) > 1 else ""
        return self._run_tool(slug, material)

    def _run_tool(self, slug: str, material: str) -> CommandResult:
        ui = self.services.ui
        try:
            tool = resolve_tool(slug)
        except UnknownToolError:
            suggestions = difflib.get_close_matches(slug, list(TOOLS), n=3, cutoff=0.4)
            hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
            ui.error(f"Unknown ritual {slug!r}.{hint}")
            return CommandResult()
        if not material:
            material = self._read_multiline(f"{tool.name.lower()} material")
        if not material.strip():
            ui.info("No material was provided; the ritual was cancelled.")
            return CommandResult()
        prompt = build_prompt(tool, material)
        return CommandResult(
            send_text=material,
            prompt_text=prompt,
            display=f"dev/{tool.slug}",
        )

    # ---------------------------------------------------------------- appearance
    def _theme(self, args: str) -> CommandResult:
        ui = self.services.ui
        if not args:
            rows = [
                (
                    theme.name,
                    theme.label,
                    theme.description,
                    "← current" if theme.name == ui.theme.name else "",
                )
                for theme in THEMES.values()
            ]
            ui.table(
                "PALETTES",
                ["name", "label", "atmosphere", "state"],
                rows,
                styles=["primary", "accent", "secondary", "muted"],
            )
            ui.info("Switch with /theme <name>.")
            return CommandResult()
        name = args.split()[0].lower()
        theme = find_theme(name)
        if theme is None:
            suggestions = difflib.get_close_matches(name, list(THEMES), n=3, cutoff=0.4)
            hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
            ui.error(f"Unknown palette {name!r}.{hint}")
            return CommandResult()
        ui.set_theme(theme)
        self.services.effects.transition(ui, f"palette → {theme.label}", "accent")
        return CommandResult()

    def _effects(self, args: str) -> CommandResult:
        ui = self.services.ui
        effects = self.services.effects
        parts = args.split()
        action = parts[0].lower() if parts else "status"
        if action in {"status", "show"}:
            ui.detail_panel(
                "EFFECTS",
                [
                    ("animation", "on" if effects.enabled else "off"),
                    ("speed", f"{effects.speed:g}×"),
                    ("typewriter", "on" if effects.enabled else "off"),
                    ("whispers", "on" if effects.enabled else "off"),
                    ("flicker", "on" if effects.enabled else "off"),
                ],
                subtitle="disable everything with /effects off",
            )
            return CommandResult()
        if action in {"on", "off"}:
            enabled = action == "on"
            effects.update(enabled=enabled)
            self.services.config.animation = enabled
            ui.success(f"Haunted effects are now {'on' if enabled else 'off'}.")
            if not enabled:
                ui.info("No animation. No glitches. Just the work.")
            return CommandResult()
        if action == "speed":
            if len(parts) < 2:
                ui.error("Usage: /effects speed <0.1–10>")
                return CommandResult()
            try:
                speed = float(parts[1])
            except ValueError:
                ui.error("Speed must be a number between 0.1 and 10.")
                return CommandResult()
            if not 0.1 <= speed <= 10:
                ui.error("Speed must be between 0.1 and 10.")
                return CommandResult()
            effects.update(speed=speed)
            self.services.config.animation_speed = speed
            ui.success(f"Animation speed is now {speed:g}×.")
            return CommandResult()
        ui.error("Unknown effects action. Use on, off, speed N, or status.")
        return CommandResult()

    # ------------------------------------------------------------------ unknown
    def _unknown(self, name: str) -> CommandResult:
        ui = self.services.ui
        candidates = _all_command_names()
        suggestions = difflib.get_close_matches(name, candidates, n=3, cutoff=0.4)
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        ui.error(f"Unknown ritual '/{name}'.{hint} Try /help for the full list.")
        return CommandResult()


def _help_entries() -> list[tuple[str, str, str]]:
    order = ["Session", "Presence", "Developer", "Appearance", "Memory", "System"]
    entries: list[tuple[str, str, str]] = []
    for group in order:
        for spec in COMMANDS:
            if spec.group == group:
                entries.append((group, spec.usage, spec.description))
    return entries


__all__ = [
    "COMMANDS",
    "CommandSpec",
    "CommandInvocation",
    "CommandResult",
    "CommandServices",
    "CommandProcessor",
    "CommandParseError",
    "parse_command",
]
