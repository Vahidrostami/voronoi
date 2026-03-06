"""Tests for the investigation dispatcher."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from voronoi.server.dispatcher import (
    DispatcherConfig,
    InvestigationDispatcher,
    RunningInvestigation,
)


@pytest.fixture
def dispatcher_setup(tmp_path):
    """Create a dispatcher with a temp directory."""
    config = DispatcherConfig(
        base_dir=tmp_path,
        max_concurrent=2,
        max_agents=4,
        agent_command="echo",  # won't actually run anything
    )
    messages = []
    dispatcher = InvestigationDispatcher(config, lambda msg: messages.append(msg))
    return dispatcher, messages, tmp_path


class TestInboxProcessing:
    def test_poll_empty_inbox(self, dispatcher_setup):
        d, msgs, tmp_path = dispatcher_setup
        d.poll_inbox()  # should not raise
        assert len(msgs) == 0

    def test_poll_inbox_processes_investigate_command(self, dispatcher_setup):
        d, msgs, tmp_path = dispatcher_setup
        # Create inbox directory and command file
        inbox = tmp_path / ".swarm" / "inbox"
        inbox.mkdir(parents=True)
        cmd = {
            "id": "test-123",
            "action": "investigate",
            "params": {
                "question": "Why is accuracy dropping?",
                "mode": "investigate",
                "rigor": "scientific",
            },
            "timestamp": time.time(),
            "source": "telegram",
        }
        (inbox / "test-123.json").write_text(json.dumps(cmd))

        # Mock queue so we don't need sqlite
        mock_queue = MagicMock()
        mock_queue.enqueue.return_value = 1
        mock_queue.get_queued.return_value = []
        mock_queue.get_running.return_value = []
        mock_queue.next_ready.return_value = None
        d._queue = mock_queue

        d.poll_inbox()

        # Command should be enqueued
        mock_queue.enqueue.assert_called_once()
        # Message sent to Telegram
        assert any("queued" in m.lower() for m in msgs)
        # File moved to processed
        assert not (inbox / "test-123.json").exists()
        assert (inbox / "processed" / "test-123.json").exists()

    def test_poll_inbox_handles_bad_json(self, dispatcher_setup):
        d, msgs, tmp_path = dispatcher_setup
        inbox = tmp_path / ".swarm" / "inbox"
        inbox.mkdir(parents=True)
        (inbox / "bad.json").write_text("not json{{{")

        d.poll_inbox()

        # File moved to failed
        assert not (inbox / "bad.json").exists()
        assert (inbox / "failed" / "bad.json").exists()

    def test_abort_kills_running(self, dispatcher_setup):
        d, msgs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        d.running[1] = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path / "ws",
            tmux_session="test-session",
            question="test",
            mode="investigate",
        )

        with patch("subprocess.run"):
            d._handle_abort()

        assert len(d.running) == 0
        mock_queue.fail.assert_called_once()


class TestProgressMonitoring:
    def test_diff_tasks_detects_completion(self, dispatcher_setup):
        d, msgs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="investigate",
        )
        run.task_snapshot = {
            "bd-1": {"status": "in_progress", "title": "Task 1"},
            "bd-2": {"status": "open", "title": "Task 2"},
        }

        new_tasks = [
            {"id": "bd-1", "status": "closed", "title": "Task 1"},
            {"id": "bd-2", "status": "in_progress", "title": "Task 2"},
        ]

        events = d._diff_tasks(run, new_tasks)
        types = [e["type"] for e in events]
        assert "task_done" in types
        assert "task_started" in types

    def test_detect_phase_change(self, dispatcher_setup):
        d, msgs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="investigate",
            phase="starting",
        )
        run.task_snapshot = {"bd-1": {"status": "open", "title": "Task 1"}}

        events = d._detect_phase(run)
        assert run.phase == "planning"
        assert any("planning" in e["msg"].lower() for e in events)

    def test_is_complete_with_deliverable(self, dispatcher_setup):
        d, msgs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="investigate",
        )
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "deliverable.md").write_text("# Results\n")

        assert d._is_complete(run) is True

    def test_finding_detection(self, dispatcher_setup):
        d, msgs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="investigate",
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps([
                    {"id": "bd-5", "title": "FINDING: EWC beats replay d=0.82", "notes": "EFFECT_SIZE:0.82"},
                ]),
                stderr="",
            )
            events = d._check_findings(run)

        assert len(events) == 1
        assert "FINDING" in events[0]["msg"]
        assert "bd-5" in run.notified_findings

    def test_progress_bar_format(self, dispatcher_setup):
        d, msgs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="investigate",
        )
        run.task_snapshot = {"bd-1": {"status": "open", "title": "Old"}}

        tasks = [
            {"id": "bd-1", "status": "closed", "title": "Old"},
            {"id": "bd-2", "status": "open", "title": "New"},
        ]
        events = d._diff_tasks(run, tasks)
        progress_events = [e for e in events if e["type"] == "progress"]
        assert len(progress_events) == 1
        assert "█" in progress_events[0]["msg"]
        assert "50%" in progress_events[0]["msg"]
