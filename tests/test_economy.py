"""Тесты экономики: стоимость награды, баллы дня и подсказки в админке."""

from __future__ import annotations

import pytest

from alice_skill.economy import (
    RANDOM_TASKS_PER_DAY,
    daily_share_percent,
    days_to_earn,
    expected_daily_points,
    planned_daily_points,
    realistic_daily_points,
    recommended_reward_cost,
)
from factories import make_task

# Баллы из sql/002_seed.sql: ежедневные задачи и пул случайных.
SEED_DAILY_POINTS = 10
SEED_RANDOM_POINTS = [2, 1, 2, 1, 2, 1]


def test_reward_cost_matches_one_week_of_points() -> None:
    planned = expected_daily_points(SEED_DAILY_POINTS, SEED_RANDOM_POINTS)

    assert planned == 13
    assert recommended_reward_cost(planned) == 70, "главный приз — примерно за неделю"


def test_reward_cost_is_whole_and_rounded_to_ten() -> None:
    assert recommended_reward_cost(50) == 280
    assert recommended_reward_cost(51) == 290
    assert isinstance(recommended_reward_cost(13), int)


def test_reward_cost_scales_with_days() -> None:
    assert recommended_reward_cost(50, days=14) == 560


def test_expected_daily_points_without_random_pool() -> None:
    assert expected_daily_points(10, []) == 10
    assert expected_daily_points(10, [2, 1], random_count=0) == 10


def test_expected_daily_points_rounds_up_and_limits_picks_to_pool_size() -> None:
    # В пуле 2 задачи: больше двух взять нельзя, ожидание = 2 × 15.
    assert expected_daily_points(0, [10, 20], random_count=5) == 30
    # 2 из [1, 2, 2]: 5 × 2 / 3 = 3,33 → 4, чтобы план не занижался.
    assert expected_daily_points(10, [1, 2, 2], random_count=2) == 14


def test_planned_daily_points_uses_active_tasks_only() -> None:
    tasks = [
        make_task(1, "Зарядка", points=2),
        make_task(2, "Заправить кровать", points=1),
        make_task(3, "Погулять", kind="random", points=2),
        make_task(4, "Нарисовать", kind="random", points=1),
        make_task(5, "Полить цветы", kind="optional", points=5),
        make_task(6, "Выключенная", points=9, is_active=False),
    ]

    assert planned_daily_points(tasks) == 6, "3 балла ежедневных + 3 ожидаемых случайных"
    assert planned_daily_points(tasks, random_count=1) == 5


def test_planned_daily_points_respects_weekday_schedule() -> None:
    tasks = [
        make_task(1, "Каждый день", points=3),
        make_task(2, "Только вторник", points=5, weekdays=(2,)),
        make_task(3, "Случайная по средам", kind="random", points=2, weekdays=(3,)),
    ]

    assert planned_daily_points(tasks, random_count=1, weekday=1) == 3
    assert planned_daily_points(tasks, random_count=1, weekday=2) == 8
    assert planned_daily_points(tasks, random_count=1, weekday=3) == 5


@pytest.mark.parametrize("weekday", [0, 8])
def test_planned_daily_points_rejects_bad_weekday(weekday: int) -> None:
    with pytest.raises(ValueError):
        planned_daily_points([], weekday=weekday)


def test_realistic_daily_points_applies_completion_rate() -> None:
    assert realistic_daily_points(13) == 10
    assert realistic_daily_points(1) == 1, "минимум один балл в день"


def test_days_to_earn_rounds_up() -> None:
    assert days_to_earn(70, 13) == 7
    assert days_to_earn(25, 13) == 3
    assert days_to_earn(10, 13) == 1
    assert days_to_earn(1, 13) == 1


def test_daily_share_percent() -> None:
    assert daily_share_percent(2, 13) == 15
    assert daily_share_percent(13, 13) == 100
    assert daily_share_percent(0, 13) == 0


def test_default_random_tasks_per_day() -> None:
    assert RANDOM_TASKS_PER_DAY == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"planned_daily_points": 0},
        {"planned_daily_points": -5},
        {"planned_daily_points": 10, "days": 0},
        {"planned_daily_points": 10, "completion_percent": 0},
        {"planned_daily_points": 10, "completion_percent": 101},
        {"planned_daily_points": 10, "rounding": 0},
    ],
)
def test_reward_cost_rejects_invalid_input(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        recommended_reward_cost(**kwargs)


@pytest.mark.parametrize(
    ("cost", "planned"),
    [(0, 13), (-5, 13), (10, 0), (10, -1)],
)
def test_days_to_earn_rejects_invalid_input(cost: int, planned: int) -> None:
    with pytest.raises(ValueError):
        days_to_earn(cost, planned)


@pytest.mark.parametrize(
    ("points", "planned"),
    [(-1, 13), (2, 0)],
)
def test_daily_share_percent_rejects_invalid_input(points: int, planned: int) -> None:
    with pytest.raises(ValueError):
        daily_share_percent(points, planned)

