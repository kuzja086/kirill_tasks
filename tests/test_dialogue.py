"""Тесты сценариев диалога (без реального Postgres)."""

from __future__ import annotations

import datetime as dt

import pytest

from alice_skill import dialogue
from alice_skill.dialogue import respond
from alice_skill.models import (
    STATUS_AWAITING_CONFIRMATION,
    STATUS_DONE,
    AliceRequest,
)
from factories import FakeSkillRepository, make_assignment, make_reward

TODAY = dt.date(2026, 11, 15)


def _request(
    alice_event,
    command: str = "",
    *,
    intent: str | None = None,
    is_new_session: bool = False,
    user_id: str = "user-1",
) -> AliceRequest:
    return AliceRequest.from_event(
        alice_event(command, intent=intent, is_new_session=is_new_session, user_id=user_id)
    )


def test_new_session_without_command_greets_without_database(alice_event, repository) -> None:
    response = respond(_request(alice_event, is_new_session=True), repository, TODAY)

    assert response.text.startswith("Привет")
    assert repository.plan_requests == []


def test_unknown_intent_returns_help(alice_event, repository) -> None:
    response = respond(_request(alice_event, "какая погода"), repository, TODAY)

    assert "Я умею" in response.text
    assert repository.plan_requests == []


def test_without_user_id_returns_error(alice_event, repository) -> None:
    request = _request(alice_event, "какие задачи", intent=dialogue.INTENT_LIST_TASKS, user_id="")

    response = respond(request, repository, TODAY)

    assert response.text == dialogue.NO_USER_TEXT


def test_list_tasks_shows_titles_points_and_balance(alice_event, repository) -> None:
    request = _request(alice_event, "какие задачи на сегодня", intent=dialogue.INTENT_LIST_TASKS)

    response = respond(request, repository, TODAY)

    assert "Зарядка — 10 баллов" in response.text
    assert "Прочитать 20 минут — 15 баллов" in response.text
    assert "25 баллов" in response.text
    assert "420 баллов" in response.text
    assert repository.plan_requests == [("user-1", TODAY)]


def test_list_tasks_without_plan_explains_what_to_do(alice_event) -> None:
    request = _request(alice_event, "какие задачи", intent=dialogue.INTENT_LIST_TASKS)

    response = respond(request, FakeSkillRepository(), TODAY)

    assert "задач нет" in response.text
def test_my_points_without_goal_suggests_choosing_reward(alice_event, repository) -> None:
    request = _request(alice_event, "сколько у меня баллов", intent=dialogue.INTENT_MY_POINTS)

    response = respond(request, repository, TODAY)

    assert "420 баллов" in response.text
    assert "Цель пока не выбрана" in response.text


def test_my_points_with_goal_shows_remaining(alice_event, repository) -> None:
    repository.goal = make_reward(2, "Настольная игра", cost=970)
    request = _request(alice_event, "сколько у меня баллов", intent=dialogue.INTENT_MY_POINTS)

    response = respond(request, repository, TODAY)

    assert "420 баллов" in response.text
    assert "550 баллов" in response.text


def test_my_points_when_goal_is_affordable(alice_event, repository) -> None:
    repository.goal = make_reward(1, "Мороженое", cost=350)
    request = _request(alice_event, "сколько у меня баллов", intent=dialogue.INTENT_MY_POINTS)

    response = respond(request, repository, TODAY)

    assert "уже хватает" in response.text


def test_my_goal_without_goal_points_to_cheapest_reward(alice_event) -> None:
    repository = FakeSkillRepository(
        rewards=[make_reward(1, "Наклейка", cost=200), make_reward(2, "Кино", cost=1100)],
        balance=50,
    )
    request = _request(alice_event, "какая у меня цель", intent=dialogue.INTENT_MY_GOAL)

    response = respond(request, repository, TODAY)

    assert "Наклейка" in response.text
    assert "150 баллов" in response.text


def test_my_goal_reports_remaining_points(alice_event, repository) -> None:
    repository.goal = make_reward(2, "Настольная игра", cost=970)
    request = _request(alice_event, "сколько осталось до цели", intent=dialogue.INTENT_MY_GOAL)

    response = respond(request, repository, TODAY)

    assert "Настольная игра" in response.text
    assert "970 баллов" in response.text
    assert "550 баллов" in response.text


def test_my_goal_when_points_are_enough(alice_event, repository) -> None:
    repository.goal = make_reward(1, "Мороженое", cost=350)
    request = _request(alice_event, "какая цель", intent=dialogue.INTENT_MY_GOAL)

    response = respond(request, repository, TODAY)

    assert "Баллов хватает" in response.text


def test_list_rewards_marks_availability(alice_event, repository) -> None:
    request = _request(alice_event, "какие награды", intent=dialogue.INTENT_LIST_REWARDS)

    response = respond(request, repository, TODAY)

    assert "Мороженое — 350 баллов, можно брать" in response.text
    assert "Настольная игра — 970 баллов, накопить ещё 550 баллов" in response.text
