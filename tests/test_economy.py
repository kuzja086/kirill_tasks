"""Тесты экономики: стоимость награды и ожидаемые баллы дня."""

from __future__ import annotations

import pytest

from alice_skill.economy import (
    RANDOM_TASKS_PER_DAY,
    expected_daily_points,
    recommended_reward_cost,
)

# Баллы из sql/002_seed.sql: ежедневные задачи и пул случайных.
SEED_DAILY_POINTS = 60
SEED_RANDOM_POINTS = [15, 15, 15, 10, 15, 10]


def test_reward_cost_matches_two_weeks_of_points() -> None:
    daily = expected_daily_points(SEED_DAILY_POINTS, SEED_RANDOM_POINTS)
    planned = round(daily)

    assert planned == 87
    assert recommended_reward_cost(planned) == 970


def test_reward_cost_rounds_to_ten() -> None:
    assert recommended_reward_cost(50) == 560
    assert recommended_reward_cost(51) == 570


def test_reward_cost_scales_with_days() -> None:
    assert recommended_reward_cost(50, days=7) == 280


def test_expected_daily_points_without_random_pool() -> None:
    assert expected_daily_points(60, []) == 60.0


def test_expected_daily_points_limits_picks_to_pool_size() -> None:
    # В пуле 2 задачи: больше двух взять нельзя, ожидание = 2 × 15.
    assert expected_daily_points(0, [10, 20], random_count=5) == 30.0


def test_default_random_tasks_per_day() -> None:
    assert RANDOM_TASKS_PER_DAY == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"planned_daily_points": 0},
        {"planned_daily_points": -5},
        {"planned_daily_points": 10, "days": 0},
        {"planned_daily_points": 10, "completion_rate": 0},
        {"planned_daily_points": 10, "completion_rate": 1.5},
        {"planned_daily_points": 10, "rounding": 0},
    ],
)
def test_reward_cost_rejects_invalid_input(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        recommended_reward_cost(**kwargs)
