"""Тесты формирования дневного плана."""

from __future__ import annotations

from alice_skill.plan import build_daily_plan, select_random_tasks
from factories import make_task

DAILY = [make_task(1, "Зарядка"), make_task(2, "Читать")]
POOL = [make_task(index, f"Случайная {index}", kind="random") for index in range(3, 13)]


def test_selection_is_reproducible_for_same_seed() -> None:
    first = select_random_tasks(POOL, 3, seed="user-1:2026-11-15")
    second = select_random_tasks(list(reversed(POOL)), 3, seed="user-1:2026-11-15")

    assert [task.id for task in first] == [task.id for task in second]


def test_selection_changes_between_days() -> None:
    first = select_random_tasks(POOL, 3, seed="user-1:2026-11-15")
    second = select_random_tasks(POOL, 3, seed="user-1:2026-11-16")

    assert [task.id for task in first] != [task.id for task in second]


def test_selection_changes_between_children() -> None:
    first = select_random_tasks(POOL, 3, seed="user-1:2026-11-15")
    second = select_random_tasks(POOL, 3, seed="user-2:2026-11-15")

    assert [task.id for task in first] != [task.id for task in second]


def test_selection_returns_requested_count() -> None:
    assert len(select_random_tasks(POOL, 2, seed="seed")) == 2


def test_selection_returns_whole_pool_if_pool_is_small() -> None:
    pool = POOL[:2]

    selected = select_random_tasks(pool, 5, seed="seed")

    assert {task.id for task in selected} == {task.id for task in pool}


def test_selection_returns_nothing_for_zero_count() -> None:
    assert select_random_tasks(POOL, 0, seed="seed") == ()


def test_daily_plan_starts_with_daily_tasks() -> None:
    scheduled = build_daily_plan(DAILY, POOL, seed="user-1:2026-11-15", random_count=2)

    assert [task.id for task in scheduled[: len(DAILY)]] == [task.id for task in DAILY]
    assert len(scheduled) == len(DAILY) + 2
    assert all(task.kind == "random" for task in scheduled[len(DAILY) :])
