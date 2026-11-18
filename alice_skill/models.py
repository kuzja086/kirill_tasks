"""Модели навыка: протокол Яндекс.Диалогов и предметные сущности."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Iterable

from alice_skill.config import PROTOCOL_VERSION

# Виды задач: ежедневные (повторяются каждый день), случайные (выборка на день)
# и дополнительные (ребёнок берёт их сам, за пропуск баллы не списываются).
KIND_DAILY = "daily"
KIND_RANDOM = "random"
KIND_OPTIONAL = "optional"

TASK_KINDS = (KIND_DAILY, KIND_RANDOM, KIND_OPTIONAL)

# Ограничения справочника — общие для навыка и админки.
# Баллы целые и мелкие: ребёнок должен складывать их в уме.
TITLE_MAX_LENGTH = 60
TASK_MIN_POINTS = 1
TASK_MAX_POINTS = 10
REWARD_MIN_COST = 1
REWARD_MAX_COST = 100000

# Дни недели в ISO-нумерации: 1 — понедельник, 7 — воскресенье.
# Пустой набор означает «каждый день».
WEEKDAYS = (1, 2, 3, 4, 5, 6, 7)

# Статусы задачи в дневном плане.
STATUS_PENDING = "pending"
STATUS_AWAITING_CONFIRMATION = "awaiting_confirmation"
STATUS_DONE = "done"
STATUS_MISSED = "missed"

# Результат claim_optional_task: заявка на дополнительную задачу создана сейчас.
CLAIM_CREATED = "created"

# Результаты попытки потратить баллы на награду.
REDEEM_OK = "ok"
REDEEM_INSUFFICIENT = "insufficient"
REDEEM_NOT_FOUND = "not_found"

# Статусы заявки на штраф: баллы списываются только при подтверждении.
PENALTY_AWAITING = "awaiting_confirmation"
PENALTY_APPLIED = "applied"
PENALTY_REJECTED = "rejected"

# Источник заявки на штраф: голос ребёнка, админка или автозаявка
# за пропущенную задачу (списание всё равно ждёт подтверждения).
SOURCE_ALICE = "alice"
SOURCE_ADMIN = "admin"
SOURCE_AUTO = "auto"

# Результаты создания заявки на штраф.
PENALTY_CREATED = "created"
PENALTY_LIMIT_EXCEEDED = "limit_exceeded"
PENALTY_INVALID = "invalid"


def clean_title(value: str) -> str:
    """Схлопывает пробелы и проверяет длину названия задачи или награды."""
    cleaned = " ".join(str(value or "").split())
    if not cleaned:
        raise ValueError("Название не может быть пустым")
    if len(cleaned) > TITLE_MAX_LENGTH:
        raise ValueError(f"Название длиннее {TITLE_MAX_LENGTH} символов")
    return cleaned


def _as_whole_number(value: Any, *, minimum: int, maximum: int, label: str) -> int:
    """Приводит значение из формы к целому числу и проверяет диапазон."""
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{label}: нужно целое число")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label}: нужно целое число") from error
    if not minimum <= number <= maximum:
        raise ValueError(f"{label}: допустимо от {minimum} до {maximum}")
    return number


def _as_weekdays(value: Any) -> tuple[int, ...]:
    """Нормализует дни недели: ``None``/пусто — каждый день, иначе 1..7."""
    if value is None:
        return ()

    if isinstance(value, str):
        items: list[Any] = [item for item in value.replace(" ", "").split(",") if item]
    elif isinstance(value, int):
        items = [value]
    else:
        items = list(value)

    days = {
        _as_whole_number(item, minimum=1, maximum=7, label="День недели")
        for item in items
        if item != ""
    }
    return tuple(sorted(days))


def validate_task_input(
    title: str,
    kind: str,
    points: Any,
    weekdays: Iterable[Any] | None = None,
) -> tuple[str, str, int, tuple[int, ...]]:
    """Проверяет данные задачи из админки.

    :param weekdays: дни недели (1 = Пн ... 7 = Вс); пусто — каждый день.
    :raises ValueError: если название пустое или длинное, вид неизвестен,
        баллы не целое число из допустимого диапазона или день недели
        не входит в 1..7.
    """
    cleaned_title = clean_title(title)
    if kind not in TASK_KINDS:
        raise ValueError("Неизвестный вид задачи")
    cleaned_points = _as_whole_number(
        points,
        minimum=TASK_MIN_POINTS,
        maximum=TASK_MAX_POINTS,
        label="Баллы",
    )
    return cleaned_title, kind, cleaned_points, _as_weekdays(weekdays)


def validate_reward_input(title: str, cost: Any) -> tuple[str, int]:
    """Проверяет данные награды из админки.

    :raises ValueError: если название пустое или длинное, стоимость не целое
        число из допустимого диапазона.
    """
    cleaned_title = clean_title(title)
    cleaned_cost = _as_whole_number(
        cost,
        minimum=REWARD_MIN_COST,
        maximum=REWARD_MAX_COST,
        label="Стоимость",
    )
    return cleaned_title, cleaned_cost


@dataclass(frozen=True)
class Task:
    """Задача из справочника.

    ``weekdays`` — дни недели, когда задача попадает в план (1 = Пн ... 7 = Вс).
    Пустой набор означает «каждый день».
    """

    id: int
    title: str
    kind: str
    points: int
    is_active: bool = True
    weekdays: tuple[int, ...] = ()

    def scheduled_on_weekday(self, weekday: int) -> bool:
        """Попадает ли задача в план на этот день недели (1 = Пн ... 7 = Вс)."""
        return not self.weekdays or weekday in self.weekdays

    def scheduled_on(self, day: dt.date) -> bool:
        """Попадает ли задача в план на этот день."""
        return self.scheduled_on_weekday(day.isoweekday())


@dataclass(frozen=True)
class Assignment:
    """Задача, назначенная ребёнку на конкретный день."""

    id: int
    title: str
    points: int
    status: str = STATUS_PENDING
    kind: str = KIND_DAILY


@dataclass(frozen=True)
class Reward:
    """Награда из списка призов."""

    id: int
    title: str
    cost: int
    is_active: bool = True


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
    """Заявка на штраф.

    ``points`` — сколько запрошено, ``charged_points`` — сколько реально
    списано: баланс не может уйти в минус, поэтому при нехватке баллов
    списывается только остаток (``None`` — заявка ещё не применена).
    """

    id: int
    user_id: str
    points: int
    comment: str
    source: str
    status: str
    created_at: dt.datetime | None = None
    charged_points: int | None = None


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
    kind: str = KIND_DAILY


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
