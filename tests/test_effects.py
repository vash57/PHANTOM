from __future__ import annotations

import random

from src.effects import WHISPERS, Effects


class FakeWriter:
    def __init__(self, *, tty: bool = True) -> None:
        self.width = 80
        self.is_tty = tty
        self.writes: list[str] = []
        self.lines: list[str] = []
        self.cleared = 0
        self.flushes = 0

    def write(self, text: str, style: str = "primary", *, bold: bool = False) -> None:
        self.writes.append(text)

    def line(self, text: str = "", style: str = "primary", **kwargs) -> None:
        self.lines.append(text)

    def clear_line(self) -> None:
        self.cleared += 1

    def flush(self) -> None:
        self.flushes += 1


def make_effects(**kwargs):
    calls: list[float] = []
    effects = Effects(
        rng=random.Random(7),
        sleep=calls.append,
        **kwargs,
    )
    return effects, calls


def test_typewriter_writes_each_character_on_tty():
    effects, calls = make_effects()
    writer = FakeWriter()

    effects.typewriter(writer, "abc")

    assert "".join(writer.writes) == "abc"
    assert writer.lines == [""]
    assert calls
    assert writer.flushes == 1


def test_typewriter_falls_back_to_a_line_when_not_tty():
    effects, calls = make_effects()
    writer = FakeWriter(tty=False)

    effects.typewriter(writer, "abc")

    assert writer.lines == ["abc"]
    assert writer.writes == []
    assert calls == []


def test_disabled_effects_never_animate():
    effects, calls = make_effects(enabled=False)
    writer = FakeWriter()

    effects.typewriter(writer, "abc")
    effects.glitch(writer, "abc")
    effects.flicker(writer, "abc")
    effects.transition(writer, "abc")
    effects.pause(1.0)

    assert writer.writes == []
    assert writer.lines == ["abc", "abc", "abc", "abc"]
    assert calls == []


def test_glitch_text_preserves_shape_and_spaces():
    effects, _ = make_effects()

    corrupted = effects.glitch_text("hello world", intensity=1.0)

    assert len(corrupted) == len("hello world")
    assert corrupted[5] == " "
    assert corrupted != "hello world"


def test_glitch_and_flicker_render_frames():
    effects, calls = make_effects()
    writer = FakeWriter()

    effects.glitch(writer, "signal", frames=2)
    effects.flicker(writer, "signal", frames=2)

    assert writer.lines[-1] == "signal"
    assert writer.cleared >= 4
    assert calls


def test_transition_ends_on_readable_text():
    effects, _ = make_effects()
    writer = FakeWriter()

    effects.transition(writer, "the presence shifts")

    assert writer.lines[-1] == "the presence shifts"


def test_whisper_probability_and_disable():
    effects, _ = make_effects()
    assert effects.whisper(probability=0.0) is None
    assert effects.whisper(probability=1.0) in WHISPERS

    effects.update(enabled=False)
    assert effects.whisper(probability=1.0) is None


def test_speed_is_clamped_and_update_changes_it():
    effects, calls = make_effects(speed=0.0)
    assert effects.speed == 0.1

    effects.update(speed=99)
    assert effects.speed == 10.0

    effects.pause(1.0)
    assert calls == [0.1]


def test_typewriter_lines_uses_plain_lines_without_tty():
    effects, _ = make_effects()
    writer = FakeWriter(tty=False)

    effects.typewriter_lines(writer, ["one", "two"])

    assert writer.lines == ["one", "two"]
