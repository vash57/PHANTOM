"""Colour palettes for the haunted terminal."""

from __future__ import annotations

from dataclasses import dataclass


class UnknownThemeError(ValueError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(
            f"Unknown theme {name!r}. Available: {', '.join(THEMES)}."
        )


@dataclass(frozen=True)
class Theme:
    name: str
    label: str
    description: str
    background: str
    surface: str
    primary: str
    secondary: str
    accent: str
    warning: str
    muted: str
    border: str

    def color(self, style: str) -> str:
        """Resolve a semantic style key to a hex colour."""

        mapping = {
            "primary": self.primary,
            "secondary": self.secondary,
            "accent": self.accent,
            "warning": self.warning,
            "danger": self.warning,
            "muted": self.muted,
            "border": self.border,
            "surface": self.surface,
            "background": self.background,
        }
        return mapping.get(style, self.primary)


THEMES: dict[str, Theme] = {
    "phosphor": Theme(
        name="phosphor",
        label="Phosphor",
        description="Deep black, phosphor green, a bruise of purple.",
        background="#000000",
        surface="#030804",
        primary="#39ff14",
        secondary="#8affc1",
        accent="#b388ff",
        warning="#ff3b3b",
        muted="#4f7a58",
        border="#1f7a3f",
    ),
    "blood": Theme(
        name="blood",
        label="Blood Static",
        description="Terminal red, old bone, warning lights.",
        background="#000000",
        surface="#0c0202",
        primary="#ff4d4d",
        secondary="#ff8a65",
        accent="#ffd166",
        warning="#ff1744",
        muted="#7a3b3b",
        border="#6b1111",
    ),
    "violet": Theme(
        name="violet",
        label="Violet Signal",
        description="Cold violet, electric blue, a distant transmission.",
        background="#000000",
        surface="#06030c",
        primary="#c792ea",
        secondary="#82aaff",
        accent="#f78cff",
        warning="#ff5370",
        muted="#5d5375",
        border="#4a2c6b",
    ),
    "mono": Theme(
        name="mono",
        label="Mono",
        description="No colour. Maximum contrast, minimum spectacle.",
        background="#000000",
        surface="#050505",
        primary="#d6d6d6",
        secondary="#f2f2f2",
        accent="#ffffff",
        warning="#ffffff",
        muted="#7a7a7a",
        border="#4a4a4a",
    ),
}

DEFAULT_THEME = "phosphor"


def get_theme(name: str) -> Theme:
    try:
        return THEMES[name.strip().lower()]
    except (KeyError, AttributeError) as exc:
        raise UnknownThemeError(str(name)) from exc


def find_theme(name: str) -> Theme | None:
    try:
        return THEMES[name.strip().lower()]
    except (KeyError, AttributeError):
        return None


__all__ = [
    "Theme",
    "UnknownThemeError",
    "THEMES",
    "DEFAULT_THEME",
    "get_theme",
    "find_theme",
]
