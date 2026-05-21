"""Tests for TTA configuration model."""

import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from tta.config import Environment, LogLevel, Settings, get_settings

# Required env vars for a valid Settings instance
REQUIRED_ENV = {
    "TTA_DATABASE_URL": "postgresql://user:password@localhost/tta",
    "TTA_NEO4J_PASSWORD": "secret",
}

_SENTINEL = object()


def build_settings(*, env_file: object = _SENTINEL, **overrides: Any) -> Settings:
    """Construct ``Settings`` while allowing tests to control dotenv loading."""
    kwargs: dict[str, Any] = dict(overrides)
    if env_file is not _SENTINEL:
        kwargs["_env_file"] = env_file
    return Settings(**kwargs)  # type: ignore[reportCallIssue]


@pytest.fixture(autouse=True)
def _clean_tta_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all TTA_ env vars so host env doesn't leak into tests."""
    for key in list(os.environ):
        if key.startswith("TTA_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the minimum required env vars."""
    for key, val in REQUIRED_ENV.items():
        monkeypatch.setenv(key, val)


class TestSettingsInstantiation:
    """Settings can be created with required env vars."""

    def test_with_required_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key, val in REQUIRED_ENV.items():
            monkeypatch.setenv(key, val)
        s = build_settings(env_file=None)
        assert s.database_url == REQUIRED_ENV["TTA_DATABASE_URL"]
        assert s.neo4j_password == REQUIRED_ENV["TTA_NEO4J_PASSWORD"]

    def test_missing_database_url_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TTA_NEO4J_PASSWORD", "secret")
        with pytest.raises(ValidationError):
            build_settings(env_file=None)

    def test_missing_neo4j_password_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TTA_DATABASE_URL", "postgresql://x@localhost/tta")
        with pytest.raises(ValidationError):
            build_settings(env_file=None)


class TestDefaults:
    """Unset optional fields fall back to code defaults."""

    @pytest.mark.usefixtures("_set_required_env")
    def test_default_values(self) -> None:
        s = build_settings(env_file=None)
        assert s.redis_url == "redis://localhost:6379"
        assert s.neo4j_uri == ""
        assert s.neo4j_user == "neo4j"
        assert s.llm_backend == "openai"
        assert s.openai_api_base == "http://localhost:3456/v1"
        assert s.openai_api_key == ""
        assert s.litellm_model == "openai/gpt-4o-mini"
        assert s.litellm_fallback_model == "openai/gpt-4o-mini"
        assert s.environment == Environment.DEVELOPMENT
        assert s.log_level == LogLevel.INFO
        assert s.idle_timeout_minutes == 30
        assert s.session_token_ttl == 86400

    @pytest.mark.usefixtures("_set_required_env")
    def test_langfuse_defaults_none(self) -> None:
        s = build_settings(env_file=None)
        assert s.langfuse_host is None
        assert s.langfuse_public_key is None
        assert s.langfuse_secret_key is None


class TestEnumValidation:
    """StrEnum fields reject invalid values."""

    def test_valid_log_levels(self) -> None:
        for level in LogLevel:
            s = build_settings(
                env_file=None,
                database_url="postgresql://x@localhost/tta",
                neo4j_password="s",
                log_level=level,
            )
            assert s.log_level == level

    def test_valid_environments(self) -> None:
        for env in Environment:
            s = build_settings(
                env_file=None,
                database_url="postgresql://x@localhost/tta",
                neo4j_password="s",
                environment=env,
                jwt_secret="test-secret-that-is-not-the-default-value",
            )
            assert s.environment == env

    def test_invalid_log_level_rejected(self) -> None:
        with pytest.raises(ValidationError):
            build_settings(
                env_file=None,
                database_url="postgresql://x@localhost/tta",
                neo4j_password="s",
                log_level="TRACE",
            )

    def test_invalid_environment_rejected(self) -> None:
        with pytest.raises(ValidationError):
            build_settings(
                env_file=None,
                database_url="postgresql://x@localhost/tta",
                neo4j_password="s",
                environment="local",
            )


class TestEnvPrefix:
    """TTA_ prefix maps env vars to fields."""

    def test_prefix_mapping(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TTA_DATABASE_URL", "postgresql://x@localhost/tta")
        monkeypatch.setenv("TTA_NEO4J_PASSWORD", "pw")
        monkeypatch.setenv("TTA_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("TTA_ENVIRONMENT", "production")
        monkeypatch.setenv("TTA_JWT_SECRET", "test-secret-not-default")
        s = build_settings(env_file=None)
        assert s.log_level == LogLevel.DEBUG
        assert s.environment == Environment.PRODUCTION

    def test_dotenv_file_is_loaded_from_cwd(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        dotenv = tmp_path / ".env"
        dotenv.write_text(
            "TTA_DATABASE_URL=postgresql://dotenv@localhost/tta\n"
            "TTA_NEO4J_PASSWORD=dotenv-secret\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)

        s = build_settings()

        assert s.database_url == "postgresql://dotenv@localhost/tta"
        assert s.neo4j_password == "dotenv-secret"

    def test_environment_variables_override_dotenv(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        dotenv = tmp_path / ".env"
        dotenv.write_text(
            "TTA_DATABASE_URL=postgresql://dotenv@localhost/tta\n"
            "TTA_NEO4J_PASSWORD=dotenv-secret\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("TTA_DATABASE_URL", "postgresql://env@localhost/tta")
        monkeypatch.setenv("TTA_NEO4J_PASSWORD", "env-secret")

        s = build_settings(env_file=dotenv)

        assert s.database_url == "postgresql://env@localhost/tta"
        assert s.neo4j_password == "env-secret"


class TestGetSettings:
    """get_settings() returns a cached singleton."""

    def test_returns_same_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key, val in REQUIRED_ENV.items():
            monkeypatch.setenv(key, val)
        monkeypatch.chdir("/")
        get_settings.cache_clear()
        first = get_settings()
        second = get_settings()
        assert first is second
