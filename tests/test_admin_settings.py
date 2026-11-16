"""Тесты настроек и подписей админки."""

from __future__ import annotations

import pytest

from admin.labels import penalty_status_label, reason_label, source_label
from admin.settings import AdminSettings, load_admin_settings
from alice_skill.config import ConfigError


def test_admin_settings_require_password() -> None:
    with pytest.raises(ConfigError) as error:
        load_admin_settings({})

    assert "ADMIN_PASSWORD" in str(error.value)


def test_admin_settings_defaults() -> None:
    settings = load_admin_settings({"ADMIN_PASSWORD": "s3cret"})

    assert settings == AdminSettings(
        password="s3cret",
        secret_key="s3cret",
        host="0.0.0.0",
        port=8080,
    )


def test_admin_settings_read_custom_values() -> None:
    settings = load_admin_settings(
        {
            "ADMIN_PASSWORD": "s3cret",
            "ADMIN_SECRET_KEY": "sign-me",
            "ADMIN_HOST": "127.0.0.1",
            "ADMIN_PORT": "9000",
        }
    )

    assert settings.secret_key == "sign-me"
    assert settings.host == "127.0.0.1"
    assert settings.port == 9000


@pytest.mark.parametrize("port", ["0", "70000", "abc"])
def test_admin_settings_reject_invalid_port(port: str) -> None:
    with pytest.raises(ConfigError):
        load_admin_settings({"ADMIN_PASSWORD": "s3cret", "ADMIN_PORT": port})


def test_reason_labels() -> None:
    assert reason_label("penalty") == "Штраф"
    assert reason_label("task_done") == "Задача выполнена"
    assert reason_label("unknown") == "unknown"


def test_penalty_status_and_source_labels() -> None:
    assert penalty_status_label("awaiting_confirmation") == "ждёт подтверждения"
    assert penalty_status_label("applied") == "применён"
    assert source_label("alice") == "Алиса"
    assert source_label("admin") == "админка"
