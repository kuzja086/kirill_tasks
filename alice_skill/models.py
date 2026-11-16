"""Модели навыка: протокол Яндекс.Диалогов и предметные сущности."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from alice_skill.config import PROTOCOL_VERSION

# Виды задач: ежедневные (повторяются каждый день) и случайные (выборка на день).
KIND_DAILY = "daily"
KIND_RANDOM = "random"

# Статусы задачи в дневном плане.
STATUS_PENDING = "pending"
STATUS_AWAITING_CONFIRMATION = "awaiting_confirmation"
STATUS_DONE = "done"
STATUS_MISSED = "missed"

# Результаты попытки потратить баллы на награду.
REDEEM_OK = "ok"
REDEEM_INSUFFICIENT = "insufficient"
REDEEM_NOT_FOUND = "not_found"

# Статусы заявки на штраф: баллы списываются только при подтверждении.
PENALTY_AWAITING = "awaiting_confirmation"
PENALTY_APPLIED = "applied"
PENALTY_REJECTED = "rejected"

# Источник заявки на штраф.
SOURCE_ALICE = "alice"
SOURCE_ADMIN = "admin"

# Результаты создания заявки на штраф.
PENALTY_CREATED = "created"
PENALTY_LIMIT_EXCEEDED = "limit_exceeded"
PENALTY_INVALID = "invalid"


@dataclass(frozen=True)
class Task:
    """Задача из справочника."""

    id: int
    title: str
    kind: str
    points: int


@dataclass(frozen=True)
class Assignment:
    """Задача, назначенная ребёнку на конкретный день."""

    id: int
    title: str
    points: int
    status: str = STATUS_PENDING


@dataclass(frozen=True)
class Reward:
    """Награда из списка призов."""

    id: int
    title: str
    cost: int


@dataclass(frozen=True)
class RedeemOutcome:
    """Результат попытки потратить баллы на награду."""

    status: str
    balance: int
    missing: int = 0
    redemption_id: int | None = None
    reward: Reward | None = None


@dataclass(frozen=True)
class Penalty:
    """Заявка на штраф."""

    id: int
    user_id: str
    points: int
    comment: str
    source: str
    status: str
    created_at: dt.datetime | None = None


@dataclass(frozen=True)
class PenaltyResult:
    """Результат создания заявки на штраф."""

    status: str
    penalty: Penalty | None = None
    daily_count: int = 0
    max_points: int = 0


@dataclass(frozen=True)
class LedgerEntry:
    """Запись журнала баллов для истории в админке."""

    id: int
    delta: int
    reason: str
    comment: str | None = None
    details: str | None = None
    created_at: dt.datetime | None = None


@dataclass(frozen=True)
class PendingAssignment:
    """Заявка на выполнение, ждущая подтверждения взрослым."""

    id: int
    user_id: str
    plan_date: dt.date
    title: str
    points: int


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
            intent=next(iter(intents), None) or _intent_from_payload(request),
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


def _intent_from_payload(request: dict[str, Any]) -> str | None:
    """Интент из payload кнопки.

    Alice присылает ``request.type = ButtonPressed`` и payload, который навык
    положил в кнопку (``{"intent": "list_tasks"}``), — NLU при этом может быть
    пустым.
    """
    payload = request.get("payload")
    if not isinstance(payload, dict):
        return None

    intent = payload.get("intent")
    if isinstance(intent, str) and intent.strip():
        return intent.strip()
    return None


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
