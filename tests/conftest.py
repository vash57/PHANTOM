from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import load_config  # noqa: E402
from src.commands import CommandProcessor, CommandServices  # noqa: E402
from src.effects import Effects  # noqa: E402
from src.engine import ChatEngine  # noqa: E402
from src.memory import MemoryStore  # noqa: E402
from src.ollama_client import OllamaStatus  # noqa: E402
from src.themes import get_theme  # noqa: E402


class FakeClient:
    def __init__(
        self,
        model: str = "test:latest",
        *,
        models: list[str] | None = None,
        reachable: bool = True,
    ) -> None:
        self.model = model
        self.models = list(models or [model])
        self.reachable = reachable
        self.calls: list[tuple[list[dict[str, str]], str | None]] = []
        self.error = "No signal at http://localhost:11434."

    def set_model(self, model: str) -> None:
        self.model = model

    def status(self, model: str | None = None) -> OllamaStatus:
        checked = (model or self.model).strip()
        if not self.reachable:
            return OllamaStatus(
                reachable=False,
                base_url="http://localhost:11434",
                checked_model=checked,
                error=self.error,
            )
        return OllamaStatus(
            reachable=True,
            base_url="http://localhost:11434",
            version="0.9.0",
            models=list(self.models),
            model_available=checked in self.models,
            checked_model=checked,
            latency_ms=1.0,
        )


class FakeUI:
    def __init__(self) -> None:
        self.theme = get_theme("phosphor")
        self.lines: list[str] = []
        self.tables: list[tuple] = []
        self.panels: list[tuple] = []
        self.help: list[tuple] = []
        self.history: list[tuple] = []
        self.errors: list[str] = []
        self.infos: list[str] = []
        self.successes: list[str] = []
        self.warnings: list[str] = []
        self.about_calls = 0
        self.logo_calls = 0
        self.cleared = 0
        self.is_tty = False
        self.width = 80
        self.unicode = True
        self.confirm_answer = True
        self.multiline = ""

    def line(self, text: str = "", style: str = "primary", **kwargs) -> None:
        self.lines.append(text)

    def write(self, text: str, style: str = "primary", **kwargs) -> None:
        self.lines.append(text)

    def blank(self, count: int = 1) -> None:
        self.lines.extend([""] * count)

    def info(self, text: str) -> None:
        self.infos.append(text)
        self.lines.append(text)

    def success(self, text: str) -> None:
        self.successes.append(text)
        self.lines.append(text)

    def warning(self, text: str) -> None:
        self.warnings.append(text)
        self.lines.append(text)

    def error(self, text: str, *, title: str = "SIGNAL LOST") -> None:
        self.errors.append(text)
        self.lines.append(text)

    def ghost_note(self, text: str) -> None:
        self.lines.append(text)

    def detail_panel(self, title, rows, subtitle="", **kwargs) -> None:
        self.panels.append((title, tuple(rows), subtitle))

    def status_panel(self, rows, subtitle="") -> None:
        self.panels.append(("VITAL SIGNS", tuple(rows), subtitle))

    def table(self, title, headers, rows, styles=None) -> None:
        self.tables.append((title, tuple(headers), tuple(rows)))

    def show_help(self, entries) -> None:
        self.help.append(tuple(entries))

    def show_history(self, messages) -> None:
        self.history.append(tuple(messages))

    def about_panel(self, *args, **kwargs) -> None:
        self.about_calls += 1

    def clear_screen(self) -> None:
        self.cleared += 1

    def logo(self, **kwargs) -> None:
        self.logo_calls += 1

    def set_theme(self, theme):
        self.theme = get_theme(theme) if isinstance(theme, str) else theme
        return self.theme

    def confirm(self, question: str, default: bool = False) -> bool:
        return self.confirm_answer

    def read_multiline(self, label: str = "paste") -> str:
        return self.multiline


@pytest.fixture
def config():
    return load_config(env_file=None, environ={})


@pytest.fixture
def memory(tmp_path):
    return MemoryStore(tmp_path / "sessions")


@pytest.fixture
def fake_client():
    return FakeClient()


@pytest.fixture
def fake_ui():
    return FakeUI()


@pytest.fixture
def services(config, memory, fake_client, fake_ui):
    effects = Effects(enabled=False, sleep=lambda _: None)
    engine = ChatEngine(config, fake_client, memory)
    engine.start_new_session()
    return CommandServices(
        config=config,
        engine=engine,
        memory=memory,
        client=fake_client,
        ui=fake_ui,
        effects=effects,
    )


@pytest.fixture
def processor(services):
    return CommandProcessor(services)
