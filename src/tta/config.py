"""Centralized application configuration from environment variables."""

from enum import StrEnum
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Deployment environment."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Supported log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class Settings(BaseSettings):
    """TTA application configuration from environment variables."""

    model_config = SettingsConfigDict(env_prefix="TTA_")

    # PostgreSQL (required)
    database_url: str

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, v: str) -> str:
        if not v.startswith(("postgresql://", "postgresql+asyncpg://")):
            msg = "database_url must start with postgresql:// or postgresql+asyncpg://"
            raise ValueError(msg)
        return v

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Neo4j
    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str

    # LiteLLM
    litellm_model: str = "openai/gpt-4o-mini"
    litellm_fallback_model: str = "openai/gpt-4o-mini"
    llm_mock: bool = False

    # Pipeline / cost
    session_cost_cap_usd: float = 1.0
    pipeline_timeout_seconds: float = 120.0

    # Langfuse (optional)
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None

    # OpenTelemetry (optional)
    otel_enabled: bool = False
    otel_endpoint: str = "http://localhost:4317"

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    # Cost tracking (S15 §4 US-15.11)
    daily_llm_cost_alert_usd: float = 50.0

    # Application
    session_token_ttl: int = 86400
    max_active_games: int = 5
    max_input_length: int = 2000
    log_level: LogLevel = LogLevel.INFO
    log_format: str = "json"
    log_sensitive: bool = False
    environment: Environment = Environment.DEVELOPMENT


@lru_cache
def get_settings() -> Settings:
    """Singleton access to application settings."""
    return Settings()  # type: ignore[reportCallIssue]  # env vars via pydantic-settings
