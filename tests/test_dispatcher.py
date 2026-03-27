"""Tests for the investigation dispatcher (refactored).

inbox processing has been removed — the router enqueues directly.
The dispatcher now only: dispatch_next() + poll_progress().
"""

import json
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
            mode="discover",
        )
        run.task_snapshot = {"bd-1": {"status": "open", "title": "Incomplete"}}

        d._handle_completion(run, failed=True, failure_reason="Agent exited unexpectedly")

        mock_queue.fail.assert_called_once_with(1, "Agent exited unexpectedly")
        mock_queue.complete.assert_not_called()
        assert len(msgs) >= 1
        assert "failed" in msgs[0].lower()

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
             patch("voronoi.server.dispatcher.subprocess.run") as mock_run:
            d._launch_in_tmux("test-session", tmp_path)

        assert mock_run.call_count >= 3


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

        d._check_context_pressure(run, elapsed_hours=13)

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

        d._check_context_pressure(run, elapsed_hours=21)

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

        d._check_context_pressure(run, elapsed_hours=13)
        d._check_context_pressure(run, elapsed_hours=14)

        # Should not re-write if same level
        assert run.context_directive_level == "context_advisory"


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
