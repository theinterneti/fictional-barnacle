"""Tests for S39 — Universe Composition Model (AC-39.01–39.12).

Validates:
- Composition dataclass parsing and validation
- ToneProfile derivation
- Context fragment generation
- Seed immutability and auto-generation
- Empty config acceptance
"""

from __future__ import annotations

import pytest
import structlog.testing

from tta.universe.composition import (
    CompositionValidator,
    UniverseComposition,
    derive_tone_profile,
)

# ---------------------------------------------------------------------------
# AC-39.01 — Empty config is valid; defaults are well-defined
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-39.01")
def test_empty_config_is_valid() -> None:
    comp = UniverseComposition.from_config({})
    assert comp is not None
    assert comp.themes == []
    assert comp.tropes == []
    assert comp.archetypes == []
    assert comp.genre_twists == []


@pytest.mark.spec("AC-39.01")
def test_none_composition_block_is_valid() -> None:
    comp = UniverseComposition.from_config({"composition": None})
    assert comp is not None


# ---------------------------------------------------------------------------
# AC-39.02 — Seed auto-generated if absent; empty config treated as valid
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-39.02")
def test_composition_round_trips_without_seed() -> None:
    """from_config/to_dict round-trip should not inject a seed."""
    config = {
        "composition": {
            "primary_genre": "urban_fantasy",
            "themes": [{"name": "loss", "weight": 0.7}],
        }
    }
    comp = UniverseComposition.from_config(config)
    d = comp.to_dict()
    assert "seed" not in d


# ---------------------------------------------------------------------------
# AC-39.03 — Composition stored with composition_version = "1.0"
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-39.03")
def test_to_dict_includes_composition_version() -> None:
    comp = UniverseComposition.from_config({})
    d = comp.to_dict()
    assert d.get("composition_version") == "1.0"


# ---------------------------------------------------------------------------
# AC-39.04 — Layer limits enforced
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-39.04")
def test_theme_limit_exceeded_returns_error() -> None:
    config = {
        "composition": {
            "themes": [{"name": f"theme_{i}", "weight": 0.5} for i in range(6)],
        }
    }
    comp = UniverseComposition.from_config(config)
    validator = CompositionValidator()
    errors = validator.validate(comp)
    assert any("themes" in e for e in errors)


@pytest.mark.spec("AC-39.04")
def test_trope_limit_exceeded_returns_error() -> None:
    config = {
        "composition": {
            "tropes": [{"name": f"trope_{i}", "weight": 0.5} for i in range(11)],
        }
    }
    comp = UniverseComposition.from_config(config)
    validator = CompositionValidator()
    errors = validator.validate(comp)
    assert any("tropes" in e for e in errors)


@pytest.mark.spec("AC-39.04")
def test_archetype_limit_exceeded_returns_error() -> None:
    config = {
        "composition": {
            "archetypes": [
                {"name": f"arc_{i}", "npc_tier": "key", "weight": 0.5} for i in range(9)
            ],
        }
    }
    comp = UniverseComposition.from_config(config)
    validator = CompositionValidator()
    errors = validator.validate(comp)
    assert any("archetypes" in e for e in errors)


@pytest.mark.spec("AC-39.04")
def test_genre_twist_limit_exceeded_returns_error() -> None:
    config = {
        "composition": {
            "genre_twists": [{"name": f"twist_{i}", "strength": 0.5} for i in range(4)],
        }
    }
    comp = UniverseComposition.from_config(config)
    validator = CompositionValidator()
    errors = validator.validate(comp)
    assert any("genre_twist" in e for e in errors)


# ---------------------------------------------------------------------------
# AC-39.05 — Seed immutability (HTTP 409 / category "conflict")
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-39.05")
def test_seed_not_in_to_dict() -> None:
    """Seed is not persisted in the composition blob itself."""
    comp = UniverseComposition.from_config({"seed": "abc123"})
    d = comp.to_dict()
    assert "seed" not in d


