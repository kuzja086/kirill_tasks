"""Тесты точки входа Cloud Functions."""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from typing import Any

import handler as cloud_function
from handler import ERROR_TEXT


def _payload(response: dict[str, Any]) -> dict[str, Any]:
    """Тело ответа HTTP-интеграции в виде разобранного JSON."""
    return json.loads(response["body"])


def _http_event(alice_request: dict[str, Any], *, encode_body_as_base64: bool = False) -> dict[str, Any]:
    raw_body = json.dumps(alice_request, ensure_ascii=False)
    if encode_body_as_base64:
        raw_body = base64.b64encode(raw_body.encode("utf-8")).decode("ascii")
    return {
        "httpMethod": "POST",
        "headers": {"Content-Type": "application/json"},
        "body": raw_body,
        "isBase64Encoded": encode_body_as_base64,
    }


def test_handler_returns_http_integration_response(alice_event, repository, monkeypatch) -> None:
    monkeypatch.setattr(cloud_function, "_repository", repository)
    event = alice_event(
        "запомни меня аня",
        tokens=["запомни", "меня", "аня"],
        intent="remember_name",
    )

    response = cloud_function.handler(event, SimpleNamespace(request_id="req-1"))

    assert response["statusCode"] == 200
    assert response["isBase64Encoded"] is False
    assert response["headers"]["Content-Type"].startswith("application/json")
    payload = _payload(response)
    assert payload["version"] == "1.0"
    assert payload["response"]["end_session"] is False
    assert "Аня" in payload["response"]["text"]
    assert repository.saved == [("user-1", "Аня")]


def test_handler_reads_request_from_http_body(alice_event, repository, monkeypatch) -> None:
    monkeypatch.setattr(cloud_function, "_repository", repository)
    event = _http_event(alice_event("", is_new_session=True))

    response = cloud_function.handler(event, None)

    assert _payload(response)["response"]["text"].startswith("Привет")


def test_handler_reads_base64_encoded_body(alice_event, repository, monkeypatch) -> None:
    monkeypatch.setattr(cloud_function, "_repository", repository)
    event = _http_event(alice_event("как меня зовут", intent="ask_name"), encode_body_as_base64=True)

    response = cloud_function.handler(event, None)

    assert "не знакомы" in _payload(response)["response"]["text"]


def test_handler_returns_valid_response_on_backend_error(alice_event, monkeypatch) -> None:
    class BrokenRepository:
        def get_user_name(self, user_id: str) -> str | None:
            raise RuntimeError("Postgres недоступен")

        def save_user_name(self, user_id: str, display_name: str) -> None:
            raise RuntimeError("Postgres недоступен")

    monkeypatch.setattr(cloud_function, "_repository", BrokenRepository())

    response = cloud_function.handler(alice_event("как меня зовут", intent="ask_name"), None)

    assert response["statusCode"] == 200
    assert _payload(response) == {
        "version": "1.0",
        "response": {"text": ERROR_TEXT, "end_session": False},
    }


def test_handler_returns_error_text_on_invalid_json(repository, monkeypatch) -> None:
    monkeypatch.setattr(cloud_function, "_repository", repository)

    response = cloud_function.handler(_http_event({"session": {}}) | {"body": "не json"}, None)

    assert response["statusCode"] == 200
    assert _payload(response)["response"]["text"] == ERROR_TEXT


def test_handler_echoes_request_version(alice_event, repository, monkeypatch) -> None:
    monkeypatch.setattr(cloud_function, "_repository", repository)
    event = alice_event("привет")
    event["version"] = "2.0"

    response = cloud_function.handler(event, None)

    assert _payload(response)["version"] == "2.0"


def test_error_text_hides_details_by_default(monkeypatch) -> None:
    monkeypatch.delenv(cloud_function.DEBUG_ENV_VAR, raising=False)

    assert cloud_function._error_text(RuntimeError("boom")) == ERROR_TEXT


def test_error_text_shows_details_when_debug_enabled(monkeypatch) -> None:
    monkeypatch.setenv(cloud_function.DEBUG_ENV_VAR, "1")

    assert cloud_function._error_text(RuntimeError("boom")) == "RuntimeError: boom"


def test_repository_is_created_once(monkeypatch) -> None:
    created: list[object] = []

    class DummyRepository:
        def __init__(self, settings: object) -> None:
            created.append(settings)

    monkeypatch.setattr(cloud_function, "_repository", None)
    monkeypatch.setattr(cloud_function, "PostgresRepository", DummyRepository)
    monkeypatch.setattr(cloud_function, "load_settings", lambda: "settings")

    first = cloud_function._get_repository()
    second = cloud_function._get_repository()

    assert first is second
    assert created == ["settings"]
