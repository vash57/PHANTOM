from __future__ import annotations

import pytest

from config import load_config
from src.engine import ChatEngine
from src.memory import MemoryStore, SessionNotFoundError
from src.ollama_client import OllamaProtocolError


class FakeStreamClient:
    def __init__(self, chunks):
        self.model = "test:latest"
        self.chunks = list(chunks)
        self.calls = []

    def set_model(self, model: str) -> None:
        self.model = model

    def stream_chat(self, messages, *, model=None, options=None):
        self.calls.append((messages, model))
        for chunk in self.chunks:
            if isinstance(chunk, BaseException):
                raise chunk
            yield chunk


@pytest.fixture
def engine(tmp_path):
    config = load_config(env_file=None, environ={})
    memory = MemoryStore(tmp_path / "sessions")
    client = FakeStreamClient(["Hel", "lo"])
    return ChatEngine(config, client, memory), memory, client


def test_send_streams_stores_and_titles(engine):
    chat, memory, client = engine
    chat.start_new_session()
    tokens = []

    answer = chat.send("Explain this function", on_token=tokens.append)

    assert answer == "Hello"
    assert tokens == ["Hel", "lo"]
    assert chat.session is not None
    assert chat.session.title == "Explain this function"
    assert [message.role for message in chat.session.messages] == [
        "user",
        "assistant",
    ]
    assert chat.session.messages[0].content == "Explain this function"
    assert chat.session.messages[1].content == "Hello"
    assert memory.load(chat.session.id).message_count == 2
    assert client.calls


def test_prompt_text_is_sent_but_user_text_is_stored(engine):
    chat, _, client = engine
    chat.start_new_session()

    chat.send("print(1)", prompt_text="RITUAL WRAPPER")

    messages, model = client.calls[-1]
    assert model == "test:latest"
    assert messages[-1]["content"] == "RITUAL WRAPPER"
    assert chat.history()[-2]["content"] == "print(1)"


def test_context_contains_system_prompt_and_is_bounded(tmp_path):
    config = load_config(env_file=None, environ={})
    memory = MemoryStore(tmp_path / "sessions")
    client = FakeStreamClient([])
    chat = ChatEngine(config, client, memory, history_limit=2, char_budget=2_000)
    chat.start_new_session()

    for index in range(6):
        chat.session.add_message("user" if index % 2 == 0 else "assistant", f"m{index}")

    context = chat.context_messages()

    assert context[0]["role"] == "system"
    assert "Shared rules for every presence" in context[0]["content"]
    assert 1 <= len(context) - 1 <= 2


def test_context_override_replaces_last_message(engine):
    chat, _, _ = engine
    chat.start_new_session()
    chat.session.add_message("user", "original")

    context = chat.context_messages(last_user_override="wrapped")

    assert context[-1]["content"] == "wrapped"


def test_set_title_personality_and_model(engine):
    chat, memory, client = engine
    chat.start_new_session()

    chat.set_title("  A   new   name  ")
    assert chat.session.title == "A new name"

    chat.set_personality("oracle")
    assert chat.personality.slug == "oracle"
    assert chat.session.personality == "oracle"

    chat.set_model("other:latest")
    assert chat.model == "other:latest"
    assert client.model == "other:latest"
    assert chat.session.model == "other:latest"
    assert memory.load(chat.session.id).title == "A new name"


def test_set_title_rejects_empty(engine):
    chat, _, _ = engine
    chat.start_new_session()

    with pytest.raises(ValueError):
        chat.set_title("   ")


def test_start_new_session_saves_previous(engine):
    chat, memory, _ = engine
    first = chat.start_new_session()
    first.add_message("user", "hello")
    chat.save()

    second = chat.start_new_session()

    assert second.id != first.id
    assert memory.load(first.id).message_count == 1


def test_start_new_session_does_not_persist_an_empty_room(engine):
    chat, memory, _ = engine
    first = chat.start_new_session()

    second = chat.start_new_session()

    assert second.id != first.id
    assert memory.count() == 0
    with pytest.raises(SessionNotFoundError):
        memory.load(first.id)


def test_load_session_restores_transcript_and_presence(engine):
    chat, memory, _ = engine
    original = chat.start_new_session()
    original.add_message("user", "remember me")
    original.add_message("assistant", "I do")
    original.personality = "nightmare"
    original.model = "test:latest"
    chat.save()

    other_client = FakeStreamClient([])
    other = ChatEngine(chat.config, other_client, memory)
    loaded = other.load_session(original.id)

    assert loaded.id == original.id
    assert other.history()[0]["content"] == "remember me"
    assert other.personality.slug == "nightmare"
    assert other.model == "test:latest"


def test_empty_response_is_not_saved(tmp_path):
    config = load_config(env_file=None, environ={})
    memory = MemoryStore(tmp_path / "sessions")
    client = FakeStreamClient([])
    chat = ChatEngine(config, client, memory)
    chat.start_new_session()

    with pytest.raises(OllamaProtocolError):
        chat.send("say nothing")

    assert [message.role for message in chat.session.messages] == ["user"]
    assert memory.load(chat.session.id).message_count == 1


def test_interrupted_response_keeps_user_message_only(tmp_path):
    config = load_config(env_file=None, environ={})
    memory = MemoryStore(tmp_path / "sessions")
    client = FakeStreamClient(["partial", KeyboardInterrupt()])
    chat = ChatEngine(config, client, memory)
    chat.start_new_session()

    with pytest.raises(KeyboardInterrupt):
        chat.send("interrupt me")

    assert [message.role for message in chat.session.messages] == ["user"]
    assert memory.load(chat.session.id).message_count == 1


def test_last_assistant_message(engine):
    chat, _, _ = engine
    chat.start_new_session()
    assert chat.last_assistant_message() is None

    chat.send("hello")

    assert chat.last_assistant_message() == "Hello"
