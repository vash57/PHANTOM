"""Configuration loading for PHANTOM.exe.

Configuration precedence, highest first:

1. Real process environment variables.
2. Values in a local ``.env`` file.
3. Built-in defaults.

No configuration is ever uploaded.  Secrets are not required, and URL
credentials are redacted before anything is rendered.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

from src.personality import PERSONALITIES

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "gemma4:e2b"
DEFAULT_PERSONALITY = "phantom"
DEFAULT_MEMORY_DIR = "data/sessions"
DEFAULT_ANIMATION = True
DEFAULT_ANIMATION_SPEED = 1.0
DEFAULT_REQUEST_TIMEOUT = 180.0
DEFAULT_STATUS_TIMEOUT = 3.0

MIN_ANIMATION_SPEED = 0.1
MAX_ANIMATION_SPEED = 10.0

_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class Config:
    """Validated, immutable-in-spirit runtime configuration."""

    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    personality: str = DEFAULT_PERSONALITY
    animation: bool = DEFAULT_ANIMATION
    animation_speed: float = DEFAULT_ANIMATION_SPEED
    memory_dir: Path = field(default_factory=lambda: Path(DEFAULT_MEMORY_DIR))
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    status_timeout: float = DEFAULT_STATUS_TIMEOUT
    env_file: Path | None = None
    warnings: list[str] = field(default_factory=list)

    def redacted_base_url(self) -> str:
        """Return the Ollama endpoint with any credentials stripped."""

        return redact_url(self.base_url)

    def summary(self) -> dict[str, object]:
        """A safe-to-display summary that never exposes environment values."""

        return {
            "ollama": self.redacted_base_url(),
            "model": self.model,
            "personality": self.personality,
            "animation": self.animation,
            "animation_speed": self.animation_speed,
            "memory_dir": str(self.memory_dir),
        }


def redact_url(url: str) -> str:
    """Remove username/password and query material from a URL."""

    try:
        parts = urlsplit(url)
    except ValueError:
        return "<invalid-url>"
    host = parts.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    if port:
        host = f"{host}:{port}"
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, host, path, "", ""))


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a small, shell-like ``.env`` file without external packages.

    Supported syntax is intentionally modest: ``KEY=value``, optional
    ``export`` prefix, single or double quoted values, blank lines and ``#``
    comments.  No command substitution or variable interpolation is performed.
    """

    values: dict[str, str] = {}
    text = path.read_text(encoding="utf-8-sig")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not _ENV_KEY.match(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        values[key] = value
    return values


def _parse_bool(value: str, default: bool) -> bool:
    normalised = value.strip().lower()
    if normalised in {"1", "true", "yes", "on", "y"}:
        return True
    if normalised in {"0", "false", "no", "off", "n"}:
        return False
    return default


def _parse_speed(value: str, default: float) -> float:
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return default
    if speed != speed:  # NaN
        return default
    return max(MIN_ANIMATION_SPEED, min(MAX_ANIMATION_SPEED, speed))


def _valid_base_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
        parts.port
    except ValueError:
        return False
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def load_config(
    env_file: str | Path | None = ".env",
    environ: Mapping[str, str] | None = None,
) -> Config:
    """Load and validate configuration.

    ``env_file=None`` disables file loading, which is useful for tests and for
    embedding PHANTOM in another application.
    """

    env = dict(os.environ if environ is None else environ)
    file_values: dict[str, str] = {}
    resolved_env_file: Path | None = None
    warnings: list[str] = []

    if env_file is not None:
        candidate = Path(env_file).expanduser()
        resolved_env_file = candidate
        if candidate.is_file():
            try:
                file_values = parse_env_file(candidate)
            except (OSError, UnicodeError) as exc:
                warnings.append(f"Could not read {candidate}: {exc}")
        elif str(env_file) != ".env":
            warnings.append(f"Environment file not found: {candidate}")

    def get(name: str) -> str | None:
        value = env.get(name)
        if value is not None and value.strip() != "":
            return value.strip()
        value = file_values.get(name)
        if value is not None and value.strip() != "":
            return value.strip()
        return None

    base_url = get("OLLAMA_BASE_URL") or DEFAULT_BASE_URL
    base_url = base_url.rstrip("/")
    if not _valid_base_url(base_url):
        warnings.append(
            f"OLLAMA_BASE_URL is not a valid http(s) URL; using {DEFAULT_BASE_URL}."
        )
        base_url = DEFAULT_BASE_URL

    model = get("OLLAMA_MODEL") or DEFAULT_MODEL
    if not model.strip():
        warnings.append(f"OLLAMA_MODEL is empty; using {DEFAULT_MODEL}.")
        model = DEFAULT_MODEL

    personality = (get("PHANTOM_PERSONALITY") or DEFAULT_PERSONALITY).lower()
    if personality not in PERSONALITIES:
        warnings.append(
            f"Unknown PHANTOM_PERSONALITY {personality!r}; using {DEFAULT_PERSONALITY}."
        )
        personality = DEFAULT_PERSONALITY

    animation_raw = get("PHANTOM_ANIMATION")
    animation = (
        _parse_bool(animation_raw, DEFAULT_ANIMATION)
        if animation_raw is not None
        else DEFAULT_ANIMATION
    )

    speed_raw = get("PHANTOM_ANIMATION_SPEED")
    animation_speed = (
        _parse_speed(speed_raw, DEFAULT_ANIMATION_SPEED)
        if speed_raw is not None
        else DEFAULT_ANIMATION_SPEED
    )
    if speed_raw is not None:
        try:
            original = float(speed_raw)
        except ValueError:
            original = None
        if original is None or original != animation_speed:
            warnings.append(
                "PHANTOM_ANIMATION_SPEED must be between "
                f"{MIN_ANIMATION_SPEED} and {MAX_ANIMATION_SPEED}; "
                f"using {animation_speed}."
            )

    memory_raw = get("PHANTOM_MEMORY_DIR") or DEFAULT_MEMORY_DIR
    memory_dir = Path(memory_raw).expanduser()

    return Config(
        base_url=base_url,
        model=model,
        personality=personality,
        animation=animation,
        animation_speed=animation_speed,
        memory_dir=memory_dir,
        env_file=resolved_env_file,
        warnings=warnings,
    )
