"""Локальная песочница навыка: диалог и подтверждение задач без Алисы.

Работает с тем же кодом и той же базой, что и облачная функция, поэтому
подходит для проверки сценариев, начисления баллов и штрафов.

Примеры:

    python tools/local.py ask "какие задачи на сегодня"
    python tools/local.py ask "я выполнил зарядку"
    python tools/local.py today
    python tools/local.py pending
    python tools/local.py confirm 42
    python tools/local.py reject 42

По умолчанию берётся пользователь ``local-user``; своего можно задать
через ``--user``, дату плана — через ``--date`` (формат ГГГГ-ММ-ДД).
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alice_skill import dialogue, text  # noqa: E402
from alice_skill.config import load_settings  # noqa: E402
from alice_skill.db import Database  # noqa: E402
from alice_skill.models import STATUS_AWAITING_CONFIRMATION, AliceRequest  # noqa: E402
from alice_skill.repository import PostgresSkillRepository  # noqa: E402

DEFAULT_USER = "local-user"

PENDING_SQL = """
    SELECT id, plan_date, title, points
      FROM daily_assignments
     WHERE user_id = %s AND status = %s
     ORDER BY plan_date, id
"""


def parse_env_file(raw: str) -> dict[str, str]:
    """Разбирает содержимое .env: пары KEY=VALUE, комментарии и пустые строки пропускаются."""
    values: dict[str, str] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_env_from_file(path: Path) -> None:
    """Подставляет значения из .env в окружение, не затирая уже заданные."""
    if not path.exists():
        return
    for key, value in parse_env_file(path.read_text(encoding="utf-8")).items():
        os.environ.setdefault(key, value)


def build_event(phrase: str, *, user_id: str) -> dict[str, Any]:
    """Событие в формате Яндекс.Диалогов: интент определяется по фразе."""
    return {
        "meta": {"locale": "ru-RU", "timezone": "Europe/Moscow"},
        "session": {
            "message_id": 1,
            "session_id": "local-session",
            "skill_id": "local-skill",
            "user": {"user_id": user_id},
            "application": {"application_id": "local-app"},
            "new": False,
        },
        "request": {
            "type": "SimpleUtterance",
            "command": phrase,
            "original_utterance": phrase,
            "nlu": {"tokens": phrase.split(), "entities": [], "intents": {}},
            "markup": {"dangerous_context": False},
            "payload": {},
        },
        "version": "1.0",
    }


def print_pending(rows: Iterable[tuple[Any, ...]]) -> None:
    rows = list(rows)
    if not rows:
        print("Заявок на подтверждение нет.")
        return
    for assignment_id, plan_date, title, points in rows:
        print(f"#{assignment_id}  {plan_date}  {title} — {text.format_points(points)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Песочница навыка-мотиватора")
    parser.add_argument("--user", default=DEFAULT_USER, help="идентификатор ребёнка")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ask_parser = subparsers.add_parser("ask", help="отправить фразу навыку")
    ask_parser.add_argument("phrase")
    ask_parser.add_argument("--date", help="дата плана, ГГГГ-ММ-ДД (по умолчанию сегодня)")

    subparsers.add_parser("today", help="показать план на сегодня и баланс")
    subparsers.add_parser("pending", help="показать заявки, ждущие подтверждения")

    for name in ("confirm", "reject"):
        action_parser = subparsers.add_parser(name, help=f"{name} заявку на выполнение по id")
        action_parser.add_argument("assignment_id", type=int)

    subparsers.add_parser("penalties", help="последние заявки на штраф")

    for name in ("apply-penalty", "reject-penalty"):
        penalty_parser = subparsers.add_parser(name, help=f"{name} заявку на штраф по id")
        penalty_parser.add_argument("penalty_id", type=int)

    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    load_env_from_file(ROOT / ".env")
    repository = PostgresSkillRepository(load_settings())
    today = dt.date.today()

    try:
        if args.command == "ask":
            plan_date = dt.date.fromisoformat(args.date) if args.date else today
            request = AliceRequest.from_event(build_event(args.phrase, user_id=args.user))
            print(f"Интент: {dialogue.detect_intent(request)}")
            response = dialogue.respond(request, repository, plan_date)
            print(response.text)
            return 0

        if args.command == "today":
            assignments = repository.ensure_daily_plan(args.user, today)
            balance = repository.get_balance(args.user)
            for index, assignment in enumerate(assignments, start=1):
                print(text.format_task_line(assignment, index))
            print(f"Баланс: {text.format_points(balance)}")
            return 0

        if args.command == "pending":
            database = Database(load_settings())
            try:
                with database.transaction() as cursor:
                    cursor.execute(PENDING_SQL, (args.user, STATUS_AWAITING_CONFIRMATION))
                    print_pending(cursor.fetchall())
            finally:
                database.close()
            return 0

        if args.command == "confirm":
            repository.confirm_assignment(args.assignment_id)
            print(f"Заявка #{args.assignment_id} подтверждена, баллы начислены.")
            return 0

        if args.command == "penalties":
            penalties = repository.list_penalties(limit=20)
            if not penalties:
                print("Заявок на штраф нет.")
            for penalty in penalties:
                print(
                    f"#{penalty.id}  {penalty.status:22} "
                    f"{text.format_points(penalty.points):>12}  {penalty.comment}  ({penalty.source})"
                )
            return 0

        if args.command == "apply-penalty":
            applied = repository.confirm_penalty(args.penalty_id, resolved_by="local-cli")
            print(
                "Штраф применён, баллы списаны."
                if applied
                else "Заявка не найдена или уже обработана."
            )
            return 0

        if args.command == "reject-penalty":
            rejected = repository.reject_penalty(args.penalty_id, resolved_by="local-cli")
            print(
                "Заявка на штраф отклонена, баллы не списаны."
                if rejected
                else "Заявка не найдена или уже обработана."
            )
            return 0

        repository.reject_assignment(args.assignment_id)
        print(f"Заявка #{args.assignment_id} отклонена, баллы списаны.")
        return 0
    finally:
        repository.close()


if __name__ == "__main__":
    raise SystemExit(main())
