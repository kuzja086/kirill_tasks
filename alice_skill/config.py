"""Настройки навыка, получаемые из переменных окружения Cloud Functions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

PROTOCOL_VERSION = "1.0"

DEFAULT_PORT = 5432
DEFAULT_SSLMODE = "prefer"
DEFAULT_CONNECT_TIMEOUT = 5

REQUIRED_VARIABLES = ("PG_HOST", "PG_DATABASE", "PG_USER", "PG_PASSWORD")


class ConfigError(RuntimeError):
    """Обязательные переменные окружения не заданы или заданы неверно."""


@dataclass(frozen=True)
class Settings:
    """Параметры подключения к Postgres."""

    pg_host: str
    pg_port: int
    pg_database: str
    pg_user: str
    pg_password: str
    pg_sslmode: str = DEFAULT_SSLMODE
    pg_connect_timeout: int = DEFAULT_CONNECT_TIMEOUT

    @property
    def connection_params(self) -> dict[str, str | int]:
        """Параметры для ``psycopg2.connect(**params)``.

        Возвращаем kwargs, а не DSN-строку, чтобы не экранировать вручную
        спецсимволы в пароле.
        """
        return {
            "host": self.pg_host,
            "port": self.pg_port,
            "dbname": self.pg_database,
            "user": self.pg_user,
            "password": self.pg_password,
            "sslmode": self.pg_sslmode,
            "connect_timeout": self.pg_connect_timeout,
        }


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Читает настройки из окружения.

    :param env: подменяется в тестах; по умолчанию используется ``os.environ``.
    :raises ConfigError: если не заданы обязательные переменные.
    """
    source = os.environ if env is None else env

    missing = [name for name in REQUIRED_VARIABLES if not source.get(name)]
    if missing:
        raise ConfigError("Не заданы переменные окружения: " + ", ".join(missing))

    return Settings(
        pg_host=source["PG_HOST"].strip(),
        pg_port=_as_int(source.get("PG_PORT"), DEFAULT_PORT, "PG_PORT"),
        pg_database=source["PG_DATABASE"].strip(),
        pg_user=source["PG_USER"].strip(),
        pg_password=source["PG_PASSWORD"],
        pg_sslmode=(source.get("PG_SSLMODE") or DEFAULT_SSLMODE).strip(),
        pg_connect_timeout=_as_int(
            source.get("PG_CONNECT_TIMEOUT"),
            DEFAULT_CONNECT_TIMEOUT,
            "PG_CONNECT_TIMEOUT",
        ),
    )


def _as_int(raw: str | None, default: int, name: str) -> int:
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise ConfigError(
            f"Переменная {name} должна быть целым числом, получено: {raw!r}"
        ) from error
