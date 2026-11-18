"""Формирование дневного плана: ежедневные задачи + случайная выборка.

Выбор случайных задач детерминирован парой (ребёнок, дата): в течение дня
ребёнок и родитель видят один и тот же набор, а на следующий день он меняется.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Sequence

from alice_skill.economy import RANDOM_TASKS_PER_DAY
from alice_skill.models import KIND_DAILY, KIND_RANDOM, Task


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
    plan_date: dt.date | None = None,
) -> tuple[Task, ...]:
    """План дня: ежедневные задачи плюс случайная выборка из пула.

    Дополнительные задачи (``kind = 'optional'``) в план не попадают: ребёнок
    берёт их сам, и за пропуск баллы не списываются. Задачи с расписанием
    (``weekdays``) участвуют только в свои дни недели. Фильтры стоят здесь,
    а не только в SQL, чтобы правила нельзя было обойти вызовом из кода.
    """
    daily = tuple(task for task in daily_tasks if task.kind == KIND_DAILY)
    pool = tuple(task for task in random_pool if task.kind == KIND_RANDOM)

    if plan_date is not None:
        daily = tuple(task for task in daily if task.scheduled_on(plan_date))
        pool = tuple(task for task in pool if task.scheduled_on(plan_date))

    return daily + select_random_tasks(pool, random_count, seed=seed)
