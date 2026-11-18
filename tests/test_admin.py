"""Тесты веб-админки: доступ, заявки, штрафы и история."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from admin.app import create_app
from alice_skill.models import (
    PENALTY_APPLIED,
    STATUS_AWAITING_CONFIRMATION,
    STATUS_DONE,
    STATUS_MISSED,
)
from factories import FakeSkillRepository, make_assignment, make_reward, make_task

PASSWORD = "test-password"


def _client(repository: FakeSkillRepository) -> TestClient:
    app = create_app(repository, password=PASSWORD, secret_key="test-secret")
    return TestClient(app)


def _login(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_requires_login() -> None:
    client = _client(FakeSkillRepository())

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_with_wrong_password() -> None:
    client = _client(FakeSkillRepository())

    response = client.post("/login", data={"password": "nope"})

    assert response.status_code == 200
    assert "Неверный пароль" in response.text


def test_dashboard_shows_balances_and_counts() -> None:
    repository = FakeSkillRepository(
        assignments=[make_assignment(1, "Зарядка", status=STATUS_AWAITING_CONFIRMATION)],
        balance=30,
    )
    repository.add_penalty("user-1", 10, "не выключил свет")
    client = _client(repository)

    _login(client)
    response = client.get("/")

    assert response.status_code == 200
    assert "Сводка" in response.text
    assert "30 баллов" in response.text
    assert "не выключил свет" in response.text


def test_logout_clears_session() -> None:
    client = _client(FakeSkillRepository())
    _login(client)

    response = client.post("/logout", follow_redirects=False)

    assert response.status_code == 303
    assert client.get("/", follow_redirects=False).status_code == 303


def test_assignment_can_be_confirmed() -> None:
    repository = FakeSkillRepository(
        assignments=[make_assignment(1, "Зарядка", points=10, status=STATUS_AWAITING_CONFIRMATION)]
    )
    client = _client(repository)
    _login(client)

    page = client.get("/assignments")
    assert "Зарядка" in page.text

    response = client.post("/assignments/1/confirm", follow_redirects=False)

    assert response.status_code == 303
    assert repository.assignments[0].status == STATUS_DONE
    assert repository.balance == 10


def test_assignment_can_be_rejected() -> None:
    repository = FakeSkillRepository(
        assignments=[make_assignment(1, "Зарядка", points=10, status=STATUS_AWAITING_CONFIRMATION)]
    )
    client = _client(repository)
    _login(client)

    response = client.post("/assignments/1/reject", follow_redirects=False)

    assert response.status_code == 303
    assert repository.assignments[0].status == STATUS_MISSED
    assert repository.balance == 0, "списывать нечего: баланс и так 0"


def test_assignment_rejection_does_not_go_below_zero() -> None:
    repository = FakeSkillRepository(
        assignments=[make_assignment(1, "Зарядка", points=10, status=STATUS_AWAITING_CONFIRMATION)],
        balance=3,
    )
    client = _client(repository)
    _login(client)

    client.post("/assignments/1/reject", follow_redirects=False)

    assert repository.balance == 0
    assert [entry.delta for entry in repository.ledger] == [-3]


def test_penalty_can_be_applied_from_admin() -> None:
    repository = FakeSkillRepository(balance=50)
    repository.add_penalty("user-1", 10, "не выключил свет")
    client = _client(repository)
    _login(client)

    page = client.get("/penalties")
    assert "не выключил свет" in page.text
    assert "ждёт подтверждения" in page.text

    response = client.post("/penalties/1/apply", follow_redirects=False)

    assert response.status_code == 303
    assert repository.penalties[0].status == PENALTY_APPLIED
    assert repository.penalties[0].charged_points == 10
    assert repository.balance == 40


def test_penalty_is_capped_by_available_points() -> None:
    repository = FakeSkillRepository(balance=3)
    repository.add_penalty("user-1", 10, "разбил чашку")
    client = _client(repository)
    _login(client)

    client.post("/penalties/1/apply", follow_redirects=False)

    assert repository.penalties[0].charged_points == 3
    assert repository.balance == 0
    assert [entry.delta for entry in repository.ledger] == [-3]

    page = client.get("/penalties?status=applied")
    assert "−3" in page.text
    assert "из 10" in page.text


def test_manual_penalty_creates_request() -> None:
    repository = FakeSkillRepository()
    client = _client(repository)
    _login(client)

    response = client.post(
        "/penalties",
        data={"user_id": "user-1", "points": "5", "comment": "разбил чашку"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert len(repository.penalties) == 1
    assert repository.penalties[0].source == "admin"
    assert repository.penalties[0].points == 5
    assert repository.penalties[0].comment == "разбил чашку"


def test_manual_penalty_rejects_invalid_amount() -> None:
    repository = FakeSkillRepository()
    client = _client(repository)
    _login(client)

    response = client.post(
        "/penalties",
        data={"user_id": "user-1", "points": "0", "comment": "пусто"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("error=invalid")
    assert repository.penalties == []


def test_history_shows_reasons() -> None:
    repository = FakeSkillRepository(balance=20)
    repository.add_penalty("user-1", 10, "не выключил свет")
    repository.confirm_penalty(1)
    client = _client(repository)
    _login(client)

    page = client.get("/history?user_id=user-1")

    assert page.status_code == 200
    assert "Штраф" in page.text
    assert "не выключил свет" in page.text
    assert "-10" in page.text


def test_healthz() -> None:
    client = _client(FakeSkillRepository())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- справочник задач и наград ---


def test_tasks_page_lists_tasks_with_kind() -> None:
    repository = FakeSkillRepository(
        tasks=[make_task(1, "Зарядка", points=10), make_task(2, "Полить цветы", kind="optional", points=5)]
    )
    client = _client(repository)
    _login(client)

    page = client.get("/tasks")

    assert page.status_code == 200
    assert "Зарядка" in page.text
    assert "Полить цветы" in page.text
    assert "дополнительная" in page.text


def test_task_can_be_created_from_admin() -> None:
    repository = FakeSkillRepository()
    client = _client(repository)
    _login(client)

    response = client.post(
        "/tasks",
        data={"title": "Полить цветы", "kind": "optional", "points": "5"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("message=created")
    assert len(repository.tasks) == 1
    assert repository.tasks[0].title == "Полить цветы"
    assert repository.tasks[0].kind == "optional"
    assert repository.tasks[0].points == 5


def test_task_with_duplicate_title_is_rejected() -> None:
    repository = FakeSkillRepository(tasks=[make_task(1, "Зарядка")])
    client = _client(repository)
    _login(client)

    response = client.post(
        "/tasks",
        data={"title": "зарядка", "kind": "daily", "points": "10"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("error=duplicate")
    assert len(repository.tasks) == 1


def test_task_with_non_integer_points_is_rejected() -> None:
    repository = FakeSkillRepository()
    client = _client(repository)
    _login(client)

    response = client.post(
        "/tasks",
        data={"title": "Полить цветы", "kind": "daily", "points": "2.5"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("error=invalid")
    assert repository.tasks == []


def test_task_can_be_edited_and_disabled() -> None:
    repository = FakeSkillRepository(tasks=[make_task(1, "Зарядка", points=10)])
    client = _client(repository)
    _login(client)

    response = client.post(
        "/tasks/1",
        data={"title": "Зарядка утром", "kind": "daily", "points": "5"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("message=updated")
    assert repository.tasks[0].title == "Зарядка утром"
    assert repository.tasks[0].points == 5
    assert repository.tasks[0].is_active is False


def test_editing_unknown_task_reports_missing() -> None:
    client = _client(FakeSkillRepository())
    _login(client)

    response = client.post(
        "/tasks/99",
        data={"title": "Зарядка", "kind": "daily", "points": "10"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("error=missing")


def test_tasks_page_shows_planned_day_and_share() -> None:
    repository = FakeSkillRepository(
        tasks=[
            make_task(1, "Зарядка", points=10),
            make_task(2, "Погулять", kind="random", points=2),
            make_task(3, "Нарисовать", kind="random", points=1),
        ]
    )
    client = _client(repository)
    _login(client)

    page = client.get("/tasks")

    assert "План дня сейчас — 13 баллов" in page.text
    assert "77%" in page.text


def test_rewards_page_shows_days_to_earn() -> None:
    repository = FakeSkillRepository(
        tasks=[
            make_task(1, "Зарядка", points=10),
            make_task(2, "Погулять", kind="random", points=2),
            make_task(3, "Нарисовать", kind="random", points=1),
        ],
        rewards=[make_reward(1, "Наклейка", cost=10), make_reward(2, "Настольная игра", cost=70)],
    )
    client = _client(repository)
    _login(client)

    page = client.get("/rewards")

    assert "10 баллов в день × 7 = 70" in page.text
    assert "≈ дней копить" in page.text
    assert "<td>7</td>" in page.text


def test_reward_cost_can_be_edited() -> None:
    repository = FakeSkillRepository(rewards=[make_reward(1, "Мороженое", cost=25)])
    client = _client(repository)
    _login(client)

    page = client.get("/rewards")
    assert "Мороженое" in page.text

    response = client.post(
        "/rewards/1",
        data={"title": "Мороженое", "cost": "20", "is_active": "true"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("message=updated")
    assert repository.rewards[0].cost == 20
    assert repository.rewards[0].is_active is True


def test_optional_assignment_is_labelled_and_not_penalized() -> None:
    repository = FakeSkillRepository(
        tasks=[make_task(2, "Полить цветы", kind="optional", points=5)],
        balance=10,
    )
    repository.claim_optional_task("user-1", dt.date(2026, 11, 15), repository.tasks[0])
    client = _client(repository)
    _login(client)

    page = client.get("/assignments")
    assert "дополнительная" in page.text

    client.post("/assignments/1/reject", follow_redirects=False)

    assert repository.assignments[0].status == STATUS_MISSED
    assert repository.balance == 10, "за дополнительную задачу баллы не списываются"
    assert repository.ledger == []
