from __future__ import annotations

from io import StringIO

from src.effects import Effects
from src.personality import get_personality
from src.terminal_ui import TerminalUI


def make_ui(inputs=None, *, width=80):
    stream = StringIO()
    queue = list(inputs or [])

    def input_fn(prompt=""):
        if not queue:
            raise EOFError
        return queue.pop(0)

    ui = TerminalUI(
        output=stream,
        input_fn=input_fn,
        force_plain=True,
        force_color=False,
        width=width,
    )
    return ui, stream


def test_plain_ui_configuration_and_basic_output():
    ui, stream = make_ui(width=60)

    assert ui.use_rich is False
    assert ui.color_enabled is False
    assert ui.width == 60

    ui.line("hello")
    ui.blank(2)
    ui.write("world")

    assert stream.getvalue() == "hello\n\n\nworld"


def test_compact_logo_contains_name():
    ui, stream = make_ui()

    ui.logo(compact=True)

    assert "P H A N T O M" in stream.getvalue()
    assert "ghost" in stream.getvalue()


def test_big_logo_when_wide_and_unicode():
    ui, stream = make_ui(width=200)

    ui.logo()

    output = stream.getvalue()
    assert "e x e" in output
    assert "ghost living inside your terminal" in output


def test_panel_detail_and_table_plain_rendering():
    ui, stream = make_ui(width=70)

    ui.panel("body text", title="TITLE", subtitle="sub")
    ui.detail_panel("DETAIL", [("key", "value")])
    ui.table("TABLE", ["a", "b"], [["1", "2"]])

    output = stream.getvalue()
    assert "TITLE" in output
    assert "key" in output
    assert "value" in output
    assert "TABLE" in output
    assert "1" in output


def test_history_help_about_and_status():
    ui, stream = make_ui(width=90)

    ui.show_history(
        [
            {"role": "user", "content": "hello", "timestamp": "2026-01-01T00:00:00+00:00"},
            {"role": "assistant", "content": "hi", "timestamp": "2026-01-01T00:00:01+00:00"},
        ]
    )
    ui.show_help([("System", "/help", "Show help")])
    ui.about_panel()
    ui.status_panel([("signal", "online")], subtitle="all good")

    output = stream.getvalue()
    assert "you" in output
    assert "phantom" in output
    assert "RITUALS OF THE MACHINE" in output
    assert "ABOUT THE PRESENCE" in output
    assert "VITAL SIGNS" in output


def test_history_empty():
    ui, stream = make_ui()

    ui.show_history([])

    assert "No words" in stream.getvalue()


def test_read_multiline_stops_at_marker():
    ui, _ = make_ui(["line one", "line two", "/end"])

    assert ui.read_multiline() == "line one\nline two"


def test_read_multiline_handles_eof():
    ui, _ = make_ui(["only line"])

    assert ui.read_multiline() == "only line"


def test_confirm_yes_no_default_and_retry():
    yes, _ = make_ui(["yes"])
    no, _ = make_ui(["n"])
    default, _ = make_ui([""])
    retry, _ = make_ui(["maybe", "y"])

    assert yes.confirm("ok?", False) is True
    assert no.confirm("ok?", True) is False
    assert default.confirm("ok?", True) is True
    assert retry.confirm("ok?", False) is True


def test_confirm_handles_eof():
    ui, _ = make_ui([])

    assert ui.confirm("ok?", True) is True
    assert ui.confirm("ok?", False) is False


def test_narrative_methods_render():
    ui, stream = make_ui()
    personality = get_personality("phantom")

    ui.intro(
        model="test:latest",
        personality=personality,
        signal="offline",
        memory="1 saved",
        session="abc",
    )
    ui.greeting(personality)
    ui.user_label()
    ui.assistant_header(personality)
    ui.stream("token")
    ui.end_response()
    ui.interrupted()
    ui.farewell("goodbye")
    ui.ghost_note("a note")
    ui.info("info")
    ui.success("success")
    ui.warning("warning")
    ui.error("error")

    output = stream.getvalue()
    assert "PHANTOM.exe" in output
    assert "token" in output
    assert "goodbye" in output
    assert "SIGNAL LOST" in output


def test_prompt_and_theme_switch():
    ui, _ = make_ui(["answer"])

    assert ui.prompt(get_personality("phantom")) == "answer"
    assert ui.theme.name == "phosphor"

    ui.set_theme("blood")
    assert ui.theme.name == "blood"


def test_clear_screen_non_tty_and_boot():
    effects = Effects(enabled=False, sleep=lambda _: None)
    stream = StringIO()
    ui = TerminalUI(
        output=stream,
        force_plain=True,
        force_color=False,
        width=80,
        effects=effects,
    )

    ui.clear_screen()
    ui.boot(animate=False)

    output = stream.getvalue()
    assert "SYSTEM BOOTING" in output
    assert "PHANTOM.exe is awake." in output
    assert effects.enabled is False
