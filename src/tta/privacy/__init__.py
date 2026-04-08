"""Privacy module — data classification, retention, and cost tracking.

Spec refs: S17 (Data Privacy), S15 §1.3 (privacy filtering).
"""

from tta.privacy.classification import (
    DataCategory,
    FieldClassification,
    classify_field,
    get_pii_fields,
)
from tta.privacy.cost import (
    LLMCostTracker,
    ModelPricing,
    estimate_cost,
    get_cost_tracker,
)
from tta.privacy.retention import (
    RetentionPolicy,
    get_retention_policy,
)

__all__ = [
    "DataCategory",
    "FieldClassification",
    "LLMCostTracker",
    "ModelPricing",
    "RetentionPolicy",
    "classify_field",
    "estimate_cost",
    "get_cost_tracker",
    "get_pii_fields",
    "get_retention_policy",
]
