"""Data classification registry per S17 §2.

Every data field is classified into one of four categories.
PII fields can be queried programmatically (FR-17.5).
"""

from enum import StrEnum


class DataCategory(StrEnum):
    """S17 FR-17.3 — four-tier data classification."""

    PII = "pii"
    SENSITIVE_GAME_DATA = "sensitive_game_data"
    GAME_DATA = "game_data"
    SYSTEM_DATA = "system_data"


class FieldClassification:
    """A single field's classification metadata."""

    __slots__ = ("category", "erasable", "name", "retention_days", "storage")

    def __init__(
        self,
        name: str,
        category: DataCategory,
        storage: str,
        retention_days: int | None,
        *,
        erasable: bool = True,
    ) -> None:
        self.name = name
        self.category = category
        self.storage = storage
        self.retention_days = retention_days
        self.erasable = erasable


# S17 §1.2 FR-17.1 — complete data inventory
_FIELD_REGISTRY: list[FieldClassification] = [
    # Player profile data
    FieldClassification(
        "player_id", DataCategory.PII, "postgresql", None, erasable=True
    ),
    FieldClassification(
        "display_name", DataCategory.PII, "postgresql", None, erasable=True
    ),
    FieldClassification("email", DataCategory.PII, "postgresql", None, erasable=True),
    FieldClassification(
        "password_hash", DataCategory.PII, "postgresql", None, erasable=True
    ),
    FieldClassification(
        "account_created_at",
        DataCategory.SYSTEM_DATA,
        "postgresql",
        None,
    ),
    FieldClassification(
        "last_login",
        DataCategory.SYSTEM_DATA,
        "postgresql",
        None,
    ),
    FieldClassification(
        "consent_records",
        DataCategory.PII,
        "postgresql",
        None,
        erasable=False,
    ),
    # Consent & age gate (S17 FR-17.22, GDPR Art. 7(1) — retained for legal proof)
    FieldClassification(
        "consent_version", DataCategory.PII, "postgresql", None, erasable=False
    ),
    FieldClassification(
        "consent_accepted_at", DataCategory.PII, "postgresql", None, erasable=False
    ),
    FieldClassification(
        "consent_categories", DataCategory.PII, "postgresql", None, erasable=False
    ),
    FieldClassification(
        "age_confirmed_at", DataCategory.PII, "postgresql", None, erasable=False
    ),
    FieldClassification(
        "consent_ip_hash", DataCategory.PII, "postgresql", None, erasable=False
    ),
    # Game state data
    FieldClassification("world_state", DataCategory.GAME_DATA, "neo4j", 30),
    FieldClassification(
        "narrative_history",
        DataCategory.SENSITIVE_GAME_DATA,
        "neo4j",
        30,
    ),
    FieldClassification("player_choices", DataCategory.GAME_DATA, "neo4j", 30),
    FieldClassification(
        "session_metadata_live",
        DataCategory.SYSTEM_DATA,
        "redis",
        1,
    ),
    FieldClassification(
        "session_metadata_archived",
        DataCategory.SYSTEM_DATA,
        "postgresql",
        90,
    ),
    FieldClassification("game_progress", DataCategory.GAME_DATA, "postgresql", None),
    # LLM interaction data
    FieldClassification(
        "player_input",
        DataCategory.SENSITIVE_GAME_DATA,
        "langfuse",
        90,
    ),
    FieldClassification("system_prompts", DataCategory.SYSTEM_DATA, "langfuse", 90),
    FieldClassification("llm_responses", DataCategory.GAME_DATA, "langfuse", 90),
    FieldClassification("token_counts", DataCategory.SYSTEM_DATA, "prometheus", 30),
    FieldClassification("model_used", DataCategory.SYSTEM_DATA, "langfuse", 90),
    # Operational data
    FieldClassification("application_logs", DataCategory.SYSTEM_DATA, "stdout", 30),
    FieldClassification("metrics", DataCategory.SYSTEM_DATA, "prometheus", 30),
    FieldClassification("traces", DataCategory.SYSTEM_DATA, "jaeger", 7),
    FieldClassification("error_reports", DataCategory.SYSTEM_DATA, "stdout", 30),
]


def classify_field(name: str) -> FieldClassification | None:
    """Look up a field's classification by name."""
    for field in _FIELD_REGISTRY:
        if field.name == name:
            return field
    return None


def get_pii_fields() -> list[FieldClassification]:
    """Return all fields classified as PII (FR-17.5)."""
    return [f for f in _FIELD_REGISTRY if f.category == DataCategory.PII]


def get_fields_by_category(
    category: DataCategory,
) -> list[FieldClassification]:
    """Return all fields in a given category."""
    return [f for f in _FIELD_REGISTRY if f.category == category]


def get_all_fields() -> list[FieldClassification]:
    """Return the full field registry."""
    return list(_FIELD_REGISTRY)
