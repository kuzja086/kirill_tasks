"""Применение миграций из ``sql/*.sql`` по порядку.

    python tools/db_migrate.py                 # применить все миграции
    python tools/db_migrate.py --hostaddr IP   # обойти неверный DNS

Файлы применяются в лексикографическом порядке (001, 002, 003...). Скрипты
написаны идемпотентно (``IF NOT EXISTS`` / ``IF EXISTS``), поэтому повторный
запуск безопасен.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg2  # noqa: E402

from alice_skill.config import ConfigError, Settings, load_settings  # noqa: E402
from tools.local import load_env_from_file  # noqa: E402

SQL_DIR = ROOT / "sql"


def migration_files(directory: Path = SQL_DIR) -> list[Path]:
    """Файлы миграций в порядке применения."""
    return sorted(directory.glob("*.sql"))


def apply_migrations(
    settings: Settings,
    directory: Path = SQL_DIR,
    *,
    connection_factory=None,
) -> list[str]:
    """Выполняет все миграции и возвращает имена применённых файлов."""
    factory = connection_factory or psycopg2.connect
    applied: list[str] = []
    connection = factory(**settings.connection_params)
    try:
        for path in migration_files(directory):
            sql = path.read_text(encoding="utf-8")
            with connection.cursor() as cursor:
                cursor.execute(sql)
            connection.commit()
            applied.append(path.name)
    finally:
        connection.close()
    return applied


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Применение миграций навыка")
    parser.add_argument("--hostaddr", help="подключиться по IP (когда DNS врёт)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    load_env_from_file(ROOT / ".env")
    try:
        settings = load_settings()
    except ConfigError as error:
        print(f"ОШИБКА конфигурации: {error}")
        return 2

    if args.hostaddr:
        settings = replace(settings, pg_hostaddr=args.hostaddr)

    print(
        f"База: {settings.pg_host}:{settings.pg_port}/{settings.pg_database}, "
        f"пользователь {settings.pg_user}"
    )
    try:
        applied = apply_migrations(settings)
    except Exception as error:  # noqa: BLE001 — нужен текст ошибки драйвера
        print(f"ОШИБКА применения миграций: {type(error).__name__}: {error}")
        return 1

    for name in applied:
        print(f"применено: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
