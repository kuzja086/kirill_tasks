"""Тесты чтения настроек из окружения."""

from __future__ import annotations

import pytest

from alice_skill.config import ConfigError, load_settings

VALID_ENV = {
    "PG_HOST": "203.0.113.10",
    "PG_PORT": "6543",
    "PG_DATABASE": "alice_skill",
    "PG_USER": "alice_skill",
    "PG_PASSWORD": "s3cret",
    "PG_SSLMODE": "require",
    "PG_CONNECT_TIMEOUT": "3",
}


def test_load_settings_uses_env_values() -> None:
    settings = load_settings(VALID_ENV)

    assert settings.pg_host == "203.0.113.10"
    assert settings.pg_port == 6543
    assert settings.pg_sslmode == "require"
    assert settings.pg_connect_timeout == 3
    assert settings.connection_params == {
        "host": "203.0.113.10",
        "port": 6543,
        "dbname": "alice_skill",
        "user": "alice_skill",
        "password": "s3cret",
        "sslmode": "require",
        "connect_timeout": 3,
    }


def test_load_settings_applies_defaults() -> None:
    env = {key: VALID_ENV[key] for key in ("PG_HOST", "PG_DATABASE", "PG_USER", "PG_PASSWORD")}

    settings = load_settings(env)

    assert settings.pg_port == 5432
    assert settings.pg_sslmode == "prefer"
    assert settings.pg_connect_timeout == 5


@pytest.mark.parametrize("missing", ["PG_HOST", "PG_DATABASE", "PG_USER", "PG_PASSWORD"])
def test_load_settings_requires_variables(missing: str) -> None:
    env = {key: value for key, value in VALID_ENV.items() if key != missing}

    with pytest.raises(ConfigError) as error:
        load_settings(env)

    assert missing in str(error.value)


def test_load_settings_rejects_non_integer_port() -> None:
    env = dict(VALID_ENV, PG_PORT="not-a-port")

    with pytest.raises(ConfigError) as error:
        load_settings(env)

    assert "PG_PORT" in str(error.value)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("enable", "require"),
        ("ENABLED", "require"),
        ("on", "require"),
        ("true", "require"),
        ("off", "disable"),
        ("false", "disable"),
        ("require", "require"),
        ("prefer", "prefer"),
        ("verify-full", "verify-full"),
    ],
)
def test_load_settings_normalizes_sslmode(raw: str, expected: str) -> None:
    settings = load_settings(dict(VALID_ENV, PG_SSLMODE=raw))

    assert settings.pg_sslmode == expected


def test_load_settings_rejects_unknown_sslmode() -> None:
    env = dict(VALID_ENV, PG_SSLMODE="secure")

    with pytest.raises(ConfigError) as error:
        load_settings(env)

    assert "PG_SSLMODE" in str(error.value)