# ---------------------------------------------------------------------------
# AC-39.06 — Tone profile derived from theme keywords
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-39.06")
def test_tone_profile_dark_keywords() -> None:
    tone = derive_tone_profile(["cosmic_horror", "void", "dread"])
    assert tone.warmth < 0.5
    assert tone.intensity > 0.5


@pytest.mark.spec("AC-39.06")
def test_tone_profile_cozy_keywords() -> None:
    tone = derive_tone_profile(["cozy", "warmth", "hopeful"])
    assert tone.warmth > 0.5
    assert tone.intensity < 0.5


@pytest.mark.spec("AC-39.06")
def test_tone_profile_neutral_default() -> None:
    tone = derive_tone_profile(["adventure", "journey"])
    assert tone.warmth == 0.5
    assert tone.intensity == 0.5


@pytest.mark.spec("AC-39.06")
def test_tone_profile_mixed_signals_defaults() -> None:
    """Dark + cozy keywords → neutral default (mixed signals)."""
    tone = derive_tone_profile(["cosmic_horror", "cozy"])
    assert tone.warmth == 0.5
    assert tone.intensity == 0.5


# ---------------------------------------------------------------------------
# AC-39.07 — Composition validator rejects invalid names
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-39.07")
def test_invalid_theme_name_rejected() -> None:
    config = {
        "composition": {
            "themes": [{"name": "Invalid Name!", "weight": 0.5}],
        }
    }
    comp = UniverseComposition.from_config(config)
    validator = CompositionValidator()
    errors = validator.validate(comp)
    assert any("name" in e.lower() for e in errors)


@pytest.mark.spec("AC-39.07")
def test_valid_theme_name_accepted() -> None:
    config = {
        "composition": {
            "themes": [{"name": "cosmic_horror", "weight": 0.7}],
        }
    }
    comp = UniverseComposition.from_config(config)
    validator = CompositionValidator()
    errors = validator.validate(comp)
    assert not errors


# ---------------------------------------------------------------------------
# AC-39.08 — Prose config validation
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-39.08")
def test_invalid_pacing_rejected() -> None:
    config = {
        "composition": {
            "prose": {"pacing": "turbo", "description_density": "medium"},
        }
    }
    comp = UniverseComposition.from_config(config)
    validator = CompositionValidator()
    errors = validator.validate(comp)
    assert any("pacing" in e for e in errors)


@pytest.mark.spec("AC-39.08")
def test_invalid_density_rejected() -> None:
    config = {
        "composition": {
            "prose": {"pacing": "balanced", "description_density": "verbose"},
        }
    }
    comp = UniverseComposition.from_config(config)
    validator = CompositionValidator()
    errors = validator.validate(comp)
    assert any("description_density" in e for e in errors)


@pytest.mark.spec("AC-39.08")
def test_valid_prose_config_accepted() -> None:
    config = {
        "composition": {
            "prose": {"pacing": "fast", "description_density": "sparse"},
        }
    }
    comp = UniverseComposition.from_config(config)
    validator = CompositionValidator()
    errors = validator.validate(comp)
    assert not errors


# ---------------------------------------------------------------------------
# AC-39.09 — context fragment for LLM prompts
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-39.09")
def test_context_fragment_includes_genre() -> None:
    config = {
        "composition": {
            "primary_genre": "cosmic_horror",
            "themes": [{"name": "dread", "weight": 0.9}],
        }
    }
    comp = UniverseComposition.from_config(config)
    fragment = comp.get_context_fragment()
    assert "cosmic_horror" in fragment


@pytest.mark.spec("AC-39.09")
def test_context_fragment_excludes_low_weight_themes() -> None:
    config = {
        "composition": {
            "themes": [
                {"name": "high_weight", "weight": 0.8},
                {"name": "low_weight", "weight": 0.1},
            ],
        }
    }
    comp = UniverseComposition.from_config(config)
    fragment = comp.get_context_fragment()
    assert "high_weight" in fragment
    assert "low_weight" not in fragment


