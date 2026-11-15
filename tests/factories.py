"""Фабрики предметных объектов и in-memory репозиторий для тестов."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from alice_skill.models import (
    REDEEM_INSUFFICIENT,
    REDEEM_OK,
    STATUS_AWAITING_CONFIRMATION,
    STATUS_PENDING,
    Assignment,
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
    ) -> None:
        self.assignments = list(assignments or [])
        self.rewards = list(rewards or [])
        self.balance = balance
        self.goal: Reward | None = None
        self.plan_requests: list[tuple[str, Any]] = []
        self.claims: list[int] = []
        self.redemptions: list[int] = []
        self.goal_requests: list[int] = []

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

