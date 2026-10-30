from __future__ import annotations

import pytest

from src.commands import (
    CommandInvocation,
    CommandParseError,
    CommandProcessor,
    CommandResult,
    parse_command,
)


def test_parse_command_returns_none_for_chat():
    assert parse_command("hello") is None
    assert parse_command("   ") is None


def test_parse_command_extracts_name_and_args():
    invocation = parse_command("/dev explain print(1)")

    assert invocation == CommandInvocation(
        name="dev",
        args="explain print(1)",
        raw="/dev explain print(1)",
    )


def test_parse_command_rejects_empty_names():
    with pytest.raises(CommandParseError):
        parse_command("/")
    with pytest.raises(CommandParseError):
        parse_command("/   ")


def test_help_lists_commands_and_shortcuts(processor, fake_ui):
    result = processor.handle("/help")

    assert result == CommandResult()
    assert fake_ui.help
    assert any("Shortcuts" in line for line in fake_ui.infos)
    assert any("/ghost" in usage for _, usage, _ in fake_ui.help[0])
    usages = [usage for _, usage, _ in fake_ui.help[0]]
    assert usages.count("/dev <ritual> [material]") == 1


def test_clear_keeps_session(processor, fake_ui, services):
    session_id = services.engine.session.id

    processor.handle("/clear")

    assert fake_ui.cleared == 1
    assert fake_ui.logo_calls == 1
    assert services.engine.session.id == session_id


def test_status_online_and_offline(processor, fake_ui, fake_client):
    processor.handle("/status")
    assert any(title == "VITAL SIGNS" for title, _, _ in fake_ui.panels)
    assert not fake_ui.errors

    fake_ui.panels.clear()
    fake_client.reachable = False
    processor.handle("/status")

    assert any(title == "VITAL SIGNS" for title, _, _ in fake_ui.panels)
    assert fake_ui.errors


def test_scan_reports_local_checks(processor, fake_ui):
    processor.handle("/scan")

    assert fake_ui.tables
    title, headers, rows = fake_ui.tables[-1]
    assert title == "LOCAL CONFIGURATION SCAN"
    assert headers == ("check", "state", "detail")
    assert any(row[0] == "auto-exec" for row in rows)
    assert any(row[0] == "privacy" for row in rows)


def test_about(processor, fake_ui):
    processor.handle("/about")

    assert fake_ui.about_calls == 1


def test_exit_saves_and_requests_shutdown(processor, services):
    services.engine.session.add_message("user", "remember this")

    result = processor.handle("/exit")

    assert result is not None
    assert result.should_exit is True
    assert services.memory.load(services.engine.session.id).message_count == 1


def test_ghost_table_and_switch(processor, fake_ui, services):
    processor.handle("/ghost")
    assert fake_ui.tables
    assert fake_ui.tables[-1][0] == "PRESENCES"

    processor.handle("/ghost wraith")
    assert services.engine.personality.slug == "wraith"

    processor.handle("/ghost wraith")
    assert any("already here" in line for line in fake_ui.infos)

    processor.handle("/ghost ghost")
    assert fake_ui.errors


def test_model_display_list_switch_and_missing(
    processor, fake_ui, fake_client, services
):
    fake_client.models.append("other:latest")
    processor.handle("/model")
    assert any(title == "VESSEL" for title, _, _ in fake_ui.panels)

    processor.handle("/model list")
    assert fake_ui.tables[-1][0] == "INSTALLED MODELS"

    processor.handle("/model other:latest")
    assert services.engine.model == "other:latest"
    assert fake_ui.successes

    processor.handle("/model missing:latest")
    assert services.engine.model == "other:latest"
    assert fake_ui.errors


def test_model_offline_sets_with_warning(processor, fake_ui, fake_client, services):
    fake_client.reachable = False

    processor.handle("/model maybe:latest")

    assert services.engine.model == "maybe:latest"
    assert fake_ui.warnings
    assert not fake_ui.errors


def test_new_save_and_rename(processor, fake_ui, services, memory):
    old = services.engine.session.id
    services.engine.ensure_session().add_message("user", "keep this")
    services.engine.save()

    processor.handle("/new")
    assert services.engine.session.id != old
    assert memory.load(old) is not None

    processor.handle("/rename A better name")
    assert services.engine.session.title == "A better name"

    processor.handle("/save")
    assert memory.load(services.engine.session.id).title == "A better name"

    processor.handle("/rename")
    assert fake_ui.errors


def test_paste_returns_material(processor, fake_ui):
    fake_ui.multiline = "line one\nline two"

    result = processor.handle("/paste")

    assert result is not None
    assert result.send_text == "line one\nline two"
    assert result.display == "paste"


def test_paste_empty_cancels(processor, fake_ui):
    fake_ui.multiline = "   "

    result = processor.handle("/paste")

    assert result is not None
    assert result.send_text is None
    assert any("Nothing" in line for line in fake_ui.infos)


