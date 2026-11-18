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
    CLAIM_CREATED,
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
    Redemption,
    Reward,
    Task,
)
from alice_skill.repository import (
    CANCEL_REDEMPTION,
    CLAIM_ASSIGNMENT,
    CONFIRM_ASSIGNMENT,
    CONFIRM_PENALTY,
    COUNT_RECENT_PENALTIES,
    CREATE_MISSED_PENALTIES,
    DELETE_GOAL,
    DuplicateTitleError,
    INSERT_ASSIGNMENT,
    INSERT_OPTIONAL_ASSIGNMENT,
    INSERT_PENALTY,
    INSERT_PENALTY_LEDGER,
    INSERT_REDEEM_LEDGER,
    INSERT_REDEMPTION,
    INSERT_REFUND_LEDGER,
    INSERT_REWARD,
    INSERT_TASK,
    ISSUE_REDEMPTION,
    LINK_PENALTY_LEDGER,
    PostgresSkillRepository,
    REJECT_ASSIGNMENT,
    REJECT_PENALTY,
    SELECT_ALL_REWARDS,
    SELECT_ALL_TASKS,
    SELECT_ASSIGNMENT_STATUS,
    SELECT_ASSIGNMENT_STATUS_BY_TASK,
    SELECT_BALANCE,
    SELECT_DAILY_TASKS,
    SELECT_GOAL,
    SELECT_LEDGER,
    SELECT_OPTIONAL_TASKS,
    SELECT_PENALTIES,
    SELECT_PENDING_ASSIGNMENTS,
    SELECT_PLAN,
    SELECT_RANDOM_TASKS,
    SELECT_REDEMPTIONS,
    SELECT_REWARD,
    SELECT_REWARDS,
    SELECT_USERS,
    UPDATE_REWARD,
    UPDATE_TASK,
    UPSERT_GOAL,
)

TODAY = dt.date(2026, 11, 15)


class FakeCursor:
    """Курсор с заранее заданными ответами: `{sql: [ответ, ответ, ...]}`."""

    def __init__(
        self,
        script: dict[str, list[list[tuple[Any, ...]]]],
        errors: dict[str, BaseException] | None = None,
    ) -> None:
        self._script = {key: list(values) for key, values in script.items()}
        self._errors = errors or {}
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self._rows: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.executed.append((sql, params))
        error = self._errors.get(sql)
        if error is not None:
            raise error
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
        errors: dict[str, BaseException] | None = None,
    ) -> None:
        self._script = script or {}
        self._errors = errors or {}
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
        cursor = FakeCursor(self._script, self._errors)
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
    database = FakeDatabase({SELECT_REWARDS: [[(1, "Мороженое", 25), (2, "Игра", 70)]]})

    rewards = _repository(database).list_rewards()

    assert rewards == [Reward(1, "Мороженое", 25), Reward(2, "Игра", 70)]


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
            CREATE_MISSED_PENALTIES: [[]],
            SELECT_PLAN: [[], [(11, "Зарядка", "daily", 10, "pending")]],
            SELECT_DAILY_TASKS: [[(1, "Зарядка", "daily", 10, None)]],
            SELECT_RANDOM_TASKS: [
                [(2, "Погулять", "random", 15, None), (3, "Поделка", "random", 15, None)]
            ],
        }
    )

    assignments = _repository(database).ensure_daily_plan("user-1", TODAY)

    assert assignments == [
        Assignment(id=11, title="Зарядка", points=10, status="pending", kind="daily")
    ]
    weekday = (TODAY.isoweekday(),)
    assert _executed(database, SELECT_DAILY_TASKS) == [weekday]
    assert _executed(database, SELECT_RANDOM_TASKS) == [weekday]
    inserts = _executed(database, INSERT_ASSIGNMENT)
    assert len(inserts) == 1 + economy.RANDOM_TASKS_PER_DAY
    assert inserts[0] == ("user-1", TODAY, 1, "Зарядка", "daily", 10)
    assert database.locks == ["user-1"]


