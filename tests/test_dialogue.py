"""Тесты сценариев диалога (без реального Postgres)."""

from __future__ import annotations

import datetime as dt

import pytest

from alice_skill import dialogue
from alice_skill.dialogue import respond
from alice_skill.models import (
    PENALTY_AWAITING,
    STATUS_AWAITING_CONFIRMATION,
    STATUS_DONE,
    STATUS_MISSED,
    STATUS_PENDING,
    REDEMPTION_REQUESTED,
    AliceRequest,
)
from factories import FakeSkillRepository, make_assignment, make_reward, make_task

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

    assert "Зарядка — 2 балла" in response.text
    assert "Прочитать 20 минут — 2 балла" in response.text
    assert "4 балла" in response.text
    assert "30 баллов" in response.text
    assert repository.plan_requests == [("user-1", TODAY)]


def test_list_tasks_without_plan_explains_what_to_do(alice_event) -> None:
    request = _request(alice_event, "какие задачи", intent=dialogue.INTENT_LIST_TASKS)

    response = respond(request, FakeSkillRepository(), TODAY)

    assert "задач нет" in response.text


def test_voice_lists_only_unfinished_tasks_without_points_and_statuses(alice_event) -> None:
    repository = FakeSkillRepository(
        assignments=[
            make_assignment(1, "Зарядка", points=2, status=STATUS_DONE),
            make_assignment(2, "Прочитать 20 минут", points=2, status=STATUS_PENDING),
        ]
    )
    request = _request(alice_event, "какие задачи", intent=dialogue.INTENT_LIST_TASKS)

    response = respond(request, repository, TODAY)

    assert response.tts is not None
    assert "Осталось сделать: Прочитать 20 минут" in response.tts
    assert "Зарядка" not in response.tts, "выполненные задачи не озвучиваются"
    assert "не отмечена" not in response.tts
    assert "балл" not in response.tts
    # Экран остаётся подробным: цена и статус видны.
    assert "Зарядка — 2 балла, засчитано" in response.text
    assert "Прочитать 20 минут — 2 балла, не отмечена" in response.text


def test_voice_mentions_waiting_tasks_when_some_are_pending(alice_event) -> None:
    repository = FakeSkillRepository(
        assignments=[
            make_assignment(1, "Зарядка", status=STATUS_PENDING),
            make_assignment(2, "Читать", status=STATUS_AWAITING_CONFIRMATION),
        ]
    )
    request = _request(alice_event, "какие задачи", intent=dialogue.INTENT_LIST_TASKS)

    response = respond(request, repository, TODAY)

    assert "Осталось сделать: Зарядка" in response.tts
    assert "Остальные задачи ждут подтверждения" in response.tts
    assert "Читать" not in response.tts


def test_voice_praises_when_all_tasks_done(alice_event) -> None:
    repository = FakeSkillRepository(
        assignments=[
            make_assignment(1, "Зарядка", status=STATUS_DONE),
            make_assignment(2, "Читать", status=STATUS_DONE),
        ]
    )
    request = _request(alice_event, "какие задачи", intent=dialogue.INTENT_LIST_TASKS)

    response = respond(request, repository, TODAY)

    assert "Ты молодец" in response.tts
    assert "Зарядка" not in response.tts
    assert "Все обязательные задачи выполнены" in response.text
    assert "молодец" in response.text


def test_voice_praises_when_only_optional_tasks_remain(alice_event) -> None:
    repository = FakeSkillRepository(
        assignments=[make_assignment(1, "Зарядка", status=STATUS_DONE)],
        tasks=[make_task(21, "Полить цветы", kind="optional", points=1)],
    )
    request = _request(alice_event, "какие задачи", intent=dialogue.INTENT_LIST_TASKS)

    response = respond(request, repository, TODAY)

    assert "Ты молодец" in response.tts
    assert "Если хочешь, можно ещё" in response.tts
    assert "Полить цветы" in response.tts


