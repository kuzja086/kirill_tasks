"""Общие фикстуры тестов: подмена Postgres и генератор событий Алисы."""

from __future__ import annotations

from typing import Any, Callable

import pytest


class FakeUserRepository:
    """In-memory реализация ``alice_skill.db.UserRepository``."""

    def __init__(self) -> None:
        self.users: dict[str, str] = {}
        self.saved: list[tuple[str, str]] = []

    def get_user_name(self, user_id: str) -> str | None:
        return self.users.get(user_id)

    def save_user_name(self, user_id: str, display_name: str) -> None:
        self.users[user_id] = display_name
        self.saved.append((user_id, display_name))


@pytest.fixture
def repository() -> FakeUserRepository:
    return FakeUserRepository()


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
                "timezone": "Europe/Moscow",
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