def test_ensure_daily_plan_creates_missed_penalty_requests_first() -> None:
    database = FakeDatabase(
        {
            CREATE_MISSED_PENALTIES: [[]],
            SELECT_PLAN: [[(11, "Зарядка", "daily", 10, "missed")]],
        }
    )

    _repository(database).ensure_daily_plan("user-1", TODAY)

    assert _executed(database, CREATE_MISSED_PENALTIES) == [("user-1", TODAY, "user-1")]
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
            SELECT_REWARD: [[(1, "Мороженое", 25)]],
            SELECT_BALANCE: [[(30,)]],
            INSERT_REDEMPTION: [[(77,)]],
        }
    )

    outcome = _repository(database).redeem_reward("user-1", 1)

    assert outcome.status == REDEEM_OK
    assert outcome.balance == 5
    assert outcome.redemption_id == 77
    assert _executed(database, INSERT_REDEEM_LEDGER) == [("user-1", -25, 77)]
    assert _executed(database, DELETE_GOAL) == [("user-1", 1)]
    assert database.locks == ["user-1"]


def test_redeem_reward_reports_missing_points() -> None:
    database = FakeDatabase(
        {
            SELECT_REWARD: [[(2, "Настольная игра", 70)]],
            SELECT_BALANCE: [[(30,)]],
        }
    )

    outcome = _repository(database).redeem_reward("user-1", 2)

    assert outcome.status == REDEEM_INSUFFICIENT
    assert outcome.balance == 30
    assert outcome.missing == 40
    assert _executed(database, INSERT_REDEMPTION) == []


def test_redeem_reward_returns_not_found_for_unknown_reward() -> None:
    database = FakeDatabase({SELECT_REWARD: [[]], SELECT_BALANCE: [[(30,)]]})

    outcome = _repository(database).redeem_reward("user-1", 99)

    assert outcome.status == REDEEM_NOT_FOUND
    assert outcome.reward is None


def test_list_redemptions_maps_rows() -> None:
    created_at = dt.datetime(2026, 11, 18, 12, 0)
    resolved_at = dt.datetime(2026, 11, 18, 13, 0)
    database = FakeDatabase(
        {
            SELECT_REDEMPTIONS: [
                [
                    (
                        3,
                        "user-1",
                        "Мороженое",
                        25,
                        "issued",
                        created_at,
                        resolved_at,
                        "admin",
                    )
                ]
            ]
        }
    )

    redemptions = _repository(database).list_redemptions(
        user_id="user-1", status="issued"
    )

    assert redemptions == [
        Redemption(
            id=3,
            user_id="user-1",
            title="Мороженое",
            cost=25,
            status="issued",
            created_at=created_at,
            resolved_at=resolved_at,
            resolved_by="admin",
        )
    ]
    assert _executed(database, SELECT_REDEMPTIONS) == [
        ("user-1", "user-1", "issued", "issued", 50)
    ]


def test_issue_redemption_marks_request_as_issued() -> None:
    database = FakeDatabase({ISSUE_REDEMPTION: [[(3,)]]})

    assert _repository(database).issue_redemption(3) is True
    assert _executed(database, ISSUE_REDEMPTION) == [("admin", 3)]
    assert _executed(database, INSERT_REFUND_LEDGER) == []


def test_issue_redemption_returns_false_for_resolved_request() -> None:
    database = FakeDatabase({ISSUE_REDEMPTION: [[]]})

    assert _repository(database).issue_redemption(3) is False
    assert _executed(database, INSERT_REFUND_LEDGER) == []


def test_cancel_redemption_refunds_points() -> None:
    database = FakeDatabase({CANCEL_REDEMPTION: [[(3, "user-1", 25)]]})

    assert _repository(database).cancel_redemption(3) is True
    assert _executed(database, CANCEL_REDEMPTION) == [("admin", 3)]
    assert _executed(database, INSERT_REFUND_LEDGER) == [("user-1", 25, 3)]


def test_cancel_redemption_does_not_refund_twice() -> None:
    database = FakeDatabase({CANCEL_REDEMPTION: [[]]})

    assert _repository(database).cancel_redemption(3) is False
    assert _executed(database, INSERT_REFUND_LEDGER) == []


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
    assert result.max_points == 10
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
            CONFIRM_PENALTY: [[(7, "user-1", 10, "не выключил свет", 3)]],
            INSERT_PENALTY_LEDGER: [[(99,)]],
        }
    )

    assert _repository(database).confirm_penalty(7) is True

    assert _executed(database, INSERT_PENALTY_LEDGER) == [
        ("user-1", -3, "не выключил свет")
    ], "списываем только остаток, а не всю сумму штрафа"
    assert _executed(database, LINK_PENALTY_LEDGER) == [(99, 7)]


