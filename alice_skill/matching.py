"""Сопоставление произнесённой фразы с названием задачи или награды.

NLU-модели у навыка нет, поэтому используется мягкое сравнение: нормализация,
отсечение частотных слов и грубый стемминг («зарядку» → «зарядк»).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

# Порог: какая доля слов названия должна найтись в фразе.
MATCH_THRESHOLD = 0.5

# Служебные слова и глаголы-команды: в названиях задач их обычно нет.
STOP_WORDS = frozenset(
    {
        "я", "мы", "мне", "меня", "могу", "можно", "уже", "это", "эту", "эта",
        "еще", "все", "всё", "есть", "покажи", "скажи", "какие", "какой", "какую",
        "выполнил", "выполнила", "сделал", "сделала", "сделать", "сделаю",
        "отметь", "отметила", "отметить", "готово", "задачу", "задача", "задачи",
        "хочу", "хотел", "хотела", "награду", "награда", "награды", "приз",
        "купить", "получить", "пожалуйста",
    }
)

_ENDINGS = "аяуюоеыиьй"
_ILLEGAL_CHARS = re.compile(r"[^0-9a-zа-я\s]+")
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class Match:
    """Найденное совпадение: индекс в списке кандидатов и его оценка."""

    index: int
    score: float


def normalize(text: str) -> str:
    """Приводит фразу к нижнему регистру без пунктуации и лишних пробелов."""
    lowered = text.lower().replace("ё", "е")
    return _SPACES.sub(" ", _ILLEGAL_CHARS.sub(" ", lowered)).strip()


def stem(token: str) -> str:
    """Грубо отрезает окончание, чтобы «зубы» и «зуб» считались одним словом."""
    word = token
    while len(word) > 3 and word[-1] in _ENDINGS:
        word = word[:-1]
    return word


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(
        stem(part) for part in normalize(text).split() if part not in STOP_WORDS
    )


def _tokens_match(left: str, right: str) -> bool:
    """Совпадение слов или общий префикс не короче 4 букв (для разных форм глаголов)."""
    if left == right:
        return True
    common = 0
    for left_char, right_char in zip(left, right):
        if left_char != right_char:
            break
        common += 1
    return common >= 4


def score(title: str, phrase_tokens: Sequence[str]) -> float:
    """Доля слов названия, найденных во фразе (от 0 до 1)."""
    title_tokens = _tokens(title)
    if not title_tokens or not phrase_tokens:
        return 0.0

    matched = sum(
        1
        for title_token in title_tokens
        if any(_tokens_match(title_token, phrase_token) for phrase_token in phrase_tokens)
    )
    return matched / len(title_tokens)


def find_match(
    candidates: Sequence[str],
    phrase: str,
    *,
    threshold: float = MATCH_THRESHOLD,
) -> Match | None:
    """Ищет лучшее совпадение фразы среди названий.

    Возвращает ``None``, если ни одно название не набрало порог.
    """
    phrase_tokens = _tokens(phrase)
    if not phrase_tokens:
        return None

    best: Match | None = None
    for index, title in enumerate(candidates):
        value = score(title, phrase_tokens)
        if value >= threshold and (best is None or value > best.score):
            best = Match(index=index, score=value)
    return best
