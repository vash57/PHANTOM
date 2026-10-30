"""A tiny, dependency-free Ollama client with streaming and honest failures."""

from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass, field
from http.client import HTTPException
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from config import redact_url


class OllamaError(RuntimeError):
    """Base class for every Ollama-facing failure."""


class OllamaUnavailable(OllamaError):
    """Ollama is not running, unreachable, or timed out."""


class OllamaModelNotFound(OllamaError):
    """The requested model is not installed."""


class OllamaProtocolError(OllamaError):
    """Ollama answered, but not in a shape PHANTOM can trust."""


@dataclass
class OllamaStatus:
    reachable: bool
    base_url: str
    version: str | None = None
    models: list[str] = field(default_factory=list)
    model_available: bool = False
    checked_model: str | None = None
    error: str | None = None
    latency_ms: float | None = None

    @property
    def summary(self) -> str:
        if not self.reachable:
            return "offline"
        model_state = "ready" if self.model_available else "model missing"
        return f"online · {len(self.models)} model(s) · {model_state}"


def normalise_model(name: str) -> str:
    name = name.strip()
    return name if ":" in name else f"{name}:latest"


def model_is_installed(requested: str, installed: Sequence[str]) -> bool:
    wanted = normalise_model(requested)
    return any(normalise_model(candidate) == wanted for candidate in installed)


