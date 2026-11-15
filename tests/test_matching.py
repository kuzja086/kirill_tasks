"""Тесты сопоставления фразы с названием задачи или награды."""

from __future__ import annotations

import pytest

from alice_skill.matching import find_match, normalize, score, stem


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Почистить зубы, утром!", "почистить зубы утром"),
        ("  Мороженое   и   кино  ", "мороженое и кино"),
        ("Час мультиков — перец", "час мультиков перец"),
    ],
)
def test_normalize(text: str, expected: str) -> None:
    assert normalize(text) == expected


def test_normalize_replaces_yo() -> None:
    assert normalize("Помочь с готовкой, ещё") == "помочь с готовкой еще"


@pytest.mark.parametrize(
    ("word", "expected"),
    [("зарядку", "зарядк"), ("зубы", "зуб"), ("пять", "пят"), ("час", "час")],
)
def test_stem(word: str, expected: str) -> None:
    assert stem(word) == expected


def test_score_counts_whole_title_coverage() -> None:
    assert score("Зарядка", ("зарядк",)) == 1.0
    assert score("Почистить зубы утром", ("почистил", "зуб")) == pytest.approx(2 / 3)
    assert score("Зарядка", ("посуда",)) == 0.0


def test_find_match_recognizes_task_done_phrase() -> None:
    match = find_match(["Зарядка", "Прочитать 20 минут"], "я выполнил зарядку")

    assert match is not None
    assert match.index == 0


def test_find_match_ignores_task_number_words() -> None:
    match = find_match(["Зарядка", "Прочитать 20 минут"], "отметь задачу прочитать 20 минут")

    assert match is not None
    assert match.index == 1


def test_find_match_handles_verb_forms() -> None:
    match = find_match(["Почистить зубы утром", "Помыть посуду"], "почистил зубы утром")

    assert match is not None
    assert match.index == 0


def test_find_match_returns_none_for_unrelated_phrase() -> None:
    assert find_match(["Зарядка"], "какая сегодня погода") is None


def test_find_match_returns_none_for_empty_candidates() -> None:
    assert find_match([], "зарядка") is None


def test_find_match_returns_none_for_empty_phrase() -> None:
    assert find_match(["Зарядка"], "") is None


def test_find_match_prefers_higher_score() -> None:
    match = find_match(["Час мультиков", "Мороженое"], "хочу мороженое")

    assert match is not None
    assert match.index == 1
