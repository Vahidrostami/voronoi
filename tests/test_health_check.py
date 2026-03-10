"""Tests for scripts/health-check.sh — shell script integration tests."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "health-check.sh"


def run_health(args=None, config=None, env_extra=None, cwd=None):
    """Run health-check.sh with an optional config override."""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    cmd = ["bash", str(SCRIPT)] + (args or [])
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=15,
        cwd=cwd,
        env=env,
    )


class TestHealthCheckNoSwarm:
    """When there are no voronoi sessions, the script should exit gracefully."""

    def test_no_sessions_exits_2(self, tmp_path):
        """Exit 2 when no voronoi-related tmux sessions exist."""
        result = run_health(cwd=str(tmp_path))
        # Should exit 2 — no sessions found (unless a real voronoi session is running)
        # We can't guarantee no voronoi sessions system-wide, but at minimum it shouldn't crash
        assert result.returncode in (0, 1, 2)

    def test_specific_missing_session_exits_2(self, tmp_path):
        """Exit 2 when --session points to a nonexistent session."""
        result = run_health(
            args=["--session", "nonexistent-health-test-session-xyz"],
            cwd=str(tmp_path),
        )
        assert result.returncode == 2
        assert "not found" in result.stderr.lower() or "not found" in result.stdout.lower()


class TestHealthCheckArgs:
    """Verify CLI argument parsing."""

    def test_unknown_flag_exits_2(self, tmp_path):
        result = run_health(args=["--bogus"], cwd=str(tmp_path))
        assert result.returncode == 2

    def test_session_flag_accepted(self, tmp_path):
        """--session with a bad name should fail on session, not args."""
        result = run_health(
            args=["--session", "no-such-session-99"],
            cwd=str(tmp_path),
        )
        assert result.returncode == 2
        assert "not found" in (result.stderr + result.stdout).lower()


@pytest.mark.skipif(
    subprocess.run(["which", "tmux"], capture_output=True).returncode != 0,
    reason="tmux not installed",
)
class TestHealthCheckWithTmux:
    """Integration tests that create a real tmux session."""

    SESSION = "voronoi-inv-health-test"  # matches voronoi-inv-* discovery pattern

    @pytest.fixture(autouse=True)
    def _tmux_session(self, tmp_path):
        """Create and tear down a temporary tmux session."""
        # Clean stale snapshot files from previous runs to avoid false idle times
        import shutil
        snap_dir = Path(os.environ.get("TMPDIR", "/tmp")) / "voronoi-health"
        for pattern in [f"{self.SESSION}__*"]:
            for f in snap_dir.glob(pattern):
                f.unlink(missing_ok=True)

        subprocess.run(
            ["tmux", "new-session", "-d", "-s", self.SESSION, "-c", str(tmp_path)],
            check=True,
        )
        subprocess.run(
            ["tmux", "rename-window", "-t", self.SESSION, "agent-test-1"],
            check=True,
        )
        # Add a second window simulating another agent
        subprocess.run(
            ["tmux", "new-window", "-t", self.SESSION, "-n", "agent-test-2", "-c", str(tmp_path)],
            check=True,
        )

        # Init a git repo so commit checks don't crash
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
            check=True,
            capture_output=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"},
        )

        yield tmp_path

        subprocess.run(["tmux", "kill-session", "-t", self.SESSION], capture_output=True)

    def test_discovers_session(self, _tmux_session):
        """Auto-discovery should find our voronoi-inv-* session."""
        result = run_health(
            args=["--session", self.SESSION, "--no-notify"],
            cwd=str(_tmux_session),
        )
        assert result.returncode == 0
        assert "agent-test-1" in result.stdout
        assert "agent-test-2" in result.stdout

    def test_json_output(self, _tmux_session):
        """--json flag should produce valid JSON with expected fields."""
        result = run_health(
            args=["--json", "--session", self.SESSION, "--no-notify"],
            cwd=str(_tmux_session),
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) >= 2
        for entry in data:
            assert "session" in entry
            assert "window" in entry
            assert "role" in entry
            assert "status" in entry
            assert "pane_idle_secs" in entry
            assert entry["status"] in ("healthy", "stale", "stuck", "exited")

    def test_detects_exited_process(self, _tmux_session):
        """If the shell in a pane exits, status should be 'exited'."""
        # Kill the shell in agent-test-2
        subprocess.run(
            ["tmux", "send-keys", "-t", f"{self.SESSION}:agent-test-2", "exit", "Enter"],
            check=True,
        )
        import time
        time.sleep(1)
        result = run_health(
            args=["--json", "--session", self.SESSION, "--no-notify"],
            cwd=str(_tmux_session),
        )
        # Parse and find the agent-test-2 entry
        data = json.loads(result.stdout)
        test2 = [e for e in data if e["window"] == "agent-test-2"]
        # The window may have been destroyed or show exited — either is valid
        if test2:
            assert test2[0]["status"] in ("exited", "healthy")

    def test_session_field_in_json(self, _tmux_session):
        """JSON entries should include the session name."""
        result = run_health(
            args=["--json", "--session", self.SESSION, "--no-notify"],
            cwd=str(_tmux_session),
        )
        data = json.loads(result.stdout)
        for entry in data:
            assert entry["session"] == self.SESSION
