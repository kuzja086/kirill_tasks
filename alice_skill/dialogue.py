"""Сценарии диалога: задачи на сегодня, баллы, цель и награды.

Интенты (имена должны совпадать с натренированными интентами в консоли
Яндекс.Диалогов):

* ``list_tasks`` — «какие задачи на сегодня»;
* ``my_points`` — «сколько у меня баллов»;
* ``my_goal`` — «какая у меня цель», «сколько осталось»;
* ``list_rewards`` — «какие награды»;
* ``task_done`` — «я выполнил зарядку»;
* ``want_reward`` — «хочу мороженое».
"""

from __future__ import annotations

import datetime as dt

from alice_skill import matching, penalties, text
from alice_skill.models import (
    CLAIM_CREATED,
    PENALTY_CREATED,
    PENALTY_LIMIT_EXCEEDED,
    REDEEM_INSUFFICIENT,
    REDEEM_OK,
    STATUS_AWAITING_CONFIRMATION,
    STATUS_DONE,
    STATUS_MISSED,
    AliceRequest,
    AliceResponse,
    Assignment,
    Reward,
    Task,
    make_button,
)
from alice_skill.repository import SkillRepository
from alice_skill.timeutil import SKILL_TIMEZONE, today_in_skill_timezone

INTENT_LIST_TASKS = "list_tasks"
INTENT_MY_POINTS = "my_points"
INTENT_MY_GOAL = "my_goal"
INTENT_LIST_REWARDS = "list_rewards"
INTENT_TASK_DONE = "task_done"
INTENT_WANT_REWARD = "want_reward"
INTENT_ADD_PENALTY = "add_penalty"

MAX_LINES = 10
# Сколько дополнительных задач перечислять: они не обязательны и не должны
# вытеснять план дня из ответа.
OPTIONAL_LINES = 3

TASKS_BUTTON = "Какие задачи на сегодня?"
POINTS_BUTTON = "Сколько у меня баллов?"
REWARDS_BUTTON = "Какие награды?"

WELCOME_TEXT = (
    "Привет! Я помогаю с задачами и баллами. Спроси, какие задачи на сегодня, "
    "сколько у тебя баллов или какие есть награды."
)
WELCOME_TTS = (
    "Привет! Я помогаю с задачами и баллами. Спроси: какие задачи на сегодня, "
    "сколько у меня баллов или какие есть награды."
)
HELP_TEXT = (
    "Я умею показывать задачи на сегодня, считать баллы и показывать награды. "
    "Скажи «я выполнил зарядку» или «хочу мороженое»."
)
HELP_TTS = (
    "Я умею показывать задачи на сегодня, считать баллы и показывать награды. "
    "Скажи: я выполнил зарядку, или: хочу мороженое."
)
NO_USER_TEXT = "Не получилось определить, кто говорит. Попробуйте открыть навык заново."

# Для этих интентов нужен дневной план: он же начисляет штрафы за прошлые дни.
INTENTS_WITH_DAILY_PLAN = frozenset(
    {
        INTENT_LIST_TASKS,
        INTENT_MY_POINTS,
        INTENT_MY_GOAL,
        INTENT_LIST_REWARDS,
        INTENT_TASK_DONE,
        INTENT_WANT_REWARD,
        INTENT_ADD_PENALTY,
    }
)

# Резервное распознавание, пока интенты не натренированы в консоли Диалогов:
# тогда nlu.intents пуст и без этой таблицы навык отвечал бы только справкой.
# Ключи сравниваются как подстроки нормализованной фразы, порядок важен.
KEYWORD_INTENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (INTENT_ADD_PENALTY, ("штраф",)),
    (INTENT_TASK_DONE, ("выполн", "сдела", "отметь", "готово", "закончи")),
    (INTENT_WANT_REWARD, ("хочу", "купить", "получить", "дай")),
    (INTENT_MY_POINTS, ("балл", "очк", "баланс")),
    (INTENT_MY_GOAL, ("цел", "осталось", "копить")),
    (INTENT_LIST_REWARDS, ("наград", "приз", "подар")),
    (INTENT_LIST_TASKS, ("задач", "делать", "план", "сегодня")),
)


def detect_intent(request: AliceRequest) -> str | None:
    """Определяет интент: NLU/кнопка, иначе ключевые слова фразы."""
    if request.intent:
        return request.intent

    phrase = matching.normalize(f"{request.command} {request.original_utterance}")
    if not phrase:
        return None

    for intent, keywords in KEYWORD_INTENTS:
        if any(keyword in phrase for keyword in keywords):
            return intent
    return None


