"""Model role definitions for LLM routing."""

from enum import StrEnum


class ModelRole(StrEnum):
    """Semantic role that determines which model to use."""

    GENERATION = "generation"
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
