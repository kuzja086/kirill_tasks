"""Тесты раннера миграций."""

from __future__ import annotations

from pathlib import Path

from alice_skill.config import Settings
from tools import db_migrate


class FakeCursor:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def execute(self, sql: str) -> None:
        self._log.append(sql)


class FakeConnection:
    def __init__(self, log: list[str]) -> None:
        self._log = log
        self.commits = 0
        self.closed = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._log)

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = 1


def _settings() -> Settings:
    return Settings(
        pg_host="203.0.113.10",
        pg_port=5432,
        pg_database="alice_skill",
        pg_user="alice_skill",
        pg_password="s3cret",
    )


def test_migration_files_are_sorted(tmp_path: Path) -> None:
    (tmp_path / "003_penalties.sql").write_text("-- 3", encoding="utf-8")
    (tmp_path / "001_init.sql").write_text("-- 1", encoding="utf-8")
    (tmp_path / "002_seed.sql").write_text("-- 2", encoding="utf-8")
    (tmp_path / "readme.md").write_text("не миграция", encoding="utf-8")

    assert [path.name for path in db_migrate.migration_files(tmp_path)] == [
        "001_init.sql",
        "002_seed.sql",
        "003_penalties.sql",
    ]


def test_apply_migrations_executes_files_in_order(tmp_path: Path) -> None:
    (tmp_path / "001_init.sql").write_text("-- 1", encoding="utf-8")
    (tmp_path / "002_seed.sql").write_text("-- 2", encoding="utf-8")
    log: list[str] = []
    connection = FakeConnection(log)

    applied = db_migrate.apply_migrations(
        _settings(),
        tmp_path,
        connection_factory=lambda **params: connection,
    )

    assert applied == ["001_init.sql", "002_seed.sql"]
    assert log == ["-- 1", "-- 2"]
    assert connection.commits == 2
    assert connection.closed == 1


def test_main_reports_config_error(monkeypatch, capsys) -> None:
    from alice_skill.config import ConfigError

    def raise_config_error() -> Settings:
        raise ConfigError("Не заданы переменные окружения: PG_HOST")

    monkeypatch.setattr(db_migrate, "load_env_from_file", lambda path: None)
    monkeypatch.setattr(db_migrate, "load_settings", raise_config_error)

    assert db_migrate.main([]) == 2
    assert "ОШИБКА конфигурации" in capsys.readouterr().out


def test_main_reports_connection_error(monkeypatch, capsys) -> None:
    def fail(**params: object) -> None:
        raise RuntimeError("connection refused")

    monkeypatch.setattr(db_migrate, "load_env_from_file", lambda path: None)
    monkeypatch.setattr(db_migrate, "load_settings", _settings)
    monkeypatch.setattr(db_migrate.psycopg2, "connect", fail)

    assert db_migrate.main([]) == 1
    output = capsys.readouterr().out
    assert "ОШИБКА применения миграций" in output
    assert "s3cret" not in output
