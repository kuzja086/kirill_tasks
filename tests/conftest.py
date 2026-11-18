"""Общие фикстуры тестов: репозиторий и генератор событий Алисы."""

from __future__ import annotations

from typing import Any, Callable

import pytest

from factories import FakeSkillRepository, make_assignment, make_reward


@pytest.fixture
def repository() -> FakeSkillRepository:
    return FakeSkillRepository(
        assignments=[
            make_assignment(1, "Зарядка", points=2),
            make_assignment(2, "Прочитать 20 минут", points=2),
        ],
        rewards=[
            make_reward(1, "Мороженое", cost=25),
            make_reward(2, "Настольная игра", cost=70),
        ],
        balance=30,
    )



@pytest.fixture
def alice_event() -> Callable[..., dict[str, Any]]:
    """Фабрика событий Cloud Functions в формате Яндекс.Диалогов."""

    def build(
        command: str = "",
        *,
        tokens: list[str] | None = None,
        intent: str | None = None,
        payload: dict[str, Any] | None = None,
        is_new_session: bool = False,
        user_id: str = "user-1",
    ) -> dict[str, Any]:
        nlu: dict[str, Any] = {
            "tokens": command.split() if tokens is None else tokens,
            "entities": [],
        }
        if intent is not None:
            nlu["intents"] = {intent: {"slots": {}}}

        return {
            "meta": {
                "locale": "ru-RU",
                "timezone": "Asia/Yekaterinburg",
                "client_id": "ru.yandex.searchplugin/7.16",
            },
            "session": {
                "message_id": 0,
                "session_id": "session-1",
                "skill_id": "skill-1",
                "user": {"user_id": user_id},
                "application": {"application_id": "app-1"},
                "new": is_new_session,
            },
            "request": {
                "type": "SimpleUtterance",
                "command": command,
                "original_utterance": command,
                "nlu": nlu,
                "markup": {"dangerous_context": False},
                "payload": payload or {},
            },
            "version": "1.0",
        }

    return build
