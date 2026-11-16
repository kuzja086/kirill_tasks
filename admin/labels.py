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

SOURCE_LABELS = {
    "alice": "Алиса",
    "admin": "админка",
}


def reason_label(reason: str) -> str:
    return REASON_LABELS.get(reason, reason)


def penalty_status_label(status: str) -> str:
    return PENALTY_STATUS_LABELS.get(status, status)


def source_label(source: str) -> str:
    return SOURCE_LABELS.get(source, source)
