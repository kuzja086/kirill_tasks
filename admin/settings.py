"""Настройки веб-админки из переменных окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from alice_skill.config import ConfigError

DEFAULT_PORT = 8080
DEFAULT_HOST = "0.0.0.0"


@dataclass(frozen=True)
class AdminSettings:
    """Пароль и параметры запуска админки."""

    password: str
    secret_key: str
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT


def load_admin_settings(env: Mapping[str, str] | None = None) -> AdminSettings:
    """Читает ADMIN_PASSWORD/ADMIN_SECRET_KEY/ADMIN_HOST/ADMIN_PORT."""
    source = os.environ if env is None else env

    password = (source.get("ADMIN_PASSWORD") or "").strip()
    if not password:
        raise ConfigError(
            "Не задан ADMIN_PASSWORD — без пароля админка не запускается"
        )

    secret_key = (source.get("ADMIN_SECRET_KEY") or password).strip()
    host = (source.get("ADMIN_HOST") or DEFAULT_HOST).strip()
    port = _as_port(source.get("ADMIN_PORT"))
    return AdminSettings(password=password, secret_key=secret_key, host=host, port=port)


def _as_port(raw: str | None) -> int:
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError as error:
        raise ConfigError(f"ADMIN_PORT должен быть целым числом, получено: {raw!r}") from error
    if not 1 <= port <= 65535:
        raise ConfigError(f"ADMIN_PORT вне диапазона 1..65535: {port}")
    return port
