"""Сценарии диалога: маршрутизация интентов и тексты ответов.

Заготовка навыка-«знакомства»: запоминает имя пользователя в Postgres
и напоминает его. Замените тексты и обработчики на свою логику.
"""

from __future__ import annotations

from alice_skill.db import UserRepository
from alice_skill.models import AliceRequest, AliceResponse, make_button

INTENT_REMEMBER_NAME = "remember_name"
INTENT_ASK_NAME = "ask_name"

WELCOME_TEXT = "Привет! Я запоминаю имена. Скажите «запомни меня» и назовите своё имя."
WELCOME_TTS = "Привет! Я запоминаю имена. Скажите: запомни меня, и назовите своё имя."
FALLBACK_TEXT = (
    "Я пока умею немного: запомнить ваше имя и напомнить его. "
    "Скажите «запомни меня»."
)
FALLBACK_TTS = "Я пока умею немного. Скажите: запомни меня."
NAME_REQUEST_TEXT = "Как вас зовут?"
NAME_UNKNOWN_TEXT = "Мы ещё не знакомы. Скажите «запомни меня» и назовите имя."

REMEMBER_BUTTON_TITLE = "Запомни меня"
ASK_NAME_BUTTON_TITLE = "Как меня зовут?"


def respond(request: AliceRequest, repository: UserRepository) -> AliceResponse:
    """Формирует ответ навыка на запрос Алисы.

    Исключения не перехватываются: их обрабатывает точка входа, чтобы любая
    ошибка (в том числе недоступность Postgres) стала валидным ответом.
    """
    if request.intent == INTENT_REMEMBER_NAME:
        return _remember_name(request, repository)
    if request.intent == INTENT_ASK_NAME:
        return _recall_name(request, repository)
    if request.is_new_session and request.is_empty:
        return AliceResponse(text=WELCOME_TEXT, tts=WELCOME_TTS)
    return AliceResponse(text=FALLBACK_TEXT, tts=FALLBACK_TTS)


def _remember_name(
    request: AliceRequest,
    repository: UserRepository,
) -> AliceResponse:
    name = _extract_name(request)
    if name is None:
        return AliceResponse(
            text=NAME_REQUEST_TEXT,
            tts=NAME_REQUEST_TEXT,
            buttons=[make_button(REMEMBER_BUTTON_TITLE, payload={"intent": INTENT_REMEMBER_NAME})],
        )

    repository.save_user_name(request.user_id, name)
    return AliceResponse(
        text=f"Запомнила. Вас зовут {name}.",
        tts=f"Запомнила. Вас зовут {name}.",
        buttons=[make_button(ASK_NAME_BUTTON_TITLE, payload={"intent": INTENT_ASK_NAME})],
    )


def _recall_name(
    request: AliceRequest,
    repository: UserRepository,
) -> AliceResponse:
    name = repository.get_user_name(request.user_id)
    if name is None:
        return AliceResponse(
            text=NAME_UNKNOWN_TEXT,
            tts=NAME_UNKNOWN_TEXT,
            buttons=[make_button(REMEMBER_BUTTON_TITLE, payload={"intent": INTENT_REMEMBER_NAME})],
        )
    return AliceResponse(text=f"Вас зовут {name}.", tts=f"Вас зовут {name}.")


def _extract_name(request: AliceRequest) -> str | None:
    """Достаёт имя из запроса.

    У навыка пока нет обученной NLU-модели, поэтому имя берётся из payload
    кнопки, а если его там нет — эвристикой «последнее слово фразы».
    После обучения модели намерения имя будет приходить в слоте интента.
    """
    payload_name = request.payload.get("name")
    if isinstance(payload_name, str) and payload_name.strip():
        return _normalize_name(payload_name)

    if len(request.tokens) >= 3:
        return _normalize_name(request.tokens[-1])
    return None


def _normalize_name(raw: str) -> str:
    name = raw.strip()
    return name[:1].upper() + name[1:]
