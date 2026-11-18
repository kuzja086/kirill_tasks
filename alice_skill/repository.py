"""Репозиторий навыка: задачи, дневной план, баллы, цели и награды.

Все операции выполняются в транзакции. Если соединение с Postgres потеряно
(простой, перезапуск сервера), операция повторяется один раз на новом
соединении.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Callable, Protocol, TypeVar, runtime_checkable

import psycopg2.extensions

from alice_skill import economy, plan
from alice_skill.config import Settings
from alice_skill.db import CONNECTION_ERRORS, Database
from alice_skill.models import (
    CLAIM_CREATED,
    PENALTY_CREATED,
    PENALTY_INVALID,
    PENALTY_LIMIT_EXCEEDED,
    REDEEM_INSUFFICIENT,
    REDEEM_NOT_FOUND,
    REDEEM_OK,
    SOURCE_ALICE,
    Assignment,
    LedgerEntry,
    Penalty,
    PenaltyResult,
    PendingAssignment,
    RedeemOutcome,
    Reward,
    Task,
    validate_reward_input,
    validate_task_input,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class DuplicateTitleError(ValueError):
    """Задача или награда с таким названием уже есть в справочнике."""

SELECT_BALANCE = "SELECT COALESCE(SUM(delta), 0) FROM points_ledger WHERE user_id = %s"

SELECT_REWARDS = "SELECT id, title, cost FROM rewards WHERE is_active ORDER BY cost, id"
SELECT_REWARD = "SELECT id, title, cost FROM rewards WHERE id = %s AND is_active"

# Справочник наград для админки: включает выключенные, чтобы их можно было вернуть.
SELECT_ALL_REWARDS = "SELECT id, title, cost, is_active FROM rewards ORDER BY cost, id"

INSERT_REWARD = """
    INSERT INTO rewards (title, cost)
    VALUES (%s, %s)
    RETURNING id, title, cost, is_active
"""

UPDATE_REWARD = """
    UPDATE rewards
       SET title = %s, cost = %s, is_active = %s
     WHERE id = %s
    RETURNING id, title, cost, is_active
"""

SELECT_GOAL = """
    SELECT r.id, r.title, r.cost
      FROM user_goals g
      JOIN rewards r ON r.id = g.reward_id
     WHERE g.user_id = %s AND r.is_active
"""

UPSERT_GOAL = """
    INSERT INTO user_goals (user_id, reward_id)
    VALUES (%s, %s)
    ON CONFLICT (user_id) DO UPDATE
       SET reward_id = EXCLUDED.reward_id,
           created_at = now()
"""

DELETE_GOAL = "DELETE FROM user_goals WHERE user_id = %s AND reward_id = %s"
# Пропущенные задачи не списывают баллы сами: в начале нового дня за каждую
# создаётся заявка на штраф (source = 'auto'), а списание происходит только
# после подтверждения взрослым — как и у штрафа, сказанного голосом.
CREATE_MISSED_PENALTIES = """
    WITH missed AS (
        UPDATE daily_assignments
           SET status = 'missed', resolved_at = now()
         WHERE user_id = %s
           AND plan_date < %s
           AND status = 'pending'
           AND kind <> 'optional'
        RETURNING id, title, points
    )
    INSERT INTO penalties (user_id, points, comment, source, assignment_id)
    SELECT %s, points, 'Не выполнено: ' || title, 'auto', id
      FROM missed
    ON CONFLICT DO NOTHING
"""

SELECT_PLAN = """
    SELECT id, title, kind, points, status
      FROM daily_assignments
     WHERE user_id = %s AND plan_date = %s
       AND kind <> 'optional'
     ORDER BY CASE kind WHEN 'daily' THEN 0 ELSE 1 END, id
"""

SELECT_DAILY_TASKS = """
    SELECT id, title, kind, points
      FROM tasks
     WHERE is_active AND kind = 'daily'
     ORDER BY id
"""

SELECT_RANDOM_TASKS = """
    SELECT id, title, kind, points
      FROM tasks
     WHERE is_active AND kind = 'random'
     ORDER BY id
