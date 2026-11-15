"""Экономика навыка: сколько баллов приносит день и сколько стоит награда.

Логика: ребёнок должен получать ощутимую награду примерно раз в две недели.
Поэтому стоимость «главной» награды считается от плановых баллов дня:

    стоимость ≈ баллы_за_день × доля_выполнения × дни

При плановых 87 баллах в день и выполнении 80% за 14 дней набегает
87 × 0.8 × 14 ≈ 974 балла — это и есть цена награды «за две недели».
"""

from __future__ import annotations

from typing import Sequence

# Через сколько дней ребёнок должен зарабатывать награду.
REWARD_INTERVAL_DAYS = 14
# Реалистичная доля выполненных задач: ребёнок пропускает часть.
EXPECTED_COMPLETION_RATE = 0.8
# Сколько случайных задач выдаётся в день.
RANDOM_TASKS_PER_DAY = 2
# Округление стоимости награды, баллы.
COST_ROUNDING = 10


def recommended_reward_cost(
    planned_daily_points: int,
    *,
    days: int = REWARD_INTERVAL_DAYS,
    completion_rate: float = EXPECTED_COMPLETION_RATE,
    rounding: int = COST_ROUNDING,
) -> int:
    """Стоимость награды, которую ребёнок копит ``days`` дней.

    :param planned_daily_points: сумма баллов всех задач дня (ежедневные +
        ожидаемые случайные).
    :param days: горизонт накопления, дни.
    :param completion_rate: ожидаемая доля выполненных задач (0, 1].
    :param rounding: до какого значения округлять стоимость.
    """
    if planned_daily_points <= 0:
        raise ValueError("planned_daily_points должен быть положительным")
    if days <= 0:
        raise ValueError("days должен быть положительным")
    if not 0 < completion_rate <= 1:
        raise ValueError("completion_rate должен быть в диапазоне (0, 1]")
    if rounding <= 0:
        raise ValueError("rounding должен быть положительным")

    raw = planned_daily_points * completion_rate * days
    return int(round(raw / rounding) * rounding)


def expected_daily_points(
    daily_points: int,
    random_pool_points: Sequence[int],
    *,
    random_count: int = RANDOM_TASKS_PER_DAY,
) -> float:
    """Ожидаемые баллы за день: все ежедневные плюс случайная выборка из пула."""
    if random_count <= 0 or not random_pool_points:
        return float(daily_points)

    average = sum(random_pool_points) / len(random_pool_points)
    picks = min(random_count, len(random_pool_points))
    return daily_points + average * picks
