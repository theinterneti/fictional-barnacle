"""Transport abstraction package (S32).

Public API
----------
NarrativeTransport
    The ``@runtime_checkable`` Protocol all transports implement.
SSETransport
    Production transport that delivers events over a FastAPI SSE stream.
MemoryTransport
    In-memory transport for tests (records events to ``self.events``).
split_narrative
    Sentence-aligned chunking utility (moved here from games.py, FR-32.05d).
"""

from tta.transport._chunking import split_narrative
from tta.transport.memory import MemoryTransport
from tta.transport.protocol import NarrativeTransport
from tta.transport.sse import SSETransport

__all__ = [
    "NarrativeTransport",
    "SSETransport",
    "MemoryTransport",
    "split_narrative",
]