"""

SELECT_OPTIONAL_TASKS = """
    SELECT id, title, kind, points
      FROM tasks
     WHERE is_active AND kind = 'optional'
     ORDER BY id
"""

SELECT_ALL_TASKS = """
    SELECT id, title, kind, points, is_active
      FROM tasks
     ORDER BY CASE kind WHEN 'daily' THEN 0 WHEN 'random' THEN 1 ELSE 2 END,
              lower(title),
              id
"""

INSERT_TASK = """
    INSERT INTO tasks (title, kind, points)
    VALUES (%s, %s, %s)
    RETURNING id, title, kind, points, is_active
"""

UPDATE_TASK = """
    UPDATE tasks
       SET title = %s, kind = %s, points = %s, is_active = %s
     WHERE id = %s
    RETURNING id, title, kind, points, is_active
"""

# Дополнительная задача: assignment создаётся сразу «ждёт подтверждения»,
# чтобы за невыполнение не начислялся штраф (в плане её нет).
INSERT_OPTIONAL_ASSIGNMENT = """
    INSERT INTO daily_assignments
           (user_id, plan_date, task_id, title, kind, points, status, claimed_at)
    VALUES (%s, %s, %s, %s, 'optional', %s, 'awaiting_confirmation', now())
    ON CONFLICT (user_id, plan_date, task_id) DO NOTHING
    RETURNING status
"""

SELECT_ASSIGNMENT_STATUS_BY_TASK = """
    SELECT status
      FROM daily_assignments
     WHERE user_id = %s AND plan_date = %s AND task_id = %s
"""

INSERT_ASSIGNMENT = """
    INSERT INTO daily_assignments (user_id, plan_date, task_id, title, kind, points)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (user_id, plan_date, task_id) DO NOTHING
"""

CLAIM_ASSIGNMENT = """
    UPDATE daily_assignments
       SET status = 'awaiting_confirmation', claimed_at = now()
     WHERE id = %s AND status = 'pending'
    RETURNING status
"""

SELECT_ASSIGNMENT_STATUS = "SELECT status FROM daily_assignments WHERE id = %s"
CONFIRM_ASSIGNMENT = """
    WITH done AS (
        UPDATE daily_assignments
           SET status = 'done', resolved_at = now()
         WHERE id = %s AND status = 'awaiting_confirmation'
        RETURNING id, user_id, points
    )
    INSERT INTO points_ledger (user_id, delta, reason, assignment_id)
    SELECT user_id, points, 'task_done', id FROM done
    ON CONFLICT (assignment_id, reason) DO NOTHING
"""

REJECT_ASSIGNMENT = """
    WITH rejected AS (
        UPDATE daily_assignments
           SET status = 'missed', resolved_at = now()
         WHERE id = %s AND status = 'awaiting_confirmation'
        RETURNING id, user_id, points, kind
    ),
    charged AS (
        SELECT r.id, r.user_id,
               LEAST(r.points, GREATEST(COALESCE(b.amount, 0), 0)) AS points
          FROM rejected r
          LEFT JOIN LATERAL (
              SELECT SUM(delta) AS amount
                FROM points_ledger
               WHERE user_id = r.user_id
          ) b ON TRUE
         WHERE r.kind <> 'optional'
    )
    INSERT INTO points_ledger (user_id, delta, reason, assignment_id)
    SELECT user_id, -points, 'task_missed', id
      FROM charged
     WHERE points > 0
    ON CONFLICT (assignment_id, reason) DO NOTHING
"""

INSERT_REDEMPTION = """
    INSERT INTO reward_redemptions (user_id, reward_id, title, cost)
    VALUES (%s, %s, %s, %s)
    RETURNING id
"""

INSERT_REDEEM_LEDGER = """
    INSERT INTO points_ledger (user_id, delta, reason, reward_redemption_id)
    VALUES (%s, %s, 'reward_redeem', %s)