def test_task_done_moves_task_to_confirmation(alice_event, repository) -> None:
    request = _request(alice_event, "я выполнил зарядку", intent=dialogue.INTENT_TASK_DONE)

    response = respond(request, repository, TODAY)

    assert "ждёт подтверждения" in response.text
    assert "10 баллов" in response.text
    assert repository.claims == [1]
    assert repository.assignments[0].status == STATUS_AWAITING_CONFIRMATION


def test_task_done_with_unknown_task_lists_today_plan(alice_event, repository) -> None:
    request = _request(alice_event, "я выполнил уборку снега", intent=dialogue.INTENT_TASK_DONE)

    response = respond(request, repository, TODAY)

    assert "Не нашла такую задачу" in response.text
    assert "Зарядка" in response.text
    assert repository.claims == []


def test_task_done_for_already_counted_task(alice_event) -> None:
    repository = FakeSkillRepository(
        assignments=[make_assignment(1, "Зарядка", status=STATUS_DONE)]
    )
    request = _request(alice_event, "я сделал зарядку", intent=dialogue.INTENT_TASK_DONE)

    response = respond(request, repository, TODAY)

    assert "уже засчитана" in response.text


def test_want_reward_spends_points(alice_event, repository) -> None:
    request = _request(alice_event, "хочу мороженое", intent=dialogue.INTENT_WANT_REWARD)

    response = respond(request, repository, TODAY)

    assert "Готово" in response.text
    assert "70 баллов" in response.text
    assert repository.redemptions == [1]
    assert repository.balance == 70


def test_want_unaffordable_reward_sets_goal(alice_event, repository) -> None:
    request = _request(alice_event, "хочу настольную игру", intent=dialogue.INTENT_WANT_REWARD)

    response = respond(request, repository, TODAY)

    assert "Пока не хватает 550 баллов" in response.text
    assert repository.goal_requests == [2]
    assert repository.goal is not None
    assert repository.redemptions == []


def test_want_unknown_reward_lists_rewards(alice_event, repository) -> None:
    request = _request(alice_event, "хочу пони", intent=dialogue.INTENT_WANT_REWARD)

    response = respond(request, repository, TODAY)

    assert "Не нашла такую награду" in response.text
    assert "Мороженое" in response.text
    assert repository.redemptions == []


def test_today_in_skill_timezone_is_date() -> None:
    assert isinstance(dialogue.today_in_skill_timezone(), dt.date)


@pytest.mark.parametrize(
    ("phrase", "expected_intent"),
    [
        ("какие задачи на сегодня", dialogue.INTENT_LIST_TASKS),
        ("что мне делать", dialogue.INTENT_LIST_TASKS),
        ("какие награды", dialogue.INTENT_LIST_REWARDS),
        ("сколько у меня баллов", dialogue.INTENT_MY_POINTS),
        ("какая у меня цель", dialogue.INTENT_MY_GOAL),
        ("я выполнил зарядку", dialogue.INTENT_TASK_DONE),
        ("хочу мороженое", dialogue.INTENT_WANT_REWARD),
        ("какая погода", None),
        ("", None),
    ],
)
def test_detect_intent_falls_back_to_keywords(alice_event, phrase, expected_intent) -> None:
    request = _request(alice_event, phrase)

    assert dialogue.detect_intent(request) == expected_intent


def test_detect_intent_prefers_nlu_intent(alice_event) -> None:
    request = _request(alice_event, "какие задачи", intent=dialogue.INTENT_MY_POINTS)

    assert dialogue.detect_intent(request) == dialogue.INTENT_MY_POINTS


def test_button_payload_without_nlu_is_routed(alice_event, repository) -> None:
    """Кнопка из ответа навыка: nlu.intents пуст, интент приходит в payload."""
    event = alice_event("", payload={"intent": dialogue.INTENT_LIST_TASKS})
    event["request"]["type"] = "ButtonPressed"

    response = respond(AliceRequest.from_event(event), repository, TODAY)

    assert "Задачи на сегодня" in response.text
    assert repository.plan_requests == [("user-1", TODAY)]


def test_voice_phrase_without_nlu_is_routed(alice_event, repository) -> None:
    request = _request(alice_event, "сколько у меня баллов")

    response = respond(request, repository, TODAY)

    assert "420 баллов" in response.text


@pytest.mark.parametrize(
    ("intent", "expected_text"),
    [
        (dialogue.INTENT_LIST_TASKS, "Задачи на сегодня"),
        (dialogue.INTENT_LIST_REWARDS, "Награды"),
        (dialogue.INTENT_MY_POINTS, "У тебя"),
        (dialogue.INTENT_MY_GOAL, "Цель"),
    ],
)
def test_every_intent_creates_daily_plan(alice_event, repository, intent, expected_text) -> None:
    request = _request(alice_event, "запрос", intent=intent)

    response = respond(request, repository, TODAY)

    assert expected_text in response.text
    assert repository.plan_requests == [("user-1", TODAY)]


