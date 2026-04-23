"""S47 — Live Neo4j in CI: AC compliance tests.

Spec ref: specs/47-live-neo4j-in-ci.md
ACs: 47.01 – 47.05
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).parents[4]
COMPOSE_FILE = REPO_ROOT / "docker-compose.test.yml"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "neo4j"
INTEGRATION_CONFTEST = REPO_ROOT / "tests" / "integration" / "conftest.py"


# -- AC-47.01: Neo4j healthcheck passes within 60s -------------------------


@pytest.mark.spec("AC-47.01")
def test_neo4j_service_healthcheck_configured():
    """Compose file has a healthcheck on the neo4j service."""
    with open(COMPOSE_FILE) as fh:
        compose = yaml.safe_load(fh)

    services = compose.get("services", {})
    neo4j = services.get("neo4j")
    assert neo4j is not None, "neo4j service not found in docker-compose.test.yml"

    hc = neo4j.get("healthcheck")
    assert hc is not None, "neo4j service has no healthcheck"

    test_cmd = " ".join(hc["test"]) if isinstance(hc["test"], list) else hc["test"]
    assert "cypher-shell" in test_cmd, f"Expected cypher-shell in healthcheck, got: {test_cmd}"

    timeout = int(hc.get("timeout", "0s").rstrip("s"))
    start = int(hc.get("start_period", "0s").rstrip("s"))
    retries = int(hc.get("retries", 0))
    assert timeout * retries + start <= 60, (
        f"Healthcheck may take more than 60s to resolve: "
        f"timeout={timeout}s retries={retries} start={start}s"
    )


@pytest.mark.spec("AC-47.01")
def test_neo4j_service_no_auth():
    """Compose file uses NEO4J_AUTH: none for no-credential access."""
    with open(COMPOSE_FILE) as fh:
        compose = yaml.safe_load(fh)

    neo4j_env = (
        compose.get("services", {}).get("neo4j", {}).get("environment", {})
    )
    if isinstance(neo4j_env, list):
        neo4j_env = dict(item.split("=", 1) for item in neo4j_env if "=" in item)

    assert neo4j_env.get("NEO4J_AUTH") == "none", (
        f"Expected NEO4J_AUTH=none, got: {neo4j_env.get('NEO4J_AUTH')}"
    )


# -- AC-47.02: Each test runs against a fresh graph -------------------------


@pytest.mark.spec("AC-47.02")
def test_conftest_has_teardown_delete_all():
    """Integration conftest neo4j_session fixture includes DETACH DELETE n teardown."""
    conftest_text = INTEGRATION_CONFTEST.read_text()
    assert "MATCH (n) DETACH DELETE n" in conftest_text, (
        "conftest.py neo4j_session fixture must include 'MATCH (n) DETACH DELETE n' teardown"
    )


@pytest.mark.spec("AC-47.02")
def test_conftest_has_function_scoped_neo4j_session():
    """Integration conftest defines a function-scoped neo4j_session fixture."""
    conftest_text = INTEGRATION_CONFTEST.read_text()
    assert "async def neo4j_session(" in conftest_text, (
        "conftest.py must define a neo4j_session fixture"
    )
    # Ensure it's function-scoped (default scope, not session)
    # The neo4j_db is session-scoped; neo4j_session must NOT be
    assert 'scope="session"' not in conftest_text.split("async def neo4j_session(")[1][:200], (
        "neo4j_session fixture must be function-scoped (default)"
    )


# -- AC-47.03: No mock Neo4j drivers in integration tests -------------------


@pytest.mark.spec("AC-47.03")
def test_no_mock_neo4j_in_integration_tests():
    """Integration test directory contains no mocked AsyncDriver instances."""
    integration_dir = REPO_ROOT / "tests" / "integration"
    if not integration_dir.exists():
        pytest.skip("No integration test directory found")

    mocked_driver_files: list[str] = []
    for py_file in integration_dir.rglob("*.py"):
        text = py_file.read_text()
        if ("AsyncMock" in text or "MagicMock" in text) and (
            "AsyncDriver" in text or "neo4j" in text.lower()
        ):
            # Check for actual mock usage, not just comments
            for line in text.splitlines():
                if line.strip().startswith("#"):
                    continue
                if (
                    ("AsyncMock" in line or "MagicMock" in line)
                    and ("driver" in line.lower() or "neo4j" in line.lower())
                ):
                    mocked_driver_files.append(str(py_file.relative_to(REPO_ROOT)))
                    break

    assert mocked_driver_files == [], (
        f"Mocked Neo4j drivers found in integration tests: {mocked_driver_files}"
    )


# -- AC-47.04: Neo4j absence doesn't hang ----------------------------------


@pytest.mark.spec("AC-47.04")
def test_conftest_has_session_scoped_neo4j_db():
    """Integration conftest defines a session-scoped neo4j_db fixture with skip-on-miss."""
    conftest_text = INTEGRATION_CONFTEST.read_text()
    assert "async def neo4j_db(" in conftest_text, (
        "conftest.py must define a neo4j_db session-scoped fixture"
    )
    # Must have connection_acquisition_timeout for fast failure
    assert "connection_acquisition_timeout" in conftest_text, (
        "neo4j_db fixture must set connection_acquisition_timeout"
    )
    # Must skip on unavailability
    assert "pytest.skip" in conftest_text, (
        "neo4j_db fixture must call pytest.skip when Neo4j is unavailable"
    )


@pytest.mark.spec("AC-47.04")
def test_neo4j_driver_init_uses_no_auth():
    """Integration conftest initialises Neo4j driver with auth=None."""
    conftest_text = INTEGRATION_CONFTEST.read_text()
    # auth=None must appear in the neo4j_db fixture block
    db_fixture_block = conftest_text.split("async def neo4j_db(")[1].split(
        "async def "
    )[0]
    assert "auth=None" in db_fixture_block, (
        "neo4j_db fixture must use auth=None for no-auth Neo4j instance"
    )


# -- AC-47.05: world_full.cypher validates S13 schema ----------------------


@pytest.mark.spec("AC-47.05")
def test_world_full_cypher_exists():
    """tests/fixtures/neo4j/world_full.cypher file exists."""
    assert (FIXTURES_DIR / "world_full.cypher").is_file(), (
        "tests/fixtures/neo4j/world_full.cypher not found"
    )


@pytest.mark.spec("AC-47.05")
def test_world_full_cypher_contains_s13_constraints():
    """world_full.cypher includes uniqueness constraints for all S13 node types."""
    text = (FIXTURES_DIR / "world_full.cypher").read_text()
    expected_labels = [
        "Universe",
        "Region",
        "Location",
        "NPC",
        "Item",
        "Event",
        "Quest",
    ]
    for label in expected_labels:
        assert label in text, (
            f"world_full.cypher missing constraint/node for label: {label}"
        )
    assert "CONSTRAINT" in text.upper(), (
        "world_full.cypher must define uniqueness constraints"
    )


@pytest.mark.spec("AC-47.05")
def test_all_neo4j_fixtures_exist():
    """All four Neo4j fixture files are present."""
    expected = ["empty.cypher", "world_minimal.cypher", "world_with_npcs.cypher", "world_full.cypher"]
    for fname in expected:
        assert (FIXTURES_DIR / fname).is_file(), (
            f"Missing Neo4j fixture: tests/fixtures/neo4j/{fname}"
        )
