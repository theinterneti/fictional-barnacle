"""Universe Composition Model (S39).

Implements the 4-layer composition schema:
  themes (≤5), tropes (≤10), archetypes (≤8), genre_twists (≤3)

``config["seed"]`` lives at the **top level** of ``universes.config`` JSONB — NOT
inside the ``composition`` block.  ``config["composition"]`` holds the
``UniverseComposition`` blob.

An empty config ``{}`` is always valid — seed is auto-generated on first session
open (AC-39.02).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal
from uuid import UUID

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Leaf dataclasses (Appendix A of S39 spec)
# ---------------------------------------------------------------------------


@dataclass
class ThemeSpec:
    name: str
    weight: float = 0.5
    description: str | None = None


@dataclass
class TropeSpec:
    name: str
    weight: float = 0.5
    required: bool = False
    description: str | None = None


@dataclass
class ArchetypeSpec:
    name: str
    npc_tier: Literal["key", "supporting"] = "supporting"
    weight: float = 0.5
    description: str | None = None


@dataclass
class GenreTwist:
    name: str
    strength: float = 0.5
    description: str | None = None


@dataclass
class ProseConfig:
    voice: str = "default"
    pacing: Literal["slow", "balanced", "fast"] = "balanced"
    description_density: Literal["sparse", "medium", "rich"] = "medium"
    second_person: bool = True


@dataclass
class ToneProfile:
    primary: str = "neutral"
    secondary: str | None = None
    warmth: float = 0.5
    intensity: float = 0.5


# ---------------------------------------------------------------------------
# Tone derivation  (derived at parse time — not stored)
# ---------------------------------------------------------------------------

_DARK_KEYWORDS = frozenset(
    {
        "cosmic_horror",
        "existential_dread",
        "decay",
        "horror",
        "dread",
        "darkness",
        "void",
        "nihil",
    }
)
_COZY_KEYWORDS = frozenset(
    {
        "cozy",
        "warm",
        "cheerful",
        "light",
        "hopeful",
        "comfort",
        "peaceful",
        "gentle",
    }
)


def derive_tone_profile(keywords: list[str]) -> ToneProfile:
    """Derive a ToneProfile from a list of keyword strings (AC-39.06).

    Each keyword is tokenised on non-word boundaries; tokens are matched
    against the dark/cozy signal sets.

    Dark signals → warmth=0.2, intensity=0.8.
    Cozy signals → warmth=0.9, intensity=0.2.
    Mixed or absent → default warmth=0.5, intensity=0.5.
    """
    tokens: set[str] = set()
    for kw in keywords:
        for part in re.split(r"\W+", kw.lower()):
            if part:
                tokens.add(part)

    has_dark = bool(tokens & _DARK_KEYWORDS)
    has_cozy = bool(tokens & _COZY_KEYWORDS)

    if has_dark and not has_cozy:
        return ToneProfile(primary="dark", warmth=0.2, intensity=0.8)
    if has_cozy and not has_dark:
        return ToneProfile(primary="cozy", warmth=0.9, intensity=0.2)
    return ToneProfile()


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_VALID_PACING = frozenset({"slow", "balanced", "fast"})
_VALID_DENSITY = frozenset({"sparse", "medium", "rich"})
_VALID_NPC_TIER = frozenset({"key", "supporting"})

# Subsystem namespaces that CompositionValidator must never touch
_RESERVED_NAMESPACES = frozenset({"memory", "time", "npc"})

_DEFAULT_MAX_LIMITS = {"themes": 5, "tropes": 10, "archetypes": 8, "genre_twists": 3}


def _max_limit(field_max: int | None, key: str) -> int:
    return field_max if field_max is not None else _DEFAULT_MAX_LIMITS[key]


class CompositionValidator:
    """Validates a ``UniverseComposition`` against S39 rules (AC-39.07/08).

    NFR-39.01: validation < 5ms.
    """

    def validate(
        self, comp: UniverseComposition, universe_id: UUID | None = None
    ) -> list[str]:
        """Return a list of validation error strings (empty = valid)."""
        if comp.composition_version != "1.0":
            return [
                f"composition_version {comp.composition_version!r} is not supported"
            ]

        errors: list[str] = []

        # Count limits (AC-39.08/39.09)
        lim_themes = _max_limit(comp.max_themes, "themes")
        if len(comp.themes) > lim_themes:
            errors.append(f"themes: max {lim_themes}, got {len(comp.themes)}")
        lim_tropes = _max_limit(comp.max_tropes, "tropes")
        if len(comp.tropes) > lim_tropes:
            errors.append(f"tropes: max {lim_tropes}, got {len(comp.tropes)}")
        lim_archetypes = _max_limit(comp.max_archetypes, "archetypes")
        if len(comp.archetypes) > lim_archetypes:
            errors.append(
                f"archetypes: max {lim_archetypes}, got {len(comp.archetypes)}"
            )
        lim_twists = _max_limit(comp.max_genre_twists, "genre_twists")
        if len(comp.genre_twists) > lim_twists:
            errors.append(
                f"genre_twists: max {lim_twists}, got {len(comp.genre_twists)}"
            )

        # Name pattern
        for theme in comp.themes:
            if not _NAME_RE.match(theme.name):
                errors.append(
                    f"themes[{theme.name!r}]: name must match ^[a-z][a-z0-9_]*$"
                )
            if not 0.0 <= theme.weight <= 1.0:
                errors.append(f"themes[{theme.name!r}]: weight must be 0.0–1.0")

        for trope in comp.tropes:
            if not _NAME_RE.match(trope.name):
                errors.append(
                    f"tropes[{trope.name!r}]: name must match ^[a-z][a-z0-9_]*$"
                )
            if not 0.0 <= trope.weight <= 1.0:
                errors.append(f"tropes[{trope.name!r}]: weight must be 0.0–1.0")

        for arch in comp.archetypes:
            if not _NAME_RE.match(arch.name):
                errors.append(
                    f"archetypes[{arch.name!r}]: name must match ^[a-z][a-z0-9_]*$"
                )
            if arch.npc_tier not in _VALID_NPC_TIER:
                errors.append(
                    f"archetypes[{arch.name!r}]: npc_tier must be 'key' or 'supporting'"
                )
            if not 0.0 <= arch.weight <= 1.0:
                errors.append(f"archetypes[{arch.name!r}]: weight must be 0.0–1.0")

        for twist in comp.genre_twists:
            if not _NAME_RE.match(twist.name):
                errors.append(
                    f"genre_twists[{twist.name!r}]: name must match ^[a-z][a-z0-9_]*$"
                )
            if not 0.0 <= twist.strength <= 1.0:
                errors.append(f"genre_twists[{twist.name!r}]: strength must be 0.0–1.0")

        # ProseConfig
        if comp.prose.pacing not in _VALID_PACING:
            errors.append(
                f"prose.pacing must be one of {sorted(_VALID_PACING)}, "
                f"got {comp.prose.pacing!r}"
            )
        if comp.prose.description_density not in _VALID_DENSITY:
            errors.append(
                f"prose.description_density must be one of {sorted(_VALID_DENSITY)}, "
                f"got {comp.prose.description_density!r}"
            )

        log.info(
            "composition_validated",
            universe_id=str(universe_id) if universe_id else None,
            composition_version=comp.composition_version,
            validation_result="ok" if not errors else "error",
        )
        return errors


_VALIDATOR = CompositionValidator()


# ---------------------------------------------------------------------------
# Root composition dataclass with factory + serialisation helpers
# ---------------------------------------------------------------------------


@dataclass
class UniverseComposition:
    composition_version: str = "1.0"
    primary_genre: str = "fantasy"
    themes: list[ThemeSpec] = field(default_factory=list)
    tropes: list[TropeSpec] = field(default_factory=list)
    archetypes: list[ArchetypeSpec] = field(default_factory=list)
    genre_twists: list[GenreTwist] = field(default_factory=list)
    prose: ProseConfig = field(default_factory=ProseConfig)
    tone: ToneProfile = field(default_factory=ToneProfile)
    max_themes: int | None = None
    max_tropes: int | None = None
    max_archetypes: int | None = None
    max_genre_twists: int | None = None

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> UniverseComposition:
        """Parse a ``universes.config`` JSONB dict into a ``UniverseComposition``.

        An empty (or absent) ``composition`` key returns a default instance
        (AC-39.01).  ToneProfile is derived at parse time — not read from the
        stored blob (NFR-39.02: parse < 2ms).
        """
        blob: dict[str, Any] = config.get("composition", {}) or {}

        themes = [ThemeSpec(**t) for t in blob.get("themes", [])]
        tropes = [TropeSpec(**t) for t in blob.get("tropes", [])]
        archetypes = [ArchetypeSpec(**a) for a in blob.get("archetypes", [])]
        genre_twists = [GenreTwist(**g) for g in blob.get("genre_twists", [])]

        prose_data = blob.get("prose", {})
        prose = ProseConfig(**prose_data) if prose_data else ProseConfig()

        comp = cls(
            composition_version=blob.get("composition_version", "1.0"),
            primary_genre=blob.get("primary_genre", "fantasy"),
            themes=themes,
            tropes=tropes,
            archetypes=archetypes,
            genre_twists=genre_twists,
            prose=prose,
            max_themes=blob.get("max_themes"),
            max_tropes=blob.get("max_tropes"),
            max_archetypes=blob.get("max_archetypes"),
            max_genre_twists=blob.get("max_genre_twists"),
        )
        # Preserve stored primary/secondary if present; otherwise derive from keywords
        tone_blob = blob.get("tone", {})
        if tone_blob.get("primary"):
            comp.tone = ToneProfile(
                primary=tone_blob["primary"],
                secondary=tone_blob.get("secondary"),
            )
        else:
            kw_sources: list[str] = [comp.primary_genre]
            kw_sources += [t.name for t in themes]
            kw_sources += [t.name for t in tropes]
            comp.tone = derive_tone_profile(kw_sources)
        return comp

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict suitable for storing as JSONB.

        ``warmth`` and ``intensity`` are derived at load time and excluded.
        ``primary`` and ``secondary`` are stored so explicit FR-39.07a author
        overrides survive a save→load round-trip.
        """
        d = asdict(self)
        tone = d.pop("tone", None)
        if tone and tone.get("primary"):
            d["tone"] = {"primary": tone["primary"], "secondary": tone.get("secondary")}
        return d

    # ------------------------------------------------------------------
    # Context injection
    # ------------------------------------------------------------------

    def get_context_fragment(self) -> str:
        """Return a prose fragment injected into generation prompts (AC-39.06).

        Includes: primary genre, prose voice/pacing, tone primary, and any
        themes with weight ≥ 0.4.
        """
        lines: list[str] = []

        lines.append(f"Genre: {self.primary_genre}")
        lines.append(
            f"Prose: {self.prose.voice} voice, {self.prose.pacing} pacing, "
            f"{self.prose.description_density} description density"
        )
        lines.append(
            f"Tone: {self.tone.primary}"
            + (f" / {self.tone.secondary}" if self.tone.secondary else "")
        )

        heavy_themes = [
            f"{t.name} ({t.weight:.1f})" for t in self.themes if t.weight >= 0.4
        ]
        if heavy_themes:
            lines.append("Themes: " + ", ".join(heavy_themes))

        req_tropes = [t.name for t in self.tropes if t.required]
        if req_tropes:
            lines.append("Required tropes: " + ", ".join(req_tropes))

        return "\n".join(lines)