def test_confirm_penalty_with_zero_balance_writes_nothing() -> None:
    database = FakeDatabase({CONFIRM_PENALTY: [[(7, "user-1", 10, "шум", 0)]]})

    assert _repository(database).confirm_penalty(7) is True

    assert _executed(database, INSERT_PENALTY_LEDGER) == []
    assert _executed(database, LINK_PENALTY_LEDGER) == []


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
                [
                    (
                        7,
                        "user-1",
                        10,
                        "шум",
                        "alice",
                        "awaiting_confirmation",
                        created_at,
                        None,
                    )
                ]
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
        {SELECT_PENDING_ASSIGNMENTS: [[(3, "user-1", TODAY, "Зарядка", 10, "optional")]]}
    )

    assignments = _repository(database).list_pending_assignments()

    assert assignments == [
        PendingAssignment(
            id=3,
            user_id="user-1",
            plan_date=TODAY,
            title="Зарядка",
            points=10,
            kind="optional",
        )
    ]


def test_list_users_returns_identifiers() -> None:
    database = FakeDatabase({SELECT_USERS: [[("kid-1",), ("kid-2",)]]})

    assert _repository(database).list_users() == ["kid-1", "kid-2"]


# --- справочник задач и наград ---


def test_list_tasks_includes_inactive_tasks() -> None:
    database = FakeDatabase(
        {
            SELECT_ALL_TASKS: [
                [
                    (1, "Зарядка", "daily", 10, True, None),
                    (2, "Помыть посуду", "optional", 5, False, [1, 3]),
                ]
            ]
        }
    )

    tasks = _repository(database).list_tasks()

    assert tasks == [
        Task(id=1, title="Зарядка", kind="daily", points=10),
        Task(
            id=2,
            title="Помыть посуду",
            kind="optional",
            points=5,
            is_active=False,
            weekdays=(1, 3),
        ),
    ]


def test_list_optional_tasks_uses_optional_query() -> None:
    database = FakeDatabase(
        {SELECT_OPTIONAL_TASKS: [[(7, "Полить цветы", "optional", 5, [2])]]}
    )

    tasks = _repository(database).list_optional_tasks()

    assert tasks == [
        Task(id=7, title="Полить цветы", kind="optional", points=5, weekdays=(2,))
    ]
    assert _executed(database, SELECT_OPTIONAL_TASKS) == [(None, None)]


def test_list_optional_tasks_filters_by_weekday() -> None:
    database = FakeDatabase({SELECT_OPTIONAL_TASKS: [[]]})

    _repository(database).list_optional_tasks(TODAY)

    assert _executed(database, SELECT_OPTIONAL_TASKS) == [
        (TODAY.isoweekday(), TODAY.isoweekday())
    ]


def test_create_task_normalizes_title_and_returns_row() -> None:
    database = FakeDatabase(
        {INSERT_TASK: [[(5, "Помыть посуду", "daily", 10, True, None)]]}
    )

    task = _repository(database).create_task("  Помыть   посуду ", "daily", 10)

    assert task == Task(id=5, title="Помыть посуду", kind="daily", points=10)
    assert _executed(database, INSERT_TASK) == [("Помыть посуду", "daily", 10, [])]


def test_create_task_saves_weekdays() -> None:
    database = FakeDatabase(
        {INSERT_TASK: [[(5, "Полить цветы", "daily", 1, True, [1, 3])]]}
    )

    task = _repository(database).create_task(
        "Полить цветы",
        "daily",
        1,
        weekdays=(3, 1, 1),
    )

    assert task.weekdays == (1, 3)
    assert _executed(database, INSERT_TASK) == [("Полить цветы", "daily", 1, [1, 3])]


def test_create_task_rejects_duplicate_title() -> None:
    database = FakeDatabase(errors={INSERT_TASK: psycopg2.errors.UniqueViolation("dup")})

    with pytest.raises(DuplicateTitleError):
        _repository(database).create_task("Зарядка", "daily", 10)


@pytest.mark.parametrize(
    ("title", "kind", "points"),
    [
        ("", "daily", 10),
        ("Задача", "weekly", 10),
        ("Задача", "daily", 0),
        ("Задача", "daily", 101),
    ],
)
def test_create_task_validates_input(title: str, kind: str, points: int) -> None:
    database = FakeDatabase()

    with pytest.raises(ValueError):
        _repository(database).create_task(title, kind, points)

    assert database.cursors == [], "невалидные данные не должны доходить до SQL"


def test_update_task_returns_none_for_unknown_id() -> None:
    database = FakeDatabase({UPDATE_TASK: [[]]})

    updated = _repository(database).update_task(
        99,
        title="Зарядка",
        kind="daily",
        points=10,
        is_active=False,
    )

    assert updated is None
    assert _executed(database, UPDATE_TASK) == [("Зарядка", "daily", 10, False, [], 99)]


