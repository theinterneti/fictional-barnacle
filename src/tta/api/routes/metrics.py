"""Prometheus metrics endpoint.

Returns metrics in the Prometheus text exposition format.
This endpoint is intentionally outside the /api/v1 prefix so
Prometheus can scrape it at the conventional ``/metrics`` path.
"""

from fastapi import APIRouter, Response

from tta.observability.metrics import REGISTRY, generate_latest

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def prometheus_metrics() -> Response:
    """Return Prometheus metrics in text exposition format."""
    return Response(
        content=generate_latest(REGISTRY),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
