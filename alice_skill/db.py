"""Доступ к Postgres. Драйвер — psycopg2, версия указана в requirements.txt."""

from __future__ import annotations

import contextlib
import logging
from typing import Any, Iterator, Protocol, runtime_checkable

import psycopg2
import psycopg2.extensions

from alice_skill.config import Settings

logger = logging.getLogger(__name__)

SELECT_USER_NAME = "SELECT display_name FROM skill_users WHERE user_id = %s"

UPSERT_USER_NAME = """
    INSERT INTO skill_users (user_id, display_name)
    VALUES (%s, %s)
    ON CONFLICT (user_id) DO UPDATE
       SET display_name = EXCLUDED.display_name,
           updated_at = now()
"""


@runtime_checkable
class UserRepository(Protocol):
    """Хранилище пользователей навыка.

    Сценарии диалога зависят от протокола, а не от Postgres: в тестах
    подставляется in-memory реализация.
    """

    def get_user_name(self, user_id: str) -> str | None:
        """Возвращает сохранённое имя пользователя или ``None``."""

    def save_user_name(self, user_id: str, display_name: str) -> None:
        """Сохраняет имя пользователя (вставка или обновление)."""


class PostgresRepository:
    """Репозиторий поверх Postgres.

    Соединение создаётся лениво и переиспользуется между вызовами функции
    в пределах одного «тёплого» инстанса Cloud Functions. Если соединение
    потеряно (простой, перезапуск сервера), операция повторяется один раз
    на новом соединении.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._connection: psycopg2.extensions.connection | None = None

    def get_user_name(self, user_id: str) -> str | None:
        row = self._run(SELECT_USER_NAME, (user_id,), fetch=True)
        return None if row is None else str(row[0])

    def save_user_name(self, user_id: str, display_name: str) -> None:
        self._run(UPSERT_USER_NAME, (user_id, display_name), fetch=False)

    def close(self) -> None:
        """Закрывает соединение, если оно открыто."""
        if self._connection is not None and not self._connection.closed:
            self._connection.close()
        self._connection = None

    def _run(
        self,
        query: str,
        params: tuple[Any, ...],
        *,
        fetch: bool,
    ) -> tuple[Any, ...] | None:
        for attempt in (1, 2):
            try:
                with self._cursor() as cursor:
                    cursor.execute(query, params)
                    return cursor.fetchone() if fetch else None
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                self.close()
                if attempt == 2:
                    raise
                logger.warning("Соединение с Postgres потеряно, повторяем запрос")
        return None

    @contextlib.contextmanager
    def _cursor(self) -> Iterator[psycopg2.extensions.cursor]:
        connection = self._connect()
        with connection.cursor() as cursor:
            try:
                yield cursor
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def _connect(self) -> psycopg2.extensions.connection:
        if self._connection is None or self._connection.closed:
            self._connection = psycopg2.connect(**self._settings.connection_params)
        return self._connection
