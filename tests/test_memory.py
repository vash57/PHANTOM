from __future__ import annotations

import json

import pytest

from src.memory import (
    DEFAULT_TITLE,
    MemoryHealth,
    MemoryStore,
    MemoryStoreError,
    Message,
    Session,
    SessionNotFoundError,
    title_from_text,
)
from src.utils import safe_session_id


def test_create_save_and_load_round_trip(memory):
    session = memory.create_session(
        personality="oracle",
        model="test:latest",
        title="A test séance",
    )
    session.add_message("user", "hello")
    session.add_message("assistant", "hello back")
    memory.save(session)

    loaded = memory.load(session.id)

    assert loaded.id == session.id
    assert loaded.title == "A test séance"
    assert loaded.personality == "oracle"
    assert loaded.model == "test:latest"
    assert loaded.message_count == 2
    assert loaded.messages[0].role == "user"
    assert loaded.messages[1].content == "hello back"
    assert loaded.preview == "hello"


def test_list_latest_and_count(memory):
    first = memory.create_session(title="first")
    second = memory.create_session(title="second")
    second.add_message("user", "newer")
    memory.save(second)

    summaries = memory.list_sessions()

    assert {summary.id for summary in summaries} == {first.id, second.id}
    assert memory.count() == 2
    assert memory.latest() is not None
    assert memory.latest().id == second.id


def test_find_and_resolve_by_id_prefix_and_title(memory):
    session = memory.create_session(title="Unique Title")
    session.add_message("user", "content")
    memory.save(session)

    assert memory.find(session.id)[0].id == session.id
    assert memory.find(session.id[:10])[0].id == session.id
    assert memory.find("unique")[0].id == session.id
    assert memory.resolve(session.id[:10]).id == session.id


def test_resolve_is_ambiguous_for_shared_titles(memory):
    first = memory.create_session(title="Same")
    second = memory.create_session(title="Same")
    memory.save(first)
    memory.save(second)

    with pytest.raises(MemoryStoreError):
        memory.resolve("Same")


def test_missing_and_deleted_sessions(memory):
    session = memory.create_session(title="temporary")
    memory.delete(session.id)

    with pytest.raises(SessionNotFoundError):
        memory.load(session.id)
    with pytest.raises(SessionNotFoundError):
        memory.delete(session.id)
    with pytest.raises(SessionNotFoundError):
        memory.resolve("does-not-exist")


def test_clear_all_removes_every_session(memory):
    memory.create_session(title="one")
    memory.create_session(title="two")

    removed = memory.clear_all()

    assert removed == 2
    assert memory.count() == 0
    assert memory.list_sessions() == []


def test_health_isolates_corrupt_files(memory):
    good = memory.create_session(title="good")
    good.add_message("user", "still readable")
    memory.save(good)
    (memory.directory / "session-corrupt.json").write_text("{not json", encoding="utf-8")

    health = memory.health()

    assert isinstance(health, MemoryHealth)
    assert health.total_files == 2
    assert health.valid_sessions == 1
    assert health.corrupt_files == ("session-corrupt.json",)
    assert memory.count() == 1


def test_health_is_empty_for_new_store(memory):
    health = memory.health()

    assert health.total_files == 0
    assert health.valid_sessions == 0
    assert health.corrupt_files == ()


def test_title_from_text_prefers_first_meaningful_line():
    assert title_from_text("hello world") == "hello world"
    assert title_from_text("# Heading\nbody") == "Heading"
    assert title_from_text("```python\nprint(1)\n```") == "print(1)"
    assert title_from_text("   \n\n") == DEFAULT_TITLE
    assert title_from_text("```\n```") == DEFAULT_TITLE


def test_message_and_session_validation():
    with pytest.raises(ValueError):
        Message.from_dict({"role": "system", "content": "nope"})
    with pytest.raises(ValueError):
        Message.from_dict({"role": "user", "content": 123})
    with pytest.raises(ValueError):
        Session.from_dict({"id": "", "messages": "not-a-list"})

    session = Session(id="abc", title="t")
    with pytest.raises(ValueError):
        session.add_message("system", "nope")


def test_session_json_shape_and_reload(memory):
    session = memory.create_session(title="shape")
    session.add_message("user", "hi")
    memory.save(session)
    path = memory.path_for(session.id)

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["version"] == 1
    assert payload["id"] == session.id
    assert payload["messages"][0]["role"] == "user"
    assert payload["messages"][0]["timestamp"]


def test_unsafe_session_ids_are_rejected(memory):
    with pytest.raises(ValueError):
        safe_session_id("../escape")
    with pytest.raises(ValueError):
        memory.path_for("../escape")
    with pytest.raises(ValueError):
        safe_session_id("")
    with pytest.raises(ValueError):
        safe_session_id("has space")
