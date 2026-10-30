from __future__ import annotations

import json
from http.client import IncompleteRead
from io import BytesIO

import pytest
from urllib.error import HTTPError, URLError

from src.ollama_client import (
    OllamaClient,
    OllamaError,
    OllamaModelNotFound,
    OllamaProtocolError,
    OllamaUnavailable,
    model_is_installed,
    normalise_model,
)


class FakeResponse:
    def __init__(self, payload: bytes = b"", lines=None):
        self.payload = payload
        self.lines = lines or []
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        return self.payload

    def __iter__(self):
        return iter(self.lines)

    def close(self) -> None:
        self.closed = True


def tags_opener(request, timeout=None):
    if request.full_url.endswith("/api/tags"):
        return FakeResponse(
            payload=json.dumps(
                {"models": [{"name": "test:latest"}, {"name": "other:latest"}]}
            ).encode()
        )
    if request.full_url.endswith("/api/version"):
        return FakeResponse(payload=json.dumps({"version": "0.9.1"}).encode())
    raise AssertionError(request.full_url)


def test_model_normalisation_and_installed_check():
    assert normalise_model("llama") == "llama:latest"
    assert normalise_model("llama:3b") == "llama:3b"
    assert model_is_installed("llama", ["llama:latest"])
    assert not model_is_installed("llama", ["other:latest"])


def test_status_reports_online_models_and_version():
    client = OllamaClient(opener=tags_opener)

    status = client.status("test:latest")

    assert status.reachable is True
    assert status.version == "0.9.1"
    assert status.models == ["other:latest", "test:latest"]
    assert status.model_available is True
    assert status.checked_model == "test:latest"
    assert status.latency_ms is not None
    assert "online" in status.summary


def test_status_reports_missing_model():
    client = OllamaClient(opener=tags_opener)

    status = client.status("missing:latest")

    assert status.reachable is True
    assert status.model_available is False
    assert "model missing" in status.summary


def test_status_never_raises_when_offline():
    def opener(request, timeout=None):
        raise URLError("Connection refused")

    client = OllamaClient(opener=opener)

    status = client.status()

    assert status.reachable is False
    assert status.error
    assert status.summary == "offline"


def test_status_handles_http_errors():
    def opener(request, timeout=None):
        raise HTTPError(
            request.full_url,
            500,
            "Server Error",
            None,
            BytesIO(b'{"error":"boom"}'),
        )

    client = OllamaClient(opener=opener)

    status = client.status()

    assert status.reachable is False
    assert "boom" in (status.error or "")


def test_list_models_and_ensure_model():
    client = OllamaClient(opener=tags_opener)

    assert client.list_models() == ["other:latest", "test:latest"]
    client.ensure_model("test:latest")

    with pytest.raises(OllamaModelNotFound):
        client.ensure_model("missing:latest")


def test_stream_chat_yields_chunks_and_closes_response():
    response = FakeResponse(
        lines=[
            b'{"message":{"content":"Hel"}}\n',
            b'{"message":{"content":"lo"},"done":true}\n',
        ]
    )
    client = OllamaClient(opener=lambda request, timeout=None: response)

    chunks = list(
        client.stream_chat([{"role": "user", "content": "hi"}], model="test:latest")
    )

    assert chunks == ["Hel", "lo"]
    assert response.closed is True


def test_stream_chat_accepts_data_prefix():
    response = FakeResponse(
        lines=[
            b'data: {"message":{"content":"signal"},"done":true}\n',
        ]
    )
    client = OllamaClient(opener=lambda request, timeout=None: response)

    assert list(
        client.stream_chat([{"role": "user", "content": "hi"}])
    ) == ["signal"]


def test_stream_chat_surfaces_model_errors():
    response = FakeResponse(lines=[b'{"error":"model not found"}\n'])
    client = OllamaClient(opener=lambda request, timeout=None: response)

    with pytest.raises(OllamaError) as excinfo:
        list(client.stream_chat([{"role": "user", "content": "hi"}]))

    assert "not installed" in str(excinfo.value)


def test_stream_chat_rejects_empty_stream():
    response = FakeResponse(lines=[])
    client = OllamaClient(opener=lambda request, timeout=None: response)

    with pytest.raises(OllamaProtocolError):
        list(client.stream_chat([{"role": "user", "content": "hi"}]))


def test_stream_chat_reports_connection_failure():
    def opener(request, timeout=None):
        raise URLError("Connection refused")

    client = OllamaClient(opener=opener)

    with pytest.raises(OllamaUnavailable):
        list(client.stream_chat([{"role": "user", "content": "hi"}]))


def test_stream_chat_discards_partial_answer_on_midstream_failure():
    class BrokenResponse(FakeResponse):
        def __iter__(self):
            yield b'{"message":{"content":"partial"}}\n'
            raise OSError("connection reset")

    client = OllamaClient(opener=lambda request, timeout=None: BrokenResponse())

    with pytest.raises(OllamaProtocolError) as excinfo:
        list(client.stream_chat([{"role": "user", "content": "hi"}]))

    assert "partial" in str(excinfo.value).lower()


def test_incomplete_json_reply_is_reported_as_protocol_error():
    class IncompleteResponse(FakeResponse):
        def read(self, size: int = -1) -> bytes:
            raise IncompleteRead(b'{"models": [')

    client = OllamaClient(opener=lambda request, timeout=None: IncompleteResponse())

    with pytest.raises(OllamaProtocolError):
        client.list_models()


def test_message_validation():
    client = OllamaClient()

    with pytest.raises(ValueError):
        list(client.stream_chat([]))
    with pytest.raises(ValueError):
        list(client.stream_chat([{"role": "system", "content": 1}]))
    with pytest.raises(ValueError):
        list(client.stream_chat([{"role": "tool", "content": "x"}]))
