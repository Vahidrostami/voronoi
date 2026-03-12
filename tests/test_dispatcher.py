"""Tests for the investigation dispatcher (refactored).

inbox processing has been removed — the router enqueues directly.
The dispatcher now only: dispatch_next() + poll_progress().
"""

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
        agent_command="echo",
    )
    messages = []
    documents = []

    def send_msg(msg):
        messages.append(msg)

    def send_doc(chat_id, path, caption=""):
        documents.append((chat_id, path, caption))

    dispatcher = InvestigationDispatcher(config, send_msg, send_doc)
    return dispatcher, messages, documents, tmp_path


class TestDispatchNext:
    def test_dispatch_next_no_queue(self, dispatcher_setup):
        d, msgs, docs, _ = dispatcher_setup
        mock_queue = MagicMock()
        mock_queue.next_ready.return_value = None
        d._queue = mock_queue
        d.dispatch_next()
        assert len(msgs) == 0

    def test_abort_kills_running(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
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
        d, msgs, docs, tmp_path = dispatcher_setup
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
        d, msgs, docs, tmp_path = dispatcher_setup
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
        d, msgs, docs, tmp_path = dispatcher_setup
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
        d, msgs, docs, tmp_path = dispatcher_setup
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
        d, msgs, docs, tmp_path = dispatcher_setup
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

    def test_handle_completion_sends_teaser(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "deliverable.md").write_text("# Done\nResults here.")

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="Why is model degrading?",
            mode="investigate",
        )
        run.task_snapshot = {"bd-1": {"status": "closed", "title": "Done"}}

        with patch("voronoi.server.dispatcher.subprocess.run"):
            d._handle_completion(run)

        mock_queue.complete.assert_called_once_with(1)
        assert len(msgs) >= 1
        assert "COMPLETE" in msgs[0]

    def test_handle_completion_failed_calls_fail(self, dispatcher_setup):
        """When tmux exits without deliverable, should call queue.fail()."""
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="Why is model degrading?",
            mode="investigate",
        )
        run.task_snapshot = {"bd-1": {"status": "open", "title": "Incomplete"}}

        d._handle_completion(run, failed=True, failure_reason="Agent exited unexpectedly")

        mock_queue.fail.assert_called_once_with(1, "Agent exited unexpectedly")
        mock_queue.complete.assert_not_called()
        assert len(msgs) >= 1
        assert "FAILED" in msgs[0]

    def test_handle_completion_uses_chat_id(self, dispatcher_setup):
        """Document send should use per-investigation chat_id, not global file."""
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "deliverable.md").write_text("# Done")

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="Test question",
            mode="build",
            chat_id="12345",
        )
        run.task_snapshot = {"bd-1": {"status": "closed", "title": "Done"}}

        with patch("voronoi.server.dispatcher.subprocess.run"):
            d._handle_completion(run)

        # If a document was sent, it should use the per-investigation chat_id
        for doc in docs:
            assert doc[0] == "12345", f"Expected chat_id '12345', got '{doc[0]}'"


class TestAbortSignal:
    def test_abort_signal_triggers_handle_abort(self, dispatcher_setup):
        """Abort signal file should trigger _handle_abort."""
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        ws = tmp_path / "ws"
        (ws / ".swarm").mkdir(parents=True)
        (ws / ".swarm" / "abort-signal").write_text("abort\n")

        d.running[1] = RunningInvestigation(
            investigation_id=1,
            workspace_path=ws,
            tmux_session="test-session",
            question="test",
            mode="investigate",
        )

        with patch("subprocess.run"):
            d._check_abort_signal()

        assert len(d.running) == 0
        mock_queue.fail.assert_called_once()
        # Signal file should be cleaned up
        assert not (ws / ".swarm" / "abort-signal").exists()

    def test_no_abort_signal_no_action(self, dispatcher_setup):
        """No abort signal file should leave running investigations alone."""
        d, msgs, docs, tmp_path = dispatcher_setup

        ws = tmp_path / "ws"
        ws.mkdir()

        d.running[1] = RunningInvestigation(
            investigation_id=1,
            workspace_path=ws,
            tmux_session="test-session",
            question="test",
            mode="investigate",
        )

        d._check_abort_signal()

        assert len(d.running) == 1  # Still running


# ---------------------------------------------------------------------------
# Heartbeat stall detection in dispatcher
# ---------------------------------------------------------------------------

class TestHeartbeatStallDetection:
    def test_check_heartbeat_no_files(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="investigate",
        )
        events = d._check_heartbeat_stalls(run)
        assert events == []

    def test_check_heartbeat_stalled(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="investigate",
        )
        # Create a stalled heartbeat file
        from datetime import datetime, timezone, timedelta
        base = datetime.now(timezone.utc) - timedelta(minutes=15)
        path = tmp_path / ".swarm" / "heartbeat-stuck-agent.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for i in range(5):
            ts = (base + timedelta(minutes=i * 3)).isoformat()
            lines.append(json.dumps({
                "branch": "stuck-agent", "phase": "building", "iteration": 1,
                "last_action": "waiting", "status": "idle", "timestamp": ts,
            }))
        path.write_text("\n".join(lines) + "\n")

        events = d._check_heartbeat_stalls(run)
        assert len(events) == 1
        assert "stuck" in events[0]["msg"]


# ---------------------------------------------------------------------------
# DESIGN_INVALID detection
# ---------------------------------------------------------------------------

class TestDesignInvalidDetection:
    def test_detects_design_invalid(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="investigate",
        )
        tasks = [
            {"id": "bd-5", "title": "Test encoding ablation", "status": "open",
             "notes": "DESIGN_INVALID: L1 beats L4, encoding inputs identical"},
        ]
        events = d._check_design_invalid(run, tasks)
        assert len(events) == 1
        assert events[0]["type"] == "design_invalid"
        assert "DESIGN INVALID" in events[0]["msg"]

    def test_ignores_closed_design_invalid(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="investigate",
        )
        tasks = [
            {"id": "bd-5", "title": "Test encoding", "status": "closed",
             "notes": "DESIGN_INVALID: was fixed"},
        ]
        events = d._check_design_invalid(run, tasks)
        assert len(events) == 0

    def test_notifies_only_once(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="investigate",
        )
        tasks = [
            {"id": "bd-5", "title": "Test", "status": "open",
             "notes": "DESIGN_INVALID: broken"},
        ]
        events1 = d._check_design_invalid(run, tasks)
        events2 = d._check_design_invalid(run, tasks)
        assert len(events1) == 1
        assert len(events2) == 0  # Already notified
