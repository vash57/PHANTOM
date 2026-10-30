"""Local JSON-based session memory for PHANTOM.exe.

Every séance is a single JSON file.  Writes are atomic, permissions are kept
private where the OS supports it, and malformed files are isolated instead of
being allowed to crash the terminal.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.utils import (
    atomic_write_json,
    ensure_private_dir,
    now_iso,
    read_json,
    safe_session_id,
    truncate,
)

DEFAULT_TITLE = "Untitled séance"
SESSION_PREFIX = "session-"
SESSION_SUFFIX = ".json"
_SESSION_FILE_RE = re.compile(r"^session-[A-Za-z0-9][A-Za-z0-9_-]{0,63}\.json$")


class MemoryStoreError(RuntimeError):
    """Base class for memory problems that the UI can explain."""


class SessionNotFoundError(MemoryStoreError):
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"No session matches {session_id!r}.")


class SessionCorruptError(MemoryStoreError):
    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        super().__init__(f"Unreadable memory file {path.name}: {detail}")


@dataclass
class Message:
    role: str
    content: str
    timestamp: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, str]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "Message":
        if not isinstance(payload, dict):
            raise ValueError("message is not an object")
        role = payload.get("role")
        content = payload.get("content")
        timestamp = payload.get("timestamp") or now_iso()
        if role not in {"user", "assistant"}:
            raise ValueError(f"invalid role {role!r}")
        if not isinstance(content, str):
            raise ValueError("message content is not text")
        if not isinstance(timestamp, str):
            timestamp = now_iso()
        return cls(role=role, content=content, timestamp=timestamp)


@dataclass
class Session:
    id: str
    title: str = DEFAULT_TITLE
    personality: str = "phantom"
    model: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    messages: list[Message] = field(default_factory=list)

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def preview(self) -> str:
        for message in reversed(self.messages):
            if message.role == "user" and message.content.strip():
                return truncate(message.content.replace("\n", " "), 72)
        return "an empty room"

    def add_message(self, role: str, content: str) -> Message:
        if role not in {"user", "assistant"}:
            raise ValueError(f"Invalid message role: {role}")
        message = Message(role=role, content=content)
        self.messages.append(message)
        self.updated_at = message.timestamp
        return message

    def message_dicts(self) -> list[dict[str, str]]:
        return [message.to_dict() for message in self.messages]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "id": self.id,
            "title": self.title,
            "personality": self.personality,
            "model": self.model,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [message.to_dict() for message in self.messages],
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "Session":
        if not isinstance(payload, dict):
            raise ValueError("session is not an object")
        raw_id = payload.get("id")
        if not isinstance(raw_id, str):
            raise ValueError("session id is missing")
        session_id = safe_session_id(raw_id)
        raw_messages = payload.get("messages", [])
        if not isinstance(raw_messages, list):
            raise ValueError("messages is not a list")
        messages = [Message.from_dict(item) for item in raw_messages]
        return cls(
            id=session_id,
            title=str(payload.get("title") or DEFAULT_TITLE),
            personality=str(payload.get("personality") or "phantom"),
            model=str(payload.get("model") or ""),
            created_at=str(payload.get("created_at") or now_iso()),
            updated_at=str(payload.get("updated_at") or now_iso()),
            messages=messages,
        )


@dataclass(frozen=True)
class SessionSummary:
    id: str
    title: str
    personality: str
    model: str
    created_at: str
    updated_at: str
    message_count: int
    preview: str

    @classmethod
    def from_session(cls, session: Session) -> "SessionSummary":
        return cls(
            id=session.id,
            title=session.title,
            personality=session.personality,
            model=session.model,
            created_at=session.created_at,
            updated_at=session.updated_at,
            message_count=session.message_count,
            preview=session.preview,
        )


@dataclass(frozen=True)
class MemoryHealth:
    directory: Path
    total_files: int
    valid_sessions: int
    corrupt_files: tuple[str, ...]


def title_from_text(text: str, fallback: str = DEFAULT_TITLE) -> str:
    """Turn the first meaningful line of a message into a session title."""

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("```"):
            continue
        line = re.sub(r"^[#>*`\-\s]+", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            return truncate(line, 62)
    return fallback


class MemoryStore:
    """A directory of session files plus safe CRUD operations."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).expanduser()
        try:
            ensure_private_dir(self.directory)
        except OSError as exc:
            raise MemoryStoreError(
                f"Cannot create memory directory {self.directory}: {exc}"
            ) from exc
        if not os.access(self.directory, os.W_OK):
            raise MemoryStoreError(
                f"Memory directory is not writable: {self.directory}"
            )

    def path_for(self, session_id: str) -> Path:
        return self.directory / f"{SESSION_PREFIX}{safe_session_id(session_id)}{SESSION_SUFFIX}"

    def _new_id(self) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"{stamp}-{secrets.token_hex(3)}"

    def create_session(
        self,
        *,
        personality: str = "phantom",
        model: str = "",
        title: str = DEFAULT_TITLE,
        persist: bool = True,
    ) -> Session:
        session = Session(
            id=self._new_id(),
            title=title,
            personality=personality,
            model=model,
        )
        if persist:
            self.save(session)
        return session

    def save(self, session: Session) -> Path:
        session.updated_at = now_iso()
        path = self.path_for(session.id)
        try:
            atomic_write_json(path, session.to_dict())
        except OSError as exc:
            raise MemoryStoreError(f"Could not write {path.name}: {exc}") from exc
        return path

    def load(self, session_id: str) -> Session:
        path = self.path_for(session_id)
        if not path.is_file():
            raise SessionNotFoundError(session_id)
        try:
            payload = read_json(path)
            session = Session.from_dict(payload)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise SessionCorruptError(path, str(exc)) from exc
        if session.id != session_id:
            raise SessionCorruptError(path, "session id does not match filename")
        return session

    def _iter_paths(self) -> Iterable[Path]:
        if not self.directory.is_dir():
            return []

        def modified(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0

        return sorted(
            (
                path
                for path in self.directory.iterdir()
                if path.is_file() and _SESSION_FILE_RE.match(path.name)
            ),
            key=modified,
            reverse=True,
        )

    def list_sessions(self) -> list[SessionSummary]:
        summaries: list[SessionSummary] = []
        for path in self._iter_paths():
            try:
                session = Session.from_dict(read_json(path))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            summaries.append(SessionSummary.from_session(session))
        summaries.sort(key=lambda summary: summary.updated_at, reverse=True)
        return summaries

    def latest(self) -> SessionSummary | None:
        sessions = self.list_sessions()
        return sessions[0] if sessions else None

    def find(self, needle: str) -> list[SessionSummary]:
        needle = needle.strip().lower()
        if not needle:
            return []
        sessions = self.list_sessions()
        exact = [session for session in sessions if session.id == needle]
        if exact:
            return exact
        return [
            session
            for session in sessions
            if session.id.lower().startswith(needle)
            or session.title.lower().startswith(needle)
        ]

    def resolve(self, needle: str) -> SessionSummary:
        matches = self.find(needle)
        if not matches:
            raise SessionNotFoundError(needle)
        if len(matches) > 1:
            ids = ", ".join(match.id for match in matches[:5])
            raise MemoryStoreError(
                f"Ambiguous session {needle!r}; it matches {len(matches)} echoes: {ids}"
            )
        return matches[0]

    def delete(self, session_id: str) -> None:
        path = self.path_for(session_id)
        if not path.is_file():
            raise SessionNotFoundError(session_id)
        try:
            path.unlink()
        except OSError as exc:
            raise MemoryStoreError(f"Could not delete {path.name}: {exc}") from exc

    def clear_all(self) -> int:
        removed = 0
        errors: list[str] = []
        for path in self._iter_paths():
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                errors.append(f"{path.name}: {exc}")
        if errors:
            raise MemoryStoreError(
                f"Removed {removed} session(s), but {len(errors)} could not be "
                f"deleted: {'; '.join(errors)}"
            )
        return removed

    def health(self) -> MemoryHealth:
        total = 0
        valid = 0
        corrupt: list[str] = []
        for path in self._iter_paths():
            total += 1
            try:
                Session.from_dict(read_json(path))
                valid += 1
            except (OSError, ValueError, json.JSONDecodeError):
                corrupt.append(path.name)
        return MemoryHealth(
            directory=self.directory,
            total_files=total,
            valid_sessions=valid,
            corrupt_files=tuple(corrupt),
        )

    def count(self) -> int:
        return len(self.list_sessions())


__all__ = [
    "Message",
    "Session",
    "SessionSummary",
    "MemoryHealth",
    "MemoryStore",
    "MemoryStoreError",
    "SessionNotFoundError",
    "SessionCorruptError",
    "DEFAULT_TITLE",
    "title_from_text",
]