def today_in_skill_timezone() -> dt.date:
    """Сегодняшняя дата по времени навыка (Екатеринбург, UTC+5)."""
    return dt.datetime.now(SKILL_TIMEZONE).date()


def respond(
    request: AliceRequest,
    repository: SkillRepository,
    today: dt.date | None = None,
) -> AliceResponse:
    """Формирует ответ на запрос ребёнка.

    Исключения не перехватываются: их обрабатывает точка входа, чтобы любая
    ошибка (в том числе недоступность Postgres) стала валидным ответом.
    """
    today = today or today_in_skill_timezone()
    intent = detect_intent(request)

    if intent in INTENTS_WITH_DAILY_PLAN:
        if not request.user_id:
            return AliceResponse(text=NO_USER_TEXT)

        assignments = repository.ensure_daily_plan(request.user_id, today)
        balance = repository.get_balance(request.user_id)

        if intent == INTENT_LIST_TASKS:
            return _list_tasks(
                assignments,
                balance,
                repository.list_optional_tasks(today),
            )
        if intent == INTENT_MY_POINTS:
            return _my_points(repository, request.user_id, balance)
        if intent == INTENT_MY_GOAL:
            return _my_goal(repository, request.user_id, balance)
        if intent == INTENT_LIST_REWARDS:
            return _list_rewards(repository, balance)
        if intent == INTENT_TASK_DONE:
            return _task_done(request, repository, assignments, today)
        if intent == INTENT_ADD_PENALTY:
            return _add_penalty(request, repository)
        return _want_reward(request, repository)

    if request.is_new_session and request.is_empty:
        return _welcome()

    return _help()


def _welcome() -> AliceResponse:
    return AliceResponse(
        text=WELCOME_TEXT,
        tts=WELCOME_TTS,
        buttons=[
            make_button(TASKS_BUTTON, payload={"intent": INTENT_LIST_TASKS}),
            make_button(POINTS_BUTTON, payload={"intent": INTENT_MY_POINTS}),
        ],
    )


def _help() -> AliceResponse:
    return AliceResponse(
        text=HELP_TEXT,
        tts=HELP_TTS,
        buttons=[
            make_button(TASKS_BUTTON, payload={"intent": INTENT_LIST_TASKS}),
            make_button(REWARDS_BUTTON, payload={"intent": INTENT_LIST_REWARDS}),
        ],
    )


def _list_tasks(
    assignments: list[Assignment],
    balance: int,
    optional: list[Task] | None = None,
) -> AliceResponse:
    optional_note = _optional_tasks_note(optional or [])

    if not assignments:
        return AliceResponse(
            text=(
                "На сегодня обязательных задач нет. "
                f"Попросите взрослого добавить задачи в список.{optional_note}"
            )
        )

    shown = assignments[:MAX_LINES]
    lines_text = "; ".join(
        text.format_task_line(assignment, index) for index, assignment in enumerate(shown, start=1)
    )
    lines_tts = "; ".join(text.format_task_line(assignment) for assignment in shown)
    tail = f", и ещё {len(assignments) - len(shown)}" if len(assignments) > len(shown) else ""
    total = sum(assignment.points for assignment in assignments)

    return AliceResponse(
        text=(
            f"Задачи на сегодня: {lines_text}{tail}. "
            f"Всего можно получить {text.format_points(total)}, у тебя {text.format_points(balance)}."
            f"{optional_note}"
        ),
        tts=(
            f"Задачи на сегодня: {lines_tts}{tail}. "
            f"Всего можно получить {text.format_points(total)}."
            f"{optional_note}"
        ),
        buttons=[make_button(POINTS_BUTTON, payload={"intent": INTENT_MY_POINTS})],
    )


def _optional_tasks_note(optional: list[Task]) -> str:
    """Блок «если хочешь»: дополнительные задачи, за пропуск баллы не списываются."""
    if not optional:
        return ""

    shown = optional[:OPTIONAL_LINES]
    lines = "; ".join(
        f"{task.title} — {text.format_points(task.points)}" for task in shown
    )
    tail = f", и ещё {len(optional) - len(shown)}" if len(optional) > len(shown) else ""
    return (
        f" Если хочешь, можно ещё: {lines}{tail}. "
        "За них баллы не списываются, если не сделаешь."
    )


