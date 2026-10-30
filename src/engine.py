"""Conversation orchestration for PHANTOM.exe.

The engine owns the active session, builds a bounded context window, streams
model output token by token, and saves only complete assistant replies.  It
never fabricates a response when Ollama is unavailable.
"""

from __future__ import annotations

from typing import Callable, Sequence

from config import Config
from src.memory import (
    DEFAULT_TITLE,
    MemoryStore,
    Message,
    Session,
    title_from_text,
)
from src.ollama_client import OllamaClient, OllamaProtocolError
from src.personality import Personality, find_personality, get_personality

BASE_SYSTEM_PROMPT = """\
You are PHANTOM.exe, a local AI developer companion living in the user's
terminal. You are genuinely useful: you explain code, debug errors, review
implementations, and teach programming concepts.

Shared rules for every presence:
- You can only see the conversation text. You cannot read files, execute code,
  run commands, browse the internet, or inspect the user's machine.
- Never claim that you ran code or a command. Never invent command output,
  test results, benchmarks, or file contents.
- When you suggest a shell command, put it in a fenced block, explain what it
  does, and make clear the user must run it themselves. Never present a
  command as already executed.
- Warn clearly before destructive or irreversible operations. Do not help
  conceal malware, exfiltrate secrets, or bypass authentication.
- Never ask for API keys, passwords, tokens, or private keys. If the user
  pastes a secret, tell them to rotate it and redact it.
- Be accurate. If you are unsure, say so and describe what you would check.
- Answer in concise, terminal-friendly Markdown. Use fenced code blocks with a
  language tag. Avoid huge tables and decorative noise.
- Prefer the smallest correct explanation or patch. Ask a focused clarifying
  question only when the request is genuinely ambiguous.
- Stay in character, but never let atmosphere reduce technical accuracy.
"""


class ChatEngine:
    """Stateful conversation engine with bounded context and local memory."""

    def __init__(
        self,
        config: Config,
        client: OllamaClient,
        memory: MemoryStore,
        *,
        personality: str | None = None,
        history_limit: int = 24,
        char_budget: int = 24_000,
    ) -> None:
        self.config = config
        self.client = client
        self.memory = memory
        self.history_limit = max(2, history_limit)
        self.char_budget = max(2_000, char_budget)
        chosen = personality or config.personality
        self.personality: Personality = find_personality(chosen) or get_personality(
            "phantom"
        )
        self.session: Session | None = None

    # ------------------------------------------------------------------ model
    @property
    def model(self) -> str:
        return self.client.model

    def set_model(self, model: str) -> None:
        self.client.set_model(model)
        self.config.model = model
        if self.session is not None:
            self.session.model = model
            self.memory.save(self.session)

    # ------------------------------------------------------------- personality
    def set_personality(self, slug: str) -> Personality:
        personality = get_personality(slug)
        self.personality = personality
        if self.session is not None:
            self.session.personality = personality.slug
            self.memory.save(self.session)
        return personality

    def set_title(self, title: str) -> None:
        """Rename the active session, keeping the transcript intact."""

        cleaned = " ".join(str(title).split()).strip()
        if not cleaned:
            raise ValueError("A session title cannot be empty.")
        session = self.ensure_session()
        session.title = cleaned[:80]
        self.memory.save(session)

    # ---------------------------------------------------------------- sessions
    def start_new_session(self, *, title: str = DEFAULT_TITLE) -> Session:
        self.save()
        self.session = self.memory.create_session(
            personality=self.personality.slug,
            model=self.model,
            title=title,
            persist=False,
        )
        return self.session

    def load_session(self, session_id: str) -> Session:
        session = self.memory.load(session_id)
        self.save()
        self.session = session
        restored = find_personality(session.personality)
        if restored is not None:
            self.personality = restored
        if session.model:
            self.client.set_model(session.model)
            self.config.model = session.model
        return session

    def save(self) -> None:
        if self.session is not None and self.session.messages:
            self.memory.save(self.session)

    def history(self) -> list[dict[str, str]]:
        if self.session is None:
            return []
        return self.session.message_dicts()

    def ensure_session(self) -> Session:
        if self.session is None:
            self.start_new_session()
        assert self.session is not None
        return self.session

    # ----------------------------------------------------------------- context
    def build_system_prompt(self) -> str:
        return (
            BASE_SYSTEM_PROMPT
            + "\nActive presence: "
            + self.personality.name
            + "\n\n"
            + self.personality.system_prompt.strip()
            + "\n"
        )

    def context_messages(self, *, last_user_override: str | None = None) -> list[dict[str, str]]:
        session = self.ensure_session()
        messages = list(session.messages)
        if last_user_override is not None and messages:
            messages[-1] = Message(
                role="user",
                content=last_user_override,
                timestamp=messages[-1].timestamp,
            )

        trimmed: list[Message] = []
        used = 0
        for message in reversed(messages):
            cost = len(message.content) + 16
            if trimmed and (
                len(trimmed) >= self.history_limit or used + cost > self.char_budget
            ):
                break
            trimmed.append(message)
            used += cost
        trimmed.reverse()
        while len(trimmed) > 1 and trimmed[0].role != "user":
            trimmed.pop(0)
        return [
            {"role": "system", "content": self.build_system_prompt()},
            *(
                {"role": message.role, "content": message.content}
                for message in trimmed
            ),
        ]

    # -------------------------------------------------------------------- chat
    def send(
        self,
        user_text: str,
        *,
        prompt_text: str | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """Send a message and return the complete assistant response.

        ``prompt_text`` is what the model receives; ``user_text`` is what is
        stored and displayed in history.  The developer toolkit uses this to
        wrap a pasted snippet without cluttering the transcript.
        """

        if not isinstance(user_text, str) or not user_text.strip():
            raise ValueError("The message is empty.")
        session = self.ensure_session()
        if not session.messages and session.title == DEFAULT_TITLE:
            session.title = title_from_text(user_text)

        session.add_message("user", user_text)
        self.memory.save(session)

        effective_prompt = prompt_text if prompt_text is not None else user_text
        messages = self.context_messages(last_user_override=effective_prompt)
        chunks: list[str] = []
        stream = self.client.stream_chat(messages, model=self.model)
        try:
            for chunk in stream:
                if not chunk:
                    continue
                chunks.append(chunk)
                if on_token is not None:
                    on_token(chunk)
        except KeyboardInterrupt:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
            self.memory.save(session)
            raise
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()

        answer = "".join(chunks)
        if not answer.strip():
            self.memory.save(session)
            raise OllamaProtocolError(
                "The presence answered with silence. The empty reply was not saved."
            )
        session.add_message("assistant", answer)
        self.memory.save(session)
        return answer

    def last_assistant_message(self) -> str | None:
        if self.session is None:
            return None
        for message in reversed(self.session.messages):
            if message.role == "assistant":
                return message.content
        return None


__all__ = ["ChatEngine", "BASE_SYSTEM_PROMPT"]