"""
# --- SQL-КОНСТАНТЫ-ШТРАФОВ ---

COUNT_RECENT_PENALTIES = """
    SELECT count(*)
      FROM penalties
     WHERE user_id = %s
       AND source = 'alice'
       AND created_at >= now() - interval '1 day'
"""

INSERT_PENALTY = """
    INSERT INTO penalties (user_id, points, comment, source)
    VALUES (%s, %s, %s, %s)
    RETURNING id, user_id, points, comment, source, status, created_at
"""

SELECT_PENALTIES = """
    SELECT id, user_id, points, comment, source, status, created_at,
           charged_points
      FROM penalties
     WHERE (%s::text IS NULL OR user_id = %s)
       AND (%s::text IS NULL OR status = %s)
     ORDER BY created_at DESC, id DESC
     LIMIT %s
"""

# Баланс не может уйти в минус: списываем не больше того, что накоплено.
CONFIRM_PENALTY = """
    UPDATE penalties AS p
       SET status = 'applied',
           resolved_at = now(),
           resolved_by = %s,
           charged_points = LEAST(
               p.points,
               GREATEST(
                   COALESCE(
                       (SELECT SUM(delta)
                          FROM points_ledger
                         WHERE user_id = p.user_id),
                       0
                   ),
                   0
               )
           )
     WHERE p.id = %s AND p.status = 'awaiting_confirmation'
    RETURNING id, user_id, points, comment, charged_points
"""

REJECT_PENALTY = """
    UPDATE penalties
       SET status = 'rejected', resolved_at = now(), resolved_by = %s
     WHERE id = %s AND status = 'awaiting_confirmation'
    RETURNING id
"""

INSERT_PENALTY_LEDGER = """
    INSERT INTO points_ledger (user_id, delta, reason, comment)
    VALUES (%s, %s, 'penalty', %s)
    RETURNING id
"""

LINK_PENALTY_LEDGER = "UPDATE penalties SET ledger_id = %s WHERE id = %s"

SELECT_LEDGER = """
    SELECT l.id, l.created_at, l.delta, l.reason, l.comment,
           COALESCE(a.title, r.title) AS details
      FROM points_ledger l
      LEFT JOIN daily_assignments a ON a.id = l.assignment_id
      LEFT JOIN reward_redemptions r ON r.id = l.reward_redemption_id
     WHERE l.user_id = %s
     ORDER BY l.created_at DESC, l.id DESC
     LIMIT %s
"""

SELECT_PENDING_ASSIGNMENTS = """
    SELECT id, user_id, plan_date, title, points, kind
      FROM daily_assignments
     WHERE status = 'awaiting_confirmation'
     ORDER BY plan_date, id
"""

SELECT_USERS = """
    SELECT user_id
      FROM (
            SELECT user_id FROM daily_assignments
            UNION SELECT user_id FROM points_ledger
            UNION SELECT user_id FROM penalties
            UNION SELECT user_id FROM user_goals
           ) AS known
     ORDER BY user_id
