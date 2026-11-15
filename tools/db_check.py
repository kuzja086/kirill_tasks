"""Проверка подключения к Postgres по параметрам из .env.

Запуск:

    python tools/db_check.py

Печатает адрес, базу и пользователя (пароль не показывается), затем пытается
подключиться и выводит версию сервера либо текст ошибки. Коды возврата:
0 — подключение есть, 1 — ошибка подключения, 2 — не хватает переменных.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg2  # noqa: E402

from alice_skill.config import ConfigError, Settings, load_settings  # noqa: E402
from tools.local import load_env_from_file  # noqa: E402


def server_version(settings: Settings) -> str:
    """Подключается к базе и возвращает версию сервера."""
    connection = psycopg2.connect(**settings.connection_params)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version()")
            return str(cursor.fetchone()[0])
    finally:
        connection.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    load_env_from_file(ROOT / ".env")
    try:
        settings = load_settings()
    except ConfigError as error:
        print(f"ОШИБКА конфигурации: {error}")
        return 2

    print(
        f"Хост: {settings.pg_host}:{settings.pg_port}, база {settings.pg_database}, "
        f"пользователь {settings.pg_user}, sslmode={settings.pg_sslmode}"
    )
    try:
        version = server_version(settings)
    except Exception as error:  # noqa: BLE001 — нужен любой текст ошибки драйвера
        print(f"ОШИБКА подключения: {type(error).__name__}: {error}")
        return 1

    print(f"OK: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