def test_voice_waits_for_confirmation_without_praise(alice_event) -> None:
    repository = FakeSkillRepository(
        assignments=[make_assignment(1, "Зарядка", status=STATUS_AWAITING_CONFIRMATION)]
    )
    request = _request(alice_event, "какие задачи", intent=dialogue.INTENT_LIST_TASKS)

    response = respond(request, repository, TODAY)

    assert "ждут подтверждения взрослого" in response.tts
    assert "молодец" not in response.tts


def test_voice_does_not_praise_for_missed_task(alice_event) -> None:
    repository = FakeSkillRepository(
        assignments=[make_assignment(1, "Зарядка", status=STATUS_MISSED)]
    )
    request = _request(alice_event, "какие задачи", intent=dialogue.INTENT_LIST_TASKS)

    response = respond(request, repository, TODAY)

    assert "На сегодня обязательных задач не осталось" in response.tts
    assert "молодец" not in response.tts
def test_my_points_without_goal_suggests_choosing_reward(alice_event, repository) -> None:
    request = _request(alice_event, "сколько у меня баллов", intent=dialogue.INTENT_MY_POINTS)

    response = respond(request, repository, TODAY)

    assert "30 баллов" in response.text
    assert "Цель пока не выбрана" in response.text


def test_my_points_with_goal_shows_remaining(alice_event, repository) -> None:
    repository.goal = make_reward(2, "Настольная игра", cost=70)
    request = _request(alice_event, "сколько у меня баллов", intent=dialogue.INTENT_MY_POINTS)

    response = respond(request, repository, TODAY)

    assert "30 баллов" in response.text
    assert "40 баллов" in response.text


def test_my_points_when_goal_is_affordable(alice_event, repository) -> None:
    repository.goal = make_reward(1, "Мороженое", cost=25)
    request = _request(alice_event, "сколько у меня баллов", intent=dialogue.INTENT_MY_POINTS)

    response = respond(request, repository, TODAY)

    assert "уже хватает" in response.text


def test_my_goal_without_goal_points_to_cheapest_reward(alice_event) -> None:
    repository = FakeSkillRepository(
        rewards=[make_reward(1, "Наклейка", cost=10), make_reward(2, "Кино", cost=100)],
        balance=5,
    )
    request = _request(alice_event, "какая у меня цель", intent=dialogue.INTENT_MY_GOAL)

    response = respond(request, repository, TODAY)

    assert "Наклейка" in response.text
    assert "5 баллов" in response.text


def test_my_goal_reports_remaining_points(alice_event, repository) -> None:
    repository.goal = make_reward(2, "Настольная игра", cost=70)
    request = _request(alice_event, "сколько осталось до цели", intent=dialogue.INTENT_MY_GOAL)

    response = respond(request, repository, TODAY)

    assert "Настольная игра" in response.text
    assert "70 баллов" in response.text
    assert "40 баллов" in response.text


def test_my_goal_when_points_are_enough(alice_event, repository) -> None:
    repository.goal = make_reward(1, "Мороженое", cost=25)
    request = _request(alice_event, "какая цель", intent=dialogue.INTENT_MY_GOAL)

    response = respond(request, repository, TODAY)

    assert "Баллов хватает" in response.text


def test_list_rewards_marks_availability(alice_event, repository) -> None:
    request = _request(alice_event, "какие награды", intent=dialogue.INTENT_LIST_REWARDS)

    response = respond(request, repository, TODAY)

    assert "Мороженое — 25 баллов, можно брать" in response.text
    assert "Настольная игра — 70 баллов, накопить ещё 40 баллов" in response.text
def test_task_done_moves_task_to_confirmation(alice_event, repository) -> None:
    request = _request(alice_event, "я выполнил зарядку", intent=dialogue.INTENT_TASK_DONE)

    response = respond(request, repository, TODAY)

    assert "ждёт подтверждения" in response.text
    assert "2 балла" in response.text
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
    assert "5 баллов" in response.text
    assert repository.redeemed_reward_ids == [1]
    assert repository.balance == 5
    assert repository.redemptions[0].status == REDEMPTION_REQUESTED


