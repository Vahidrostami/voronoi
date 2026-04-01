"""Tests for the investigation dispatcher (refactored).

inbox processing has been removed — the router enqueues directly.
The dispatcher now only: dispatch_next() + poll_progress().
"""

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from voronoi.server.dispatcher import (
    DispatcherConfig,
    InvestigationDispatcher,
    RunningInvestigation,
)
from voronoi.server.events import SwarmEvent, append_event


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
            mode="discover",
        )

        with patch("subprocess.run"):
            d._handle_abort()

        assert len(d.running) == 0
        mock_queue.fail.assert_called_once()

    def test_recover_running_scientific_requires_completion_gate(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "deliverable.md").write_text("# Partial\n")

        mock_queue.get_running.return_value = [
            SimpleNamespace(
                id=1,
                workspace_path=str(tmp_path),
                question="test",
                mode="prove",
                codename="Dopamine",
                chat_id="123",
                rigor="scientific",
                started_at=time.time(),
            )
        ]

        with patch("voronoi.server.dispatcher.subprocess.run", return_value=MagicMock(returncode=1)), \
             patch.object(d, "_try_restart", return_value=False) as try_restart, \
             patch.object(d, "_handle_completion") as handle_completion:
            d._recover_running()

        try_restart.assert_called_once()
        assert handle_completion.call_count == 1
        assert handle_completion.call_args.kwargs["failed"] is True


