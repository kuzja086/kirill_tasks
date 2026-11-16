"""Тесты разбора голосовой фразы о штрафе."""

from __future__ import annotations

import pytest

from alice_skill.penalties import MAX_COMMENT_LENGTH, parse_penalty_phrase


@pytest.mark.parametrize(
    ("phrase", "points", "comment"),
    [
        ("добавь штраф 10 баллов — не выключил свет", 10, "не выключил свет"),
        ("штраф десять баллов за беспорядок", 10, "беспорядок"),
        ("поставь штраф двадцать пять баллов за грубость", 25, "грубость"),
        ("запиши штраф 50 баллов за обман", 50, "обман"),
        ("штраф пять баллов не убрал посуду", 5, "не убрал посуду"),
        ("штраф сто баллов за разбитую чашку", 100, "разбитую чашку"),
    ],
)
def test_parse_penalty_phrase(phrase: str, points: int, comment: str) -> None:
    parsed = parse_penalty_phrase(phrase)

    assert parsed is not None
    assert parsed.points == points
    assert parsed.comment == comment


def test_parse_penalty_phrase_requires_points() -> None:
    assert parse_penalty_phrase("какая сегодня погода") is None
    assert parse_penalty_phrase("") is None


def test_parse_penalty_phrase_ignores_zero() -> None:
    assert parse_penalty_phrase("штраф ноль баллов") is None


def test_parse_penalty_phrase_without_reason() -> None:
    parsed = parse_penalty_phrase("добавь штраф 15 баллов")

    assert parsed is not None
    assert parsed.points == 15
    assert parsed.comment == ""


def test_parse_penalty_phrase_prefers_digits() -> None:
    parsed = parse_penalty_phrase("штраф 7 баллов за шум")

    assert parsed is not None
    assert parsed.points == 7
    assert parsed.comment == "шум"


def test_parse_penalty_phrase_truncates_long_comment() -> None:
    phrase = "штраф 10 баллов за " + "очень " * 60

    parsed = parse_penalty_phrase(phrase)

    assert parsed is not None
    assert len(parsed.comment) == MAX_COMMENT_LENGTH
