"""Tests for the /privacy endpoint (S17 FR-17.51-54)."""

from __future__ import annotations

import httpx
import pytest

from tta.api.app import create_app
from tta.config import Settings


@pytest.fixture
def _app():
    settings = Settings(
        database_url="postgresql+asyncpg://x:x@localhost:5432/x",
        neo4j_uri="",
        neo4j_password="test",
    )
    return create_app(settings)


class TestPrivacyEndpoint:
    """FR-17.51: /privacy returns the privacy policy."""

    @pytest.mark.asyncio
    async def test_privacy_returns_html(self, _app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/privacy")

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_privacy_contains_required_sections(self, _app):
        """FR-17.51 items 1-10 must all be covered."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/privacy")

        body = resp.text
        # 1. What data is collected
        assert "What Data We Collect" in body
        # 2. How data is used
        assert "How Your Data Is Used" in body
        # 3. Who data is shared with
        assert "Who Your Data Is Shared With" in body
        # 4. Player rights
        assert "Your Rights" in body
        # 5. Data retention
        assert "Data Retention" in body
        # 6. Children's privacy
        assert "Children" in body
        # 7. NOT HIPAA
        assert "NOT HIPAA" in body
        # 8. Contact information
        assert "Contact" in body
        # 9. Export/deletion how-to
        assert "Data Export or Deletion" in body
        # 10. Cookie/tracking
        assert "Cookies and Tracking" in body

    @pytest.mark.asyncio
    async def test_privacy_plain_language(self, _app):
        """FR-17.52: Written in plain language."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/privacy")

        body = resp.text
        assert "plain" in body.lower()
        assert "language" in body.lower()

    @pytest.mark.asyncio
    async def test_privacy_has_last_updated(self, _app):
        """FR-17.53: Includes a last updated date."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/privacy")

        assert "Last Updated" in resp.text
