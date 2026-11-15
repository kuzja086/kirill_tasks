"""Формирование дневного плана: ежедневные задачи + случайная выборка.

Выбор случайных задач детерминирован парой (ребёнок, дата): в течение дня
ребёнок и родитель видят один и тот же набор, а на следующий день он меняется.
"""

from __future__ import annotations

import hashlib
from typing import Sequence

from alice_skill.economy import RANDOM_TASKS_PER_DAY
from alice_skill.models import Task


def selection_key(seed: str, task_id: int) -> str:
    """Псевдослучайный, но воспроизводимый ключ сортировки задачи."""
    return hashlib.sha256(f"{seed}:{task_id}".encode("utf-8")).hexdigest()


def select_random_tasks(
    pool: Sequence[Task],
    count: int,
    *,
    seed: str,
) -> tuple[Task, ...]:
    """Выбирает ``count`` задач из пула так, чтобы выбор зависел только от seed."""
    if count <= 0 or not pool:
        return ()

    ordered = sorted(pool, key=lambda task: (selection_key(seed, task.id), task.id))
    return tuple(ordered[:count])


def build_daily_plan(
    daily_tasks: Sequence[Task],
    random_pool: Sequence[Task],
    *,
    seed: str,
    random_count: int = RANDOM_TASKS_PER_DAY,
) -> tuple[Task, ...]:
    """План дня: все ежедневные задачи плюс случайная выборка из пула."""
    return tuple(daily_tasks) + select_random_tasks(random_pool, random_count, seed=seed)
