"""Centralized application configuration from environment variables."""

from __future__ import annotations

import json
from enum import StrEnum
from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, EnvSettingsSource, SettingsConfigDict

# S17 FR-17.22 — consent version & required categories
CURRENT_CONSENT_VERSION = "1.0"
REQUIRED_CONSENT_CATEGORIES: frozenset[str] = frozenset(
    {"core_gameplay", "llm_processing"}
)


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


class _TtaEnvSource(EnvSettingsSource):
    """Custom env source that accepts CSV for ``cors_origins``."""

    def decode_complex_value(
        self,
        field_name: str,
        field: Any,
        value: Any,
    ) -> Any:
        if field_name == "cors_origins" and isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, ValueError):
                return [s.strip() for s in value.split(",") if s.strip()]
        return super().decode_complex_value(field_name, field, value)


class Settings(BaseSettings):
    """TTA application configuration from environment variables."""

    model_config = SettingsConfigDict(env_prefix="TTA_")

    @classmethod
    def settings_customise_sources(  # type: ignore[override]
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        return (
            init_settings,
            _TtaEnvSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )

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
    session_cost_warn_pct: float = 0.8
    turn_cost_cap_usd: float = 0.10
    pipeline_timeout_seconds: float = 120.0

    # Langfuse (optional)
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None

    # OpenTelemetry (optional)
    otel_enabled: bool = False
    otel_endpoint: str = "http://localhost:4317"

    # CORS
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8080"]

    # Cost tracking (S15 §4 US-15.11)
    daily_llm_cost_alert_usd: float = 50.0
    llm_pricing_path: str | None = None

    # Rate limiting (S25 §3.2)
    rate_limit_enabled: bool = True
    rate_limit_turns_per_minute: int = 10
    rate_limit_game_mgmt_per_minute: int = 30
    rate_limit_auth_per_minute: int = 10
    rate_limit_sse_per_minute: int = 5

    # Anti-abuse detection (S25 §3.5)
    anti_abuse_enabled: bool = True
    anti_abuse_max_cooldown: int = 86400  # 24 hours cap (FR-25.11)

    # Content moderation (S24)
    moderation_enabled: bool = True
    moderation_fail_mode: str = "open"  # "open" | "closed"
    # Per-category verdict overrides (FR-24.05). JSON dict mapping
    # category name → verdict name, e.g. '{"off_topic": "block"}'.
    # Only applies to overridable categories; ALWAYS_BLOCK cannot
    # be relaxed.
    moderation_category_overrides: str = "{}"
    # Session auto-flagging thresholds (FR-24.11)
    moderation_flag_threshold: int = 5  # N blocked actions
    moderation_flag_window_minutes: int = 10  # within M minutes

    @field_validator("moderation_fail_mode")
    @classmethod
    def _validate_moderation_fail_mode(cls, v: str) -> str:
        if v not in ("open", "closed"):
            msg = "moderation_fail_mode must be 'open' or 'closed'"
            raise ValueError(msg)
        return v

    # --- S28 Performance & Scaling ---

    # PostgreSQL pool (FR-28.07) — wired into build_engine() via app.py
    pg_pool_min: int = 5
    pg_pool_max: int = 20
    pg_pool_timeout: int = 5  # seconds
    pg_pool_idle_timeout: int = 300  # seconds

    # Redis pool (FR-28.08) — ready for wiring when Redis adapter lands
    redis_pool_max: int = 20
    redis_timeout: int = 2  # seconds
    redis_retry_count: int = 3

    # Neo4j pool (FR-28.09) — ready for wiring when Neo4j adapter lands
    neo4j_pool_max: int = 10
    neo4j_timeout: int = 5  # seconds

    # LLM concurrency (FR-28.11–FR-28.14)
    llm_max_concurrent: int = 10
    llm_queue_size: int = 50
    llm_timeout: int = 30  # seconds
    # Token limits — ready for wiring in prompt builder / turn pipeline
    llm_max_input_tokens: int = 4000
    llm_max_output_tokens: int = 2000

    # Latency budget (S28 §3.3 guidance)
    latency_budget_warn_ms: int = 5000
    latency_budget_abort_ms: int = 30000

    # --- S26 Admin ---
    admin_api_key: str = ""

    # Auto-save / resume (S27 FR-27.05–FR-27.15)
    resume_turn_count: int = 10  # recent turns loaded on resume
    summary_interval: int = 5  # regen summary every N turns
    summary_staleness_hours: int = 24  # force regen if older
    summary_model: str = ""  # lighter model for summaries; empty = use default

    # SSE heartbeat (FR-10.39)
    sse_heartbeat_interval: float = 15.0

    @field_validator("sse_heartbeat_interval")
    @classmethod
    def _validate_heartbeat(cls, v: float) -> float:
        if v <= 0:
            msg = "sse_heartbeat_interval must be positive"
            raise ValueError(msg)
        if v > 15.0:
            msg = "sse_heartbeat_interval must be <= 15s (FR-10.38)"
            raise ValueError(msg)
        return v

    # JWT / Auth (S11, FR-11.29 lifetimes)
    jwt_secret: str = "CHANGE-ME-IN-PRODUCTION"
    jwt_algorithm: str = "HS256"
    access_token_ttl: int = 3_600  # 1 h registered (FR-11.29)
    anon_access_token_ttl: int = 86_400  # 24 h anonymous (FR-11.29)
    refresh_token_ttl: int = 2_592_000  # 30 d registered (FR-11.29)
    anon_refresh_token_ttl: int = 604_800  # 7 d anonymous (FR-11.29)
    bcrypt_cost: int = 12
    anon_max_active_games: int = 1
    anon_cleanup_days: int = 30

    # Application
    session_token_ttl: int = 86400  # legacy, kept for compat
    max_active_games: int = 5
    game_listing_default_size: int = 10
    game_listing_max_size: int = 50
    max_input_length: int = 2000
    log_level: LogLevel = LogLevel.INFO
    log_format: str = "json"
    log_sensitive: bool = False
    idle_timeout_minutes: int = 30
    environment: Environment = Environment.DEVELOPMENT


@lru_cache
def get_settings() -> Settings:
    """Singleton access to application settings."""
    return Settings()  # type: ignore[reportCallIssue]  # env vars via pydantic-settings
