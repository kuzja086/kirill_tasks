"""Тесты SQL-слоя: psycopg2 подменяется fake-базой со сценарием ответов."""

from __future__ import annotations

import contextlib
import datetime as dt
from typing import Any

import psycopg2
import pytest

from alice_skill import economy
from alice_skill.config import Settings
from alice_skill.models import (
    PENALTY_CREATED,
    PENALTY_INVALID,
    PENALTY_LIMIT_EXCEEDED,
    REDEEM_INSUFFICIENT,
    REDEEM_NOT_FOUND,
    REDEEM_OK,
    Assignment,
    LedgerEntry,
    Penalty,
    PendingAssignment,
    Reward,
)
from alice_skill.repository import (
    APPLY_MISSED_PENALTIES,
    CLAIM_ASSIGNMENT,
    CONFIRM_ASSIGNMENT,
    CONFIRM_PENALTY,
    COUNT_RECENT_PENALTIES,
    DELETE_GOAL,
    INSERT_ASSIGNMENT,
    INSERT_PENALTY,
    INSERT_PENALTY_LEDGER,
    INSERT_REDEEM_LEDGER,
    INSERT_REDEMPTION,
    LINK_PENALTY_LEDGER,
    PostgresSkillRepository,
    REJECT_ASSIGNMENT,
    REJECT_PENALTY,
    SELECT_ASSIGNMENT_STATUS,
    SELECT_BALANCE,
    SELECT_DAILY_TASKS,
    SELECT_GOAL,
    SELECT_LEDGER,
    SELECT_PENALTIES,
    SELECT_PENDING_ASSIGNMENTS,
    SELECT_PLAN,
    SELECT_RANDOM_TASKS,
    SELECT_REWARD,
    SELECT_REWARDS,
    SELECT_USERS,
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


def test_add_penalty_creates_request() -> None:
    created_at = dt.datetime(2026, 11, 15, 12, 0)
    database = FakeDatabase(
        {
            COUNT_RECENT_PENALTIES: [[(0,)]],
            INSERT_PENALTY: [
                [(7, "user-1", 10, "не выключил свет", "alice", "awaiting_confirmation", created_at)]
            ],
        }
    )

    result = _repository(database).add_penalty("user-1", 10, "не выключил свет")

    assert result.status == PENALTY_CREATED
    assert result.penalty == Penalty(
        id=7,
        user_id="user-1",
        points=10,
        comment="не выключил свет",
        source="alice",
        status="awaiting_confirmation",
        created_at=created_at,
    )
    assert _executed(database, INSERT_PENALTY) == [
        ("user-1", 10, "не выключил свет", "alice")
    ]


@pytest.mark.parametrize(
    ("points", "comment"),
    [(0, "причина"), (-5, "причина"), (101, "причина"), (10, "   ")],
)
def test_add_penalty_rejects_invalid_input(points: int, comment: str) -> None:
    database = FakeDatabase()

    result = _repository(database).add_penalty("user-1", points, comment)

    assert result.status == PENALTY_INVALID
    assert result.max_points == 100
    assert database.cursors[0].executed == []


def test_add_penalty_respects_daily_limit() -> None:
    database = FakeDatabase({COUNT_RECENT_PENALTIES: [[(5,)]]})

    result = _repository(database).add_penalty("user-1", 10, "шум")

    assert result.status == PENALTY_LIMIT_EXCEEDED
    assert result.daily_count == 5
    assert _executed(database, INSERT_PENALTY) == []


def test_confirm_penalty_writes_ledger_and_links_request() -> None:
    database = FakeDatabase(
        {
            CONFIRM_PENALTY: [[(7, "user-1", 10, "не выключил свет")]],
            INSERT_PENALTY_LEDGER: [[(99,)]],
        }
    )

    assert _repository(database).confirm_penalty(7) is True

    assert _executed(database, INSERT_PENALTY_LEDGER) == [("user-1", -10, "не выключил свет")]
    assert _executed(database, LINK_PENALTY_LEDGER) == [(99, 7)]


def test_confirm_penalty_returns_false_for_already_resolved() -> None:
    database = FakeDatabase({CONFIRM_PENALTY: [[]]})

    assert _repository(database).confirm_penalty(7) is False
    assert _executed(database, INSERT_PENALTY_LEDGER) == []


def test_reject_penalty_does_not_touch_ledger() -> None:
    database = FakeDatabase({REJECT_PENALTY: [[(7,)]]})

    assert _repository(database).reject_penalty(7) is True
    assert _executed(database, INSERT_PENALTY_LEDGER) == []


def test_list_penalties_maps_rows() -> None:
    created_at = dt.datetime(2026, 11, 15, 12, 0)
    database = FakeDatabase(
        {
            SELECT_PENALTIES: [
                [(7, "user-1", 10, "шум", "alice", "awaiting_confirmation", created_at)]
            ]
        }
    )

    penalties = _repository(database).list_penalties(user_id="user-1", status="awaiting_confirmation")

    assert penalties == [
        Penalty(
            id=7,
            user_id="user-1",
            points=10,
            comment="шум",
            source="alice",
            status="awaiting_confirmation",
            created_at=created_at,
        )
    ]
    assert _executed(database, SELECT_PENALTIES) == [
        ("user-1", "user-1", "awaiting_confirmation", "awaiting_confirmation", 50)
    ]


def test_list_ledger_maps_rows() -> None:
    created_at = dt.datetime(2026, 11, 15, 12, 0)
    database = FakeDatabase(
        {SELECT_LEDGER: [[(1, created_at, -10, "penalty", "шум", None)]]}
    )

    entries = _repository(database).list_ledger("user-1", limit=20)

    assert entries == [
        LedgerEntry(
            id=1,
            created_at=created_at,
            delta=-10,
            reason="penalty",
            comment="шум",
            details=None,
        )
    ]
    assert _executed(database, SELECT_LEDGER) == [("user-1", 20)]


def test_list_pending_assignments_maps_rows() -> None:
    database = FakeDatabase(
        {SELECT_PENDING_ASSIGNMENTS: [[(3, "user-1", TODAY, "Зарядка", 10)]]}
    )

    assignments = _repository(database).list_pending_assignments()

    assert assignments == [
        PendingAssignment(id=3, user_id="user-1", plan_date=TODAY, title="Зарядка", points=10)
    ]


def test_list_users_returns_identifiers() -> None:
    database = FakeDatabase({SELECT_USERS: [[("kid-1",), ("kid-2",)]]})

    assert _repository(database).list_users() == ["kid-1", "kid-2"]


