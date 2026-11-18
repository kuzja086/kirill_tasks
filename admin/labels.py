"""Русские подписи для админки: причины операций и статусы заявок."""

from __future__ import annotations

REASON_LABELS = {
    "task_done": "Задача выполнена",
    "task_missed": "Задача пропущена",
    "reward_redeem": "Награда получена",
    "reward_refund": "Возврат за награду",
    "manual": "Ручная операция",
    "penalty": "Штраф",
}

PENALTY_STATUS_LABELS = {
    "awaiting_confirmation": "ждёт подтверждения",
    "applied": "применён",
    "rejected": "отклонён",
}

REDEMPTION_STATUS_LABELS = {
    "requested": "ждёт выдачи",
    "issued": "выдано",
    "cancelled": "отменено",
}

SOURCE_LABELS = {
    "alice": "Алиса",
    "admin": "админка",
    "auto": "пропуск",
}

KIND_LABELS = {
    "daily": "ежедневная",
    "random": "случайная",
    "optional": "дополнительная",
}

# 1 = понедельник ... 7 = воскресенье (ISO).
WEEKDAY_LABELS = {
    1: "Пн",
    2: "Вт",
    3: "Ср",
    4: "Чт",
    5: "Пт",
    6: "Сб",
    7: "Вс",
}


def reason_label(reason: str) -> str:
    return REASON_LABELS.get(reason, reason)


def penalty_status_label(status: str) -> str:
    return PENALTY_STATUS_LABELS.get(status, status)


def redemption_status_label(status: str) -> str:
    return REDEMPTION_STATUS_LABELS.get(status, status)


def source_label(source: str) -> str:
    return SOURCE_LABELS.get(source, source)


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind)


def weekdays_label(values: object) -> str:
    """«каждый день» или «Пн, Ср» для набора дней недели."""
    days = list(values or ())
    if not days:
        return "каждый день"
    return ", ".join(WEEKDAY_LABELS.get(int(day), str(day)) for day in days)
