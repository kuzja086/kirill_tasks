"""Тесты локальной песочницы: разбор .env, событие и вывод заявок."""

from __future__ import annotations

import datetime as dt

from alice_skill.dialogue import INTENT_MY_POINTS, detect_intent
from alice_skill.models import AliceRequest
from tools import local


def test_parse_env_file_ignores_comments_and_blank_lines() -> None:
    raw = "# комментарий\n\nPG_HOST=127.0.0.1\nPG_PASSWORD=a=b\n# ещё\n"

    assert local.parse_env_file(raw) == {"PG_HOST": "127.0.0.1", "PG_PASSWORD": "a=b"}


def test_build_event_sets_command_and_tokens() -> None:
    event = local.build_event("я выполнил зарядку", user_id="kid")

    assert event["request"]["command"] == "я выполнил зарядку"
    assert event["request"]["nlu"]["tokens"] == ["я", "выполнил", "зарядку"]
    assert event["request"]["payload"] == {}
    assert event["session"]["user"]["user_id"] == "kid"


def test_build_event_allows_keyword_intent_detection() -> None:
    request = AliceRequest.from_event(local.build_event("сколько у меня баллов", user_id="kid"))

    assert detect_intent(request) == INTENT_MY_POINTS


def test_print_pending_without_rows(capsys) -> None:
    local.print_pending([])

    assert "нет" in capsys.readouterr().out.lower()


def test_print_pending_lists_assignments(capsys) -> None:
    local.print_pending([(7, dt.date(2026, 11, 15), "Зарядка", 10)])

    output = capsys.readouterr().out
    assert "#7" in output
    assert "Зарядка" in output
    assert "10 баллов" in output
