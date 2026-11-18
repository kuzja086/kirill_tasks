"""Веб-админка навыка: заявки на выполнение, штрафы и история операций.

Приложение не содержит бизнес-логики: все операции идут через
``SkillRepository``, поэтому в тестах подставляется in-memory реализация.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from admin.labels import (
    WEEKDAY_LABELS,
    kind_label,
    penalty_status_label,
    reason_label,
    source_label,
    weekdays_label,
)
from alice_skill import economy
from alice_skill.config import DEFAULT_PENALTY_MAX_POINTS
from alice_skill.models import (
    KIND_DAILY,
    PENALTY_AWAITING,
    PENALTY_CREATED,
    PENALTY_LIMIT_EXCEEDED,
    SOURCE_ADMIN,
    TASK_KINDS,
    TASK_MAX_POINTS,
)
from alice_skill.repository import DuplicateTitleError, SkillRepository
from alice_skill.text import format_points

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def create_app(
    repository: SkillRepository,
    *,
    password: str,
    secret_key: str = "admin-secret",
    session_max_age: int = 12 * 60 * 60,
    penalty_max_points: int = DEFAULT_PENALTY_MAX_POINTS,
) -> FastAPI:
    """Создаёт приложение админки поверх репозитория навыка."""
    expected_password = password

    app = FastAPI(title="Навык Алисы: админка")
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret_key,
        max_age=session_max_age,
    )

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["points"] = format_points
    templates.env.filters["reason"] = reason_label
    templates.env.filters["penalty_status"] = penalty_status_label
    templates.env.filters["source"] = source_label
    templates.env.filters["kind"] = kind_label
    templates.env.filters["weekdays"] = weekdays_label

    def days_to_earn(cost: int, planned: int) -> str:
        """Сколько дней копить награду; «—», если плана дня ещё нет."""
        try:
            return str(economy.days_to_earn(cost, planned))
        except ValueError:
            return "—"

    def day_share(points: int, planned: int) -> str:
        """Доля планового дня в процентах; «—», если плана дня ещё нет."""
        try:
            return str(economy.daily_share_percent(points, planned))
        except ValueError:
            return "—"

    templates.env.filters["days_to_earn"] = days_to_earn
    templates.env.filters["day_share"] = day_share

    def guard(request: Request) -> RedirectResponse | None:
        if not request.session.get("authenticated"):
            return RedirectResponse("/login", status_code=303)
        return None

    def render(
        request: Request,
        template: str,
        context: dict[str, Any] | None = None,
    ) -> HTMLResponse:
        data: dict[str, Any] = {"request": request}
        data.update(context or {})
        return templates.TemplateResponse(request, template, data)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request) -> HTMLResponse:
        return render(request, "login.html", {"error": None})

    @app.post("/login", response_class=HTMLResponse)
    def login(request: Request, password: str = Form("")) -> HTMLResponse:
        if password != expected_password:
            return render(request, "login.html", {"error": "Неверный пароль"})
        request.session["authenticated"] = True
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        redirect = guard(request)
        if redirect is not None:
            return redirect

        users = repository.list_users()
        return render(
            request,
            "dashboard.html",
            {
                "pending_assignments": repository.list_pending_assignments(),
                "pending_penalties": repository.list_penalties(
                    status=PENALTY_AWAITING, limit=20
                ),
                "balances": {user: repository.get_balance(user) for user in users},
            },
        )

    @app.get("/assignments", response_class=HTMLResponse)
    def assignments(request: Request) -> HTMLResponse:
        redirect = guard(request)
        if redirect is not None:
            return redirect

        return render(
            request,
            "assignments.html",
            {"assignments": repository.list_pending_assignments()},
        )

    @app.post("/assignments/{assignment_id}/confirm")
    def confirm_assignment(assignment_id: int, request: Request) -> RedirectResponse:
        redirect = guard(request)
        if redirect is not None:
            return redirect

        repository.confirm_assignment(assignment_id)
        return RedirectResponse("/assignments?message=confirmed", status_code=303)

    @app.post("/assignments/{assignment_id}/reject")
    def reject_assignment(assignment_id: int, request: Request) -> RedirectResponse:
        redirect = guard(request)
        if redirect is not None:
            return redirect

        repository.reject_assignment(assignment_id)
        return RedirectResponse("/assignments?message=rejected", status_code=303)

    @app.get("/penalties", response_class=HTMLResponse)
    def penalties(
        request: Request,
        status: str = PENALTY_AWAITING,
        message: str = "",
        error: str = "",
    ) -> HTMLResponse:
        redirect = guard(request)
        if redirect is not None:
            return redirect

        return render(
            request,
            "penalties.html",
            {
                "penalties": repository.list_penalties(status=status or None, limit=50),
                "users": repository.list_users(),
                "status": status,
                "message": message,
                "error": error,
                "penalty_max_points": penalty_max_points,
            },
        )

    @app.post("/penalties")
    def add_penalty(
        request: Request,
        user_id: str = Form(""),
        points: int = Form(0),
        comment: str = Form(""),
    ) -> RedirectResponse:
        redirect = guard(request)
        if redirect is not None:
            return redirect

        result = repository.add_penalty(
            user_id.strip(),
            points,
            comment,
            source=SOURCE_ADMIN,
        )
        if result.status == PENALTY_CREATED:
            return RedirectResponse("/penalties?message=created", status_code=303)
        if result.status == PENALTY_LIMIT_EXCEEDED:
            return RedirectResponse("/penalties?error=limit", status_code=303)
        return RedirectResponse("/penalties?error=invalid", status_code=303)

    @app.post("/penalties/{penalty_id}/apply")
    def apply_penalty(penalty_id: int, request: Request) -> RedirectResponse:
        redirect = guard(request)
        if redirect is not None:
            return redirect

        applied = repository.confirm_penalty(penalty_id, resolved_by="admin")
        if applied:
            return RedirectResponse("/penalties?message=applied", status_code=303)
        return RedirectResponse("/penalties?error=missing", status_code=303)

    @app.post("/penalties/{penalty_id}/reject")
    def reject_penalty(penalty_id: int, request: Request) -> RedirectResponse:
        redirect = guard(request)
        if redirect is not None:
            return redirect

        rejected = repository.reject_penalty(penalty_id, resolved_by="admin")
        if rejected:
            return RedirectResponse("/penalties?message=rejected", status_code=303)
        return RedirectResponse("/penalties?error=missing", status_code=303)

    @app.get("/history", response_class=HTMLResponse)
    def history(request: Request, user_id: str = "") -> HTMLResponse:
        redirect = guard(request)
        if redirect is not None:
            return redirect

        return render(
            request,
            "history.html",
            {
                "users": repository.list_users(),
                "selected": user_id,
                "entries": repository.list_ledger(user_id, limit=100) if user_id else [],
            },
        )

    # --- справочник задач и наград ---

    @app.get("/tasks", response_class=HTMLResponse)
    def tasks(request: Request, message: str = "", error: str = "") -> HTMLResponse:
        redirect = guard(request)
        if redirect is not None:
            return redirect

        tasks = repository.list_tasks()
        return render(
            request,
            "tasks.html",
            {
                "tasks": tasks,
                "kinds": [(kind, kind_label(kind)) for kind in TASK_KINDS],
                "weekday_options": list(WEEKDAY_LABELS.items()),
                "planned_daily_points": economy.planned_daily_points(
                    tasks,
                    weekday=dt.date.today().isoweekday(),
                ),
                "task_max_points": TASK_MAX_POINTS,
                "message": message,
                "error": error,
            },
        )

    @app.post("/tasks")
    def create_task(
        request: Request,
        title: str = Form(""),
        kind: str = Form(KIND_DAILY),
        points: str = Form(""),
        weekdays: list[int] | None = Form(None),
    ) -> RedirectResponse:
        redirect = guard(request)
        if redirect is not None:
            return redirect

        try:
            repository.create_task(title, kind, int(points), weekdays=weekdays)
        except DuplicateTitleError:
            return RedirectResponse("/tasks?error=duplicate", status_code=303)
        except ValueError:
            return RedirectResponse("/tasks?error=invalid", status_code=303)
        return RedirectResponse("/tasks?message=created", status_code=303)

    @app.post("/tasks/{task_id}")
    def update_task(
        request: Request,
        task_id: int,
        title: str = Form(""),
        kind: str = Form(KIND_DAILY),
        points: str = Form(""),
        is_active: bool = Form(False),
        weekdays: list[int] | None = Form(None),
    ) -> RedirectResponse:
        redirect = guard(request)
        if redirect is not None:
            return redirect

        try:
            updated = repository.update_task(
                task_id,
                title=title,
                kind=kind,
                points=int(points),
                is_active=is_active,
                weekdays=weekdays,
            )
        except DuplicateTitleError:
            return RedirectResponse("/tasks?error=duplicate", status_code=303)
        except ValueError:
            return RedirectResponse("/tasks?error=invalid", status_code=303)
        if updated is None:
            return RedirectResponse("/tasks?error=missing", status_code=303)
        return RedirectResponse("/tasks?message=updated", status_code=303)

    @app.get("/rewards", response_class=HTMLResponse)
    def rewards(request: Request, message: str = "", error: str = "") -> HTMLResponse:
        redirect = guard(request)
        if redirect is not None:
            return redirect

        planned = economy.planned_daily_points(repository.list_tasks())
        return render(
            request,
            "rewards.html",
            {
                "rewards": repository.list_all_rewards(),
                "planned_daily_points": planned,
                "daily_earn": economy.realistic_daily_points(planned) if planned > 0 else 0,
                "message": message,
                "error": error,
            },
        )

    @app.post("/rewards")
    def create_reward(
        request: Request,
        title: str = Form(""),
        cost: str = Form(""),
    ) -> RedirectResponse:
        redirect = guard(request)
        if redirect is not None:
            return redirect

        try:
            repository.create_reward(title, int(cost))
        except DuplicateTitleError:
            return RedirectResponse("/rewards?error=duplicate", status_code=303)
        except ValueError:
            return RedirectResponse("/rewards?error=invalid", status_code=303)
        return RedirectResponse("/rewards?message=created", status_code=303)

    @app.post("/rewards/{reward_id}")
    def update_reward(
        request: Request,
        reward_id: int,
        title: str = Form(""),
        cost: str = Form(""),
        is_active: bool = Form(False),
    ) -> RedirectResponse:
        redirect = guard(request)
        if redirect is not None:
            return redirect

        try:
            updated = repository.update_reward(
                reward_id,
                title=title,
                cost=int(cost),
                is_active=is_active,
            )
        except DuplicateTitleError:
            return RedirectResponse("/rewards?error=duplicate", status_code=303)
        except ValueError:
            return RedirectResponse("/rewards?error=invalid", status_code=303)
        if updated is None:
            return RedirectResponse("/rewards?error=missing", status_code=303)
        return RedirectResponse("/rewards?message=updated", status_code=303)

    return app

