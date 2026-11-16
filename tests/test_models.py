"""Тесты разбора запроса и сборки ответа протокола Яндекс.Диалогов."""

from __future__ import annotations

import pytest

from alice_skill.models import (
    AliceRequest,
    AliceResponse,
    make_button,
    validate_reward_input,
    validate_task_input,
)


def test_from_event_reads_all_fields(alice_event) -> None:
    event = alice_event(
        "запомни меня аня",
        intent="remember_name",
        payload={"name": "Аня"},
        is_new_session=True,
        user_id="user-42",
    )

    request = AliceRequest.from_event(event)

    assert request.command == "запомни меня аня"
    assert request.original_utterance == "запомни меня аня"
    assert request.intent == "remember_name"
    assert request.tokens == ("запомни", "меня", "аня")
    assert request.payload == {"name": "Аня"}
    assert request.session_id == "session-1"
    assert request.user_id == "user-42"
    assert request.is_new_session is True
    assert request.version == "1.0"


def test_from_event_tolerates_empty_event() -> None:
    request = AliceRequest.from_event({})

    assert request.command == ""
    assert request.intent is None
    assert request.tokens == ()
    assert request.payload == {}
    assert request.user_id == ""
    assert request.access_token is None
    assert request.version == "1.0"
    assert request.is_empty is True


def test_from_event_keeps_protocol_version(alice_event) -> None:
    event = alice_event("привет")
    event["version"] = "2.0"

    assert AliceRequest.from_event(event).version == "2.0"


def test_from_event_reads_intent_from_button_payload(alice_event) -> None:
    event = alice_event("", payload={"intent": "list_tasks"})
    event["request"]["type"] = "ButtonPressed"

    request = AliceRequest.from_event(event)

    assert request.intent == "list_tasks"


def test_nlu_intent_has_priority_over_payload(alice_event) -> None:
    event = alice_event(
        "какие награды",
        intent="list_rewards",
        payload={"intent": "list_tasks"},
    )

    assert AliceRequest.from_event(event).intent == "list_rewards"


def test_from_event_ignores_non_string_payload_intent(alice_event) -> None:
    event = alice_event("привет", payload={"intent": 42})

    assert AliceRequest.from_event(event).intent is None


def test_response_serializes_optional_fields() -> None:
    response = AliceResponse(text="Привет", tts="Привет!", buttons=[make_button("Ещё")])

    payload = response.to_dict()

    assert payload == {
        "version": "1.0",
        "response": {
            "text": "Привет",
            "tts": "Привет!",
            "end_session": False,
            "buttons": [{"title": "Ещё", "hide": True}],
        },
    }


def test_response_omits_empty_tts_and_buttons() -> None:
    payload = AliceResponse(text="Привет").to_dict(version="2.0")

    assert payload == {
        "version": "2.0",
        "response": {"text": "Привет", "end_session": False},
    }


def test_make_button_keeps_payload() -> None:
    button = make_button("Запомни меня", payload={"intent": "remember_name"}, hide=False)

    assert button == {
        "title": "Запомни меня",
        "hide": False,
        "payload": {"intent": "remember_name"},
    }


def test_validate_task_input_normalizes_title_and_points() -> None:
    assert validate_task_input("  Помыть   посуду ", "daily", "10") == (
        "Помыть посуду",
        "daily",
        10,
    )


@pytest.mark.parametrize(
    ("title", "kind", "points"),
    [
        ("", "daily", 10),
        ("   ", "daily", 10),
        ("З" * 61, "daily", 10),
        ("Задача", "weekly", 10),
        ("Задача", "daily", 0),
        ("Задача", "daily", 101),
        ("Задача", "daily", "abc"),
        ("Задача", "daily", "2.5"),
        ("Задача", "daily", 2.5),
    ],
)
def test_validate_task_input_rejects_bad_values(title: str, kind: str, points: object) -> None:
    with pytest.raises(ValueError):
        validate_task_input(title, kind, points)


def test_validate_reward_input_normalizes_title() -> None:
    assert validate_reward_input("  Мороженое ", "350") == ("Мороженое", 350)


@pytest.mark.parametrize(
    ("title", "cost"),
    [
        ("", 350),
        ("Мороженое", 0),
        ("Мороженое", -5),
        ("Мороженое", 10.5),
        ("Мороженое", "много"),
    ],
)
def test_validate_reward_input_rejects_bad_values(title: str, cost: object) -> None:
    with pytest.raises(ValueError):
        validate_reward_input(title, cost)
