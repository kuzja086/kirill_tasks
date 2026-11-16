"""Точка входа админки: ``python -m admin.serve``.

Переменные окружения: ``PG_*`` (как у функции), ``ADMIN_PASSWORD`` (обязательно),
``ADMIN_SECRET_KEY`` (подпись cookie, по умолчанию равен паролю),
``ADMIN_HOST``/``ADMIN_PORT`` (по умолчанию 0.0.0.0:8080).
"""

from __future__ import annotations

from admin.app import create_app
from admin.settings import AdminSettings, load_admin_settings
from alice_skill.config import load_settings
from alice_skill.repository import PostgresSkillRepository


def build_app() -> tuple[object, AdminSettings]:
    """Собирает приложение и настройки запуска."""
    admin_settings = load_admin_settings()
    settings = load_settings()
    repository = PostgresSkillRepository(settings)
    app = create_app(
        repository,
        password=admin_settings.password,
        secret_key=admin_settings.secret_key,
        penalty_max_points=settings.penalty_max_points,
    )
    return app, admin_settings


app, admin_settings = build_app()


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=admin_settings.host, port=admin_settings.port)


if __name__ == "__main__":
    main()