def test_want_unaffordable_reward_sets_goal(alice_event, repository) -> None:
    request = _request(alice_event, "хочу настольную игру", intent=dialogue.INTENT_WANT_REWARD)

    response = respond(request, repository, TODAY)

    assert "Пока не хватает 40 баллов" in response.text
    assert repository.goal_requests == [2]
    assert repository.goal is not None
    assert repository.redeemed_reward_ids == []


def test_want_unknown_reward_lists_rewards(alice_event, repository) -> None:
    request = _request(alice_event, "хочу пони", intent=dialogue.INTENT_WANT_REWARD)

    response = respond(request, repository, TODAY)

    assert "Не нашла такую награду" in response.text
    assert "Мороженое" in response.text
    assert repository.redeemed_reward_ids == []


def test_today_in_skill_timezone_is_date() -> None:
    assert isinstance(dialogue.today_in_skill_timezone(), dt.date)


def test_skill_timezone_is_yekaterinburg() -> None:
    assert dialogue.SKILL_TIMEZONE.utcoffset(None) == dt.timedelta(hours=5)
    assert dt.datetime(2026, 11, 18, 23, 30, tzinfo=dt.timezone.utc).astimezone(
        dialogue.SKILL_TIMEZONE
    ).date() == dt.date(2026, 11, 19)


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

    assert "30 баллов" in response.text


def test_add_penalty_creates_request_without_deduction(alice_event, repository) -> None:
    request = _request(
        alice_event,
        "добавь штраф 10 баллов — не выключил свет",
        intent=dialogue.INTENT_ADD_PENALTY,
    )

    response = respond(request, repository, TODAY)

    assert "10 баллов" in response.text
    assert "не выключил свет" in response.text
    assert "ждёт подтверждения взрослого" in response.text
    assert len(repository.penalties) == 1
    assert repository.penalties[0].status == PENALTY_AWAITING
    assert repository.balance == 30, "баллы не должны списываться до подтверждения"


def test_add_penalty_without_amount_explains_format(alice_event, repository) -> None:
    request = _request(alice_event, "добавь штраф", intent=dialogue.INTENT_ADD_PENALTY)

    response = respond(request, repository, TODAY)

    assert "Не поняла сумму штрафа" in response.text
    assert repository.penalties == []


def test_add_penalty_without_reason_asks_for_it(alice_event, repository) -> None:
    request = _request(alice_event, "добавь штраф 10 баллов", intent=dialogue.INTENT_ADD_PENALTY)

    response = respond(request, repository, TODAY)

    assert "За что штраф" in response.text
    assert repository.penalties == []


def test_add_penalty_is_recognized_by_keyword(alice_event, repository) -> None:
    request = _request(alice_event, "штраф пять баллов за беспорядок")

    assert dialogue.detect_intent(request) == dialogue.INTENT_ADD_PENALTY

    response = respond(request, repository, TODAY)

    assert len(repository.penalties) == 1
    assert repository.penalties[0].points == 5
    assert repository.penalties[0].comment == "беспорядок"


def test_add_penalty_respects_daily_limit(alice_event, repository) -> None:
    repository.daily_limit = 1
    first = _request(alice_event, "штраф 5 баллов за шум", intent=dialogue.INTENT_ADD_PENALTY)
    second = _request(alice_event, "штраф 5 баллов за шум", intent=dialogue.INTENT_ADD_PENALTY)

    respond(first, repository, TODAY)
    response = respond(second, repository, TODAY)

    assert "много заявок на штраф" in response.text
    assert len(repository.penalties) == 1


def test_add_penalty_rejects_amount_above_limit(alice_event, repository) -> None:
    repository.max_points = 20
    request = _request(alice_event, "штраф 50 баллов за шум", intent=dialogue.INTENT_ADD_PENALTY)

    response = respond(request, repository, TODAY)

    assert "от 1 до 20 баллов" in response.text
    assert repository.penalties == []


def test_add_penalty_default_limit_is_daily_plan(alice_event, repository) -> None:
    request = _request(alice_event, "штраф 11 баллов за шум", intent=dialogue.INTENT_ADD_PENALTY)

    response = respond(request, repository, TODAY)

    assert "от 1 до 10 баллов" in response.text
    assert repository.penalties == []


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


