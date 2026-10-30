from __future__ import annotations

import src.app as app_module
from config import load_config
from src.app import PhantomApp
from src.ollama_client import OllamaStatus


class FakeClient:
    def __init__(self, model: str = "test:latest") -> None:
        self.model = model

    def set_model(self, model: str) -> None:
        self.model = model

    def status(self, model: str | None = None) -> OllamaStatus:
        checked = (model or self.model).strip()
        return OllamaStatus(
            reachable=True,
            base_url="http://localhost:11434",
            version="0.9.0",
            models=["test:latest"],
            model_available=checked == "test:latest",
            checked_model=checked,
            latency_ms=1.0,
        )

    def stream_chat(self, messages, model=None):
        yield "Hello"


def make_app(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "OllamaClient", lambda *args, **kwargs: FakeClient())
    config = load_config(
        env_file=None,
        environ={"PHANTOM_MEMORY_DIR": str(tmp_path / "sessions")},
    )
    config.animation = False
    return PhantomApp(config, plain=True, color=False)


def test_status_and_list_do_not_create_a_session(monkeypatch, tmp_path, capsys):
    app = make_app(monkeypatch, tmp_path)

    assert app.status() == 0
    assert app.list_sessions() == 0
    assert app.memory.count() == 0
    assert "ollama" in capsys.readouterr().out.lower()


def test_run_without_messages_does_not_leave_an_empty_session(
    monkeypatch, tmp_path, capsys
):
    app = make_app(monkeypatch, tmp_path)
    inputs = iter(["", "/exit"])
    app.ui._input = lambda prompt: next(inputs)

    assert app.run(show_boot=False) == 0
    assert app.memory.count() == 0
    assert "Traceback" not in capsys.readouterr().out


def test_run_persists_a_completed_conversation(monkeypatch, tmp_path, capsys):
    app = make_app(monkeypatch, tmp_path)
    inputs = iter(["hello", "/exit"])
    app.ui._input = lambda prompt: next(inputs)

    assert app.run(show_boot=False) == 0

    assert app.memory.count() == 1
    summary = app.memory.latest()
    assert summary is not None
    session = app.memory.load(summary.id)
    assert [message.role for message in session.messages] == ["user", "assistant"]
    assert session.messages[1].content == "Hello"
    assert "Traceback" not in capsys.readouterr().out