class OllamaClient:
    """Minimal Ollama HTTP client.

    The client deliberately knows nothing about UI or sessions.  It raises
    typed exceptions so callers can distinguish "offline" from "model missing"
    and never mistake a local error for a model response.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "gemma4:e2b",
        *,
        timeout: float = 180.0,
        status_timeout: float = 3.0,
        opener: Callable[..., Any] | None = None,
        temperature: float = 0.65,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = float(timeout)
        self.status_timeout = float(status_timeout)
        self.temperature = float(temperature)
        self._opener = opener or urlopen

    # ------------------------------------------------------------- public API
    def set_model(self, model: str) -> None:
        model = model.strip()
        if not model:
            raise ValueError("Model name cannot be empty.")
        self.model = model

    def status(self, model: str | None = None) -> OllamaStatus:
        """Check Ollama without ever raising.  Safe to call from any command."""

        checked_model = (model or self.model).strip()
        started = time.perf_counter()
        try:
            payload = self._get_json("/api/tags", timeout=self.status_timeout)
            raw_models = payload.get("models", [])
            if not isinstance(raw_models, list):
                raise OllamaProtocolError(
                    "Ollama returned an unexpected model list."
                )
            models: list[str] = []
            for entry in raw_models:
                if isinstance(entry, dict):
                    name = entry.get("name") or entry.get("model")
                    if isinstance(name, str) and name:
                        models.append(name)
            models.sort()
            version: str | None = None
            try:
                version_payload = self._get_json(
                    "/api/version", timeout=self.status_timeout
                )
                raw_version = version_payload.get("version")
                version = raw_version if isinstance(raw_version, str) else None
            except OllamaError:
                version = None
            return OllamaStatus(
                reachable=True,
                base_url=redact_url(self.base_url),
                version=version,
                models=models,
                model_available=model_is_installed(checked_model, models),
                checked_model=checked_model,
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        except OllamaError as exc:
            return OllamaStatus(
                reachable=False,
                base_url=redact_url(self.base_url),
                checked_model=checked_model,
                error=str(exc),
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        except Exception as exc:  # defensive: status must never crash the app
            return OllamaStatus(
                reachable=False,
                base_url=redact_url(self.base_url),
                checked_model=checked_model,
                error=f"Unexpected status failure: {exc}",
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
            )

    def list_models(self) -> list[str]:
        payload = self._get_json("/api/tags", timeout=self.status_timeout)
        raw_models = payload.get("models", [])
        if not isinstance(raw_models, list):
            raise OllamaProtocolError("Ollama returned an unexpected model list.")
        models = []
        for entry in raw_models:
            if isinstance(entry, dict):
                name = entry.get("name") or entry.get("model")
                if isinstance(name, str) and name:
                    models.append(name)
        return sorted(models)

    def ensure_model(self, model: str | None = None) -> None:
        """Raise a helpful error if the model is not installed."""

        checked = (model or self.model).strip()
        models = self.list_models()
        if not model_is_installed(checked, models):
            raise OllamaModelNotFound(self._missing_model_message(checked))

    def stream_chat(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        model: str | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Iterator[str]:
        """Yield assistant text chunks from ``POST /api/chat``.

        The generator closes its HTTP response even when the caller interrupts
        iteration, which is what makes Ctrl+C during a response safe.
        """

        self._validate_messages(messages)
        selected_model = (model or self.model).strip()
        payload = {
            "model": selected_model,
            "messages": [dict(message) for message in messages],
            "stream": True,
            "options": dict(options or {"temperature": self.temperature}),
        }
        request = Request(
            urljoin(self.base_url + "/", "api/chat"),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/x-ndjson",
                "User-Agent": "PHANTOM.exe/1.0",
            },
            method="POST",
        )

        try:
            response = self._opener(request, timeout=self.timeout)
        except HTTPError as exc:
            raise self._http_error(exc, selected_model) from exc
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise OllamaUnavailable(self._connection_message(exc)) from exc

        produced_content = False
        saw_done = False
        try:
            for raw_line in response:
                if isinstance(raw_line, bytes):
                    line = raw_line.decode("utf-8", errors="replace").strip()
                else:
                    line = str(raw_line).strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("error"):
                    raise OllamaError(self._model_error_message(str(event["error"]), selected_model))
                message = event.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content:
                        produced_content = True
                        yield content
                if event.get("done") is True:
                    saw_done = True
                    break
            if not produced_content and not saw_done:
                raise OllamaProtocolError(
                    "The signal arrived empty. Ollama returned no readable text."
                )
        except (TimeoutError, socket.timeout) as exc:
            raise OllamaUnavailable(
                "The signal stalled. Ollama accepted the request but stopped "
                "speaking. Check `ollama ps` and try a smaller model."
            ) from exc
        except (URLError, OSError, HTTPException) as exc:
            if produced_content:
                raise OllamaProtocolError(
                    "The connection collapsed mid-sentence. The partial answer "
                    "was discarded."
                ) from exc
            raise OllamaUnavailable(self._connection_message(exc)) from exc
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    # --------------------------------------------------------------- internals
    @staticmethod
    def _validate_messages(messages: Sequence[Mapping[str, str]]) -> None:
        if not messages:
            raise ValueError("At least one message is required.")
        for message in messages:
            if not isinstance(message, Mapping):
                raise ValueError("Each message must be a mapping.")
            role = message.get("role")
            content = message.get("content")
            if role not in {"system", "user", "assistant"}:
                raise ValueError(f"Unsupported message role: {role!r}.")
            if not isinstance(content, str):
                raise ValueError("Message content must be a string.")

    def _get_json(self, path: str, *, timeout: float) -> dict[str, Any]:
        request = Request(
            urljoin(self.base_url + "/", path.lstrip("/")),
            headers={
                "Accept": "application/json",
                "User-Agent": "PHANTOM.exe/1.0",
            },
            method="GET",
        )
        try:
            response = self._opener(request, timeout=timeout)
        except HTTPError as exc:
            raise self._http_error(exc, self.model) from exc
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise OllamaUnavailable(self._connection_message(exc)) from exc
        try:
            raw = response.read(2_000_000)
        except (TimeoutError, socket.timeout) as exc:
            raise OllamaUnavailable(
                "Ollama did not answer in time. Is the model loading?"
            ) from exc
        except OSError as exc:
            raise OllamaUnavailable(self._connection_message(exc)) from exc
        except HTTPException as exc:
            raise OllamaProtocolError(
                "Ollama closed the connection before sending a complete reply."
            ) from exc
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise OllamaProtocolError(
                "Ollama returned something that is not JSON. Is the URL pointing "
                "at an Ollama server?"
            ) from exc
        if not isinstance(payload, dict):
            raise OllamaProtocolError("Ollama returned an unexpected payload.")
        if payload.get("error"):
            raise OllamaError(str(payload["error"]))
        return payload

    def _http_error(self, exc: HTTPError, model: str) -> OllamaError:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        detail = ""
        try:
            payload = json.loads(body)
            if isinstance(payload, dict):
                detail = str(payload.get("error") or "")
        except json.JSONDecodeError:
            detail = body.strip()
        if exc.code == 404 or "not found" in detail.lower():
            return OllamaModelNotFound(self._missing_model_message(model))
        if exc.code in {401, 403}:
            return OllamaError(
                "Ollama refused the request. If you put a reverse proxy in "
                "front of it, check the credentials; PHANTOM never needs an "
                "API key for a local Ollama server."
            )
        message = detail[:300] or exc.reason or "unknown error"
        return OllamaError(f"Ollama rejected the request (HTTP {exc.code}): {message}")

    def _model_error_message(self, detail: str, model: str) -> str:
        if "not found" in detail.lower() or "does not exist" in detail.lower():
            return self._missing_model_message(model)
        return f"Ollama error: {detail[:300]}"

    def _missing_model_message(self, model: str) -> str:
        return (
            f"Model '{model}' is not installed in Ollama.\n\n"
            f"  ollama pull {model}\n\n"
            "Or choose one of the installed models with /model list."
        )

    def _connection_message(self, exc: BaseException) -> str:
        endpoint = redact_url(self.base_url)
        text = str(exc).lower()
        if isinstance(exc, (TimeoutError, socket.timeout)) or "timed out" in text:
            return (
                f"The void did not answer in time at {endpoint}.\n\n"
                "Ollama may still be loading the model. Wait a moment, or try "
                "a smaller model with /model."
            )
        if "refused" in text or "connection refused" in text:
            return (
                f"No signal at {endpoint}. Ollama is not answering.\n\n"
                "Start it in another terminal:\n"
                "  ollama serve\n\n"
                "Then verify the model:\n"
                "  ollama list\n\n"
                "PHANTOM still works offline: /help, /memory, /status and /scan "
                "do not need Ollama."
            )
        if "name or service not known" in text or "nodename nor servname" in text:
            return (
                f"The address {endpoint} cannot be resolved.\n\n"
                "Check OLLAMA_BASE_URL in your environment or .env file."
            )
        return (
            f"Could not reach Ollama at {endpoint}.\n\n"
            f"{exc}\n\n"
            "Is `ollama serve` running? Try `ollama list` in another terminal."
        )


__all__ = [
    "OllamaClient",
    "OllamaStatus",
    "OllamaError",
    "OllamaUnavailable",
    "OllamaModelNotFound",
    "OllamaProtocolError",
    "model_is_installed",
    "normalise_model",
]
