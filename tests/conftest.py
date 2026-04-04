"""Shared pytest fixtures for voronoi tests.

Reduces boilerplate across test files — the most common setup patterns
(swarm workspace creation, queue instantiation, sample investigation)
are available as fixtures without explicit import.
"""

import subprocess

import pytest


# ---------------------------------------------------------------------------
# Session-scoped safety net: kill orphaned tmux sessions from tests
# ---------------------------------------------------------------------------

def _kill_test_tmux_sessions():
    """Kill tmux sessions created by pytest tmp_path workspaces.

    Tests that call provision_lab() without mocking _voronoi_init will
    create tmux sessions named ``<tmp_path_basename>-swarm``.  These
    match the pattern ``tmp*-swarm``.  This function kills them so
    they don't accumulate across test runs.
    """
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return
        for name in result.stdout.strip().splitlines():
            if name.startswith("tmp") and name.endswith("-swarm"):
                subprocess.run(
                    ["tmux", "kill-session", "-t", name],
                    capture_output=True, timeout=5,
                )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass  # tmux not installed or hung


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_tmux_sessions():
    """Kill orphaned tmp*-swarm tmux sessions after the full test run."""
    yield
    _kill_test_tmux_sessions()


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
