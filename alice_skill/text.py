"""Русские формулировки ответов: склонение «баллов», строки задач и наград."""

from __future__ import annotations

from alice_skill.models import (
    STATUS_AWAITING_CONFIRMATION,
    STATUS_DONE,
    STATUS_MISSED,
    STATUS_PENDING,
    Assignment,
    Reward,
)

STATUS_LABELS = {
    STATUS_PENDING: "не отмечена",
    STATUS_AWAITING_CONFIRMATION: "ждёт подтверждения",
    STATUS_DONE: "засчитано",
    STATUS_MISSED: "пропущено",
}


def points_word(points: int) -> str:
    """Возвращает «балл», «балла» или «баллов» для числа."""
    last_two = abs(points) % 100
    if 11 <= last_two <= 14:
        return "баллов"
    last = last_two % 10
    if last == 1:
        return "балл"
    if 2 <= last <= 4:
        return "балла"
    return "баллов"


def format_points(points: int) -> str:
    """Например: «1 балл», «3 балла», «25 баллов»."""
    return f"{points} {points_word(points)}"


def format_task_line(assignment: Assignment, index: int | None = None) -> str:
    """Строка списка задач; ``index`` добавляет нумерацию для экрана."""
    prefix = f"{index}) " if index is not None else ""
    label = STATUS_LABELS.get(assignment.status, assignment.status)
    return f"{prefix}{assignment.title} — {format_points(assignment.points)}, {label}"


def format_reward_line(reward: Reward, balance: int, index: int | None = None) -> str:
    """Строка списка наград: стоимость и доступность для текущего баланса."""
    prefix = f"{index}) " if index is not None else ""
    if balance >= reward.cost:
        availability = "можно брать"
    else:
        availability = f"накопить ещё {format_points(reward.cost - balance)}"
    return f"{prefix}{reward.title} — {format_points(reward.cost)}, {availability}"
