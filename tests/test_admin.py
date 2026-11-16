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
from factories import FakeSkillRepository, make_assignment

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
        balance=420,
    )
    repository.add_penalty("user-1", 10, "не выключил свет")
    client = _client(repository)

    _login(client)
    response = client.get("/")

    assert response.status_code == 200
    assert "Сводка" in response.text
    assert "420 баллов" in response.text
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
    assert repository.balance == -10


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
    assert repository.balance == 40


def test_manual_penalty_creates_request() -> None:
    repository = FakeSkillRepository()
    client = _client(repository)
    _login(client)

    response = client.post(
        "/penalties",
        data={"user_id": "user-1", "points": "15", "comment": "разбил чашку"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert len(repository.penalties) == 1
    assert repository.penalties[0].source == "admin"
    assert repository.penalties[0].points == 15
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
    repository = FakeSkillRepository()
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
