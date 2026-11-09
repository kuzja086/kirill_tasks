"""Тесты точки входа Cloud Functions."""

from __future__ import annotations

from types import SimpleNamespace

import handler as cloud_function
from handler import ERROR_TEXT


def test_handler_returns_protocol_payload(alice_event, repository, monkeypatch) -> None:
    monkeypatch.setattr(cloud_function, "_repository", repository)
    event = alice_event("запомни меня аня", tokens=["запомни", "меня", "аня"], intent="remember_name")

    payload = cloud_function.handler(event, SimpleNamespace(request_id="req-1"))

    assert payload["version"] == "1.0"
    assert payload["response"]["end_session"] is False
    assert "Аня" in payload["response"]["text"]
    assert repository.saved == [("user-1", "Аня")]


def test_handler_greets_on_new_session(alice_event, repository, monkeypatch) -> None:
    monkeypatch.setattr(cloud_function, "_repository", repository)

    payload = cloud_function.handler(alice_event("", is_new_session=True), None)

    assert payload["response"]["text"].startswith("Привет")


def test_handler_returns_valid_response_on_backend_error(alice_event, monkeypatch) -> None:
    class BrokenRepository:
        def get_user_name(self, user_id: str) -> str | None:
            raise RuntimeError("Postgres недоступен")

        def save_user_name(self, user_id: str, display_name: str) -> None:
            raise RuntimeError("Postgres недоступен")

    monkeypatch.setattr(cloud_function, "_repository", BrokenRepository())

    payload = cloud_function.handler(alice_event("как меня зовут", intent="ask_name"), None)

    assert payload == {
        "version": "1.0",
        "response": {"text": ERROR_TEXT, "end_session": False},
    }


def test_handler_echoes_request_version(alice_event, repository, monkeypatch) -> None:
    monkeypatch.setattr(cloud_function, "_repository", repository)
    event = alice_event("привет")
    event["version"] = "2.0"

    payload = cloud_function.handler(event, None)

    assert payload["version"] == "2.0"


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
