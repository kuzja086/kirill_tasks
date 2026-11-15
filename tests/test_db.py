"""Тесты обёртки соединения: транзакции, advisory-блокировка, reset."""

from __future__ import annotations

from typing import Any

import pytest

from alice_skill import db as db_module
from alice_skill.config import Settings


class FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.executed.append((sql, params))


class FakeConnection:
    def __init__(self) -> None:
        self.closed = 0
        self.commits = 0
        self.rollbacks = 0
        self.cursor_obj = FakeCursor()

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

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


def test_transaction_commits_on_success(monkeypatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(db_module.psycopg2, "connect", lambda **params: connection)
    database = db_module.Database(_settings())

    with database.transaction() as cursor:
        cursor.execute("SELECT 1")

    assert connection.commits == 1
    assert connection.rollbacks == 0


def test_transaction_rolls_back_on_error(monkeypatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(db_module.psycopg2, "connect", lambda **params: connection)
    database = db_module.Database(_settings())

    with pytest.raises(RuntimeError):
        with database.transaction():
            raise RuntimeError("ошибка в операции")

    assert connection.rollbacks == 1
    assert connection.commits == 0


def test_transaction_takes_advisory_lock(monkeypatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(db_module.psycopg2, "connect", lambda **params: connection)
    database = db_module.Database(_settings())

    with database.transaction(lock_user="user-1"):
        pass

    assert connection.cursor_obj.executed[0] == (db_module.USER_LOCK_SQL, ("user-1",))


def test_connection_is_reused_between_transactions(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    connection = FakeConnection()

    def fake_connect(**params: Any) -> FakeConnection:
        calls.append(params)
        return connection

    monkeypatch.setattr(db_module.psycopg2, "connect", fake_connect)
    database = db_module.Database(_settings())

    with database.transaction():
        pass
    with database.transaction():
        pass

    assert len(calls) == 1
    assert calls[0] == _settings().connection_params


def test_reset_closes_connection_and_forces_reconnect(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_connect(**params: Any) -> FakeConnection:
        calls.append(params)
        return FakeConnection()

    monkeypatch.setattr(db_module.psycopg2, "connect", fake_connect)
    database = db_module.Database(_settings())

    with database.transaction():
        pass
    database.reset()
    with database.transaction():
        pass

    assert len(calls) == 2
