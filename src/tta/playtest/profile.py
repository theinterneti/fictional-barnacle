"""TasteProfile and built-in persona templates for S42.

Spec §4 defines the 8-field TasteProfile and 5 named personas.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_PERSONAS_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "personas"
)

JITTER_MAGNITUDE = 0.15  # ±jitter applied to float fields on persona instantiation


@dataclass(frozen=True)
class TasteProfile:
    """8-field taste profile controlling playtester behaviour (FR-42.01, §4.1).

    Float fields are clamped to [0.0, 1.0].
    """

    # Response style
    verbosity: float  # 0.0 terse – 1.0 verbose
    boldness: float  # 0.0 cautious – 1.0 impulsive
    curiosity: float  # 0.0 passive – 1.0 probing

    # Narrative preferences
    genre_affinity: str  # e.g. 'horror', 'comedy'
    tone_affinity: str  # e.g. 'dark', 'hopeful'
    trope_affinity: tuple[str, ...] = field(default_factory=tuple)  # 0-3 tropes

    # Engagement model
    attention_span: float = 0.8  # 0.0 disengages fast – 1.0 plays full session
    meta_awareness: float = 0.1  # 0.0 in-world – 1.0 notes game mechanics

    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    @classmethod
    def from_template(
        cls,
        template: dict,
        rng: random.Random | None = None,
        jitter: bool = True,
    ) -> TasteProfile:
        """Build a TasteProfile from a raw template dict.

        If *jitter* is True, float fields are nudged by ±JITTER_MAGNITUDE
        using *rng* (or a new Random if none given).
        """
        if rng is None:
            rng = random.Random()

        def maybe_jitter(v: float) -> float:
            if not jitter:
                return cls._clamp(v)
            delta = rng.uniform(-JITTER_MAGNITUDE, JITTER_MAGNITUDE)
            return cls._clamp(v + delta)

        tropes = tuple(template.get("trope_affinity", [])[:3])
        return cls(
            verbosity=maybe_jitter(float(template["verbosity"])),
            boldness=maybe_jitter(float(template["boldness"])),
            curiosity=maybe_jitter(float(template["curiosity"])),
            genre_affinity=template["genre_affinity"],
            tone_affinity=template["tone_affinity"],
            trope_affinity=tropes,
            attention_span=maybe_jitter(float(template.get("attention_span", 0.8))),
            meta_awareness=maybe_jitter(float(template.get("meta_awareness", 0.1))),
        )


def _load_builtin_personas() -> dict[str, dict]:
    """Load all persona YAML files from data/personas/."""
    personas: dict[str, dict] = {}
    if not _PERSONAS_DIR.exists():
        return personas
    for path in sorted(_PERSONAS_DIR.glob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if isinstance(data, dict) and "persona_id" in data:
            personas[data["persona_id"]] = data
    return personas


# Module-level cache — loaded once per process.
BUILTIN_PERSONAS: dict[str, dict] = _load_builtin_personas()


def get_taste_profile(
    persona_id: str,
    jitter_seed: int,
    jitter: bool = True,
) -> TasteProfile:
    """Return a TasteProfile for *persona_id* with reproducible jitter.

    Raises KeyError if persona_id is not found.
    """
    template = BUILTIN_PERSONAS[persona_id]
    rng = random.Random(jitter_seed)
    return TasteProfile.from_template(template, rng=rng, jitter=jitter)