def _my_points(repository: SkillRepository, user_id: str, balance: int) -> AliceResponse:
    goal = repository.get_goal(user_id)
    if goal is None:
        return AliceResponse(
            text=(
                f"У тебя {text.format_points(balance)}. "
                "Цель пока не выбрана: скажи, какую награду хочешь."
            ),
            tts=f"У тебя {text.format_points(balance)}. Скажи, какую награду хочешь.",
            buttons=[make_button(REWARDS_BUTTON, payload={"intent": INTENT_LIST_REWARDS})],
        )

    left = max(0, goal.cost - balance)
    if left == 0:
        return AliceResponse(
            text=(
                f"У тебя {text.format_points(balance)}. "
                f"На цель «{goal.title}» уже хватает — скажи «хочу {goal.title.lower()}»."
            )
        )
    return AliceResponse(
        text=(
            f"У тебя {text.format_points(balance)}. "
            f"До цели «{goal.title}» осталось {text.format_points(left)}."
        )
    )


def _my_goal(repository: SkillRepository, user_id: str, balance: int) -> AliceResponse:
    goal = repository.get_goal(user_id)
    if goal is None:
        rewards = repository.list_rewards()
        if not rewards:
            return AliceResponse(
                text="Цель не выбрана, и наград в списке пока нет. Попросите взрослого добавить призы."
            )
        cheapest = rewards[0]
        left = max(0, cheapest.cost - balance)
        return AliceResponse(
            text=(
                f"Цель не выбрана. Самая доступная награда — «{cheapest.title}» "
                f"за {text.format_points(cheapest.cost)}, осталось накопить {text.format_points(left)}. "
                f"Скажи «хочу {cheapest.title.lower()}», чтобы выбрать её целью."
            ),
            buttons=[make_button(REWARDS_BUTTON, payload={"intent": INTENT_LIST_REWARDS})],
        )

    left = max(0, goal.cost - balance)
    if left == 0:
        return AliceResponse(
            text=(
                f"Цель — «{goal.title}». Баллов хватает: у тебя {text.format_points(balance)}. "
                f"Скажи «хочу {goal.title.lower()}», чтобы забрать награду."
            )
        )
    return AliceResponse(
        text=(
            f"Цель — «{goal.title}», она стоит {text.format_points(goal.cost)}. "
            f"У тебя {text.format_points(balance)}, осталось накопить {text.format_points(left)}."
        )
    )


def _list_rewards(repository: SkillRepository, balance: int) -> AliceResponse:
    rewards = repository.list_rewards()
    if not rewards:
        return AliceResponse(text="Наград пока нет. Попросите взрослого добавить призы.")

    shown = rewards[:MAX_LINES]
    lines_text = "; ".join(
        text.format_reward_line(reward, balance, index) for index, reward in enumerate(shown, start=1)
    )
    lines_tts = "; ".join(text.format_reward_line(reward, balance) for reward in shown)
    tail = f", и ещё {len(rewards) - len(shown)}" if len(rewards) > len(shown) else ""

    return AliceResponse(
        text=(
            f"Награды: {lines_text}{tail}. У тебя {text.format_points(balance)}. "
            "Скажи «хочу ...», чтобы выбрать награду."
        ),
        tts=f"Награды: {lines_tts}{tail}.",
        buttons=[make_button(POINTS_BUTTON, payload={"intent": INTENT_MY_POINTS})],
    )


