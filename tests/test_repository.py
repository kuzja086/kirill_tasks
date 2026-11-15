"""Тесты SQL-слоя: psycopg2 подменяется fake-базой со сценарием ответов."""

from __future__ import annotations

import contextlib
import datetime as dt
from typing import Any

import psycopg2
import pytest

from alice_skill import economy
from alice_skill.config import Settings
from alice_skill.models import REDEEM_INSUFFICIENT, REDEEM_NOT_FOUND, REDEEM_OK, Assignment, Reward
from alice_skill.repository import (
    APPLY_MISSED_PENALTIES,
    CLAIM_ASSIGNMENT,
    CONFIRM_ASSIGNMENT,
    DELETE_GOAL,
    INSERT_ASSIGNMENT,
    INSERT_REDEEM_LEDGER,
    INSERT_REDEMPTION,
    PostgresSkillRepository,
    REJECT_ASSIGNMENT,
    SELECT_ASSIGNMENT_STATUS,
    SELECT_BALANCE,
    SELECT_DAILY_TASKS,
    SELECT_GOAL,
    SELECT_PLAN,
    SELECT_RANDOM_TASKS,
    SELECT_REWARD,
    SELECT_REWARDS,
    UPSERT_GOAL,
)

TODAY = dt.date(2026, 11, 15)


class FakeCursor:
    """Курсор с заранее заданными ответами: `{sql: [ответ, ответ, ...]}`."""

    def __init__(self, script: dict[str, list[list[tuple[Any, ...]]]]) -> None:
        self._script = {key: list(values) for key, values in script.items()}
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self._rows: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.executed.append((sql, params))
        queue = self._script.get(sql, [])
        self._rows = queue.pop(0) if queue else []

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)


class FakeDatabase:
    """Подмена :class:`alice_skill.db.Database` с записью транзакций."""

    def __init__(
        self,
        script: dict[str, list[list[tuple[Any, ...]]]] | None = None,
        *,
        fail_times: int = 0,
    ) -> None:
        self._script = script or {}
        self.fail_times = fail_times
        self.cursors: list[FakeCursor] = []
        self.locks: list[str | None] = []
        self.resets = 0

    @contextlib.contextmanager
    def transaction(self, *, lock_user: str | None = None):
        self.locks.append(lock_user)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise psycopg2.OperationalError("server closed the connection unexpectedly")
        cursor = FakeCursor(self._script)
        self.cursors.append(cursor)
        yield cursor

    def reset(self) -> None:
        self.resets += 1


def _settings() -> Settings:
    return Settings(
        pg_host="203.0.113.10",
        pg_port=5432,
        pg_database="alice_skill",
        pg_user="alice_skill",
        pg_password="s3cret",
    )


def _repository(database: FakeDatabase) -> PostgresSkillRepository:
    return PostgresSkillRepository(_settings(), database=database)


def _executed(database: FakeDatabase, sql: str) -> list[tuple[Any, ...] | None]:
    return [params for executed_sql, params in database.cursors[0].executed if executed_sql == sql]


def test_get_balance_reads_ledger_sum() -> None:
    database = FakeDatabase({SELECT_BALANCE: [[(42,)]]})

    assert _repository(database).get_balance("user-1") == 42
    assert _executed(database, SELECT_BALANCE) == [("user-1",)]


def test_list_rewards_maps_rows() -> None:
    database = FakeDatabase({SELECT_REWARDS: [[(1, "Мороженое", 350), (2, "Игра", 970)]]})

    rewards = _repository(database).list_rewards()

    assert rewards == [Reward(1, "Мороженое", 350), Reward(2, "Игра", 970)]


def test_get_goal_returns_none_when_not_set() -> None:
    database = FakeDatabase({SELECT_GOAL: [[]]})

    assert _repository(database).get_goal("user-1") is None


def test_set_goal_upserts_row() -> None:
    database = FakeDatabase()

    _repository(database).set_goal("user-1", 2)

    assert _executed(database, UPSERT_GOAL) == [("user-1", 2)]


