"""Centralized application configuration from environment variables."""

from enum import StrEnum
from functools import lru_cache

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

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str

    # LiteLLM
    litellm_model: str = "openai/gpt-4o-mini"
    litellm_fallback_model: str = "openai/gpt-4o-mini"

    # Langfuse (optional)
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None

    # CORS
    cors_origins: list[str] = ["*"]

    # Application
    session_token_ttl: int = 86400
    log_level: LogLevel = LogLevel.INFO
    log_format: str = "json"
    environment: Environment = Environment.DEVELOPMENT


@lru_cache
def get_settings() -> Settings:
    """Singleton access to application settings."""
    return Settings()  # type: ignore[reportCallIssue]  # env vars via pydantic-settings
