"""Точка входа Яндекс Облака для навыка Алисы.

При создании версии функции указывается entrypoint ``handler.handler``
и runtime ``python312``. Файл должен лежать в корне архива функции.
"""

from __future__ import annotations

import logging
from typing import Any

from alice_skill.config import load_settings
from alice_skill.db import PostgresRepository
from alice_skill.dialogue import respond
from alice_skill.models import AliceRequest, AliceResponse

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ERROR_TEXT = "Что-то пошло не так. Попробуйте ещё раз через минуту."

_repository: PostgresRepository | None = None


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Обрабатывает запрос Алисы и возвращает ответ протокола Яндекс.Диалогов.

    :param event: тело запроса от Алисы, уже разобранное рантаймом в dict.
    :param context: контекст вызова Cloud Functions (нужен только для логов).
    """
    request = AliceRequest.from_event(event or {})
    try:
        response = respond(request, _get_repository())
    except Exception:
        logger.exception(
            "Не удалось обработать запрос: session_id=%s, request_id=%s",
            request.session_id,
            getattr(context, "request_id", None),
        )
        response = AliceResponse(text=ERROR_TEXT)
    return response.to_dict(version=request.version)


def _get_repository() -> PostgresRepository:
    """Создаёт репозиторий один раз на инстанс функции.

    Cloud Functions переиспользует контейнер между вызовами, поэтому
    соединение с Postgres переживает несколько запросов.
    """
    global _repository
    if _repository is None:
        _repository = PostgresRepository(load_settings())
    return _repository