"""
# --- ПРОТОКОЛ ---


@runtime_checkable
class SkillRepository(Protocol):
    """Интерфейс хранилища навыка: позволяет подменять Postgres в тестах."""

    def ensure_daily_plan(self, user_id: str, plan_date: dt.date) -> list[Assignment]:
        """Возвращает план на дату, создавая его при первом обращении."""

    def get_balance(self, user_id: str) -> int:
        """Текущий баланс баллов; никогда не бывает отрицательным."""

    def list_rewards(self) -> list[Reward]:
        """Активные награды, от дешёвых к дорогим."""

    def list_all_rewards(self) -> list[Reward]:
        """Все награды, включая выключенные (для админки)."""

    def create_reward(self, title: str, cost: int) -> Reward:
        """Добавляет награду.

        :raises ValueError: если данные не проходят проверку.
        :raises DuplicateTitleError: если награда с таким названием уже есть.
        """

    def update_reward(
        self,
        reward_id: int,
        *,
        title: str,
        cost: int,
        is_active: bool,
    ) -> Reward | None:
        """Меняет название, стоимость и видимость награды.

        Возвращает ``None``, если награды с таким id нет.
        """

    def get_goal(self, user_id: str) -> Reward | None:
        """Выбранная ребёнком цель или ``None``."""

    def set_goal(self, user_id: str, reward_id: int) -> None:
        """Запоминает награду как цель."""

    def redeem_reward(self, user_id: str, reward_id: int) -> RedeemOutcome:
        """Списывает баллы за награду, если их хватает."""

    def claim_assignment(self, assignment_id: int) -> str | None:
        """Переводит задачу в ожидание подтверждения и возвращает её статус."""

    def list_tasks(self) -> list[Task]:
        """Весь справочник задач, включая выключенные (для админки)."""

    def list_optional_tasks(self) -> list[Task]:
        """Дополнительные задачи: доступны по желанию, без штрафа за пропуск."""

    def create_task(self, title: str, kind: str, points: int) -> Task:
        """Добавляет задачу.

        :raises ValueError: если данные не проходят проверку.
        :raises DuplicateTitleError: если такая задача уже есть.
        """

    def update_task(
        self,
        task_id: int,
        *,
        title: str,
        kind: str,
        points: int,
        is_active: bool,
    ) -> Task | None:
        """Меняет название, вид, стоимость и видимость задачи.

        Возвращает ``None``, если задачи с таким id нет.
        """

    def claim_optional_task(
        self,
        user_id: str,
        plan_date: dt.date,
        task: Task,
    ) -> str | None:
        """Создаёт заявку на дополнительную задачу и возвращает её статус."""

    def add_penalty(
        self,
        user_id: str,
        points: int,
        comment: str,
        *,
        source: str = SOURCE_ALICE,
    ) -> PenaltyResult:
        """Создаёт заявку на штраф; баллы списываются только после подтверждения."""

    def confirm_penalty(self, penalty_id: int, *, resolved_by: str = "admin") -> bool:
        """Подтверждает штраф: списывает баллы (не больше остатка) и пишет причину в журнал."""

    def reject_penalty(self, penalty_id: int, *, resolved_by: str = "admin") -> bool:
        """Отклоняет заявку на штраф: баллы не меняются."""

    def list_penalties(
        self,
        *,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Penalty]:
        """Заявки на штраф, свежие сверху."""

    def list_ledger(self, user_id: str, *, limit: int = 50) -> list[LedgerEntry]:
        """История начислений и списаний с причинами."""

    def list_pending_assignments(self) -> list[PendingAssignment]:
        """Заявки на выполнение, ждущие подтверждения."""

    def list_users(self) -> list[str]:
        """Идентификаторы всех известных детей."""

class PostgresSkillRepository:
    """Реализация :class:`SkillRepository` поверх Postgres."""

    def __init__(self, settings: Settings, *, database: Database | None = None) -> None:
        self._settings = settings
        self._db = database if database is not None else Database(settings)

    # --- чтение ---

    def get_balance(self, user_id: str) -> int:
        return self._run(lambda cursor: self._select_balance(cursor, user_id))

    def list_rewards(self) -> list[Reward]:
        return self._run(self._select_rewards)

    def list_all_rewards(self) -> list[Reward]:
        return self._run(self._select_all_rewards)

    def create_reward(self, title: str, cost: int) -> Reward:
        cleaned_title, cleaned_cost = validate_reward_input(title, cost)
        try:
            return self._run(
                lambda cursor: self._insert_reward(cursor, cleaned_title, cleaned_cost)
            )
        except psycopg2.errors.UniqueViolation as error:
            raise DuplicateTitleError(f"Награда «{cleaned_title}» уже есть") from error

    def update_reward(
        self,
        reward_id: int,
        *,
        title: str,
        cost: int,
        is_active: bool,
    ) -> Reward | None:
        cleaned_title, cleaned_cost = validate_reward_input(title, cost)
        try:
            return self._run(
                lambda cursor: self._update_reward(
                    cursor,
                    reward_id,
                    cleaned_title,
                    cleaned_cost,
                    bool(is_active),
                )
            )
        except psycopg2.errors.UniqueViolation as error:
            raise DuplicateTitleError(f"Награда «{cleaned_title}» уже есть") from error

    def get_goal(self, user_id: str) -> Reward | None:
        return self._run(lambda cursor: self._select_goal(cursor, user_id))

    # --- справочник задач ---

    def list_tasks(self) -> list[Task]:
        return self._run(self._select_all_tasks)

    def list_optional_tasks(self) -> list[Task]:
        return self._run(lambda cursor: self._select_tasks(cursor, SELECT_OPTIONAL_TASKS))

    def create_task(self, title: str, kind: str, points: int) -> Task:
        cleaned = validate_task_input(title, kind, points)
        try:
            return self._run(lambda cursor: self._insert_task(cursor, *cleaned))
        except psycopg2.errors.UniqueViolation as error:
            raise DuplicateTitleError(f"Задача «{cleaned[0]}» уже есть") from error

    def update_task(
        self,
        task_id: int,
        *,
        title: str,
        kind: str,
        points: int,
        is_active: bool,
    ) -> Task | None:
        cleaned_title, cleaned_kind, cleaned_points = validate_task_input(title, kind, points)
        try:
            return self._run(
                lambda cursor: self._update_task(
                    cursor,
                    task_id,
                    cleaned_title,
                    cleaned_kind,
                    cleaned_points,
                    bool(is_active),
                )
            )
        except psycopg2.errors.UniqueViolation as error:
            raise DuplicateTitleError(f"Задача «{cleaned_title}» уже есть") from error

    # --- дневной план ---

    def ensure_daily_plan(self, user_id: str, plan_date: dt.date) -> list[Assignment]:
        return self._run(
            lambda cursor: self._ensure_daily_plan(cursor, user_id, plan_date),
            lock_user=user_id,
        )

    def claim_assignment(self, assignment_id: int) -> str | None:
        return self._run(lambda cursor: self._claim(cursor, assignment_id))

    def claim_optional_task(
        self,
        user_id: str,
        plan_date: dt.date,
        task: Task,
    ) -> str | None:
        return self._run(
            lambda cursor: self._claim_optional(cursor, user_id, plan_date, task),
            lock_user=user_id,
        )

    # --- награды и цели ---

    def set_goal(self, user_id: str, reward_id: int) -> None:
        self._run(lambda cursor: cursor.execute(UPSERT_GOAL, (user_id, reward_id)))

    def redeem_reward(self, user_id: str, reward_id: int) -> RedeemOutcome:
        return self._run(
            lambda cursor: self._redeem(cursor, user_id, reward_id),
            lock_user=user_id,
        )

    # --- точка расширения для будущего подтверждения задач родителем ---

    def confirm_assignment(self, assignment_id: int) -> None:
        """Подтверждает выполнение: задача «done», баллы начисляются."""
        self._run(lambda cursor: cursor.execute(CONFIRM_ASSIGNMENT, (assignment_id,)))

    def reject_assignment(self, assignment_id: int) -> None:
        """Отклоняет заявку: задача «missed», баллы списываются."""
        self._run(lambda cursor: cursor.execute(REJECT_ASSIGNMENT, (assignment_id,)))

    # --- штрафы, история и данные для админки ---

    def add_penalty(
        self,
        user_id: str,
        points: int,
        comment: str,
        *,
        source: str = SOURCE_ALICE,
    ) -> PenaltyResult:
        return self._run(
            lambda cursor: self._add_penalty(cursor, user_id, points, comment, source),
            lock_user=user_id,
        )

    def confirm_penalty(self, penalty_id: int, *, resolved_by: str = "admin") -> bool:
        return self._run(
            lambda cursor: self._confirm_penalty(cursor, penalty_id, resolved_by)
        )

    def reject_penalty(self, penalty_id: int, *, resolved_by: str = "admin") -> bool:
        return self._run(lambda cursor: self._reject_penalty(cursor, penalty_id, resolved_by))

    def list_penalties(
        self,
        *,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Penalty]:
        return self._run(
            lambda cursor: self._select_penalties(cursor, user_id, status, limit)
        )

    def list_ledger(self, user_id: str, *, limit: int = 50) -> list[LedgerEntry]:
        return self._run(lambda cursor: self._select_ledger(cursor, user_id, limit))

    def list_pending_assignments(self) -> list[PendingAssignment]:
        return self._run(self._select_pending_assignments)

    def list_users(self) -> list[str]:
        return self._run(self._select_users)


    def close(self) -> None:
        self._db.reset()

    # --- внутреннее устройство ---

    def _run(
        self,
        operation: Callable[[psycopg2.extensions.cursor], T],
        *,
        lock_user: str | None = None,
    ) -> T:
        for attempt in (1, 2):
            try:
                with self._db.transaction(lock_user=lock_user) as cursor:
                    return operation(cursor)
            except CONNECTION_ERRORS:
                self._db.reset()
                if attempt == 2:
                    raise
                logger.warning("Соединение с Postgres потеряно, повторяем операцию")
        raise RuntimeError("повтор операции завершился без результата")

    def _select_balance(self, cursor: psycopg2.extensions.cursor, user_id: str) -> int:
        cursor.execute(SELECT_BALANCE, (user_id,))
        return int(cursor.fetchone()[0])

    def _select_rewards(self, cursor: psycopg2.extensions.cursor) -> list[Reward]:
        cursor.execute(SELECT_REWARDS)
        return [Reward(id=row[0], title=row[1], cost=row[2]) for row in cursor.fetchall()]

    def _select_all_rewards(self, cursor: psycopg2.extensions.cursor) -> list[Reward]:
        cursor.execute(SELECT_ALL_REWARDS)
        return [
            Reward(id=row[0], title=row[1], cost=row[2], is_active=row[3])
            for row in cursor.fetchall()
        ]

    def _insert_reward(
        self,
        cursor: psycopg2.extensions.cursor,
        title: str,
        cost: int,
    ) -> Reward:
        cursor.execute(INSERT_REWARD, (title, cost))
        row = cursor.fetchone()
        return Reward(id=row[0], title=row[1], cost=row[2], is_active=row[3])

    def _update_reward(
        self,
        cursor: psycopg2.extensions.cursor,
        reward_id: int,
        title: str,
        cost: int,
        is_active: bool,
    ) -> Reward | None:
        cursor.execute(UPDATE_REWARD, (title, cost, is_active, reward_id))
        row = cursor.fetchone()
        if row is None:
            return None
        return Reward(id=row[0], title=row[1], cost=row[2], is_active=row[3])

    def _select_goal(
        self,
        cursor: psycopg2.extensions.cursor,
        user_id: str,
    ) -> Reward | None:
        cursor.execute(SELECT_GOAL, (user_id,))
        row = cursor.fetchone()
        return None if row is None else Reward(id=row[0], title=row[1], cost=row[2])

    def _select_plan(
        self,
        cursor: psycopg2.extensions.cursor,
        user_id: str,
        plan_date: dt.date,
    ) -> list[Assignment]:
        cursor.execute(SELECT_PLAN, (user_id, plan_date))
        return [
            Assignment(
                id=row[0],
                title=row[1],
                kind=row[2],
                points=row[3],
                status=row[4],
            )
            for row in cursor.fetchall()
        ]

    def _select_all_tasks(self, cursor: psycopg2.extensions.cursor) -> list[Task]:
        cursor.execute(SELECT_ALL_TASKS)
        return [
            Task(
                id=row[0],
                title=row[1],
                kind=row[2],
                points=row[3],
                is_active=row[4],
            )
            for row in cursor.fetchall()
        ]

    def _insert_task(
        self,
        cursor: psycopg2.extensions.cursor,
        title: str,
        kind: str,
        points: int,
    ) -> Task:
        cursor.execute(INSERT_TASK, (title, kind, points))
        row = cursor.fetchone()
        return Task(id=row[0], title=row[1], kind=row[2], points=row[3], is_active=row[4])

    def _update_task(
        self,
        cursor: psycopg2.extensions.cursor,
        task_id: int,
        title: str,
        kind: str,
        points: int,
        is_active: bool,
    ) -> Task | None:
        cursor.execute(UPDATE_TASK, (title, kind, points, is_active, task_id))
        row = cursor.fetchone()
        if row is None:
            return None
        return Task(id=row[0], title=row[1], kind=row[2], points=row[3], is_active=row[4])

    def _select_tasks(
        self,
        cursor: psycopg2.extensions.cursor,
        query: str,
    ) -> list[Task]:
        cursor.execute(query)
        return [
            Task(id=row[0], title=row[1], kind=row[2], points=row[3])
            for row in cursor.fetchall()
        ]

    def _claim_optional(
        self,
        cursor: psycopg2.extensions.cursor,
        user_id: str,
        plan_date: dt.date,
        task: Task,
    ) -> str | None:
        cursor.execute(
            INSERT_OPTIONAL_ASSIGNMENT,
            (user_id, plan_date, task.id, task.title, task.points),
        )
        row = cursor.fetchone()
        if row is not None:
            return CLAIM_CREATED

        cursor.execute(SELECT_ASSIGNMENT_STATUS_BY_TASK, (user_id, plan_date, task.id))
        row = cursor.fetchone()
        return None if row is None else str(row[0])

    def _ensure_daily_plan(
        self,
        cursor: psycopg2.extensions.cursor,
        user_id: str,
        plan_date: dt.date,
    ) -> list[Assignment]:
        # Заявки на штраф за пропущенные дни создаются лениво: при первом
        # обращении за день. Баллы спишутся только после подтверждения.
        cursor.execute(CREATE_MISSED_PENALTIES, (user_id, plan_date, user_id))

        assignments = self._select_plan(cursor, user_id, plan_date)
        if assignments:
            return assignments

        daily_tasks = self._select_tasks(cursor, SELECT_DAILY_TASKS)
        random_pool = self._select_tasks(cursor, SELECT_RANDOM_TASKS)
        scheduled = plan.build_daily_plan(
            daily_tasks,
            random_pool,
            seed=f"{user_id}:{plan_date.isoformat()}",
            random_count=economy.RANDOM_TASKS_PER_DAY,
        )
        for task in scheduled:
            cursor.execute(
                INSERT_ASSIGNMENT,
                (user_id, plan_date, task.id, task.title, task.kind, task.points),
            )
        return self._select_plan(cursor, user_id, plan_date)

    def _claim(
        self,
        cursor: psycopg2.extensions.cursor,
        assignment_id: int,
    ) -> str | None:
        cursor.execute(CLAIM_ASSIGNMENT, (assignment_id,))
        row = cursor.fetchone()
        if row is not None:
            return str(row[0])

        cursor.execute(SELECT_ASSIGNMENT_STATUS, (assignment_id,))
        row = cursor.fetchone()
        return None if row is None else str(row[0])

    def _redeem(
        self,
        cursor: psycopg2.extensions.cursor,
        user_id: str,
        reward_id: int,
    ) -> RedeemOutcome:
        cursor.execute(SELECT_REWARD, (reward_id,))
        row = cursor.fetchone()
        balance = self._select_balance(cursor, user_id)

        if row is None:
            return RedeemOutcome(status=REDEEM_NOT_FOUND, balance=balance)

        reward = Reward(id=row[0], title=row[1], cost=row[2])
        if balance < reward.cost:
            return RedeemOutcome(
                status=REDEEM_INSUFFICIENT,
                balance=balance,
                missing=reward.cost - balance,
                reward=reward,
            )

        cursor.execute(INSERT_REDEMPTION, (user_id, reward.id, reward.title, reward.cost))
        redemption_id = int(cursor.fetchone()[0])
        cursor.execute(INSERT_REDEEM_LEDGER, (user_id, -reward.cost, redemption_id))
        cursor.execute(DELETE_GOAL, (user_id, reward.id))

        return RedeemOutcome(
            status=REDEEM_OK,
            balance=balance - reward.cost,
            redemption_id=redemption_id,
            reward=reward,
        )

    def _add_penalty(
        self,
        cursor: psycopg2.extensions.cursor,
        user_id: str,
        points: int,
        comment: str,
        source: str,
    ) -> PenaltyResult:
        text = (comment or "").strip()
        max_points = self._settings.penalty_max_points
        if points <= 0 or points > max_points or not text:
            return PenaltyResult(status=PENALTY_INVALID, max_points=max_points)

        cursor.execute(COUNT_RECENT_PENALTIES, (user_id,))
        recent = int(cursor.fetchone()[0])
        if recent >= self._settings.penalty_daily_limit:
            return PenaltyResult(status=PENALTY_LIMIT_EXCEEDED, daily_count=recent)

        cursor.execute(INSERT_PENALTY, (user_id, points, text, source))
        row = cursor.fetchone()
        return PenaltyResult(
            status=PENALTY_CREATED,
            daily_count=recent + 1,
            max_points=max_points,
            penalty=Penalty(
                id=row[0],
                user_id=row[1],
                points=row[2],
                comment=row[3],
                source=row[4],
                status=row[5],
                created_at=row[6],
            ),
        )

    def _confirm_penalty(
        self,
        cursor: psycopg2.extensions.cursor,
        penalty_id: int,
        resolved_by: str,
    ) -> bool:
        cursor.execute(CONFIRM_PENALTY, (resolved_by, penalty_id))
        row = cursor.fetchone()
        if row is None:
            return False

        _, user_id, _, comment, charged_points = row
        charged = int(charged_points or 0)
        if charged <= 0:
            # Списывать нечего: баланс и так 0, журнал не трогаем.
            return True

        cursor.execute(INSERT_PENALTY_LEDGER, (user_id, -charged, comment))
        ledger_id = int(cursor.fetchone()[0])
        cursor.execute(LINK_PENALTY_LEDGER, (ledger_id, penalty_id))
        return True

    def _reject_penalty(
        self,
        cursor: psycopg2.extensions.cursor,
        penalty_id: int,
        resolved_by: str,
    ) -> bool:
        cursor.execute(REJECT_PENALTY, (resolved_by, penalty_id))
        return cursor.fetchone() is not None

    def _select_penalties(
        self,
        cursor: psycopg2.extensions.cursor,
        user_id: str | None,
        status: str | None,
        limit: int,
    ) -> list[Penalty]:
        cursor.execute(SELECT_PENALTIES, (user_id, user_id, status, status, limit))
        return [
            Penalty(
                id=row[0],
                user_id=row[1],
                points=row[2],
                comment=row[3],
                source=row[4],
                status=row[5],
                created_at=row[6],
                charged_points=row[7],
            )
            for row in cursor.fetchall()
        ]

    def _select_ledger(
        self,
        cursor: psycopg2.extensions.cursor,
        user_id: str,
        limit: int,
    ) -> list[LedgerEntry]:
        cursor.execute(SELECT_LEDGER, (user_id, limit))
        return [
            LedgerEntry(
                id=row[0],
                created_at=row[1],
                delta=row[2],
                reason=row[3],
                comment=row[4],
                details=row[5],
            )
            for row in cursor.fetchall()
        ]

    def _select_pending_assignments(
        self,
        cursor: psycopg2.extensions.cursor,
    ) -> list[PendingAssignment]:
        cursor.execute(SELECT_PENDING_ASSIGNMENTS)
        return [
            PendingAssignment(
                id=row[0],
                user_id=row[1],
                plan_date=row[2],
                title=row[3],
                points=row[4],
                kind=row[5],
            )
            for row in cursor.fetchall()
        ]

    def _select_users(self, cursor: psycopg2.extensions.cursor) -> list[str]:
        cursor.execute(SELECT_USERS)
        return [str(row[0]) for row in cursor.fetchall()]