def test_ensure_daily_plan_creates_daily_and_random_tasks() -> None:
    database = FakeDatabase(
        {
            APPLY_MISSED_PENALTIES: [[]],
            SELECT_PLAN: [[], [(11, "Зарядка", 10, "pending")]],
            SELECT_DAILY_TASKS: [[(1, "Зарядка", "daily", 10)]],
            SELECT_RANDOM_TASKS: [
                [(2, "Погулять", "random", 15), (3, "Поделка", "random", 15)]
            ],
        }
    )

    assignments = _repository(database).ensure_daily_plan("user-1", TODAY)

    assert assignments == [Assignment(id=11, title="Зарядка", points=10, status="pending")]
    inserts = _executed(database, INSERT_ASSIGNMENT)
    assert len(inserts) == 1 + economy.RANDOM_TASKS_PER_DAY
    assert inserts[0] == ("user-1", TODAY, 1, "Зарядка", "daily", 10)
    assert database.locks == ["user-1"]


def test_ensure_daily_plan_applies_penalties_first() -> None:
    database = FakeDatabase(
        {
            APPLY_MISSED_PENALTIES: [[]],
            SELECT_PLAN: [[(11, "Зарядка", 10, "missed")]],
        }
    )

    _repository(database).ensure_daily_plan("user-1", TODAY)

    assert _executed(database, APPLY_MISSED_PENALTIES) == [("user-1", TODAY, "user-1")]
    assert _executed(database, INSERT_ASSIGNMENT) == []


def test_claim_assignment_moves_pending_task_to_confirmation() -> None:
    database = FakeDatabase({CLAIM_ASSIGNMENT: [[("awaiting_confirmation",)]]})

    assert _repository(database).claim_assignment(11) == "awaiting_confirmation"


def test_claim_assignment_returns_current_status_if_already_resolved() -> None:
    database = FakeDatabase(
        {CLAIM_ASSIGNMENT: [[]], SELECT_ASSIGNMENT_STATUS: [[("done",)]]}
    )

    assert _repository(database).claim_assignment(11) == "done"


def test_confirm_assignment_executes_query() -> None:
    database = FakeDatabase()

    _repository(database).confirm_assignment(11)

    assert _executed(database, CONFIRM_ASSIGNMENT) == [(11,)]


def test_reject_assignment_executes_query() -> None:
    database = FakeDatabase()

    _repository(database).reject_assignment(11)

    assert _executed(database, REJECT_ASSIGNMENT) == [(11,)]


def test_redeem_reward_spends_points_and_clears_goal() -> None:
    database = FakeDatabase(
        {
            SELECT_REWARD: [[(1, "Мороженое", 350)]],
            SELECT_BALANCE: [[(420,)]],
            INSERT_REDEMPTION: [[(77,)]],
        }
    )

    outcome = _repository(database).redeem_reward("user-1", 1)

    assert outcome.status == REDEEM_OK
    assert outcome.balance == 70
    assert outcome.redemption_id == 77
    assert _executed(database, INSERT_REDEEM_LEDGER) == [("user-1", -350, 77)]
    assert _executed(database, DELETE_GOAL) == [("user-1", 1)]
    assert database.locks == ["user-1"]


def test_redeem_reward_reports_missing_points() -> None:
    database = FakeDatabase(
        {
            SELECT_REWARD: [[(2, "Настольная игра", 970)]],
            SELECT_BALANCE: [[(420,)]],
        }
    )

    outcome = _repository(database).redeem_reward("user-1", 2)

    assert outcome.status == REDEEM_INSUFFICIENT
    assert outcome.balance == 420
    assert outcome.missing == 550
    assert _executed(database, INSERT_REDEMPTION) == []


def test_redeem_reward_returns_not_found_for_unknown_reward() -> None:
    database = FakeDatabase({SELECT_REWARD: [[]], SELECT_BALANCE: [[(420,)]]})

    outcome = _repository(database).redeem_reward("user-1", 99)

    assert outcome.status == REDEEM_NOT_FOUND
    assert outcome.reward is None


def test_operation_retries_once_after_connection_error() -> None:
    database = FakeDatabase(fail_times=1)

    assert _repository(database).list_rewards() == []
    assert database.resets == 1


def test_operation_raises_when_connection_cannot_be_restored() -> None:
    database = FakeDatabase(fail_times=2)

    with pytest.raises(psycopg2.OperationalError):
        _repository(database).list_rewards()

    assert database.resets == 2