# ---------------------------------------------------------------------------
# AC-39.10 — to_dict preserves tone.primary/secondary; warmth/intensity excluded
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-39.10")
def test_to_dict_preserves_tone_primary_secondary() -> None:
    """to_dict stores primary/secondary so explicit overrides survive round-trips.

    warmth and intensity are always derived at load time (FR-39.07a) and must
    never appear in the serialised blob.
    """
    config = {
        "composition": {
            "themes": [{"name": "dread", "weight": 0.9}],
        }
    }
    comp = UniverseComposition.from_config(config)
    d = comp.to_dict()
    assert "tone" in d
    assert "primary" in d["tone"]
    assert "warmth" not in d["tone"]
    assert "intensity" not in d["tone"]


@pytest.mark.spec("AC-39.10")
def test_tone_override_survives_round_trip() -> None:
    """Explicit tone.primary override must survive to_dict() → from_config()."""
    from tta.universe.composition import ToneProfile

    config = {"composition": {"primary_genre": "cosmic_horror"}}
    comp = UniverseComposition.from_config(config)
    comp.tone = ToneProfile(primary="whimsical", secondary="absurd")

    blob = comp.to_dict()
    comp2 = UniverseComposition.from_config({"composition": blob})
    assert comp2.tone.primary == "whimsical"
    assert comp2.tone.secondary == "absurd"


# ---------------------------------------------------------------------------
# AC-39.11 — subsystem namespaces untouched by validator
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-39.11")
def test_validator_does_not_reject_subsystem_namespaces() -> None:
    """memory/time/npc keys must not cause validation errors."""
    config = {
        "composition": {"primary_genre": "fantasy"},
        "memory": {"compress_threshold": 4000},
        "time": {"tick_rate": 60},
        "npc": {"tier_weights": {"key": 1.0}},
    }
    comp = UniverseComposition.from_config(config)
    validator = CompositionValidator()
    errors = validator.validate(comp)
    assert not errors


# ---------------------------------------------------------------------------
# NFR-39.03 — validate() emits structured log on every call (success + failure)
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-39.11")
def test_validate_emits_log_on_success() -> None:
    """validate() logs composition_validated with validation_result=ok (NFR-39.03)."""
    comp = UniverseComposition.from_config({})
    validator = CompositionValidator()
    with structlog.testing.capture_logs() as cap:
        errors = validator.validate(comp)
    assert errors == []
    assert len(cap) == 1
    assert cap[0]["event"] == "composition_validated"
    assert cap[0]["validation_result"] == "ok"
    assert cap[0]["composition_version"] == comp.composition_version


@pytest.mark.spec("AC-39.11")
def test_validate_emits_log_on_failure() -> None:
    """validate() logs composition_validated with validation_result=error.

    Covers NFR-39.03: log on every call (not just success).
    """
    config = {"composition": {"themes": [{"name": "Bad Theme", "weight": 1.5}]}}
    comp = UniverseComposition.from_config(config)
    validator = CompositionValidator()
    with structlog.testing.capture_logs() as cap:
        errors = validator.validate(comp)
    assert errors
    assert len(cap) == 1
    assert cap[0]["event"] == "composition_validated"
    assert cap[0]["validation_result"] == "error"


# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-39.12")
def test_weight_out_of_range_rejected() -> None:
    config = {
        "composition": {
            "themes": [{"name": "loss", "weight": 1.5}],
        }
    }
    comp = UniverseComposition.from_config(config)
    validator = CompositionValidator()
    errors = validator.validate(comp)
    assert any("weight" in e for e in errors)


@pytest.mark.spec("AC-39.12")
def test_strength_out_of_range_rejected() -> None:
    config = {
        "composition": {
            "genre_twists": [{"name": "twist_a", "strength": -0.1}],
        }
    }
    comp = UniverseComposition.from_config(config)
    validator = CompositionValidator()
    errors = validator.validate(comp)
    assert any("strength" in e for e in errors)
