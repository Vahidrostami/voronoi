"""Shared pytest fixtures for voronoi tests.

Reduces boilerplate across test files — the most common setup patterns
(swarm workspace creation, queue instantiation, sample investigation)
are available as fixtures without explicit import.
"""

import pytest


@pytest.fixture
def swarm_workspace(tmp_path):
    """Workspace with .swarm/ pre-created."""
    swarm = tmp_path / ".swarm"
    swarm.mkdir()
    return tmp_path


@pytest.fixture
def test_queue(tmp_path):
    """Fresh InvestigationQueue on a temp DB."""
    from voronoi.server.queue import InvestigationQueue
    return InvestigationQueue(tmp_path / "queue.db")


@pytest.fixture
def sample_investigation():
    """Reusable Investigation kwargs factory."""
    from voronoi.server.queue import Investigation

    def _make(**overrides):
        defaults = dict(
            chat_id="test",
            question="Test question",
            slug="test-q",
            codename="TestCode",
            mode="discover",
        )
        defaults.update(overrides)
        return Investigation(**defaults)
    return _make
