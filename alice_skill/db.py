"""Подключение к Postgres и транзакции.

Соединение создаётся лениво и переиспользуется между вызовами функции
в пределах одного «тёплого» инстанса Cloud Functions.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Iterator

import psycopg2
import psycopg2.extensions

from alice_skill.config import Settings

logger = logging.getLogger(__name__)

# Ошибки, после которых соединение считается мёртвым и его нужно переоткрыть.
CONNECTION_ERRORS = (psycopg2.OperationalError, psycopg2.InterfaceError)

USER_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext(%s))"


class Database:
    """Тонкая обёртка над соединением psycopg2."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._connection: psycopg2.extensions.connection | None = None

    @contextlib.contextmanager
    def transaction(
        self,
        *,
        lock_user: str | None = None,
    ) -> Iterator[psycopg2.extensions.cursor]:
        """Открывает транзакцию: commit при успехе, rollback при исключении.

        ``lock_user`` берёт advisory-блокировку на пользователя: она
        сериализует параллельные списания баллов одного ребёнка.
        """
        connection = self._connect()
        with connection.cursor() as cursor:
            try:
                if lock_user:
                    cursor.execute(USER_LOCK_SQL, (lock_user,))
                yield cursor
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def reset(self) -> None:
        """Закрывает соединение, чтобы следующая операция открыла новое."""
        if self._connection is not None and not self._connection.closed:
            self._connection.close()
        self._connection = None

    def close(self) -> None:
        """Закрывает соединение (алиас ``reset`` для читаемости)."""
        self.reset()

    def _connect(self) -> psycopg2.extensions.connection:
        if self._connection is None or self._connection.closed:
            self._connection = psycopg2.connect(**self._settings.connection_params)
        return self._connection