class TestProgressMonitoring:
    def test_diff_tasks_detects_completion(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
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
            mode="discover",
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
            mode="discover",
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
            mode="discover",
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
            mode="discover",
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
            mode="discover",
        )
        run.task_snapshot = {"bd-1": {"status": "closed", "title": "Done"}}

        # Mock queue.get() for the review transition path
        mock_inv = MagicMock()
        mock_inv.lineage_id = None
        mock_inv.cycle_number = 1
        mock_queue.get.return_value = mock_inv

        with patch("voronoi.server.dispatcher.subprocess.run"):
            d._handle_completion(run)

        # Science investigations go to review, not complete
        mock_queue.review.assert_called_once_with(1)
        assert len(msgs) >= 1

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
            mode="discover",
        )
        run.task_snapshot = {"bd-1": {"status": "open", "title": "Incomplete"}}

        d._handle_completion(run, failed=True, failure_reason="Agent exited unexpectedly")

        mock_queue.fail.assert_called_once_with(1, "Agent exited unexpectedly")
        mock_queue.complete.assert_not_called()
        assert len(msgs) >= 1
        assert "didn't make it" in msgs[0].lower()

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
            mode="discover",
            chat_id="12345",
        )
        run.task_snapshot = {"bd-1": {"status": "closed", "title": "Done"}}

        # Mock queue.get() for the review transition path
        mock_inv = MagicMock()
        mock_inv.lineage_id = None
        mock_inv.cycle_number = 1
        mock_queue.get.return_value = mock_inv

        with patch("voronoi.server.dispatcher.subprocess.run"):
            d._handle_completion(run)

        # If a document was sent, it should use the per-investigation chat_id
        for doc in docs:
            assert doc[0] == "12345", f"Expected chat_id '12345', got '{doc[0]}'"

    def test_poll_progress_includes_event_log_alerts(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        d.running[1] = run

        with patch.object(d, "_check_abort_signal"), \
             patch.object(d, "check_human_gates"), \
             patch.object(d, "_refresh_eval_score"), \
             patch.object(d, "_check_progress", return_value=[{"type": "task_new", "msg": "task"}]), \
             patch.object(d, "_check_event_log", return_value=[{"type": "event_log", "msg": "event"}]), \
             patch.object(d, "_is_complete", return_value=False), \
             patch.object(d, "_send_progress_batch") as send_batch, \
             patch("voronoi.server.dispatcher.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            d.poll_progress()

        sent_events = send_batch.call_args.args[1]
        assert [event["type"] for event in sent_events] == ["task_new", "event_log"]

    def test_poll_progress_reports_clean_exit_before_convergence(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "agent.log").write_text(
            "Total usage est: 3 Premium requests\n"
            "Total session time: 5m 43s\n"
            "Breakdown by AI model:\n"
            "logout\n"
        )

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
            rigor="adaptive",
        )
        d.running[1] = run

        with patch.object(d, "_check_abort_signal"), \
             patch.object(d, "check_human_gates"), \
             patch.object(d, "_refresh_eval_score"), \
             patch.object(d, "_check_progress", return_value=[]), \
             patch.object(d, "_check_event_log", return_value=[]), \
             patch.object(d, "_try_restart", return_value=False), \
             patch("voronoi.server.dispatcher.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            d.poll_progress()

        failure_reason = mock_queue.fail.call_args.args[1]
        assert "cleanly before convergence" in failure_reason
        assert "no deliverable produced" in failure_reason.lower()

    def test_check_event_log_reads_worker_worktrees(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )

        swarm_dir = tmp_path / "investigation-swarm"
        worker = swarm_dir / "agent-1"
        worker.mkdir(parents=True)
        (tmp_path / ".swarm-config.json").write_text(json.dumps({"swarm_dir": str(swarm_dir)}))
        append_event(worker, SwarmEvent(agent="agent-1", event="tool_call", status="fail"))

        events = d._check_event_log(run)

        assert len(events) == 1
        assert events[0]["type"] == "event_log"
        assert "1 failures" in events[0]["msg"]


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
            mode="discover",
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
            mode="discover",
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
            mode="discover",
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
            mode="discover",
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

    def test_check_progress_does_not_emit_heartbeat_events_by_default(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        run.task_snapshot = {"bd-1": {"status": "in_progress", "title": "Task 1", "notes": ""}}

        with patch.object(d, "_check_findings", return_value=[]), \
             patch.object(d, "_check_design_invalid", return_value=[]), \
             patch.object(d, "_check_event_log", return_value=[]), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps([
                    {"id": "bd-1", "status": "in_progress", "title": "Task 1", "notes": ""},
                ]),
                stderr="",
            )
            events = d._check_progress(run)

        assert all(event["type"] != "heartbeat_stall" for event in events)


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
            mode="discover",
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
            mode="discover",
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
            mode="discover",
        )
        tasks = [
            {"id": "bd-5", "title": "Test", "status": "open",
             "notes": "DESIGN_INVALID: broken"},
        ]
        events1 = d._check_design_invalid(run, tasks)
        events2 = d._check_design_invalid(run, tasks)
        assert len(events1) == 1
        assert len(events2) == 0  # Already notified


# ---------------------------------------------------------------------------
# DESIGN_INVALID hard gate (structural enforcement)
# ---------------------------------------------------------------------------

class TestDesignInvalidHardGate:
    """Test that DESIGN_INVALID structurally blocks completion and success."""

    def test_has_open_design_invalid_true(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        run.task_snapshot = {
            "bd-1": {"status": "open", "title": "Experiment",
                     "notes": "DESIGN_INVALID: encoding identical"},
        }
        assert d._has_open_design_invalid(run) is True

    def test_has_open_design_invalid_false_when_closed(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        run.task_snapshot = {
            "bd-1": {"status": "closed", "title": "Experiment",
                     "notes": "DESIGN_INVALID: was fixed"},
        }
        assert d._has_open_design_invalid(run) is False

    def test_has_open_design_invalid_false_no_flag(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        run.task_snapshot = {
            "bd-1": {"status": "open", "title": "Task", "notes": ""},
        }
        assert d._has_open_design_invalid(run) is False

    def test_has_open_design_invalid_handles_missing_notes(self, dispatcher_setup):
        """Snapshots from before the notes field was added should not crash."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        run.task_snapshot = {
            "bd-1": {"status": "open", "title": "Task"},
        }
        assert d._has_open_design_invalid(run) is False

    def test_is_complete_blocked_by_design_invalid(self, dispatcher_setup):
        """_is_complete must return False when DESIGN_INVALID is open."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        (tmp_path / ".swarm").mkdir(parents=True)
        (tmp_path / ".swarm" / "deliverable.md").write_text("# Results\n")
        run.task_snapshot = {
            "bd-1": {"status": "open", "title": "Experiment",
                     "notes": "DESIGN_INVALID: L1 > L4"},
        }
        assert d._is_complete(run) is False

    def test_is_complete_unblocked_when_design_invalid_closed(self, dispatcher_setup):
        """Closed DESIGN_INVALID tasks should not block completion."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        (tmp_path / ".swarm").mkdir(parents=True)
        (tmp_path / ".swarm" / "deliverable.md").write_text("# Results\n")
        run.task_snapshot = {
            "bd-1": {"status": "closed", "title": "Experiment",
                     "notes": "DESIGN_INVALID: was fixed"},
        }
        assert d._is_complete(run) is True

    def test_is_complete_string_convergence_json(self, dispatcher_setup):
        """convergence.json containing a string must not crash _is_complete."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
            rigor="scientific",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "deliverable.md").write_text("# Results\n")
        # Write convergence.json as a bare string (not a dict)
        (swarm / "convergence.json").write_text('"approved"')
        # Should return False (not recognized) but must NOT raise AttributeError
        assert d._is_complete(run) is False

    def test_handle_completion_blocked_by_design_invalid(self, dispatcher_setup):
        """_handle_completion should refuse success when DESIGN_INVALID is open."""
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        run.task_snapshot = {
            "bd-1": {"status": "open", "title": "Experiment",
                     "notes": "DESIGN_INVALID: encoding broken"},
        }

        with patch("voronoi.server.dispatcher.subprocess.run"):
            d._handle_completion(run)

        # Should NOT have called queue.complete
        mock_queue.complete.assert_not_called()
        # Should have sent a blocking message
        assert any("DESIGN_INVALID" in m for m in msgs)

    def test_handle_completion_allows_failed_even_with_design_invalid(self, dispatcher_setup):
        """Failed completions should still go through (crash reporting)."""
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        run.task_snapshot = {
            "bd-1": {"status": "open", "title": "Experiment",
                     "notes": "DESIGN_INVALID: encoding broken"},
        }

        with patch("voronoi.server.dispatcher.subprocess.run"):
            d._handle_completion(run, failed=True, failure_reason="agent crashed")

        mock_queue.fail.assert_called_once()

    def test_diff_tasks_stores_notes_in_snapshot(self, dispatcher_setup):
        """_diff_tasks should capture notes so _has_open_design_invalid works."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        run.task_snapshot = {}

        tasks = [
            {"id": "bd-1", "status": "open", "title": "Experiment",
             "notes": "DESIGN_INVALID: broken"},
        ]
        d._diff_tasks(run, tasks)
        assert "DESIGN_INVALID" in run.task_snapshot["bd-1"]["notes"]


# ---------------------------------------------------------------------------
# Experiment Sentinel (contract-based structural validation)
# ---------------------------------------------------------------------------

class TestSentinelDispatcher:
    """Tests for _check_sentinel in the dispatcher."""

    def test_no_contract_no_events(self, dispatcher_setup):
        """No contract file → sentinel returns empty events."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1, workspace_path=tmp_path,
            tmux_session="test", question="test", mode="prove",
            rigor="scientific",
        )
        events = d._check_sentinel(run)
        assert events == []

    def test_missing_contract_warning_after_1h(self, dispatcher_setup):
        """At Analytical+ rigor, warn if no contract exists after 1 hour."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1, workspace_path=tmp_path,
            tmux_session="test", question="test", mode="prove",
            rigor="scientific",
        )
        # Simulate 1.5 hours elapsed
        run.started_at = time.time() - 5400
        # Add experiment-like tasks to snapshot
        run.task_snapshot = {
            "bd-1": {"status": "open", "title": "Phase 0 experiment", "notes": ""},
        }
        events = d._check_sentinel(run)
        assert len(events) == 1
        assert "SENTINEL WARNING" in events[0]["msg"]
        assert "No experiment contract" in events[0]["msg"]
        # Second call should NOT warn again
        events2 = d._check_sentinel(run)
        assert events2 == []

    def test_missing_contract_skipped_for_standard_rigor(self, dispatcher_setup):
        """Standard rigor → no warning about missing contract."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1, workspace_path=tmp_path,
            tmux_session="test", question="test", mode="discover",
            rigor="standard",
        )
        run.started_at = time.time() - 7200
        run.task_snapshot = {
            "bd-1": {"status": "open", "title": "Build experiment", "notes": ""},
        }
        events = d._check_sentinel(run)
        assert events == []

    def test_sentinel_runs_on_contract_change(self, dispatcher_setup):
        """Sentinel should trigger when contract file is modified."""
        d, msgs, docs, tmp_path = dispatcher_setup
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        # Write a contract with no checks (should pass)
        (swarm / "experiment-contract.json").write_text(json.dumps({
            "experiment_id": "e1",
            "independent_variable": "x",
            "conditions": [],
            "manipulation_checks": [],
            "required_outputs": [],
            "degeneracy_checks": [],
            "phase_gates": [],
        }))
        run = RunningInvestigation(
            investigation_id=1, workspace_path=tmp_path,
            tmux_session="test", question="test", mode="prove",
            rigor="scientific",
        )
        events = d._check_sentinel(run)
        # Should run (contract changed since no prior audit)
        assert (swarm / "sentinel-audit.json").exists()

    def test_sentinel_writes_directive_on_failure(self, dispatcher_setup):
        """Sentinel failure should write a dispatcher directive."""
        d, msgs, docs, tmp_path = dispatcher_setup
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        # Contract with a check that will fail (required output missing)
        (swarm / "experiment-contract.json").write_text(json.dumps({
            "experiment_id": "e1",
            "independent_variable": "x",
            "conditions": [],
            "manipulation_checks": [],
            "required_outputs": [{"path": "output/missing.json", "description": "test"}],
            "degeneracy_checks": [],
            "phase_gates": [],
        }))
        run = RunningInvestigation(
            investigation_id=1, workspace_path=tmp_path,
            tmux_session="test", question="test", mode="prove",
            rigor="scientific",
        )
        events = d._check_sentinel(run)
        assert len(events) == 1
        assert events[0]["type"] == "design_invalid"
        # Directive should exist
        directive = swarm / "dispatcher-directive.json"
        assert directive.exists()
        data = json.loads(directive.read_text())
        assert data["level"] == "sentinel_violation"
        assert data["action"] == "stop_and_fix"

    def test_has_experiment_tasks(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1, workspace_path=tmp_path,
            tmux_session="test", question="test", mode="prove",
        )
        run.task_snapshot = {
            "bd-1": {"status": "open", "title": "Phase 2 factorial experiment", "notes": ""},
        }
        assert d._has_experiment_tasks(run) is True

        run.task_snapshot = {
            "bd-1": {"status": "open", "title": "Write README", "notes": ""},
        }
        assert d._has_experiment_tasks(run) is False


# ---------------------------------------------------------------------------
# Resume context injection on restart
# ---------------------------------------------------------------------------

class TestResumeContextInjection:
    def test_build_resume_prompt_creates_new_file(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        run.retry_count = 1
        run.eval_score = 0.65
        run.task_snapshot = {
            "bd-1": {"status": "closed", "title": "Task 1"},
            "bd-2": {"status": "open", "title": "Write manuscript"},
        }

        prompt_file = tmp_path / ".swarm" / "orchestrator-prompt.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text("Original prompt content")

        resume_file = d._build_resume_prompt(run)

        # Resume file should be a NEW file, not the original
        assert resume_file != prompt_file
        assert resume_file.exists()
        content = resume_file.read_text()
        assert "RESTART" in content
        assert "1/2" in content  # tasks complete
        assert "Write manuscript" in content  # remaining task
        assert "0.65" in content  # eval score
        # Original prompt must NOT be modified
        assert prompt_file.read_text() == "Original prompt content"

    def test_build_resume_prompt_includes_success_criteria(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        run.retry_count = 1

        prompt_file = tmp_path / ".swarm" / "orchestrator-prompt.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text("Original prompt")

        sc_path = tmp_path / ".swarm" / "success-criteria.json"
        sc_path.write_text(json.dumps([
            {"id": "SC1", "description": "L4 > L1", "met": True},
            {"id": "SC2", "description": "Pipeline 10x", "met": False},
        ]))

        resume_file = d._build_resume_prompt(run)

        content = resume_file.read_text()
        assert "1/2 met" in content
        assert "SC1" in content
        assert "SC2" in content

    def test_build_resume_prompt_includes_checkpoint(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        run.retry_count = 1

        prompt_file = tmp_path / ".swarm" / "orchestrator-prompt.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text("Original prompt")

        from voronoi.science.convergence import OrchestratorCheckpoint, save_checkpoint
        cp = OrchestratorCheckpoint(
            cycle=5, phase="writing", total_tasks=10, closed_tasks=8,
            next_actions=["Dispatch scribe for manuscript"],
        )
        save_checkpoint(tmp_path, cp)

        resume_file = d._build_resume_prompt(run)

        content = resume_file.read_text()
        assert "cycle 5" in content
        assert "writing" in content
        assert "8/10" in content

    def test_build_resume_prompt_tolerates_missing_files(self, dispatcher_setup):
        """Should not crash if checkpoint/criteria files are missing."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        run.retry_count = 1

        prompt_file = tmp_path / ".swarm" / "orchestrator-prompt.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text("Original prompt")

        resume_file = d._build_resume_prompt(run)

        content = resume_file.read_text()
        assert "RESTART" in content
        assert "Scribe" in content


class TestLaunchInTmux:
    def test_non_copilot_agent_skips_copilot_auth(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup

        with patch.object(d, "_ensure_copilot_auth", side_effect=AssertionError("should not be called")), \
             patch("voronoi.server.dispatcher.shutil.which", return_value="/bin/echo"), \
             patch("voronoi.server.dispatcher.subprocess.run",
                   return_value=MagicMock(returncode=0, stderr=b"")) as mock_run:
            d._launch_in_tmux("test-session", tmp_path)

        assert mock_run.call_count >= 3

    def test_launch_propagates_copilot_state_env(self, dispatcher_setup, monkeypatch):
        d, msgs, docs, tmp_path = dispatcher_setup
        monkeypatch.setenv("COPILOT_HOME", "/srv/copilot-state")
        monkeypatch.setenv("GH_HOST", "github.example.com")
        (tmp_path / ".swarm").mkdir(parents=True, exist_ok=True)

        with patch("voronoi.server.dispatcher.shutil.which", return_value="/bin/echo"), \
             patch("voronoi.server.dispatcher.subprocess.run",
                   return_value=MagicMock(returncode=0, stderr=b"")) as mock_run:
            d._launch_in_tmux("test-session", tmp_path)

        calls = [call.args[0] for call in mock_run.call_args_list]
        # Still propagated via set-environment for future panes
        assert [
            "tmux", "set-environment", "-t", "test-session",
            "COPILOT_HOME", "/srv/copilot-state",
        ] in calls
        assert [
            "tmux", "set-environment", "-t", "test-session",
            "GH_HOST", "github.example.com",
        ] in calls
        # Env file written for the initial pane's shell
        env_file = tmp_path / ".swarm" / ".tmux-env"
        assert env_file.exists()
        content = env_file.read_text()
        assert "COPILOT_HOME=" in content
        assert "GH_HOST=" in content
        # File has restricted permissions
        assert oct(env_file.stat().st_mode & 0o777) == "0o600"
        # send-keys sources the env file
        send_keys_calls = [c for c in mock_run.call_args_list
                           if "send-keys" in str(c)]
        assert send_keys_calls
        cmd = str(send_keys_calls[-1])
        assert "source" in cmd
        assert ".tmux-env" in cmd

    def test_gh_token_written_to_env_file(self, dispatcher_setup, monkeypatch):
        """GH_TOKEN from .env reaches copilot via env file, not just set-environment."""
        d, msgs, docs, tmp_path = dispatcher_setup
        monkeypatch.setenv("GH_TOKEN", "ghp_test_token_value")
        (tmp_path / ".swarm").mkdir(parents=True, exist_ok=True)

        with patch("voronoi.server.dispatcher.shutil.which", return_value="/bin/echo"), \
             patch("voronoi.server.dispatcher.subprocess.run",
                   return_value=MagicMock(returncode=0, stderr=b"")):
            d._launch_in_tmux("test-session", tmp_path)

        env_file = tmp_path / ".swarm" / ".tmux-env"
        assert env_file.exists()
        content = env_file.read_text()
        assert "GH_TOKEN=" in content

    def test_launch_propagates_runtime_temp_env(self, dispatcher_setup, monkeypatch):
        d, msgs, docs, tmp_path = dispatcher_setup
        monkeypatch.setenv("TMPDIR", "/srv/voronoi-tmp")
        monkeypatch.setenv("TMP", "/srv/voronoi-tmp")
        monkeypatch.setenv("TEMP", "/srv/voronoi-tmp")
        (tmp_path / ".swarm").mkdir(parents=True, exist_ok=True)

        with patch("voronoi.server.dispatcher.shutil.which", return_value="/bin/echo"), \
             patch("voronoi.server.dispatcher.subprocess.run",
                   return_value=MagicMock(returncode=0, stderr=b"")) as mock_run:
            d._launch_in_tmux("test-session", tmp_path)

        calls = [call.args[0] for call in mock_run.call_args_list]
        assert ["tmux", "set-environment", "-t", "test-session", "TMPDIR", "/srv/voronoi-tmp"] in calls
        assert ["tmux", "set-environment", "-t", "test-session", "TMP", "/srv/voronoi-tmp"] in calls
        assert ["tmux", "set-environment", "-t", "test-session", "TEMP", "/srv/voronoi-tmp"] in calls

        env_file = tmp_path / ".swarm" / ".tmux-env"
        assert env_file.exists()
        content = env_file.read_text()
        assert "TMPDIR=" in content
        assert "TMP=" in content
        assert "TEMP=" in content

    def test_no_env_file_when_no_vars(self, dispatcher_setup, monkeypatch):
        """No env file or source command when no auth vars are set."""
        d, msgs, docs, tmp_path = dispatcher_setup
        for var in ("GH_TOKEN", "GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN",
                    "COPILOT_HOME", "GH_HOST", "TMPDIR", "TMP", "TEMP"):
            monkeypatch.delenv(var, raising=False)
        (tmp_path / ".swarm").mkdir(parents=True, exist_ok=True)

        with patch("voronoi.server.dispatcher.shutil.which", return_value="/bin/echo"), \
             patch("voronoi.server.dispatcher.subprocess.run",
                   return_value=MagicMock(returncode=0, stderr=b"")) as mock_run:
            d._launch_in_tmux("test-session", tmp_path)

        env_file = tmp_path / ".swarm" / ".tmux-env"
        assert not env_file.exists()
        send_keys_calls = [c for c in mock_run.call_args_list
                           if "send-keys" in str(c)]
        cmd = str(send_keys_calls[-1])
        assert "source" not in cmd

    def test_effort_flag_from_rigor(self, dispatcher_setup):
        """--effort flag is derived from rigor level."""
        d, msgs, docs, tmp_path = dispatcher_setup
        (tmp_path / ".swarm").mkdir(parents=True, exist_ok=True)

        with patch("voronoi.server.dispatcher.shutil.which", return_value="/bin/echo"), \
             patch("voronoi.server.dispatcher.subprocess.run",
                   return_value=MagicMock(returncode=0, stderr=b"")) as mock_run:
            d._launch_in_tmux("test-session", tmp_path, rigor="experimental")

        # Find the send-keys call containing the copilot command
        send_keys_calls = [c for c in mock_run.call_args_list
                           if "send-keys" in str(c)]
        assert send_keys_calls
        cmd = str(send_keys_calls[-1])
        assert "--effort xhigh" in cmd

    def test_effort_defaults_to_medium(self, dispatcher_setup):
        """Unknown rigor maps to medium effort."""
        d, msgs, docs, tmp_path = dispatcher_setup
        (tmp_path / ".swarm").mkdir(parents=True, exist_ok=True)

        with patch("voronoi.server.dispatcher.shutil.which", return_value="/bin/echo"), \
             patch("voronoi.server.dispatcher.subprocess.run",
                   return_value=MagicMock(returncode=0, stderr=b"")) as mock_run:
            d._launch_in_tmux("test-session", tmp_path, rigor="")

        send_keys_calls = [c for c in mock_run.call_args_list
                           if "send-keys" in str(c)]
        assert send_keys_calls
        cmd = str(send_keys_calls[-1])
        assert "--effort medium" in cmd

    def test_share_flag_included(self, dispatcher_setup):
        """--share flag points to .swarm/session.md."""
        d, msgs, docs, tmp_path = dispatcher_setup
        (tmp_path / ".swarm").mkdir(parents=True, exist_ok=True)

        with patch("voronoi.server.dispatcher.shutil.which", return_value="/bin/echo"), \
             patch("voronoi.server.dispatcher.subprocess.run",
                   return_value=MagicMock(returncode=0, stderr=b"")) as mock_run:
            d._launch_in_tmux("test-session", tmp_path)

        send_keys_calls = [c for c in mock_run.call_args_list
                           if "send-keys" in str(c)]
        assert send_keys_calls
        cmd = str(send_keys_calls[-1])
        assert "--share" in cmd
        assert "session.md" in cmd

    def test_effort_by_rigor_mapping(self):
        """Verify the complete rigor-to-effort mapping."""
        from voronoi.server.dispatcher import InvestigationDispatcher
        mapping = InvestigationDispatcher._EFFORT_BY_RIGOR
        assert mapping["adaptive"] == "high"
        assert mapping["scientific"] == "high"
        assert mapping["experimental"] == "xhigh"

    def test_patch_swarm_config(self, dispatcher_setup):
        """_patch_swarm_config writes effort, permissions, and MCP config."""
        d, msgs, docs, tmp_path = dispatcher_setup

        # Start with a minimal config
        config_path = tmp_path / ".swarm-config.json"
        config_path.write_text(json.dumps({"project_dir": str(tmp_path)}))

        d._patch_swarm_config(tmp_path, "experimental")

        data = json.loads(config_path.read_text())
        assert data["effort"] == "xhigh"
        assert "role_permissions" in data
        assert "--deny-tool=write" in data["role_permissions"]["scout"]
        assert "--deny-tool=write" in data["role_permissions"]["review_critic"]

        mcp_path = tmp_path / ".github" / "mcp-config.json"
        mcp = json.loads(mcp_path.read_text())
        assert mcp["mcpServers"]["voronoi"]["command"] == sys.executable
        assert mcp["mcpServers"]["voronoi"]["args"] == ["-m", "voronoi.mcp"]


# ---------------------------------------------------------------------------
# Workspace activity detection (Change 4)
# ---------------------------------------------------------------------------

class TestWorkspaceActivityDetection:
    def test_has_activity_with_checkpoint(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)
        (swarm / "orchestrator-checkpoint.json").write_text(
            json.dumps({"cycle": 2, "total_tasks": 5})
        )
        assert d._has_workspace_activity(run) is True

    def test_has_activity_with_experiments(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)
        (swarm / "experiments.tsv").write_text(
            "timestamp\ttask_id\tbranch\tmetric\tvalue\tstatus\tdesc\n"
            "2026-03-26\tbd-1\tagent-pilot\tMBRS\t0.3\tkeep\tpilot\n"
        )
        assert d._has_workspace_activity(run) is True

    def test_no_activity_with_empty_workspace(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        assert d._has_workspace_activity(run) is False

    def test_no_activity_with_cycle_zero(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)
        (swarm / "orchestrator-checkpoint.json").write_text(
            json.dumps({"cycle": 0, "total_tasks": 0})
        )
        assert d._has_workspace_activity(run) is False


# ---------------------------------------------------------------------------
# Context pressure directives (Changes 3, 6)
# ---------------------------------------------------------------------------

class TestContextPressure:
    def test_advisory_directive_at_threshold(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        (tmp_path / ".swarm").mkdir(parents=True, exist_ok=True)

        d._check_context_pressure(run, elapsed_hours=7)

        directive_path = tmp_path / ".swarm" / "dispatcher-directive.json"
        assert directive_path.exists()
        data = json.loads(directive_path.read_text())
        assert data["directive"] == "context_advisory"
        assert run.context_directive_level == "context_advisory"

    def test_warning_directive_escalates(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        (tmp_path / ".swarm").mkdir(parents=True, exist_ok=True)

        d._check_context_pressure(run, elapsed_hours=11)

        directive_path = tmp_path / ".swarm" / "dispatcher-directive.json"
        data = json.loads(directive_path.read_text())
        assert data["directive"] == "context_warning"
        assert run.context_directive_level == "context_warning"

    def test_critical_directive_from_checkpoint(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)
        (swarm / "orchestrator-checkpoint.json").write_text(
            json.dumps({"context_window_remaining_pct": 0.12})
        )

        d._check_context_pressure(run, elapsed_hours=5)  # early, but self-reported

        directive_path = swarm / "dispatcher-directive.json"
        assert directive_path.exists()
        data = json.loads(directive_path.read_text())
        assert data["directive"] == "context_critical"

    def test_critical_directive_from_context_snapshot(self, dispatcher_setup):
        """Dispatcher prefers ground-truth snapshot over self-reported pct."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)
        # Self-reported says 80% remaining, but snapshot says only 10% free
        (swarm / "orchestrator-checkpoint.json").write_text(
            json.dumps({
                "cycle": 10,
                "context_window_remaining_pct": 0.80,
                "context_snapshot": {
                    "model": "claude-opus-4.6",
                    "model_limit": 200000,
                    "total_used": 180000,
                    "free_tokens": 20000,
                },
            })
        )

        d._check_context_pressure(run, elapsed_hours=3)

        directive_path = swarm / "dispatcher-directive.json"
        assert directive_path.exists()
        data = json.loads(directive_path.read_text())
        assert data["directive"] == "context_critical"

    def test_snapshot_logs_context_event(self, dispatcher_setup):
        """Dispatcher logs context_snapshot events to events.jsonl."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)
        (swarm / "orchestrator-checkpoint.json").write_text(
            json.dumps({
                "cycle": 5,
                "context_snapshot": {
                    "model": "claude-opus-4.6",
                    "model_limit": 200000,
                    "total_used": 60000,
                    "system_tokens": 20000,
                    "message_tokens": 40000,
                    "free_tokens": 100000,
                    "buffer_tokens": 40000,
                },
            })
        )

        d._check_context_pressure(run, elapsed_hours=3)

        events_path = swarm / "events.jsonl"
        assert events_path.exists()
        import json as json_mod
        lines = events_path.read_text().strip().split("\n")
        assert len(lines) >= 1
        ev = json_mod.loads(lines[-1])
        assert ev["event"] == "context_snapshot"
        assert ev["tokens_used"] == 60000

    def test_no_duplicate_directives(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        (tmp_path / ".swarm").mkdir(parents=True, exist_ok=True)

        d._check_context_pressure(run, elapsed_hours=7)
        d._check_context_pressure(run, elapsed_hours=8)

        # Should not re-write if same level
        assert run.context_directive_level == "context_advisory"

    def test_warning_directive_includes_compact(self, dispatcher_setup):
        """Context warning directive tells orchestrator to run /compact."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        (tmp_path / ".swarm").mkdir(parents=True, exist_ok=True)

        d._check_context_pressure(run, elapsed_hours=11)

        directive_path = tmp_path / ".swarm" / "dispatcher-directive.json"
        data = json.loads(directive_path.read_text())
        assert "/compact" in data["message"]

    def test_critical_directive_includes_compact(self, dispatcher_setup):
        """Context critical directive tells orchestrator to run /compact."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        (tmp_path / ".swarm").mkdir(parents=True, exist_ok=True)

        d._check_context_pressure(run, elapsed_hours=15)

        directive_path = tmp_path / ".swarm" / "dispatcher-directive.json"
        data = json.loads(directive_path.read_text())
        assert "/compact" in data["message"]


# ---------------------------------------------------------------------------
# Workspace compaction (Change 5)
# ---------------------------------------------------------------------------

class TestWorkspaceCompaction:
    def test_compact_experiments_archives_old_rows(self, dispatcher_setup):
        from voronoi.server.compact import compact_workspace_state
        d, msgs, docs, tmp_path = dispatcher_setup

        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)

        header = "timestamp\ttask_id\tbranch\tmetric\tvalue\tstatus\tdesc"
        rows = [f"2026-03-{i:02d}\tbd-{i}\tagent-{i}\tMBRS\t{i/100}\tkeep\trun {i}"
                for i in range(1, 31)]
        (swarm / "experiments.tsv").write_text(
            header + "\n" + "\n".join(rows) + "\n"
        )

        compact_workspace_state(tmp_path)

        # Active file should have header + 20 recent rows
        active = (swarm / "experiments.tsv").read_text().strip().splitlines()
        assert len(active) == 21  # header + 20

        # Archive should have the 10 old rows
        archive = (swarm / "experiments.archive.tsv").read_text().strip().splitlines()
        assert len(archive) == 11  # header + 10

    def test_compact_writes_state_digest(self, dispatcher_setup):
        from voronoi.server.compact import compact_workspace_state
        d, msgs, docs, tmp_path = dispatcher_setup

        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)
        (swarm / "success-criteria.json").write_text(json.dumps([
            {"id": "SC1", "description": "Test criterion", "met": True},
        ]))

        compact_workspace_state(tmp_path)

        digest = (swarm / "state-digest.md").read_text()
        assert "State Digest" in digest
        assert "SC1" in digest
        assert "1/1 met" in digest

    def test_compact_recent_events_keeps_live_log(self, dispatcher_setup):
        from voronoi.server.compact import compact_workspace_state

        d, msgs, docs, tmp_path = dispatcher_setup
        for i in range(60):
            append_event(
                tmp_path,
                SwarmEvent(ts=time.time() - 60, agent="agent", event=f"event-{i}"),
            )

        changed = compact_workspace_state(tmp_path)

        assert changed is False
        events_file = tmp_path / ".swarm" / "events.jsonl"
        assert len(events_file.read_text().strip().splitlines()) == 60
        assert not (tmp_path / ".swarm" / "events.archive.jsonl").exists()

    def test_compact_calls_bd_compact(self, dispatcher_setup):
        """compact_workspace_state should call bd compact when .beads/ exists."""
        from voronoi.server.compact import compact_workspace_state

        d, msgs, docs, tmp_path = dispatcher_setup
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)
        (tmp_path / ".beads").mkdir()

        with patch("voronoi.beads.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="", stderr=""
            )
            changed = compact_workspace_state(tmp_path)

        assert changed is True
        # Verify bd compact was called
        calls = mock_run.call_args_list
        assert any(
            call[0][0] == ["bd", "compact"] for call in calls
        )


# ---------------------------------------------------------------------------
# New tests for reliability fixes
# ---------------------------------------------------------------------------

class TestReliabilityFixes:
    def test_resume_prompt_includes_question(self, dispatcher_setup):
        """Resume prompt must include the original investigation question."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="Does structured encoding improve decision quality?",
            mode="discover",
        )
        run.retry_count = 1
        prompt_file = tmp_path / ".swarm" / "orchestrator-prompt.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text("Original prompt")

        resume_file = d._build_resume_prompt(run)
        content = resume_file.read_text()
        assert "structured encoding" in content
        assert "Investigation Question" in content

    def test_resume_prompt_includes_protocol_reference(self, dispatcher_setup):
        """Resume prompt must reference the orchestrator role file."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test question",
            mode="discover",
        )
        run.retry_count = 1
        prompt_file = tmp_path / ".swarm" / "orchestrator-prompt.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text("Original prompt")

        resume_file = d._build_resume_prompt(run)
        content = resume_file.read_text()
        assert "swarm-orchestrator.agent.md" in content
        assert "spawn-agent.sh" in content

    def test_has_pending_human_gate(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        assert d._has_pending_human_gate(run) is False

        gate_path = tmp_path / ".swarm" / "human-gate.json"
        gate_path.parent.mkdir(parents=True, exist_ok=True)
        gate_path.write_text(json.dumps({"status": "pending", "gate": "convergence"}))
        assert d._has_pending_human_gate(run) is True

        gate_path.write_text(json.dumps({"status": "notified", "gate": "convergence"}))
        assert d._has_pending_human_gate(run) is True

        gate_path.write_text(json.dumps({"status": "approved"}))
        assert d._has_pending_human_gate(run) is False

    def test_restore_task_snapshot(self, dispatcher_setup):
        """_restore_task_snapshot should populate task_snapshot from Beads."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        assert run.task_snapshot == {}

        with patch("voronoi.beads.run_bd") as mock_bd:
            mock_bd.return_value = (0, json.dumps([
                {"id": "bd-1", "status": "closed", "title": "Task 1", "notes": ""},
                {"id": "bd-2", "status": "open", "title": "Task 2", "notes": ""},
            ]))
            d._restore_task_snapshot(run)

        assert len(run.task_snapshot) == 2
        assert run.task_snapshot["bd-1"]["status"] == "closed"
        assert run.task_snapshot["bd-2"]["status"] == "open"

    def test_is_complete_accepts_negative_result(self, dispatcher_setup):
        """_is_complete should accept negative_result convergence status."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
            rigor="scientific",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)
        (swarm / "deliverable.md").write_text("# Results")
        (swarm / "convergence.json").write_text(json.dumps({
            "status": "negative_result",
            "converged": True,
            "reason": "Valid negative result",
        }))

        assert d._is_complete(run) is True

    def test_check_criteria_progress_alerts_zero(self, dispatcher_setup):
        """Should alert when zero criteria met after 4+ hours."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)
        (swarm / "success-criteria.json").write_text(json.dumps([
            {"id": "SC1", "description": "test", "met": False},
            {"id": "SC2", "description": "test", "met": False},
        ]))

        d._check_criteria_progress(run, elapsed_hours=5.0)
        assert any("0/2 success criteria met" in m for m in msgs)

    def test_check_criteria_progress_no_alert_when_met(self, dispatcher_setup):
        """Should not alert when some criteria are met."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)
        (swarm / "success-criteria.json").write_text(json.dumps([
            {"id": "SC1", "description": "test", "met": True},
            {"id": "SC2", "description": "test", "met": False},
        ]))

        d._check_criteria_progress(run, elapsed_hours=5.0)
        assert not any("success criteria met" in m for m in msgs)


class TestAuthDetection:
    def test_looks_like_auth_failure_detects_patterns(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        log_tail = (
            "To authenticate, you can use any of the following methods:\n"
            "  • Start 'copilot' and run the '/login' command\n"
            "  • Set the COPILOT_GITHUB_TOKEN, GH_TOKEN, or GITHUB_TOKEN environment variable\n"
            "  • Run 'gh auth login' to authenticate with the GitHub CLI"
        )
        assert d._looks_like_auth_failure(log_tail) is True

    def test_looks_like_auth_failure_negative(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        log_tail = "Agent completed all tasks successfully\nlogout\ntotal session time: 2h"
        assert d._looks_like_auth_failure(log_tail) is False

    def test_looks_like_auth_failure_empty(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        assert d._looks_like_auth_failure("") is False

    def test_looks_like_auth_failure_with_tui_noise(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        log_tail = (
            "To authenticate, you can use any of the following methods:\n"
            "  • Start 'copilot' and run the '/login' command\n"
            "  • Set the COPILOT_GITHUB_TOKEN, GH_TOKEN, or GITHUB_TOKEN environment variable\n"
            "  • Run 'gh auth login' to authenticate with the GitHub CLI\n"
            "[?1049l [?1006l [?1003l [?1002l [?2004l [?1004l [?25h [?2026l [<ulogout"
        )
        assert d._looks_like_auth_failure(log_tail) is True


class TestPauseInvestigation:
    def test_pause_investigation(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test-session",
            question="test",
            mode="discover",
            codename="Synapse",
        )
        d.running[1] = run

        with patch("voronoi.server.dispatcher.subprocess.run"):
            d._pause_investigation(run, "Copilot/GitHub auth expired")

        mock_queue.pause.assert_called_once_with(1, "Copilot/GitHub auth expired")
        assert 1 not in d.running
        assert any("paused" in m.lower() for m in msgs)
        assert any("auth" in m.lower() for m in msgs)

    def test_resume_investigation_success(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup

        # Set up paused investigation data
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)
        (swarm / "orchestrator-prompt.txt").write_text("test prompt")

        mock_queue = MagicMock()
        mock_inv = MagicMock()
        mock_inv.id = 1
        mock_inv.status = "paused"
        mock_inv.workspace_path = str(tmp_path)
        mock_inv.question = "Why?"
        mock_inv.mode = "discover"
        mock_inv.codename = "Synapse"
        mock_inv.chat_id = "123"
        mock_inv.rigor = "adaptive"
        mock_queue.get.return_value = mock_inv
        mock_queue.resume.return_value = True
        d._queue = mock_queue

        with patch.object(d, "_restore_task_snapshot"), \
             patch.object(d, "_build_resume_prompt", return_value=swarm / "resume.txt"), \
             patch.object(d, "_launch_in_tmux"):
            result = d.resume_investigation(1)

        assert "resumed" in result.lower()
        mock_queue.resume.assert_called_once_with(1)
        assert 1 in d.running

    def test_resume_investigation_not_found(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        mock_queue.get.return_value = None
        d._queue = mock_queue

        result = d.resume_investigation(99)
        assert "not found" in result.lower()

    def test_resume_investigation_wrong_status(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        mock_inv = MagicMock()
        mock_inv.id = 1
        mock_inv.status = "complete"
        mock_queue.get.return_value = mock_inv
        d._queue = mock_queue

        result = d.resume_investigation(1)
        assert "complete" in result.lower()
        assert "only resume" in result.lower()

    def test_resume_failed_investigation(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup

        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)
        (swarm / "orchestrator-prompt.txt").write_text("test prompt")

        mock_queue = MagicMock()
        mock_inv = MagicMock()
        mock_inv.id = 2
        mock_inv.status = "failed"
        mock_inv.workspace_path = str(tmp_path)
        mock_inv.question = "Failed Q"
        mock_inv.mode = "prove"
        mock_inv.codename = "Dopamine"
        mock_inv.chat_id = "456"
        mock_inv.rigor = "scientific"
        mock_queue.get.return_value = mock_inv
        mock_queue.resume.return_value = True
        d._queue = mock_queue

        with patch.object(d, "_restore_task_snapshot"), \
             patch.object(d, "_build_resume_prompt", return_value=swarm / "resume.txt"), \
             patch.object(d, "_launch_in_tmux"):
            result = d.resume_investigation(2)

        assert "resumed" in result.lower()
        assert "Dopamine" in result

    def test_check_paused_timeouts(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        d.config.pause_timeout_hours = 1  # 1 hour for test

        mock_queue = MagicMock()
        mock_inv = MagicMock()
        mock_inv.id = 1
        mock_inv.codename = "Synapse"
        mock_inv.started_at = time.time() - 7200  # 2 hours ago
        mock_queue.get_paused.return_value = [mock_inv]
        mock_queue.resume.return_value = True
        d._queue = mock_queue

        d._check_paused_timeouts()

        mock_queue.resume.assert_called_once_with(1)
        mock_queue.fail.assert_called_once()
        assert any("auto-failed" in m.lower() for m in msgs)

    def test_try_restart_auth_failure_pauses(self, dispatcher_setup):
        """Auth failure during restart should pause, not exhaust retries."""
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)
        (swarm / "orchestrator-prompt.txt").write_text("prompt")

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
            codename="Synapse",
        )
        d.running[1] = run

        with patch.object(d, "_read_log_tail", return_value=""), \
             patch.object(d, "_looks_like_clean_agent_exit", return_value=False), \
             patch.object(d, "_build_resume_prompt", return_value=swarm / "resume.txt"), \
             patch.object(d, "_launch_in_tmux", side_effect=RuntimeError("authentication expired")), \
             patch("voronoi.server.dispatcher.subprocess.run"):
            result = d._try_restart(run)

        assert result is False
        mock_queue.pause.assert_called_once()
        assert run.retry_count == 0  # should be undone


class TestLaunchInTmuxSessionSafety:
    """Tests for BUG 1 fix: _launch_in_tmux kills stale sessions and checks RC."""

    def test_kills_stale_session_before_creating(self, dispatcher_setup):
        """_launch_in_tmux should kill any existing session before new-session."""
        d, msgs, docs, tmp_path = dispatcher_setup
        (tmp_path / ".swarm").mkdir(parents=True, exist_ok=True)

        call_order = []

        def track_calls(args, **kwargs):
            if isinstance(args, list) and len(args) >= 2 and args[0] == "tmux":
                call_order.append(args[1])
            return MagicMock(returncode=0, stderr=b"")

        with patch("voronoi.server.dispatcher.shutil.which", return_value="/bin/echo"), \
             patch("voronoi.server.dispatcher.subprocess.run", side_effect=track_calls):
            d._launch_in_tmux("test-session", tmp_path)

        # kill-session must come before new-session
        assert "kill-session" in call_order
        assert "new-session" in call_order
        kill_idx = call_order.index("kill-session")
        new_idx = call_order.index("new-session")
        assert kill_idx < new_idx

    def test_raises_on_tmux_new_session_failure(self, dispatcher_setup):
        """_launch_in_tmux should raise RuntimeError if tmux new-session fails."""
        d, msgs, docs, tmp_path = dispatcher_setup
        (tmp_path / ".swarm").mkdir(parents=True, exist_ok=True)

        def mock_run(args, **kwargs):
            if isinstance(args, list) and "new-session" in args:
                return MagicMock(returncode=1, stderr=b"duplicate session: test-session")
            return MagicMock(returncode=0, stderr=b"")

        with patch("voronoi.server.dispatcher.shutil.which", return_value="/bin/echo"), \
             patch("voronoi.server.dispatcher.subprocess.run", side_effect=mock_run):
            with pytest.raises(RuntimeError, match="Failed to create tmux session"):
                d._launch_in_tmux("test-session", tmp_path)


class TestResumePromptLabel:
    """Tests for BUG 2 fix: resume prompt uses correct label for user-initiated resume."""

    def test_user_resume_says_resume_not_restart(self, dispatcher_setup):
        """retry_count=0 means operator-initiated resume, not a crash restart."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test question",
            mode="discover",
        )
        run.retry_count = 0

        prompt_file = tmp_path / ".swarm" / "orchestrator-prompt.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text("Original prompt")

        resume_file = d._build_resume_prompt(run)
        content = resume_file.read_text()
        assert "RESUME" in content
        assert "operator-initiated" in content
        assert "attempt 0/" not in content

    def test_crash_restart_says_restart_with_count(self, dispatcher_setup):
        """retry_count>0 means crash restart, should show attempt number."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test question",
            mode="discover",
        )
        run.retry_count = 2

        prompt_file = tmp_path / ".swarm" / "orchestrator-prompt.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text("Original prompt")

        resume_file = d._build_resume_prompt(run)
        content = resume_file.read_text()
        assert "RESTART" in content
        assert "attempt 2/2" in content
        assert "RESUME" not in content


class TestConvergenceStatusCaseInsensitive:
    """Tests for case-insensitive convergence status checking."""

    def test_is_complete_uppercase_converged(self, dispatcher_setup):
        """_is_complete should accept uppercase CONVERGED status."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="prove",
            rigor="scientific",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "deliverable.md").write_text("# Results\n")
        (swarm / "convergence.json").write_text(json.dumps({
            "status": "CONVERGED",
            "converged": False,  # agent might not set this
        }))
        assert d._is_complete(run) is True

    def test_is_complete_mixed_case_exhausted(self, dispatcher_setup):
        """_is_complete should accept mixed-case Exhausted status."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="prove",
            rigor="experimental",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "deliverable.md").write_text("# Results\n")
        (swarm / "convergence.json").write_text(json.dumps({
            "status": "Exhausted",
        }))
        assert d._is_complete(run) is True

    def test_is_complete_uppercase_negative_result(self, dispatcher_setup):
        """_is_complete should accept NEGATIVE_RESULT status."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="prove",
            rigor="scientific",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "deliverable.md").write_text("# Results\n")
        (swarm / "convergence.json").write_text(json.dumps({
            "status": "NEGATIVE_RESULT",
        }))
        assert d._is_complete(run) is True

    def test_is_complete_no_deliverable_uppercase_converged(self, dispatcher_setup):
        """_is_complete should accept uppercase CONVERGED even without deliverable."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
            rigor="scientific",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "convergence.json").write_text(json.dumps({
            "status": "CONVERGED",
        }))
        assert d._is_complete(run) is True

    def test_convergence_status_ok_helper(self, dispatcher_setup):
        """_convergence_status_ok should be case-insensitive."""
        d, msgs, docs, tmp_path = dispatcher_setup
        assert d._convergence_status_ok({"status": "converged"}) is True
        assert d._convergence_status_ok({"status": "CONVERGED"}) is True
        assert d._convergence_status_ok({"status": "Converged"}) is True
        assert d._convergence_status_ok({"status": "EXHAUSTED"}) is True
        assert d._convergence_status_ok({"status": "DIMINISHING_RETURNS"}) is True
        assert d._convergence_status_ok({"converged": True}) is True
        assert d._convergence_status_ok({"status": "blocked"}) is False
        assert d._convergence_status_ok({"status": "not_ready"}) is False
        assert d._convergence_status_ok({}) is False
        assert d._convergence_status_ok({"status": 42}) is False


class TestSyncCriteriaFromCheckpoint:
    """Tests for syncing criteria_status from checkpoint into success-criteria.json."""

    def test_sync_updates_met_criteria(self, dispatcher_setup):
        """Criteria marked met in checkpoint should be synced to success-criteria.json."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="prove",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "criteria_status": {"SC1": True, "SC2": False, "SC3": True}
        }))
        (swarm / "success-criteria.json").write_text(json.dumps([
            {"id": "SC1", "description": "First", "met": False},
            {"id": "SC2", "description": "Second", "met": False},
            {"id": "SC3", "description": "Third", "met": False},
        ]))

        d._sync_criteria_from_checkpoint(run)

        result = json.loads((swarm / "success-criteria.json").read_text())
        assert result[0]["met"] is True   # SC1: checkpoint says True
        assert result[1]["met"] is False  # SC2: checkpoint says False
        assert result[2]["met"] is True   # SC3: checkpoint says True

    def test_sync_does_not_demote_met_criteria(self, dispatcher_setup):
        """A stale checkpoint must not clear already-met canonical criteria."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="prove",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "criteria_status": {"SC1": False, "SC2": True}
        }))
        (swarm / "success-criteria.json").write_text(json.dumps([
            {"id": "SC1", "description": "First", "met": True},
            {"id": "SC2", "description": "Second", "met": False},
        ]))

        d._sync_criteria_from_checkpoint(run)

        result = json.loads((swarm / "success-criteria.json").read_text())
        assert result[0]["met"] is True   # stale checkpoint must not demote
        assert result[1]["met"] is True   # checkpoint can still promote

    def test_sync_no_op_when_already_synced(self, dispatcher_setup):
        """Should not rewrite file if nothing changed."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="prove",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "criteria_status": {"SC1": True}
        }))
        sc_content = json.dumps([
            {"id": "SC1", "description": "First", "met": True},
        ])
        (swarm / "success-criteria.json").write_text(sc_content)
        mtime_before = (swarm / "success-criteria.json").stat().st_mtime

        import time as _time
        _time.sleep(0.01)
        d._sync_criteria_from_checkpoint(run)

        mtime_after = (swarm / "success-criteria.json").stat().st_mtime
        assert mtime_before == mtime_after  # file unchanged

    def test_sync_missing_checkpoint_is_no_op(self, dispatcher_setup):
        """Should silently skip when checkpoint doesn't exist."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="prove",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "success-criteria.json").write_text(json.dumps([
            {"id": "SC1", "description": "First", "met": False},
        ]))

        d._sync_criteria_from_checkpoint(run)  # should not raise

        result = json.loads((swarm / "success-criteria.json").read_text())
        assert result[0]["met"] is False  # unchanged

    def test_sync_missing_criteria_file_is_no_op(self, dispatcher_setup):
        """Should silently skip when success-criteria.json doesn't exist."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="prove",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "criteria_status": {"SC1": True}
        }))

        d._sync_criteria_from_checkpoint(run)  # should not raise

    def test_sync_empty_criteria_status_is_no_op(self, dispatcher_setup):
        """Should skip when checkpoint has empty criteria_status."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="prove",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "criteria_status": {}
        }))
        (swarm / "success-criteria.json").write_text(json.dumps([
            {"id": "SC1", "description": "First", "met": False},
        ]))

        d._sync_criteria_from_checkpoint(run)

        result = json.loads((swarm / "success-criteria.json").read_text())
        assert result[0]["met"] is False  # unchanged


class TestStateDigestCriteriaXref:
    """Tests for state digest cross-referencing checkpoint with criteria."""

    def test_digest_uses_checkpoint_criteria(self, tmp_path):
        """Digest should show criteria as MET when checkpoint says so,
        even if success-criteria.json is stale."""
        from voronoi.server.compact import _write_state_digest

        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "success-criteria.json").write_text(json.dumps([
            {"id": "SC1", "description": "Test 1", "met": False},
            {"id": "SC2", "description": "Test 2", "met": False},
        ]))
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "criteria_status": {"SC1": True, "SC2": False}
        }))

        _write_state_digest(tmp_path)

        digest = (swarm / "state-digest.md").read_text()
        assert "1/2 met" in digest
        assert "[MET] SC1" in digest
        assert "[PENDING] SC2" in digest

    def test_digest_without_checkpoint_uses_criteria_only(self, tmp_path):
        """Without checkpoint, digest should use success-criteria.json as-is."""
        from voronoi.server.compact import _write_state_digest

        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "success-criteria.json").write_text(json.dumps([
            {"id": "SC1", "description": "Test 1", "met": True},
            {"id": "SC2", "description": "Test 2", "met": False},
        ]))

        _write_state_digest(tmp_path)

        digest = (swarm / "state-digest.md").read_text()
        assert "1/2 met" in digest


class TestOrphanedWorkerDetection:
    """Tests for orphaned process detection in _has_active_workers."""

    def test_orphaned_process_detected(self, dispatcher_setup):
        """Should detect orphaned copilot processes referencing workspace."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "active_workers": ["worker-1"]
        }))

        tmux_no_session = MagicMock(returncode=1)
        pgrep_found = MagicMock(
            returncode=0,
            stdout=f"12345 copilot --allow-all -p @{tmp_path}/.swarm/prompt.txt\n",
        )

        with patch("voronoi.server.dispatcher.subprocess.run",
                    side_effect=[tmux_no_session, pgrep_found]):
            assert d._has_active_workers(run) is True

    def test_no_orphan_when_pgrep_empty(self, dispatcher_setup):
        """Should return False when pgrep finds nothing."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "active_workers": ["worker-1"]
        }))

        tmux_no_session = MagicMock(returncode=1)
        pgrep_empty = MagicMock(returncode=1, stdout="")

        with patch("voronoi.server.dispatcher.subprocess.run",
                    side_effect=[tmux_no_session, pgrep_empty]):
            assert d._has_active_workers(run) is False

    def test_no_orphan_when_pgrep_unavailable(self, dispatcher_setup):
        """Should return False when pgrep is not available."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "active_workers": ["worker-1"]
        }))

        tmux_no_session = MagicMock(returncode=1)

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd[0] == "tmux":
                return tmux_no_session
            raise FileNotFoundError("pgrep not found")

        with patch("voronoi.server.dispatcher.subprocess.run",
                    side_effect=side_effect):
            assert d._has_active_workers(run) is False


