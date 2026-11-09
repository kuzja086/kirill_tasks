"""Модели протокола навыков Яндекс.Диалогов (v1.0)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from alice_skill.config import PROTOCOL_VERSION


@dataclass(frozen=True)
class AliceRequest:
    """Запрос от Алисы, приведённый к плоской структуре."""

    command: str
    original_utterance: str
    intent: str | None
    tokens: tuple[str, ...]
    payload: dict[str, Any]
    session_id: str
    message_id: int
    user_id: str
    is_new_session: bool
    access_token: str | None
    version: str = PROTOCOL_VERSION

    @classmethod
    def from_event(cls, event: dict[str, Any]) -> "AliceRequest":
        """Создаёт запрос из ``event`` Cloud Functions.

        Разбор терпим к отсутствующим полям: часть данных Алиса присылает
        только при наличии у навыка соответствующих доступов, а при открытии
        навыка без реплики ``request`` может быть почти пустым.
        """
        session = event.get("session") or {}
        request = event.get("request") or {}
        user = session.get("user") or {}
        nlu = request.get("nlu") or {}
        intents = nlu.get("intents") or {}

        return cls(
            command=str(request.get("command") or "").strip(),
            original_utterance=str(request.get("original_utterance") or ""),
            intent=next(iter(intents), None),
            tokens=tuple(str(token) for token in nlu.get("tokens") or ()),
            payload=dict(request.get("payload") or {}),
            session_id=str(session.get("session_id") or ""),
            message_id=int(session.get("message_id") or 0),
            user_id=str(user.get("user_id") or ""),
            is_new_session=bool(session.get("new")),
            access_token=user.get("access_token"),
            version=str(event.get("version") or PROTOCOL_VERSION),
        )

    @property
    def is_empty(self) -> bool:
        """Признак «пустого» запроса: пользователь открыл навык и молчит."""
        return not self.command and not self.original_utterance


@dataclass
class AliceResponse:
    """Ответ навыка. Поля ``tts`` и ``buttons`` необязательны."""

    text: str
    tts: str | None = None
    end_session: bool = False
    buttons: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self, version: str = PROTOCOL_VERSION) -> dict[str, Any]:
        """Сериализует ответ в формат, ожидаемый Яндекс.Диалогами."""
        response: dict[str, Any] = {
            "text": self.text,
            "end_session": self.end_session,
        }
        if self.tts:
            response["tts"] = self.tts
        if self.buttons:
            response["buttons"] = self.buttons
        return {"version": version, "response": response}


def make_button(
    title: str,
    *,
    payload: dict[str, Any] | None = None,
    hide: bool = True,
) -> dict[str, Any]:
    """Кнопка под ответом навыка (показывается в приложении с экраном)."""
    button: dict[str, Any] = {"title": title, "hide": hide}
    if payload:
        button["payload"] = payload
    return button
