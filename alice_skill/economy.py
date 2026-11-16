"""Экономика навыка: сколько баллов приносит день и сколько стоит награда.

Ребёнок учится считать, поэтому все числа целые и мелкие: задача стоит 1–2
балла, план дня — около 13, награда — примерно за неделю.

    стоимость ≈ баллы_за_день × доля_выполнения × дни

13 × 0,8 × 7 ≈ 72, после округления — 70 баллов: это цена «награды за неделю».
Дроби наружу не выходят, все функции возвращают ``int``.
"""

from __future__ import annotations

from typing import Sequence

from alice_skill.models import KIND_DAILY, KIND_RANDOM, Task

# Через сколько дней ребёнок должен зарабатывать награду.
REWARD_INTERVAL_DAYS = 7
# Реалистичная доля выполненных задач, проценты: ребёнок пропускает часть.
COMPLETION_PERCENT = 80
# Сколько случайных задач выдаётся в день.
RANDOM_TASKS_PER_DAY = 2
# Округление стоимости награды, баллы.
COST_ROUNDING = 10


def recommended_reward_cost(
    planned_daily_points: int,
    *,
    days: int = REWARD_INTERVAL_DAYS,
    completion_percent: int = COMPLETION_PERCENT,
    rounding: int = COST_ROUNDING,
) -> int:
    """Стоимость награды, которую ребёнок копит ``days`` дней.

    Считает в целых числах: ``13 * 7 * 80 // 100 = 72``, округление до 70.

    :param planned_daily_points: сумма баллов всех задач дня (ежедневные +
        ожидаемые случайные).
    :param days: горизонт накопления, дни.
    :param completion_percent: ожидаемая доля выполненных задач, 1..100.
    :param rounding: до какого значения округлять стоимость.
    """
    if planned_daily_points <= 0:
        raise ValueError("planned_daily_points должен быть положительным")
    if days <= 0:
        raise ValueError("days должен быть положительным")
    if not 1 <= completion_percent <= 100:
        raise ValueError("completion_percent должен быть в диапазоне 1..100")
    if rounding <= 0:
        raise ValueError("rounding должен быть положительным")

    earned = planned_daily_points * days * completion_percent // 100
    return (earned + rounding // 2) // rounding * rounding


def expected_daily_points(
    daily_points: int,
    random_pool_points: Sequence[int],
    *,
    random_count: int = RANDOM_TASKS_PER_DAY,
) -> int:
    """Ожидаемые баллы за день: ежедневные плюс случайная выборка из пула.

    Среднее по пулу округляется вверх, чтобы план не занижался:
    две задачи из пула ``[2, 1, 2, 1, 2, 1]`` дают 3 балла.
    """
    if random_count <= 0 or not random_pool_points:
        return daily_points

    total = sum(random_pool_points)
    picks = min(random_count, len(random_pool_points))
    return daily_points + -(-total * picks // len(random_pool_points))


def planned_daily_points(
    tasks: Sequence[Task],
    *,
    random_count: int = RANDOM_TASKS_PER_DAY,
) -> int:
    """Плановые баллы дня по справочнику: ежедневные задачи плюс ожидание случайных."""
    daily = sum(task.points for task in tasks if task.kind == KIND_DAILY and task.is_active)
    pool = [task.points for task in tasks if task.kind == KIND_RANDOM and task.is_active]
    return expected_daily_points(daily, pool, random_count=random_count)


def realistic_daily_points(
    planned_daily_points: int,
    *,
    completion_percent: int = COMPLETION_PERCENT,
) -> int:
    """Сколько баллов ребёнок реально получает за день: план с поправкой на пропуски."""
    if planned_daily_points <= 0:
        raise ValueError("planned_daily_points должен быть положительным")
    if not 1 <= completion_percent <= 100:
        raise ValueError("completion_percent должен быть в диапазоне 1..100")

    return max(1, planned_daily_points * completion_percent // 100)


def days_to_earn(
    cost: int,
    planned_daily_points: int,
    *,
    completion_percent: int = COMPLETION_PERCENT,
) -> int:
    """Сколько дней копить награду: округление вверх, минимум один день.

    Считает по реальному дню, а не по плановому: ``13 × 80 // 100 = 10``
    баллов в день, значит награда за 70 — это неделя.
    """
    if cost <= 0:
        raise ValueError("cost должен быть положительным")

    earned_per_day = realistic_daily_points(
        planned_daily_points,
        completion_percent=completion_percent,
    )
    return max(1, -(-cost // earned_per_day))


def daily_share_percent(points: int, planned_daily_points: int) -> int:
    """Какую долю планового дня занимает задача, в процентах."""
    if points < 0:
        raise ValueError("points не может быть отрицательным")
    if planned_daily_points <= 0:
        raise ValueError("planned_daily_points должен быть положительным")

    return (points * 100 + planned_daily_points // 2) // planned_daily_points