# --- дополнительные задачи (kind = 'optional') ---

OPTIONAL_TASKS = [make_task(21, "Полить цветы", kind="optional", points=5)]


def test_list_tasks_mentions_optional_tasks_without_penalty(alice_event) -> None:
    repository = FakeSkillRepository(
        assignments=[make_assignment(1, "Зарядка", points=10)],
        tasks=OPTIONAL_TASKS,
        balance=10,
    )
    request = _request(alice_event, "какие задачи на сегодня", intent=dialogue.INTENT_LIST_TASKS)

    response = respond(request, repository, TODAY)

    assert "Если хочешь, можно ещё" in response.text
    assert "Полить цветы — 5 баллов" in response.text
    assert "не списываются" in response.text


def test_list_tasks_without_plan_still_offers_optional_tasks(alice_event) -> None:
    repository = FakeSkillRepository(tasks=OPTIONAL_TASKS)
    request = _request(alice_event, "какие задачи на сегодня", intent=dialogue.INTENT_LIST_TASKS)

    response = respond(request, repository, TODAY)

    assert "обязательных задач нет" in response.text
    assert "Полить цветы" in response.text


def test_optional_task_on_another_weekday_is_not_offered(alice_event) -> None:
    repository = FakeSkillRepository(
        tasks=[make_task(31, "Вынести мусор", kind="optional", points=1, weekdays=(1,))]
    )
    request = _request(alice_event, "какие задачи на сегодня", intent=dialogue.INTENT_LIST_TASKS)

    response = respond(request, repository, TODAY)  # воскресенье

    assert "Вынести мусор" not in response.text


def test_optional_task_is_offered_on_its_weekday(alice_event) -> None:
    repository = FakeSkillRepository(
        tasks=[make_task(31, "Вынести мусор", kind="optional", points=1, weekdays=(7,))]
    )
    request = _request(alice_event, "какие задачи на сегодня", intent=dialogue.INTENT_LIST_TASKS)

    response = respond(request, repository, TODAY)  # воскресенье

    assert "Вынести мусор" in response.text


def test_task_done_for_optional_task_creates_request_without_penalty(alice_event) -> None:
    repository = FakeSkillRepository(tasks=OPTIONAL_TASKS, balance=10)
    request = _request(alice_event, "я полил цветы", intent=dialogue.INTENT_TASK_DONE)

    response = respond(request, repository, TODAY)

    assert "дополнительная задача" in response.text
    assert "баллы не спишутся" in response.text
    assert repository.claims == []
    assert repository.optional_claims == [21]
    assert repository.assignments[0].status == STATUS_AWAITING_CONFIRMATION
    assert repository.assignments[0].kind == "optional"
    assert repository.balance == 10


def test_optional_task_is_not_claimed_twice(alice_event) -> None:
    repository = FakeSkillRepository(tasks=OPTIONAL_TASKS)
    request = _request(alice_event, "я полил цветы", intent=dialogue.INTENT_TASK_DONE)
    respond(request, repository, TODAY)

    response = respond(request, repository, TODAY)

    assert "уже ждёт подтверждения" in response.text
    assert len(repository.assignments) == 1


def test_unknown_task_message_hints_optional_tasks(alice_event) -> None:
    repository = FakeSkillRepository(
        assignments=[make_assignment(1, "Зарядка")],
        tasks=OPTIONAL_TASKS,
    )
    request = _request(alice_event, "я выполнил уборку снега", intent=dialogue.INTENT_TASK_DONE)

    response = respond(request, repository, TODAY)

    assert "Не нашла такую задачу" in response.text
    assert "Можно взять дополнительно: Полить цветы" in response.text


def test_rejecting_optional_task_does_not_deduct_points() -> None:
    repository = FakeSkillRepository(tasks=OPTIONAL_TASKS, balance=10)
    repository.claim_optional_task("user-1", TODAY, OPTIONAL_TASKS[0])

    repository.reject_assignment(1)

    assert repository.balance == 10
    assert repository.ledger == []


