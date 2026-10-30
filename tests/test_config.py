from __future__ import annotations

from pathlib import Path

from config import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_PERSONALITY,
    load_config,
    parse_env_file,
    redact_url,
)


def test_defaults_without_environment():
    config = load_config(env_file=None, environ={})

    assert config.base_url == DEFAULT_BASE_URL
    assert config.model == DEFAULT_MODEL
    assert config.personality == DEFAULT_PERSONALITY
    assert config.animation is True
    assert config.animation_speed == 1.0
    assert config.memory_dir == Path("data/sessions")
    assert config.warnings == []


def test_process_environment_overrides_defaults():
    config = load_config(
        env_file=None,
        environ={
            "OLLAMA_BASE_URL": "http://127.0.0.1:9999/",
            "OLLAMA_MODEL": "llama3.2:3b",
            "PHANTOM_PERSONALITY": "WRAITH",
            "PHANTOM_ANIMATION": "off",
            "PHANTOM_ANIMATION_SPEED": "2.5",
            "PHANTOM_MEMORY_DIR": "tmp/memory",
        },
    )

    assert config.base_url == "http://127.0.0.1:9999"
    assert config.model == "llama3.2:3b"
    assert config.personality == "wraith"
    assert config.animation is False
    assert config.animation_speed == 2.5
    assert config.memory_dir == Path("tmp/memory")


def test_process_environment_wins_over_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OLLAMA_MODEL=file-model\nOLLAMA_BASE_URL=http://file:1\n")

    config = load_config(
        env_file=env_file,
        environ={"OLLAMA_MODEL": "process-model"},
    )

    assert config.model == "process-model"
    assert config.base_url == "http://file:1"


def test_env_file_values_are_loaded(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "export OLLAMA_MODEL='quoted model'",
                'OLLAMA_BASE_URL="http://example.test:11434"',
                "PHANTOM_ANIMATION=no",
                "PHANTOM_ANIMATION_SPEED=0.5",
                "PHANTOM_MEMORY_DIR=./sessions",
                "",
            ]
        )
    )

    config = load_config(env_file=env_file, environ={})

    assert config.model == "quoted model"
    assert config.base_url == "http://example.test:11434"
    assert config.animation is False
    assert config.animation_speed == 0.5
    assert config.memory_dir == Path("./sessions")


def test_parse_env_file_supports_quotes_comments_and_export(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "export FOO='bar baz'\n"
        "PLAIN=value # trailing comment\n"
        "EMPTY=\n"
        "BAD-KEY=ignored\n"
        "NO_EQUALS\n"
    )

    values = parse_env_file(env_file)

    assert values["FOO"] == "bar baz"
    assert values["PLAIN"] == "value"
    assert values["EMPTY"] == ""
    assert "BAD-KEY" not in values
    assert "NO_EQUALS" not in values


def test_invalid_base_url_falls_back_with_warning():
    for value in (
        "ftp://not-http.example",
        "http://localhost:not-a-port",
        "not-a-url",
    ):
        config = load_config(
            env_file=None,
            environ={"OLLAMA_BASE_URL": value},
        )

        assert config.base_url == DEFAULT_BASE_URL
        assert any("OLLAMA_BASE_URL" in warning for warning in config.warnings)


def test_redact_url_tolerates_an_invalid_port():
    assert redact_url("http://localhost:not-a-port/api") == "http://localhost/api"


def test_unknown_personality_falls_back_with_warning():
    config = load_config(
        env_file=None,
        environ={"PHANTOM_PERSONALITY": "ghost"},
    )

    assert config.personality == DEFAULT_PERSONALITY
    assert any("PHANTOM_PERSONALITY" in warning for warning in config.warnings)


def test_animation_speed_is_clamped_and_warned():
    high = load_config(
        env_file=None,
        environ={"PHANTOM_ANIMATION_SPEED": "99"},
    )
    low = load_config(
        env_file=None,
        environ={"PHANTOM_ANIMATION_SPEED": "0.01"},
    )
    invalid = load_config(
        env_file=None,
        environ={"PHANTOM_ANIMATION_SPEED": "fast"},
    )

    assert high.animation_speed == 10.0
    assert low.animation_speed == 0.1
    assert invalid.animation_speed == 1.0
    for config in (high, low, invalid):
        assert any("PHANTOM_ANIMATION_SPEED" in warning for warning in config.warnings)


def test_boolean_parsing():
    for value in ("1", "true", "YES", "on", "y"):
        assert load_config(
            env_file=None, environ={"PHANTOM_ANIMATION": value}
        ).animation is True
    for value in ("0", "false", "NO", "off", "n"):
        assert load_config(
            env_file=None, environ={"PHANTOM_ANIMATION": value}
        ).animation is False


def test_redact_url_removes_credentials_and_query():
    redacted = redact_url(
        "http://user:secret@example.test:11434/api/tags?token=abc"
    )

    assert redacted == "http://example.test:11434/api/tags"
    assert "secret" not in redacted
    assert "token" not in redacted


def test_config_summary_never_exposes_credentials():
    config = load_config(
        env_file=None,
        environ={"OLLAMA_BASE_URL": "http://user:secret@example.test:11434"},
    )

    summary = config.summary()
    rendered = repr(summary)

    assert "secret" not in rendered
    assert summary["model"] == DEFAULT_MODEL


def test_missing_explicit_env_file_warns(tmp_path):
    config = load_config(env_file=tmp_path / "missing.env", environ={})

    assert any("not found" in warning for warning in config.warnings)
