"""In-game disclaimer endpoint (S17 FR-17.35)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/disclaimer", tags=["privacy"])

_DISCLAIMER_TEXT = (
    "This game is for entertainment purposes only and is NOT a substitute "
    "for professional mental health treatment. If you are in crisis, please "
    "contact a licensed professional or call a crisis hotline. "
    "No personal health information (PHI) is collected, stored, or "
    "transmitted. See /privacy for full details."
)


@router.get("")
async def get_disclaimer() -> dict:
    """Return the in-game disclaimer text."""
    return {
        "data": {
            "disclaimer": _DISCLAIMER_TEXT,
            "hipaa_notice": (
                "TTA does not collect, store, or transmit Protected "
                "Health Information (PHI) as defined by HIPAA. "
                "This application is not HIPAA-regulated."
            ),
        }
    }
