"""Tests for TTA configuration model."""

import pytest
from pydantic import ValidationError

from tta.config import Environment, LogLevel, Settings, get_settings

# Required env vars for a valid Settings instance
REQUIRED_ENV = {
    "TTA_DATABASE_URL": "postgresql://user:pass@localhost/tta",
    "TTA_NEO4J_PASSWORD": "secret",
}


@pytest.fixture()
def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the minimum required env vars."""
    for key, val in REQUIRED_ENV.items():
        monkeypatch.setenv(key, val)


class TestSettingsInstantiation:
    """Settings can be created with required env vars."""

    def test_with_required_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for key, val in REQUIRED_ENV.items():
            monkeypatch.setenv(key, val)
        s = Settings()
        assert s.database_url == REQUIRED_ENV["TTA_DATABASE_URL"]
        assert s.neo4j_password == REQUIRED_ENV["TTA_NEO4J_PASSWORD"]

    def test_missing_database_url_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TTA_NEO4J_PASSWORD", "secret")
        with pytest.raises(ValidationError):
            Settings()

    def test_missing_neo4j_password_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "TTA_DATABASE_URL", "postgresql://x@localhost/tta"
        )
        with pytest.raises(ValidationError):
            Settings()


class TestDefaults:
    """Default values are applied correctly."""

    @pytest.mark.usefixtures("_set_required_env")
    def test_default_values(self) -> None:
        s = Settings()
        assert s.redis_url == "redis://localhost:6379"
        assert s.neo4j_uri == "bolt://localhost:7687"
        assert s.neo4j_user == "neo4j"
        assert s.litellm_model == "openai/gpt-4o-mini"
        assert s.litellm_fallback_model == "openai/gpt-4o-mini"
        assert s.session_token_ttl == 86400
        assert s.log_level == LogLevel.INFO
        assert s.log_format == "json"
        assert s.environment == Environment.DEVELOPMENT

    @pytest.mark.usefixtures("_set_required_env")
    def test_langfuse_defaults_none(self) -> None:
        s = Settings()
        assert s.langfuse_host is None
        assert s.langfuse_public_key is None
        assert s.langfuse_secret_key is None


class TestEnumValidation:
    """StrEnum fields reject invalid values."""

    def test_valid_log_levels(self) -> None:
        for level in LogLevel:
            s = Settings(
                database_url="postgresql://x@localhost/tta",
                neo4j_password="s",
                log_level=level,
            )
            assert s.log_level == level

    def test_valid_environments(self) -> None:
        for env in Environment:
            s = Settings(
                database_url="postgresql://x@localhost/tta",
                neo4j_password="s",
                environment=env,
            )
            assert s.environment == env

    def test_invalid_log_level_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(
                database_url="postgresql://x@localhost/tta",
                neo4j_password="s",
                log_level="TRACE",  # type: ignore[arg-type]
            )

    def test_invalid_environment_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(
                database_url="postgresql://x@localhost/tta",
                neo4j_password="s",
                environment="local",  # type: ignore[arg-type]
            )


class TestEnvPrefix:
    """TTA_ prefix maps env vars to fields."""

    def test_prefix_mapping(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "TTA_DATABASE_URL", "postgresql://x@localhost/tta"
        )
        monkeypatch.setenv("TTA_NEO4J_PASSWORD", "pw")
        monkeypatch.setenv("TTA_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("TTA_ENVIRONMENT", "production")
        s = Settings()
        assert s.log_level == LogLevel.DEBUG
        assert s.environment == Environment.PRODUCTION


class TestGetSettings:
    """get_settings() returns a cached singleton."""

    def test_returns_same_instance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for key, val in REQUIRED_ENV.items():
            monkeypatch.setenv(key, val)
        # Clear any prior cache
        get_settings.cache_clear()
        first = get_settings()
        second = get_settings()
        assert first is second
