"""Точка входа Яндекс Облака для навыка Алисы.

При создании версии функции указывается entrypoint ``handler.handler``
и runtime ``python312``. Файл должен лежать в корне архива функции.

Функция поддерживает три способа вызова:

* HTTPS-интеграция (webhook без параметров) — рантайм передаёт HTTP-событие,
  запрос навыка лежит в ``event['body']`` строкой, а ответ нужно вернуть
  в формате ``statusCode``/``headers``/``body``;
* HTTPS-интеграция с ``?integration=raw`` — рантайм передаёт тело запроса
  как есть, ответ возвращается без обёртки;
* прямой вызов через API/CLI (``yc serverless function invoke``) — событием
  является сам JSON Яндекс.Диалогов.

Различить их можно по наличию ``httpMethod`` в событии. Это важно: консоль
Яндекс.Диалогов проверяет именно возвращаемое значение функции, поэтому
обёртка допустима только для HTTP-интеграции.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

from alice_skill.config import load_settings
from alice_skill.dialogue import respond
from alice_skill.models import AliceRequest, AliceResponse
from alice_skill.repository import PostgresSkillRepository

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ERROR_TEXT = "Что-то пошло не так. Попробуйте ещё раз через минуту."

# Переменная окружения для отладки: при DEBUG_ERRORS=1 в ответ попадает
# тип и текст исключения. Включайте только на время диагностики.
DEBUG_ENV_VAR = "DEBUG_ERRORS"

_repository: PostgresSkillRepository | None = None


def handler(event: dict[str, Any] | str, context: Any) -> dict[str, Any]:
    """Обрабатывает запрос Алисы и возвращает ответ в нужном формате.

    :param event: HTTP-событие Cloud Functions, строка или сам JSON Диалогов.
    :param context: контекст вызова Cloud Functions (нужен только для логов).
    """
    http_mode = _is_http_event(event)

    try:
        payload = _extract_request_payload(event)
    except ValueError as error:
        logger.exception("Не удалось разобрать тело запроса")
        return _format_response(AliceResponse(text=_error_text(error)).to_dict(), http_mode)

    request = AliceRequest.from_event(payload)
    try:
        response = respond(request, _get_repository())
    except Exception as error:
        logger.exception(
            "Не удалось обработать запрос: session_id=%s, request_id=%s",
            request.session_id,
            getattr(context, "request_id", None),
        )
        response = AliceResponse(text=_error_text(error))
    return _format_response(response.to_dict(version=request.version), http_mode)


def _is_http_event(event: dict[str, Any] | str) -> bool:
    """Признак HTTPS-интеграции: рантайм добавляет в событие HTTP-поля."""
    return isinstance(event, dict) and "httpMethod" in event


def _extract_request_payload(event: dict[str, Any] | str) -> dict[str, Any]:
    """Достаёт JSON навыка из события функции.

    :raises ValueError: если тело запроса не является корректным JSON.
    """
    if isinstance(event, str):
        return json.loads(event)
    if not isinstance(event, dict):
        raise ValueError(f"Неожиданный тип события: {type(event).__name__}")

    body = event.get("body")
    if body is None:
        return event
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    return json.loads(body)


def _format_response(payload: dict[str, Any], http_mode: bool) -> dict[str, Any]:
    """Возвращает ответ в формате HTTP-интеграции или «сырым» протоколом."""
    if not http_mode:
        return payload
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps(payload, ensure_ascii=False),
        "isBase64Encoded": False,
    }



def _error_text(error: Exception) -> str:
    """Текст ответа при внутренней ошибке.

    При ``DEBUG_ERRORS=1`` возвращает тип и текст исключения — помогает
    диагностировать проблему в облаке, когда логи недоступны.
    """
    if os.getenv(DEBUG_ENV_VAR) == "1":
        return f"{type(error).__name__}: {error}"
    return ERROR_TEXT


def _extract_request_payload(event: dict[str, Any] | str) -> dict[str, Any]:
    """Достаёт JSON навыка из события функции.

    :raises ValueError: если тело запроса не является корректным JSON.
    """
    if isinstance(event, str):
        return json.loads(event)
    if not isinstance(event, dict):
        raise ValueError(f"Неожиданный тип события: {type(event).__name__}")

    body = event.get("body")
    if body is None:
        return event
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    return json.loads(body)


def _http_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Оборачивает ответ навыка в структуру ответа HTTP-интеграции."""
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps(payload, ensure_ascii=False),
        "isBase64Encoded": False,
    }


def _get_repository() -> PostgresSkillRepository:
    """Создаёт репозиторий один раз на инстанс функции.

    Cloud Functions переиспользует контейнер между вызовами, поэтому
    соединение с Postgres переживает несколько запросов.
    """
    global _repository
    if _repository is None:
        _repository = PostgresSkillRepository(load_settings())
    return _repository
