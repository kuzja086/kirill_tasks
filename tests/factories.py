"""Фабрики предметных объектов и in-memory репозиторий для тестов."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from typing import Any

from alice_skill.models import (
    PENALTY_APPLIED,
    PENALTY_AWAITING,
    PENALTY_CREATED,
    PENALTY_INVALID,
    PENALTY_LIMIT_EXCEEDED,
    PENALTY_REJECTED,
    REDEEM_INSUFFICIENT,
    REDEEM_OK,
    SOURCE_ALICE,
    STATUS_AWAITING_CONFIRMATION,
    STATUS_DONE,
    STATUS_MISSED,
    STATUS_PENDING,
    Assignment,
    LedgerEntry,
    Penalty,
    PenaltyResult,
    PendingAssignment,
    RedeemOutcome,
    Reward,
    Task,
)


def make_task(task_id: int, title: str, *, kind: str = "daily", points: int = 10) -> Task:
    return Task(id=task_id, title=title, kind=kind, points=points)


def make_assignment(
    assignment_id: int,
    title: str,
    *,
    points: int = 10,
    status: str = STATUS_PENDING,
) -> Assignment:
    return Assignment(id=assignment_id, title=title, points=points, status=status)


def make_reward(reward_id: int, title: str, *, cost: int = 100) -> Reward:
    return Reward(id=reward_id, title=title, cost=cost)


class FakeSkillRepository:
    """In-memory реализация ``alice_skill.repository.SkillRepository``."""

    def __init__(
        self,
        assignments: list[Assignment] | None = None,
        rewards: list[Reward] | None = None,
        balance: int = 0,
        *,
        user_id: str = "user-1",
        max_points: int = 100,
        daily_limit: int = 5,
    ) -> None:
        self.assignments = list(assignments or [])
        self.rewards = list(rewards or [])
        self.balance = balance
        self.goal: Reward | None = None
        self.plan_requests: list[tuple[str, Any]] = []
        self.claims: list[int] = []
        self.redemptions: list[int] = []
        self.goal_requests: list[int] = []
        self.user_id = user_id
        self.max_points = max_points
        self.daily_limit = daily_limit
        self.penalties: list[Penalty] = []
        self.ledger: list[LedgerEntry] = []
        self._next_penalty_id = 1

    def ensure_daily_plan(self, user_id: str, plan_date: Any) -> list[Assignment]:
        self.plan_requests.append((user_id, plan_date))
        return list(self.assignments)

    def get_balance(self, user_id: str) -> int:
        return self.balance

    def list_rewards(self) -> list[Reward]:
        return sorted(self.rewards, key=lambda reward: (reward.cost, reward.id))

    def get_goal(self, user_id: str) -> Reward | None:
        return self.goal

    def set_goal(self, user_id: str, reward_id: int) -> None:
        self.goal_requests.append(reward_id)
        self.goal = next(reward for reward in self.rewards if reward.id == reward_id)

    def redeem_reward(self, user_id: str, reward_id: int) -> RedeemOutcome:
        reward = next(reward for reward in self.rewards if reward.id == reward_id)
        if self.balance < reward.cost:
            return RedeemOutcome(
                status=REDEEM_INSUFFICIENT,
                balance=self.balance,
                missing=reward.cost - self.balance,
                reward=reward,
            )

        self.balance -= reward.cost
        self.redemptions.append(reward.id)
        if self.goal is not None and self.goal.id == reward.id:
            self.goal = None
        return RedeemOutcome(
            status=REDEEM_OK,
            balance=self.balance,
            redemption_id=len(self.redemptions),
            reward=reward,
        )

    def claim_assignment(self, assignment_id: int) -> str | None:
        self.claims.append(assignment_id)
        for index, assignment in enumerate(self.assignments):
            if assignment.id != assignment_id:
                continue
            if assignment.status != STATUS_PENDING:
                return assignment.status
            updated = replace(assignment, status=STATUS_AWAITING_CONFIRMATION)
            self.assignments[index] = updated
            return updated.status
        return None

    # --- подтверждение задач (админка) ---

    def confirm_assignment(self, assignment_id: int) -> None:
        for index, assignment in enumerate(self.assignments):
            if assignment.id != assignment_id or assignment.status != STATUS_AWAITING_CONFIRMATION:
                continue
            self.assignments[index] = replace(assignment, status=STATUS_DONE)
            self.balance += assignment.points
            self.ledger.append(
                LedgerEntry(
                    id=len(self.ledger) + 1,
                    delta=assignment.points,
                    reason="task_done",
                    details=assignment.title,
                )
            )

    def reject_assignment(self, assignment_id: int) -> None:
        for index, assignment in enumerate(self.assignments):
            if assignment.id != assignment_id or assignment.status != STATUS_AWAITING_CONFIRMATION:
                continue
            self.assignments[index] = replace(assignment, status=STATUS_MISSED)
            self.balance -= assignment.points
            self.ledger.append(
                LedgerEntry(
                    id=len(self.ledger) + 1,
                    delta=-assignment.points,
                    reason="task_missed",
                    details=assignment.title,
                )
            )

    # --- штрафы ---

    def add_penalty(
        self,
        user_id: str,
        points: int,
        comment: str,
        *,
        source: str = SOURCE_ALICE,
    ) -> PenaltyResult:
        text = (comment or "").strip()
        if points <= 0 or points > self.max_points or not text:
            return PenaltyResult(status=PENALTY_INVALID, max_points=self.max_points)

        recent = len([p for p in self.penalties if p.source == SOURCE_ALICE])
        if recent >= self.daily_limit:
            return PenaltyResult(
                status=PENALTY_LIMIT_EXCEEDED,
                daily_count=recent,
                max_points=self.max_points,
            )

        penalty = Penalty(
            id=self._next_penalty_id,
            user_id=user_id,
            points=points,
            comment=text,
            source=source,
            status=PENALTY_AWAITING,
        )
        self._next_penalty_id += 1
        self.penalties.append(penalty)
        return PenaltyResult(
            status=PENALTY_CREATED,
            penalty=penalty,
            daily_count=recent + 1,
            max_points=self.max_points,
        )

    def confirm_penalty(self, penalty_id: int, *, resolved_by: str = "admin") -> bool:
        for index, penalty in enumerate(self.penalties):
            if penalty.id != penalty_id or penalty.status != PENALTY_AWAITING:
                continue
            self.penalties[index] = replace(penalty, status=PENALTY_APPLIED)
            self.balance -= penalty.points
            self.ledger.append(
                LedgerEntry(
                    id=len(self.ledger) + 1,
                    delta=-penalty.points,
                    reason="penalty",
                    comment=penalty.comment,
                )
            )
            return True
        return False

    def reject_penalty(self, penalty_id: int, *, resolved_by: str = "admin") -> bool:
        for index, penalty in enumerate(self.penalties):
            if penalty.id != penalty_id or penalty.status != PENALTY_AWAITING:
                continue
            self.penalties[index] = replace(penalty, status=PENALTY_REJECTED)
            return True
        return False

    def list_penalties(
        self,
        *,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Penalty]:
        found = [
            penalty
            for penalty in self.penalties
            if (user_id is None or penalty.user_id == user_id)
            and (status is None or penalty.status == status)
        ]
        return found[:limit]

    # --- история и данные для админки ---

    def list_ledger(self, user_id: str, *, limit: int = 50) -> list[LedgerEntry]:
        return self.ledger[:limit]

    def list_pending_assignments(self) -> list[PendingAssignment]:
        return [
            PendingAssignment(
                id=assignment.id,
                user_id=self.user_id,
                plan_date=dt.date(2026, 11, 15),
                title=assignment.title,
                points=assignment.points,
            )
            for assignment in self.assignments
            if assignment.status == STATUS_AWAITING_CONFIRMATION
        ]

    def list_users(self) -> list[str]:
        return [self.user_id]

