"""Тесты локальной песочницы: разбор .env, событие и вывод заявок."""

from __future__ import annotations

import datetime as dt

from alice_skill.config import Settings
from alice_skill.dialogue import INTENT_MY_POINTS, detect_intent
from alice_skill.models import AliceRequest
from tools import local


def test_parse_env_file_ignores_comments_and_blank_lines() -> None:
    raw = "# комментарий\n\nPG_HOST=127.0.0.1\nPG_PASSWORD=a=b\n# ещё\n"

    assert local.parse_env_file(raw) == {"PG_HOST": "127.0.0.1", "PG_PASSWORD": "a=b"}


def test_build_event_sets_command_and_tokens() -> None:
    event = local.build_event("я выполнил зарядку", user_id="kid")

    assert event["request"]["command"] == "я выполнил зарядку"
    assert event["request"]["nlu"]["tokens"] == ["я", "выполнил", "зарядку"]
    assert event["request"]["payload"] == {}
    assert event["session"]["user"]["user_id"] == "kid"


def test_build_event_allows_keyword_intent_detection() -> None:
    request = AliceRequest.from_event(local.build_event("сколько у меня баллов", user_id="kid"))

    assert detect_intent(request) == INTENT_MY_POINTS


def test_print_pending_without_rows(capsys) -> None:
    local.print_pending([])

    assert "нет" in capsys.readouterr().out.lower()


def test_print_pending_lists_assignments(capsys) -> None:
    local.print_pending([(7, dt.date(2026, 11, 15), "Зарядка", 10)])

    output = capsys.readouterr().out
    assert "#7" in output
    assert "Зарядка" in output
    assert "10 баллов" in output


def _settings() -> Settings:
    return Settings(
        pg_host="203.0.113.10",
        pg_port=5432,
        pg_database="alice_skill",
        pg_user="alice_skill",
        pg_password="s3cret",
    )


def test_db_check_reports_config_error(monkeypatch, capsys) -> None:
    from alice_skill.config import ConfigError
    from tools import db_check

    def raise_config_error() -> Settings:
        raise ConfigError("Не заданы переменные окружения: PG_HOST")

    monkeypatch.setattr(db_check, "load_env_from_file", lambda path: None)
    monkeypatch.setattr(db_check, "load_settings", raise_config_error)

    assert db_check.main() == 2
    assert "ОШИБКА конфигурации" in capsys.readouterr().out


def test_db_check_reports_connection_error(monkeypatch, capsys) -> None:
    import psycopg2

    from tools import db_check

    def fail_connect(**params: object) -> None:
        raise psycopg2.OperationalError("Connection refused")

    monkeypatch.setattr(db_check, "load_env_from_file", lambda path: None)
    monkeypatch.setattr(db_check, "load_settings", _settings)
    monkeypatch.setattr(db_check.psycopg2, "connect", fail_connect)

    assert db_check.main() == 1
    output = capsys.readouterr().out
    assert "203.0.113.10:5432" in output
    assert "ОШИБКА подключения" in output
    assert "s3cret" not in output


def test_db_check_reports_server_version(monkeypatch, capsys) -> None:
    from tools import db_check

    class FakeCursor:
        def __enter__(self) -> "FakeCursor":
            return self

        def __exit__(self, *exc_info: object) -> bool:
            return False

        def execute(self, sql: str) -> None:
            self.sql = sql

        def fetchone(self) -> tuple[str]:
            return ("PostgreSQL 16.4",)

    class FakeConnection:
        closed = 0

        def cursor(self) -> FakeCursor:
            return FakeCursor()

        def close(self) -> None:
            self.closed = 1

    monkeypatch.setattr(db_check, "load_env_from_file", lambda path: None)
    monkeypatch.setattr(db_check, "load_settings", _settings)
    monkeypatch.setattr(db_check.psycopg2, "connect", lambda **params: FakeConnection())

    assert db_check.main() == 0
    assert "OK: PostgreSQL 16.4" in capsys.readouterr().out

