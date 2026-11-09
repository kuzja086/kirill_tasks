"""Тесты слоя доступа к данным: psycopg2 подменяется фейковым соединением."""

from __future__ import annotations

from typing import Any

import psycopg2
import pytest

from alice_skill import db
from alice_skill.config import Settings


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self._connection = connection
        self._row: Any = None

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def execute(self, query: str, params: tuple[Any, ...]) -> None:
        if self._connection.fail_on_execute:
            raise psycopg2.ProgrammingError("ошибка в запросе")
        self._connection.executed.append((query, params))
        self._row = self._connection.row

    def fetchone(self) -> Any:
        return self._row


class FakeConnection:
    def __init__(self, row: Any = None, fail_on_execute: bool = False) -> None:
        self.row = row
        self.fail_on_execute = fail_on_execute
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

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


def test_returns_none_for_unknown_user(monkeypatch) -> None:
    connection = FakeConnection(row=None)
    monkeypatch.setattr(db.psycopg2, "connect", lambda **params: connection)

    assert db.PostgresRepository(_settings()).get_user_name("user-1") is None


def test_returns_stored_name(monkeypatch) -> None:
    connection = FakeConnection(row=("Аня",))
    monkeypatch.setattr(db.psycopg2, "connect", lambda **params: connection)

    assert db.PostgresRepository(_settings()).get_user_name("user-1") == "Аня"


def test_save_user_name_upserts_and_commits(monkeypatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(db.psycopg2, "connect", lambda **params: connection)

    db.PostgresRepository(_settings()).save_user_name("user-1", "Аня")

    assert connection.executed == [(db.UPSERT_USER_NAME, ("user-1", "Аня"))]
    assert connection.commits == 1


def test_connection_is_reused_between_calls(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    connection = FakeConnection(row=("Аня",))

    def fake_connect(**params: Any) -> FakeConnection:
        calls.append(params)
        return connection

    monkeypatch.setattr(db.psycopg2, "connect", fake_connect)
    repository = db.PostgresRepository(_settings())

    repository.get_user_name("user-1")
    repository.get_user_name("user-1")

    assert len(calls) == 1
    assert calls[0] == _settings().connection_params


def test_retries_once_after_lost_connection(monkeypatch) -> None:
    attempts: list[dict[str, Any]] = []
    connection = FakeConnection(row=("Аня",))

    def fake_connect(**params: Any) -> FakeConnection:
        attempts.append(params)
        if len(attempts) == 1:
            raise psycopg2.OperationalError("server closed the connection unexpectedly")
        return connection

    monkeypatch.setattr(db.psycopg2, "connect", fake_connect)

    assert db.PostgresRepository(_settings()).get_user_name("user-1") == "Аня"
    assert len(attempts) == 2


def test_raises_when_connection_cannot_be_restored(monkeypatch) -> None:
    def fake_connect(**params: Any) -> FakeConnection:
        raise psycopg2.OperationalError("connection refused")

    monkeypatch.setattr(db.psycopg2, "connect", fake_connect)

    with pytest.raises(psycopg2.OperationalError):
        db.PostgresRepository(_settings()).get_user_name("user-1")


def test_rolls_back_on_query_error(monkeypatch) -> None:
    connection = FakeConnection(fail_on_execute=True)
    monkeypatch.setattr(db.psycopg2, "connect", lambda **params: connection)

    with pytest.raises(psycopg2.ProgrammingError):
        db.PostgresRepository(_settings()).save_user_name("user-1", "Аня")

    assert connection.rollbacks == 1
    assert connection.commits == 0


def test_close_releases_connection(monkeypatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(db.psycopg2, "connect", lambda **params: connection)
    repository = db.PostgresRepository(_settings())

    repository.get_user_name("user-1")
    repository.close()

    assert connection.closed == 1