def test_update_task_changes_weekdays() -> None:
    database = FakeDatabase(
        {UPDATE_TASK: [[(1, "Зарядка", "daily", 10, True, [2, 4])]]}
    )

    updated = _repository(database).update_task(
        1,
        title="Зарядка",
        kind="daily",
        points=10,
        is_active=True,
        weekdays=[4, 2],
    )

    assert updated == Task(
        id=1,
        title="Зарядка",
        kind="daily",
        points=10,
        weekdays=(2, 4),
    )
    assert _executed(database, UPDATE_TASK) == [
        ("Зарядка", "daily", 10, True, [2, 4], 1)
    ]


def test_claim_optional_task_creates_assignment() -> None:
    database = FakeDatabase({INSERT_OPTIONAL_ASSIGNMENT: [[("awaiting_confirmation",)]]})
    task = Task(id=7, title="Полить цветы", kind="optional", points=5)

    status = _repository(database).claim_optional_task("user-1", TODAY, task)

    assert status == CLAIM_CREATED
    assert _executed(database, INSERT_OPTIONAL_ASSIGNMENT) == [
        ("user-1", TODAY, 7, "Полить цветы", 5)
    ]


def test_claim_optional_task_returns_existing_status() -> None:
    database = FakeDatabase(
        {
            INSERT_OPTIONAL_ASSIGNMENT: [[]],
            SELECT_ASSIGNMENT_STATUS_BY_TASK: [[("done",)]],
        }
    )
    task = Task(id=7, title="Полить цветы", kind="optional", points=5)

    assert _repository(database).claim_optional_task("user-1", TODAY, task) == "done"


def test_optional_tasks_are_not_penalized_in_sql() -> None:
    # Дополнительные задачи не штрафуются и не попадают в план дня: условия
    # живут в самом SQL, чтобы их нельзя было обойти вызовом репозитория.
    assert "kind <> 'optional'" in REJECT_ASSIGNMENT
    assert "kind <> 'optional'" in CREATE_MISSED_PENALTIES
    assert "kind <> 'optional'" in SELECT_PLAN


def test_missed_tasks_create_penalty_requests_without_deduction() -> None:
    # Пропущенная задача сама баллы не списывает: создаётся заявка на штраф,
    # а журнал пополняется только после подтверждения взрослым.
    assert "INSERT INTO penalties" in CREATE_MISSED_PENALTIES
    assert "'auto'" in CREATE_MISSED_PENALTIES
    assert "points_ledger" not in CREATE_MISSED_PENALTIES


def test_deductions_are_capped_by_balance_in_sql() -> None:
    # Баланс не может уйти в минус: каждое списание ограничено остатком.
    assert "LEAST(r.points, GREATEST(COALESCE(b.amount, 0), 0))" in REJECT_ASSIGNMENT
    assert "charged_points = LEAST(" in CONFIRM_PENALTY


def test_weekday_schedule_is_filtered_in_sql() -> None:
    # Расписание по дням недели учитывается уже в выборке задач для плана.
    for query in (SELECT_DAILY_TASKS, SELECT_RANDOM_TASKS, SELECT_OPTIONAL_TASKS):
        assert "ANY(weekdays)" in query


def test_list_all_rewards_includes_inactive() -> None:
    database = FakeDatabase(
        {SELECT_ALL_REWARDS: [[(1, "Мороженое", 25, True), (2, "Кино", 40, False)]]}
    )

    assert _repository(database).list_all_rewards() == [
        Reward(id=1, title="Мороженое", cost=25),
        Reward(id=2, title="Кино", cost=40, is_active=False),
    ]


def test_create_reward_normalizes_title_and_returns_row() -> None:
    database = FakeDatabase({INSERT_REWARD: [[(3, "Кино", 40, True)]]})

    reward = _repository(database).create_reward("  Кино ", 40)

    assert reward == Reward(id=3, title="Кино", cost=40)
    assert _executed(database, INSERT_REWARD) == [("Кино", 40)]


def test_update_reward_returns_none_for_unknown_id() -> None:
    database = FakeDatabase({UPDATE_REWARD: [[]]})

    updated = _repository(database).update_reward(9, title="Кино", cost=40, is_active=True)

    assert updated is None
    assert _executed(database, UPDATE_REWARD) == [("Кино", 40, True, 9)]


