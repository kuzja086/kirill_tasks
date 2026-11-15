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
    REDEEM_INSUFFICIENT,
    REDEEM_NOT_FOUND,
    REDEEM_OK,
    Assignment,
    RedeemOutcome,
    Reward,
    Task,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

SELECT_BALANCE = "SELECT COALESCE(SUM(delta), 0) FROM points_ledger WHERE user_id = %s"

SELECT_REWARDS = "SELECT id, title, cost FROM rewards WHERE is_active ORDER BY cost, id"
SELECT_REWARD = "SELECT id, title, cost FROM rewards WHERE id = %s AND is_active"

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
APPLY_MISSED_PENALTIES = """
    WITH missed AS (
        UPDATE daily_assignments
           SET status = 'missed', resolved_at = now()
         WHERE user_id = %s
           AND plan_date < %s
           AND status = 'pending'
        RETURNING id, points
    )
    INSERT INTO points_ledger (user_id, delta, reason, assignment_id)
    SELECT %s, -points, 'task_missed', id FROM missed
"""

SELECT_PLAN = """
    SELECT id, title, points, status
      FROM daily_assignments
     WHERE user_id = %s AND plan_date = %s
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
        RETURNING id, user_id, points
    )
    INSERT INTO points_ledger (user_id, delta, reason, assignment_id)
    SELECT user_id, -points, 'task_missed', id FROM rejected
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
@runtime_checkable
class SkillRepository(Protocol):
    """Интерфейс хранилища навыка: позволяет подменять Postgres в тестах."""

    def ensure_daily_plan(self, user_id: str, plan_date: dt.date) -> list[Assignment]:
        """Возвращает план на дату, создавая его при первом обращении."""

    def get_balance(self, user_id: str) -> int:
        """Текущий баланс баллов."""

    def list_rewards(self) -> list[Reward]:
        """Активные награды, от дешёвых к дорогим."""

    def get_goal(self, user_id: str) -> Reward | None:
        """Выбранная ребёнком цель или ``None``."""

    def set_goal(self, user_id: str, reward_id: int) -> None:
        """Запоминает награду как цель."""

    def redeem_reward(self, user_id: str, reward_id: int) -> RedeemOutcome:
        """Списывает баллы за награду, если их хватает."""

    def claim_assignment(self, assignment_id: int) -> str | None:
        """Переводит задачу в ожидание подтверждения и возвращает её статус."""
class PostgresSkillRepository:
    """Реализация :class:`SkillRepository` поверх Postgres."""

    def __init__(self, settings: Settings, *, database: Database | None = None) -> None:
        self._db = database if database is not None else Database(settings)

    # --- чтение ---

    def get_balance(self, user_id: str) -> int:
        return self._run(lambda cursor: self._select_balance(cursor, user_id))

    def list_rewards(self) -> list[Reward]:
        return self._run(self._select_rewards)

    def get_goal(self, user_id: str) -> Reward | None:
        return self._run(lambda cursor: self._select_goal(cursor, user_id))

    # --- дневной план ---

    def ensure_daily_plan(self, user_id: str, plan_date: dt.date) -> list[Assignment]:
        return self._run(
            lambda cursor: self._ensure_daily_plan(cursor, user_id, plan_date),
            lock_user=user_id,
        )

    def claim_assignment(self, assignment_id: int) -> str | None:
        return self._run(lambda cursor: self._claim(cursor, assignment_id))

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
            Assignment(id=row[0], title=row[1], points=row[2], status=row[3])
            for row in cursor.fetchall()
        ]

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

    def _ensure_daily_plan(
        self,
        cursor: psycopg2.extensions.cursor,
        user_id: str,
        plan_date: dt.date,
    ) -> list[Assignment]:
        # Штрафы за прошлые дни начисляются лениво, при первом обращении за день.
        cursor.execute(APPLY_MISSED_PENALTIES, (user_id, plan_date, user_id))

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






