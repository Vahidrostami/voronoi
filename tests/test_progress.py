"""Tests for voronoi.gateway.progress — progress streaming relay."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from voronoi.gateway.progress import (
    ProgressEvent,
    ProgressRelay,
    format_workflow_start,
    format_workflow_complete,
)


# ---------------------------------------------------------------------------
# ProgressEvent basics
# ---------------------------------------------------------------------------

class TestProgressEvent:
    def test_creation(self):
        e = ProgressEvent(event_type="test", message="hello")
        assert e.event_type == "test"
        assert e.message == "hello"
        assert e.timestamp > 0

    def test_metadata_default(self):
        e = ProgressEvent(event_type="test", message="hello")
        assert e.metadata == {}


# ---------------------------------------------------------------------------
# ProgressRelay — task polling
# ---------------------------------------------------------------------------

class TestProgressRelayTasks:
    @patch("voronoi.gateway.progress.subprocess.run")
    def test_initial_poll_populates_snapshot(self, mock_run, tmp_path):
        tasks = [
            {"id": "bd-1", "title": "Task 1", "status": "open"},
            {"id": "bd-2", "title": "Task 2", "status": "in_progress"},
        ]
        mock_run.return_value = _mock_result(0, json.dumps(tasks))

        relay = ProgressRelay(tmp_path)
        events = relay.poll()

        # Initial poll should NOT generate "new task" events
        task_created = [e for e in events if e.event_type == "task_created"]
        assert len(task_created) == 0

    @patch("voronoi.gateway.progress.subprocess.run")
    def test_detects_new_task(self, mock_run, tmp_path):
        relay = ProgressRelay(tmp_path)

        # First poll: 1 task
        tasks1 = [{"id": "bd-1", "title": "Task 1", "status": "open"}]
        mock_run.return_value = _mock_result(0, json.dumps(tasks1))
        relay.poll()

        # Second poll: 2 tasks
        tasks2 = [
            {"id": "bd-1", "title": "Task 1", "status": "open"},
            {"id": "bd-2", "title": "Task 2", "status": "open"},
        ]
        mock_run.return_value = _mock_result(0, json.dumps(tasks2))
        events = relay.poll()

        created = [e for e in events if e.event_type == "task_created"]
        assert len(created) == 1
        assert "Task 2" in created[0].message

    @patch("voronoi.gateway.progress.subprocess.run")
    def test_detects_task_closed(self, mock_run, tmp_path):
        relay = ProgressRelay(tmp_path)

        tasks1 = [{"id": "bd-1", "title": "Task 1", "status": "in_progress"}]
        mock_run.return_value = _mock_result(0, json.dumps(tasks1))
        relay.poll()

        tasks2 = [{"id": "bd-1", "title": "Task 1", "status": "closed"}]
        mock_run.return_value = _mock_result(0, json.dumps(tasks2))
        events = relay.poll()

        closed = [e for e in events if e.event_type == "task_closed"]
        assert len(closed) == 1
        assert "Task 1" in closed[0].message

    @patch("voronoi.gateway.progress.subprocess.run")
    def test_detects_task_started(self, mock_run, tmp_path):
        relay = ProgressRelay(tmp_path)

        tasks1 = [{"id": "bd-1", "title": "Task 1", "status": "open"}]
        mock_run.return_value = _mock_result(0, json.dumps(tasks1))
        relay.poll()

        tasks2 = [{"id": "bd-1", "title": "Task 1", "status": "in_progress"}]
        mock_run.return_value = _mock_result(0, json.dumps(tasks2))
        events = relay.poll()

        started = [e for e in events if e.event_type == "task_started"]
        assert len(started) == 1

    @patch("voronoi.gateway.progress.subprocess.run")
    def test_progress_summary_emitted(self, mock_run, tmp_path):
        relay = ProgressRelay(tmp_path)

        tasks1 = [{"id": "bd-1", "title": "T1", "status": "open"}]
        mock_run.return_value = _mock_result(0, json.dumps(tasks1))
        relay.poll()

        tasks2 = [{"id": "bd-1", "title": "T1", "status": "closed"},
                   {"id": "bd-2", "title": "T2", "status": "open"}]
        mock_run.return_value = _mock_result(0, json.dumps(tasks2))
        events = relay.poll()

        summary = [e for e in events if e.event_type == "progress_summary"]
        assert len(summary) == 1
        assert "1/2" in summary[0].message

    @patch("voronoi.gateway.progress.subprocess.run")
    def test_bd_failure_returns_empty(self, mock_run, tmp_path):
        mock_run.return_value = _mock_result(1, "error")
        relay = ProgressRelay(tmp_path)
        events = relay.poll()
        assert events == []


# ---------------------------------------------------------------------------
# ProgressRelay — journal
# ---------------------------------------------------------------------------

class TestProgressRelayJournal:
    def test_detects_journal_update(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        journal = swarm / "journal.md"
        journal.write_text("## Round 1\nInitial content\n")

        relay = ProgressRelay(tmp_path)
        # Patch subprocess to avoid bd calls
        with patch("voronoi.gateway.progress.subprocess.run",
                    return_value=_mock_result(0, "[]")):
            relay.poll()  # Initialize journal size

        # Append to journal
        with open(journal, "a") as f:
            f.write("\n## Round 2\nNew findings discovered\n")

        with patch("voronoi.gateway.progress.subprocess.run",
                    return_value=_mock_result(0, "[]")):
            events = relay.poll()

        journal_events = [e for e in events if e.event_type == "journal_update"]
        assert len(journal_events) == 1
        assert "New findings" in journal_events[0].message


# ---------------------------------------------------------------------------
# ProgressRelay — convergence
# ---------------------------------------------------------------------------

class TestProgressRelayConvergence:
    def test_detects_convergence(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "convergence.json").write_text(json.dumps({"status": "converged"}))

        relay = ProgressRelay(tmp_path)
        with patch("voronoi.gateway.progress.subprocess.run",
                    return_value=_mock_result(0, "[]")):
            events = relay.poll()

        conv = [e for e in events if e.event_type == "convergence"]
        assert len(conv) == 1
        assert "CONVERGED" in conv[0].message

    def test_detects_exhausted(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "convergence.json").write_text(json.dumps({"status": "exhausted"}))

        relay = ProgressRelay(tmp_path)
        with patch("voronoi.gateway.progress.subprocess.run",
                    return_value=_mock_result(0, "[]")):
            events = relay.poll()

        conv = [e for e in events if e.event_type == "convergence"]
        assert len(conv) == 1
        assert "EXHAUSTED" in conv[0].message

    def test_detects_diminishing_returns(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "convergence.json").write_text(json.dumps({"status": "diminishing_returns"}))

        relay = ProgressRelay(tmp_path)
        with patch("voronoi.gateway.progress.subprocess.run",
                    return_value=_mock_result(0, "[]")):
            events = relay.poll()

        conv = [e for e in events if e.event_type == "convergence"]
        assert len(conv) == 1
        assert "DIMINISHING" in conv[0].message

    def test_no_convergence_file(self, tmp_path):
        relay = ProgressRelay(tmp_path)
        with patch("voronoi.gateway.progress.subprocess.run",
                    return_value=_mock_result(0, "[]")):
            events = relay.poll()

        conv = [e for e in events if e.event_type == "convergence"]
        assert len(conv) == 0


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

class TestFormatting:
    def test_format_workflow_start(self):
        msg = format_workflow_start("investigate", "scientific", "Why is latency high?")
        assert "INVESTIGATE" in msg
        assert "scientific" in msg
        assert "Why is latency high?" in msg

    def test_format_workflow_start_explore(self):
        msg = format_workflow_start("explore", "analytical", "Redis vs Memcached")
        assert "EXPLORE" in msg
        assert "🧭" in msg

    def test_format_workflow_start_build(self):
        msg = format_workflow_start("build", "standard", "Build REST API")
        assert "BUILD" in msg
        assert "🔨" in msg

    def test_format_workflow_complete(self):
        msg = format_workflow_complete("investigate", 12, 3, 15.5)
        assert "INVESTIGATE" in msg
        assert "12" in msg
        assert "3" in msg
        assert "15.5" in msg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_result(returncode: int, stdout: str):
    """Create a mock subprocess.CompletedProcess."""
    result = type("Result", (), {
        "returncode": returncode,
        "stdout": stdout,
        "stderr": "",
    })()
    return result
