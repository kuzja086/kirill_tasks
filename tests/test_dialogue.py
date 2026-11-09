"""Тесты сценариев диалога (без реального Postgres)."""

from __future__ import annotations

from alice_skill.dialogue import (
    FALLBACK_TEXT,
    NAME_REQUEST_TEXT,
    NAME_UNKNOWN_TEXT,
    WELCOME_TEXT,
    respond,
)
from alice_skill.models import AliceRequest


def test_new_session_without_command_greets(alice_event, repository) -> None:
    response = respond(AliceRequest.from_event(alice_event("", is_new_session=True)), repository)

    assert response.text == WELCOME_TEXT
    assert response.end_session is False


def test_unknown_request_falls_back(alice_event, repository) -> None:
    response = respond(AliceRequest.from_event(alice_event("какая погода")), repository)

    assert response.text == FALLBACK_TEXT


def test_remember_name_without_name_asks_for_it(alice_event, repository) -> None:
    request = AliceRequest.from_event(alice_event("запомни меня", intent="remember_name"))

    response = respond(request, repository)

    assert response.text == NAME_REQUEST_TEXT
    assert response.buttons == [
        {"title": "Запомни меня", "hide": True, "payload": {"intent": "remember_name"}}
    ]
    assert repository.saved == []


def test_remember_name_takes_last_token(alice_event, repository) -> None:
    request = AliceRequest.from_event(
        alice_event("запомни меня аня", tokens=["запомни", "меня", "аня"], intent="remember_name")
    )

    response = respond(request, repository)

    assert repository.saved == [("user-1", "Аня")]
    assert "Аня" in response.text


def test_remember_name_prefers_payload(alice_event, repository) -> None:
    request = AliceRequest.from_event(
        alice_event(
            "запомни",
            tokens=["запомни"],
            intent="remember_name",
            payload={"name": "наталья"},
        )
    )

    respond(request, repository)

    assert repository.users["user-1"] == "Наталья"


def test_ask_name_for_new_user(alice_event, repository) -> None:
    request = AliceRequest.from_event(alice_event("как меня зовут", intent="ask_name"))

    response = respond(request, repository)

    assert response.text == NAME_UNKNOWN_TEXT
    assert response.buttons[0]["title"] == "Запомни меня"


def test_ask_name_for_known_user(alice_event, repository) -> None:
    repository.save_user_name("user-1", "Аня")
    request = AliceRequest.from_event(alice_event("как меня зовут", intent="ask_name"))

    response = respond(request, repository)

    assert response.text == "Вас зовут Аня."
    assert response.buttons == []
