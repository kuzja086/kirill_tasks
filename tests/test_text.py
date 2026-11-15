"""Тесты русских формулировок: склонение баллов, строки задач и наград."""

from __future__ import annotations

import pytest

from alice_skill.models import STATUS_AWAITING_CONFIRMATION, STATUS_DONE
from alice_skill.text import format_points, format_reward_line, format_task_line, points_word
from factories import make_assignment, make_reward


@pytest.mark.parametrize(
    ("points", "expected"),
    [
        (1, "балл"),
        (2, "балла"),
        (4, "балла"),
        (5, "баллов"),
        (11, "баллов"),
        (14, "баллов"),
        (21, "балл"),
        (102, "балла"),
        (0, "баллов"),
    ],
)
def test_points_word(points: int, expected: str) -> None:
    assert points_word(points) == expected


def test_format_points() -> None:
    assert format_points(42) == "42 балла"
    assert format_points(1) == "1 балл"


def test_format_task_line_with_index_and_status() -> None:
    assignment = make_assignment(1, "Зарядка", points=10, status=STATUS_DONE)

    assert format_task_line(assignment, 1) == "1) Зарядка — 10 баллов, засчитано"
    assert format_task_line(assignment) == "Зарядка — 10 баллов, засчитано"


def test_format_task_line_shows_waiting_status() -> None:
    assignment = make_assignment(1, "Зарядка", points=10, status=STATUS_AWAITING_CONFIRMATION)

    assert "ждёт подтверждения" in format_task_line(assignment)


def test_format_reward_line_when_affordable() -> None:
    reward = make_reward(1, "Мороженое", cost=350)

    assert format_reward_line(reward, 400, 1) == "1) Мороженое — 350 баллов, можно брать"


def test_format_reward_line_when_not_affordable() -> None:
    reward = make_reward(2, "Настольная игра", cost=970)

    assert format_reward_line(reward, 420) == "Настольная игра — 970 баллов, накопить ещё 550 баллов"
