"""Разбор голосовой фразы о штрафе: сумма в баллах и причина.

Примеры, которые должны разбираться:

* «добавь штраф 10 баллов — не выключил свет» → 10, «не выключил свет»
* «штраф десять баллов за беспорядок» → 10, «беспорядок»
* «поставь штраф двадцать пять баллов за грубость» → 25, «за грубость» → «грубость»
"""

from __future__ import annotations

from dataclasses import dataclass

from alice_skill.matching import normalize

MAX_COMMENT_LENGTH = 200

NUMBER_WORDS = {
    "ноль": 0,
    "один": 1,
    "одна": 1,
    "два": 2,
    "две": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
    "десять": 10,
    "одиннадцать": 11,
    "двенадцать": 12,
    "тринадцать": 13,
    "четырнадцать": 14,
    "пятнадцать": 15,
    "шестнадцать": 16,
    "семнадцать": 17,
    "восемнадцать": 18,
    "девятнадцать": 19,
    "двадцать": 20,
    "тридцать": 30,
    "сорок": 40,
    "пятьдесят": 50,
    "шестьдесят": 60,
    "семьдесят": 70,
    "восемьдесят": 80,
    "девяносто": 90,
    "сто": 100,
}

TENS = {20, 30, 40, 50, 60, 70, 80, 90}

# Служебные слова: не попадают в причину штрафа.
STOP_WORDS = frozenset(
    {
        "добавь",
        "добавить",
        "поставь",
        "поставить",
        "запиши",
        "записать",
        "объяви",
        "штраф",
        "штрафа",
        "штрафов",
        "балл",
        "балла",
        "баллов",
        "очко",
        "очка",
        "очков",
        "за",
        "мне",
        "меня",
        "я",
        "получил",
        "получила",
        "заслужил",
        "заслужила",
        "на",
        "пожалуйста",
        "это",
    }
)


@dataclass(frozen=True)
class ParsedPenalty:
    """Сумма штрафа и причина, вытащенные из фразы."""

    points: int
    comment: str


def parse_penalty_phrase(text: str) -> ParsedPenalty | None:
    """Возвращает сумму и причину штрафа или ``None``, если сумму не нашли."""
    words = normalize(text).split()
    if not words:
        return None

    points, number_indexes = _extract_points(words)
    if points is None:
        return None

    comment_words = [
        word
        for index, word in enumerate(words)
        if index not in number_indexes
        and word not in STOP_WORDS
        and word not in NUMBER_WORDS
    ]
    comment = " ".join(comment_words).strip()[:MAX_COMMENT_LENGTH]
    return ParsedPenalty(points=points, comment=comment)


def _extract_points(words: list[str]) -> tuple[int | None, set[int]]:
    """Ищет сумму: сначала цифры, потом числительные (включая «двадцать пять»)."""
    for index, word in enumerate(words):
        if word.isdigit():
            value = int(word)
            return (value if value > 0 else None), {index}

    for index, word in enumerate(words):
        value = NUMBER_WORDS.get(word)
        if value is None or value == 0:
            continue

        used = {index}
        if value in TENS and index + 1 < len(words):
            unit = NUMBER_WORDS.get(words[index + 1], 0)
            if 1 <= unit <= 9:
                value += unit
                used.add(index + 1)
        return value, used

    return None, set()
