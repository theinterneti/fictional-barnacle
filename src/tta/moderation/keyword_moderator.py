"""Keyword-based content moderation (S24 v1 default).

Fast pre-filter using pattern matching. LLM-based classification
is planned for v2; this implementation covers the minimum viable
surface area for launch.
"""

import hashlib
import re

from tta.moderation.models import (
    ALWAYS_BLOCK,
    DEFAULT_CATEGORY_ACTIONS,
    ContentCategory,
    ModerationContext,
    ModerationResult,
    ModerationVerdict,
)

# ── Pattern lists per category ─────────────────────────────────
# Patterns are case-insensitive and compiled once at import time.
# Each entry is (compiled_regex, confidence_score).

_PatternList = list[tuple[re.Pattern[str], float]]

_FLAGS = re.IGNORECASE | re.DOTALL


def _compile(
    patterns: list[tuple[str, float]],
) -> _PatternList:
    return [(re.compile(p, _FLAGS), c) for p, c in patterns]


_PATTERNS: dict[ContentCategory, _PatternList] = {
    ContentCategory.GRAPHIC_VIOLENCE: _compile(
        [
            (r"\b(dismember|decapitat|eviscerat|disembowel)\w*\b", 0.9),
            (r"\b(gouge\s+out|rip\s+apart|tear\s+off)\b", 0.85),
            (r"\btorture\s+(them|him|her|it)\b", 0.8),
        ]
    ),
    ContentCategory.SEXUAL_CONTENT: _compile(
        [
            (r"\b(explicit\s+sex|pornograph|erotic)\w*\b", 0.9),
            (r"\b(naked|nude)\s+(scene|body|character)\b", 0.7),
        ]
    ),
    ContentCategory.SELF_HARM: _compile(
        [
            (r"\b(kill\s+myself|suicide\s+method|end\s+my\s+life)\b", 0.95),
            (r"\b(cut\s+myself|self.?harm)\b", 0.9),
            (r"\bhow\s+to\s+(hang|poison|overdose)\b", 0.9),
        ]
    ),
    ContentCategory.HATE_SPEECH: _compile(
        [
            (r"\b(racial\s+slur|ethnic\s+cleansing)\b", 0.9),
            (r"\b(subhuman|dehumaniz)\w*\b", 0.85),
        ]
    ),
    ContentCategory.DANGEROUS_ACTIVITY: _compile(
        [
            (r"\bhow\s+to\s+(make|build)\s+a?\s*(bomb|weapon|explosive)\b", 0.95),
            (r"\b(synthesiz|manufactur)\w*\s+(drugs|meth|fentanyl)\b", 0.9),
        ]
    ),
    ContentCategory.PROMPT_INJECTION: _compile(
        [
            (
                r"ignore\s+(all\s+)?(previous|prior|above)"
                r"\s+(instructions?|rules?)",
                0.95,
            ),
            (r"you\s+are\s+now\s+(a|an|in)\s+\w+\s+mode", 0.9),
            (r"system\s*:\s*", 0.85),
            (r"\bDAN\s+mode\b", 0.9),
            (r"pretend\s+you\s+(are|have)\s+no\s+(rules|restrictions)", 0.9),
        ]
    ),
    ContentCategory.PERSONAL_INFO: _compile(
        [
            # Phone numbers (US/intl).
            (r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b", 0.8),
            # Email addresses.
            (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", 0.85),
            # SSN pattern.
            (r"\b\d{3}-\d{2}-\d{4}\b", 0.9),
        ]
    ),
    ContentCategory.OFF_TOPIC: _compile(
        [
            (r"\b(who\s+is\s+the\s+president|stock\s+market|bitcoin\s+price)\b", 0.7),
            (r"\bwhat\s+is\s+the\s+(weather|news|score)\b", 0.65),
        ]
    ),
}


def _content_hash(content: str) -> str:
    """SHA-256 hex digest of the content."""
    return hashlib.sha256(content.encode()).hexdigest()


def _resolve_verdict(
    category: ContentCategory,
    category_overrides: dict[ContentCategory, ModerationVerdict] | None,
) -> ModerationVerdict:
    """Determine the verdict for a matched category.

    Non-overridable categories always return BLOCK (FR-24.05).
    """
    if category in ALWAYS_BLOCK:
        return ModerationVerdict.BLOCK

    if category_overrides and category in category_overrides:
        return category_overrides[category]

    return DEFAULT_CATEGORY_ACTIONS.get(category, ModerationVerdict.FLAG)


class KeywordModerator:
    """V1 keyword/regex based content moderator.

    Scans content against compiled pattern lists and returns the
    highest-severity match.  Categories in ``ALWAYS_BLOCK`` always
    produce a ``block`` verdict regardless of configuration.
    """

    def __init__(
        self,
        category_overrides: dict[ContentCategory, ModerationVerdict] | None = None,
    ) -> None:
        self._overrides = category_overrides

    async def moderate_input(
        self,
        content: str,
        context: ModerationContext,
    ) -> ModerationResult:
        return self._scan(content)

    async def moderate_output(
        self,
        content: str,
        context: ModerationContext,
    ) -> ModerationResult:
        return self._scan(content)

    # ── internals ───────────────────────────────────────────────

    def _scan(self, content: str) -> ModerationResult:
        """Scan content against all pattern lists.

        Returns the *most severe* match (block > flag > pass).
        """
        best: ModerationResult | None = None
        chash = _content_hash(content)

        for category, patterns in _PATTERNS.items():
            for regex, confidence in patterns:
                if regex.search(content):
                    verdict = _resolve_verdict(category, self._overrides)
                    candidate = ModerationResult(
                        verdict=verdict,
                        category=category,
                        confidence=confidence,
                        reason=category.value,
                        content_hash=chash,
                    )
                    if best is None or _severity(candidate) > _severity(best):
                        best = candidate
                    break  # first match per category is enough

        if best is not None:
            return best

        return ModerationResult(
            verdict=ModerationVerdict.PASS,
            category=ContentCategory.SAFE,
            confidence=1.0,
            reason="safe",
            content_hash=chash,
        )


_SEVERITY_ORDER = {
    ModerationVerdict.PASS: 0,
    ModerationVerdict.FLAG: 1,
    ModerationVerdict.BLOCK: 2,
}


def _severity(result: ModerationResult) -> int:
    return _SEVERITY_ORDER.get(result.verdict, 0)