def test_memory_list_shows_a_resolvable_id_prefix(processor, fake_ui, services, memory):
    services.engine.ensure_session().add_message("user", "current")
    services.engine.save()
    processor.handle("/memory list")

    rows = fake_ui.tables[-1][2]
    shown = rows[0][0].lstrip("› ").strip()
    assert "..." not in shown
    assert memory.resolve(shown).id == services.engine.session.id


def test_memory_list_load_rename_and_delete(processor, fake_ui, services, memory):
    services.engine.ensure_session().add_message("user", "current")
    services.engine.save()
    processor.handle("/memory list")
    assert fake_ui.tables[-1][0] == "SAVED ECHOES"

    other = memory.create_session(title="other")
    other.add_message("user", "other content")
    memory.save(other)

    processor.handle(f"/memory load {other.id}")
    assert services.engine.session.id == other.id

    processor.handle("/memory rename Loaded")
    assert services.engine.session.title == "Loaded"

    old = services.engine.session.id
    processor.handle(f"/memory delete {old}")
    assert services.engine.session.id != old
    with pytest.raises(Exception):
        memory.load(old)


def test_memory_delete_cancel_and_unknown(processor, fake_ui, services, memory):
    session = memory.create_session(title="keep me")
    memory.save(session)
    fake_ui.confirm_answer = False

    processor.handle(f"/memory delete {session.id[:8]}")
    assert memory.load(session.id)

    processor.handle("/memory nonsense")
    assert fake_ui.errors


def test_memory_clear(processor, fake_ui, services, memory):
    memory.create_session(title="one")
    memory.create_session(title="two")

    processor.handle("/memory clear")

    assert memory.count() == 0
    assert services.engine.session is not None


def test_memory_empty_and_usage_errors(processor, fake_ui, services):
    services.memory.clear_all()
    services.engine.session = None

    processor.handle("/memory list")
    assert any("room is empty" in line for line in fake_ui.infos)

    processor.handle("/memory load")
    processor.handle("/memory delete")
    processor.handle("/memory rename")
    assert len(fake_ui.errors) >= 3


def test_history(processor, fake_ui, services):
    processor.handle("/history")
    assert any("no messages" in line for line in fake_ui.infos)

    services.engine.session.add_message("user", "one")
    services.engine.session.add_message("assistant", "two")

    processor.handle("/history")
    assert fake_ui.history

    processor.handle("/history all")
    assert fake_ui.history

    processor.handle("/history nope")
    assert fake_ui.errors


def test_dev_table_and_ritual(processor, fake_ui):
    processor.handle("/dev")
    assert fake_ui.tables[-1][0] == "DEVELOPER RITUALS"

    result = processor.handle("/dev explain print(1)")
    assert result is not None
    assert result.send_text == "print(1)"
    assert result.prompt_text is not None
    assert "RITUAL — Explain code" in result.prompt_text


def test_dev_shortcut_and_unknown(processor, fake_ui):
    result = processor.handle("/explain print(1)")
    assert result is not None
    assert result.prompt_text is not None

    processor.handle("/dev not-a-ritual material")
    assert fake_ui.errors


def test_dev_without_material_uses_multiline(processor, fake_ui):
    fake_ui.multiline = "some material"

    result = processor.handle("/dev review")

    assert result is not None
    assert result.send_text == "some material"

    fake_ui.multiline = ""
    result = processor.handle("/dev review")
    assert result is not None
    assert result.send_text is None


def test_theme_table_switch_and_unknown(processor, fake_ui):
    processor.handle("/theme")
    assert fake_ui.tables[-1][0] == "PALETTES"

    processor.handle("/theme blood")
    assert fake_ui.theme.name == "blood"

    processor.handle("/theme nope")
    assert fake_ui.errors


def test_effects_status_toggle_and_speed(processor, fake_ui, services):
    processor.handle("/effects")
    assert any(title == "EFFECTS" for title, _, _ in fake_ui.panels)

    processor.handle("/effects off")
    assert services.effects.enabled is False
    assert services.config.animation is False

    processor.handle("/effects on")
    assert services.effects.enabled is True

    processor.handle("/effects speed 2.5")
    assert services.effects.speed == 2.5
    assert services.config.animation_speed == 2.5

    processor.handle("/effects speed nope")
    processor.handle("/effects speed 99")
    processor.handle("/effects nope")
    assert len(fake_ui.errors) >= 3


def test_unknown_command_suggests(processor, fake_ui):
    processor.handle("/hlep")

    assert fake_ui.errors
    assert "Did you mean" in fake_ui.errors[-1]


def test_handle_parse_error_and_chat(processor, fake_ui):
    result = processor.handle("/")
    assert result == CommandResult()
    assert fake_ui.errors

    assert processor.handle("ordinary chat") is None
