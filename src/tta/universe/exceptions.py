"""Universe-domain exceptions (S29, S30, S31)."""


class UniverseError(Exception):
    """Base class for all universe-domain errors."""


class UniverseNotFoundError(UniverseError):
    """Raised when a Universe with the given ID does not exist."""


class UniverseAlreadyActiveError(UniverseError):
    """Raised when attempting to activate an already-active Universe (AC-29.09)."""


class UniverseArchivedError(UniverseError):
    """Raised when attempting to modify an archived Universe."""


class UniverseStatusTransitionError(UniverseError):
    """Raised when a status transition is not permitted."""

    def __init__(self, current: str, requested: str) -> None:
        super().__init__(
            f"Cannot transition universe from '{current}' to '{requested}'"
        )
        self.current = current
        self.requested = requested


class ActorNotFoundError(UniverseError):
    """Raised when an Actor with the given ID does not exist."""


class CharacterStateNotFoundError(UniverseError):
    """Raised when a CharacterState for (actor_id, universe_id) does not exist."""


class CompositionValidationError(UniverseError):
    """Raised when a UniverseComposition payload fails validation (S39)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SeedImmutabilityError(UniverseError):
    """Raised when a PATCH attempts to overwrite an already-set seed (AC-39.05).

    Note: AC-39.05 Gherkin text says ``error category is "state_conflict"`` but
    the actual ``ErrorCategory`` StrEnum value is ``"conflict"``.  Tests should
    assert ``"conflict"`` — the Gherkin wording is a spec artefact.
    """