class TestCompletionTaskFallback:
    """Tests for task count fallback when task_snapshot is empty."""

    def test_completion_falls_back_to_bd_when_snapshot_empty(self, dispatcher_setup):
        """Failed completion with empty task_snapshot should try bd list."""
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        # task_snapshot is empty (default)

        bd_result = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {"id": "bd-1", "status": "closed", "title": "Done"},
                {"id": "bd-2", "status": "open", "title": "Open"},
                {"id": "bd-3", "status": "closed", "title": "Also done"},
            ]),
        )

        with patch("voronoi.server.dispatcher.subprocess.run", return_value=bd_result):
            d._handle_completion(run, failed=True, failure_reason="test failure")

        # The failure message should show 2/3 tasks, not 0/0
        assert any("2/3" in m for m in msgs)

    def test_completion_no_fallback_when_snapshot_populated(self, dispatcher_setup):
        """Should not call bd when task_snapshot has entries."""
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        run.task_snapshot = {
            "bd-1": {"status": "closed", "title": "Done"},
        }

        with patch("voronoi.server.dispatcher.subprocess.run") as mock_run:
            d._handle_completion(run, failed=True, failure_reason="test failure")
            # subprocess should only be called for tmux cleanup, not bd
            for call in mock_run.call_args_list:
                cmd = call[0][0] if call[0] else call[1].get("args", [])
                assert cmd[0] != "bd"
