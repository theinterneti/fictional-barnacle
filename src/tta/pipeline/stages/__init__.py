"""Pipeline stage implementations.

Each stage is a pure async function: (TurnState, PipelineDeps) → TurnState.
Stages return a new TurnState via model_copy — they never mutate input.
"""

from tta.pipeline.stages.context import context_stage
from tta.pipeline.stages.deliver import deliver_stage
from tta.pipeline.stages.generate import generate_stage
from tta.pipeline.stages.understand import understand_stage

__all__ = [
    "context_stage",
    "deliver_stage",
    "generate_stage",
    "understand_stage",
]