def _task_done(
    request: AliceRequest,
    repository: SkillRepository,
    assignments: list[Assignment],
    today: dt.date,
) -> AliceResponse:
    phrase = f"{request.command} {request.original_utterance}".strip()
    match = matching.find_match([assignment.title for assignment in assignments], phrase)

    if match is not None:
        assignment = assignments[match.index]
        status = repository.claim_assignment(assignment.id)
        if status == STATUS_AWAITING_CONFIRMATION:
            return AliceResponse(
                text=(
                    f"Записала: «{assignment.title}». Задача ждёт подтверждения — "
                    f"{text.format_points(assignment.points)} начислятся после проверки."
                )
            )
        if status == STATUS_DONE:
            return AliceResponse(text=f"«{assignment.title}» уже засчитана.")
        if status == STATUS_MISSED:
            return AliceResponse(text=f"«{assignment.title}» уже отмечена пропущенной.")
        return AliceResponse(text="Не получилось отметить задачу. Попробуй ещё раз.")

    optional = repository.list_optional_tasks(today)
    optional_match = matching.find_match([task.title for task in optional], phrase)
    if optional_match is None:
        known = "; ".join(
            assignment.title for assignment in assignments[:MAX_LINES]
        ) or "задач нет"
        extra = _optional_titles(optional)
        return AliceResponse(
            text=(
                f"Не нашла такую задачу. Сегодня в плане: {known}.{extra} "
                "Назови задачу точнее."
            )
        )

    task = optional[optional_match.index]
    status = repository.claim_optional_task(request.user_id, today, task)
    if status == CLAIM_CREATED:
        return AliceResponse(
            text=(
                f"Записала: «{task.title}». Это дополнительная задача — если не сделаешь, "
                f"баллы не спишутся. {text.format_points(task.points)} начислятся "
                "после подтверждения взрослого."
            )
        )
    if status == STATUS_AWAITING_CONFIRMATION:
        return AliceResponse(text=f"«{task.title}» уже ждёт подтверждения.")
    if status == STATUS_DONE:
        return AliceResponse(text=f"«{task.title}» уже засчитана.")
    if status == STATUS_MISSED:
        return AliceResponse(text=f"«{task.title}» уже отмечена пропущенной.")
    return AliceResponse(text="Не получилось отметить задачу. Попробуй ещё раз.")


def _optional_titles(optional: list[Task]) -> str:
    """Подсказка о дополнительных задачах, когда фраза не совпала с планом."""
    if not optional:
        return ""

    titles = ", ".join(task.title for task in optional[:OPTIONAL_LINES])
    return f" Можно взять дополнительно: {titles}."


def _want_reward(request: AliceRequest, repository: SkillRepository) -> AliceResponse:
    rewards = repository.list_rewards()
    if not rewards:
        return AliceResponse(text="Наград пока нет. Попросите взрослого добавить призы.")

    phrase = f"{request.command} {request.original_utterance}".strip()
    match = matching.find_match([reward.title for reward in rewards], phrase)
    if match is None:
        known = "; ".join(reward.title for reward in rewards[:MAX_LINES])
        return AliceResponse(text=f"Не нашла такую награду. Можно выбрать: {known}.")

    reward: Reward = rewards[match.index]
    outcome = repository.redeem_reward(request.user_id, reward.id)

    if outcome.status == REDEEM_OK:
        return AliceResponse(
            text=(
                f"Готово! «{reward.title}» за {text.format_points(reward.cost)}. "
                f"Осталось {text.format_points(outcome.balance)}. Награда ждёт выдачи."
            )
        )
    if outcome.status == REDEEM_INSUFFICIENT:
        repository.set_goal(request.user_id, reward.id)
        return AliceResponse(
            text=(
                f"Пока не хватает {text.format_points(outcome.missing)}. "
                f"Поставила цель — «{reward.title}», у тебя {text.format_points(outcome.balance)}."
            )
        )
    return AliceResponse(text="Такой награды сейчас нет в списке.")


def _phrase(request: AliceRequest) -> str:
    """Текст фразы ребёнка: предпочитаем original_utterance, он богаче command."""
    return (request.original_utterance or request.command).strip()


def _add_penalty(request: AliceRequest, repository: SkillRepository) -> AliceResponse:
    phrase = _phrase(request)
    parsed = penalties.parse_penalty_phrase(phrase)

    if parsed is None:
        return AliceResponse(
            text=(
                "Не поняла сумму штрафа. Скажи, например: "
                "«добавь штраф 10 баллов — не выключил свет»."
            )
        )
    if not parsed.comment:
        return AliceResponse(
            text=(
                f"За что штраф на {text.format_points(parsed.points)}? "
                "Назови причину в той же фразе."
            )
        )

    result = repository.add_penalty(request.user_id, parsed.points, parsed.comment)

    if result.status == PENALTY_CREATED:
        return AliceResponse(
            text=(
                f"Записала штраф {text.format_points(parsed.points)}: {parsed.comment}. "
                "Он ждёт подтверждения взрослого — баллы пока не списаны."
            )
        )
    if result.status == PENALTY_LIMIT_EXCEEDED:
        return AliceResponse(
            text=(
                "Сегодня уже много заявок на штраф. "
                "Попросите взрослого добавить его вручную."
            )
        )
    return AliceResponse(
        text=f"Штраф должен быть от 1 до {result.max_points} баллов, и нужна причина."
    )


