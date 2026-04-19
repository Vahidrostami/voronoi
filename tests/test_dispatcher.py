"""Tests for the investigation dispatcher (refactored).

inbox processing has been removed — the router enqueues directly.
The dispatcher now only: dispatch_next() + poll_progress().
"""

import json
import subprocess
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

    def test_dispatch_next_skips_claim_while_launching(self, dispatcher_setup):
        """dispatch_next should skip queue claim when a launch is in progress."""
        d, msgs, docs, _ = dispatcher_setup
        mock_queue = MagicMock()
        mock_queue.next_ready.return_value = None
        d._queue = mock_queue

        # Simulate a launch in progress
        d._launching.add(99)
        d.dispatch_next()

        # next_ready should NOT have been called — we skipped the claim phase
        mock_queue.next_ready.assert_not_called()
        d._launching.discard(99)

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
        mock_queue.abort.assert_called_once()

    def test_recover_running_readopts_dead_investigation(self, dispatcher_setup):
        """Recovery re-adopts dead investigations into self.running
        instead of calling _handle_completion inline, so poll_progress
        handles completion on the next cycle (keeps dispatch_next fast)."""
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
             patch.object(d, "_handle_completion") as handle_completion:
            d._recover_running()

        # Dead investigation is re-adopted, not completed inline
        assert 1 in d.running
        handle_completion.assert_not_called()


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

        tasks = [
            {"id": "bd-5", "title": "FINDING: EWC beats replay d=0.82", "notes": "EFFECT_SIZE:0.82"},
        ]
        events = d._check_findings(run, tasks)

        assert len(events) == 1
        assert "FINDING" in events[0]["msg"]
        assert "bd-5" in run.notified_findings

    def test_serendipity_detection_from_notes(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )

        tasks = [
            {"id": "bd-8", "title": "Investigate latency",
             "notes": "SERENDIPITY: Cache hit rate correlates with memory pressure"},
        ]
        events = d._check_findings(run, tasks)

        serendipity = [e for e in events if e["type"] == "serendipity"]
        assert len(serendipity) == 1
        assert "Unexpected observation" in serendipity[0]["msg"]
        assert "Cache hit rate" in serendipity[0]["msg"]
        assert "serendipity:bd-8" in run.notified_findings

    def test_serendipity_not_duplicated(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )

        tasks = [
            {"id": "bd-8", "title": "Investigate latency",
             "notes": "SERENDIPITY: Something unexpected"},
        ]
        d._check_findings(run, tasks)
        events2 = d._check_findings(run, tasks)  # second call
        serendipity = [e for e in events2 if e["type"] == "serendipity"]
        assert len(serendipity) == 0  # not duplicated

    def test_rigor_escalation_notification(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
            rigor="adaptive",
            last_rigor="adaptive",
        )

        # Write checkpoint with escalated rigor
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "phase": "investigating",
            "rigor": "scientific",
            "eval_score": 0.0,
        }))

        events = d._detect_phase(run)
        rigor_events = [e for e in events if e["type"] == "rigor_escalation"]
        assert len(rigor_events) == 1
        assert "scientific" in rigor_events[0]["msg"]
        assert run.last_rigor == "scientific"

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

    def test_handle_completion_negative_result(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "deliverable.md").write_text("# Null Result\nHypothesis not supported.")
        (swarm / "convergence.json").write_text(json.dumps({
            "status": "negative_result",
            "converged": True,
            "reason": "Hypothesis falsified — d=0.02, p=0.78",
        }))

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="Does X improve Y?",
            mode="discover",
            codename="Synapse",
        )
        run.task_snapshot = {"bd-1": {"status": "closed", "title": "Experiment"}}
        run.eval_score = 0.78

        mock_inv = MagicMock()
        mock_inv.lineage_id = None
        mock_inv.cycle_number = 1
        mock_queue.get.return_value = mock_inv

        with patch("voronoi.server.dispatcher.subprocess.run"):
            d._handle_completion(run)

        # Should use format_negative_result, not format_failure
        assert any("negative result" in m.lower() for m in msgs)
        assert not any("didn't make it" in m for m in msgs)

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

    def test_handle_completion_writes_run_manifest(self, dispatcher_setup):
        """INV-44: every completion must produce .swarm/run-manifest.json.

        Without this integration test, a regression in
        ``build_manifest_from_workspace`` (e.g. a schema change in any source
        ``.swarm/`` file) would silently disable manifests in production
        because ``_write_run_manifest`` swallows all exceptions.
        """
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "deliverable.md").write_text("# Done")
        (swarm / "convergence.json").write_text(json.dumps({
            "converged": True,
            "status": "converged",
            "reason": "test",
        }))

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="Test question",
            mode="discover",
        )
        run.task_snapshot = {"bd-1": {"status": "closed", "title": "Done"}}

        # Use SimpleNamespace (not MagicMock) so manifest serialization gets
        # concrete values rather than Mock proxies.
        mock_inv = SimpleNamespace(
            id=1, lineage_id=None, cycle_number=1, parent_id=None,
            codename="", mode="discover", rigor="adaptive",
            question="Test question", started_at=None, completed_at=None,
        )
        mock_queue.get.return_value = mock_inv

        with patch("voronoi.server.dispatcher.subprocess.run"):
            d._handle_completion(run)

        manifest_path = tmp_path / ".swarm" / "run-manifest.json"
        assert manifest_path.exists(), "INV-44: run-manifest.json must exist after completion"
        data = json.loads(manifest_path.read_text())
        assert data.get("schema_version") == "1.0"
        assert data.get("converged") is True
        assert data.get("status") == "converged"

    def test_handle_completion_writes_run_manifest_for_build_mode(self, dispatcher_setup):
        """INV-44: build-mode completions also write a manifest."""
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "deliverable.md").write_text("# Built")

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="Build a thing",
            mode="build",
        )
        run.task_snapshot = {"bd-1": {"status": "closed", "title": "Done"}}

        mock_inv = SimpleNamespace(
            id=1, lineage_id=None, cycle_number=1, parent_id=None,
            codename="", mode="build", rigor="standard",
            question="Build a thing", started_at=None, completed_at=None,
        )
        mock_queue.get.return_value = mock_inv

        with patch("voronoi.server.dispatcher.subprocess.run"):
            d._handle_completion(run)

        manifest_path = tmp_path / ".swarm" / "run-manifest.json"
        assert manifest_path.exists(), "INV-44: build-mode must also write a manifest"
        # Build mode goes through queue.complete, not queue.review
        mock_queue.complete.assert_called_once_with(1)

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
        mock_queue.abort.assert_called_once()
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
            events = d._check_progress(run, session_alive=False)

        assert all(event["type"] != "heartbeat_stall" for event in events)

    def test_check_progress_skips_bd_when_session_alive(self, dispatcher_setup):
        """_check_progress must not call bd list --json while the agent session
        is alive — the MCP server holds an exclusive Dolt lock."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        run.task_snapshot = {"bd-1": {"status": "open", "title": "Task 1", "notes": ""}}

        with patch("voronoi.beads.run_bd_json", side_effect=AssertionError("should not be called")) as _:
            # Should NOT call run_bd_json at all when session is alive
            events = d._check_progress(run, session_alive=True)

        # No task events because bd was skipped, but phase detection still works
        assert isinstance(events, list)


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

        with patch.object(d, "_force_context_restart", return_value=False):
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

        with patch.object(d, "_force_context_restart", return_value=False):
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

        with patch.object(d, "_force_context_restart", return_value=False):
            d._check_context_pressure(run, elapsed_hours=15)

        directive_path = tmp_path / ".swarm" / "dispatcher-directive.json"
        data = json.loads(directive_path.read_text())
        assert "/compact" in data["message"]

    def test_context_critical_triggers_force_restart(self, dispatcher_setup):
        """Context critical should attempt force-restart when agent is pressured."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        (tmp_path / ".swarm").mkdir(parents=True, exist_ok=True)

        with patch.object(d, "_is_context_pressured", return_value=True), \
             patch.object(d, "_force_context_restart", return_value=True) as mock_restart:
            d._check_context_pressure(run, elapsed_hours=15)

        mock_restart.assert_called_once_with(run)
        assert run.context_directive_level == "context_critical"

    def test_context_critical_skips_restart_if_agent_healthy(self, dispatcher_setup):
        """Context critical should NOT force-restart if agent has >30% headroom."""
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
        # Agent reports 60% remaining — healthy
        (swarm / "orchestrator-checkpoint.json").write_text(
            json.dumps({"context_window_remaining_pct": 0.60})
        )

        with patch.object(d, "_force_context_restart") as mock_restart:
            d._check_context_pressure(run, elapsed_hours=15)

        mock_restart.assert_not_called()
        assert run.context_directive_level == "context_critical"
        # Still sends the directive + alert (just not a restart)
        assert len(msgs) >= 1

    def test_force_context_restart_kills_and_relaunches(self, dispatcher_setup):
        """Force context restart compacts, kills tmux, builds resume, relaunches."""
        d, msgs, docs, tmp_path = dispatcher_setup
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)
        (swarm / "orchestrator-prompt.txt").write_text("original prompt")

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
            rigor="scientific",
        )

        with patch("voronoi.server.dispatcher.subprocess.run"), \
             patch.object(d, "_launch_in_tmux") as mock_launch:
            result = d._force_context_restart(run)

        assert result is True
        assert run.context_restarts == 1
        assert run.context_directive_level == ""
        mock_launch.assert_called_once()
        # Resume prompt should have been written
        resume_path = swarm / "orchestrator-prompt-resume.txt"
        assert resume_path.exists()

    def test_force_context_restart_respects_limit(self, dispatcher_setup):
        """Force context restart should stop after max_context_restarts."""
        d, msgs, docs, tmp_path = dispatcher_setup
        d.config.max_context_restarts = 1
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)
        (swarm / "orchestrator-prompt.txt").write_text("original prompt")

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
            context_restarts=1,  # already used the one allowed
        )

        result = d._force_context_restart(run)
        assert result is False
        assert run.context_restarts == 1  # no increment

    def test_warning_triggers_force_compact(self, dispatcher_setup):
        """Context warning should immediately compact workspace."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        (tmp_path / ".swarm").mkdir(parents=True, exist_ok=True)

        with patch("voronoi.server.compact.compact_workspace_state",
                   return_value=True) as mock_compact:
            d._check_context_pressure(run, elapsed_hours=11)

        mock_compact.assert_called_once_with(tmp_path)
        assert "compacted" in msgs[0].lower() or "warning" in msgs[0].lower()

    def test_token_critical_triggers_force_restart(self, dispatcher_setup):
        """Self-reported <=15% token budget should try force-restart."""
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
            json.dumps({"context_window_remaining_pct": 0.10})
        )

        with patch.object(d, "_force_context_restart", return_value=True) as mock_restart:
            d._check_context_pressure(run, elapsed_hours=3)

        mock_restart.assert_called_once_with(run)

    def test_is_context_pressured_no_checkpoint(self, dispatcher_setup):
        """No checkpoint → assume pressured (conservative)."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        (tmp_path / ".swarm").mkdir(parents=True, exist_ok=True)
        assert d._is_context_pressured(run) is True

    def test_is_context_pressured_healthy_agent(self, dispatcher_setup):
        """Agent with >30% remaining → not pressured."""
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
            json.dumps({"context_window_remaining_pct": 0.50})
        )
        assert d._is_context_pressured(run) is False

    def test_is_context_pressured_exhausted_agent(self, dispatcher_setup):
        """Agent with ≤30% remaining → pressured."""
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
            json.dumps({"context_window_remaining_pct": 0.20})
        )
        assert d._is_context_pressured(run) is True

    def test_is_context_pressured_uses_snapshot(self, dispatcher_setup):
        """Ground-truth snapshot overrides self-reported pct."""
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
                "context_window_remaining_pct": 0.80,  # says healthy
                "context_snapshot": {
                    "model_limit": 200000,
                    "free_tokens": 30000,  # but only 15% free
                },
            })
        )
        assert d._is_context_pressured(run) is True

    def test_resume_prompt_context_refresh_label(self, dispatcher_setup):
        """Context refresh resume prompt should say CONTEXT REFRESH, not RESTART."""
        d, msgs, docs, tmp_path = dispatcher_setup
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)
        (swarm / "orchestrator-prompt.txt").write_text("original")

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test question",
            mode="discover",
            rigor="scientific",
            context_restarts=1,
        )

        path = d._build_resume_prompt(run)
        content = path.read_text()
        assert "CONTEXT REFRESH" in content
        assert "Nothing failed" in content
        assert "RESTART" not in content


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

    def test_check_criteria_progress_4h_vs_8h_alert_keys(self, dispatcher_setup):
        """BUG-005: 4h alert fires at 4-7h, 8h alert fires at 8h+."""
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
        ]))

        # At 6h, the 4h alert should fire (not the 8h alert)
        d._check_criteria_progress(run, elapsed_hours=6.0)
        assert "criteria_zero_4h" in run._criteria_alerts
        assert "criteria_zero_8h" not in run._criteria_alerts
        assert len(msgs) == 1

        # At 9h, the 8h alert should also fire
        d._check_criteria_progress(run, elapsed_hours=9.0)
        assert "criteria_zero_8h" in run._criteria_alerts
        assert len(msgs) == 2


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
        mock_inv.completed_at = time.time() - 7200  # paused 2 hours ago
        mock_queue.get_paused.return_value = [mock_inv]
        mock_queue.fail_paused.return_value = True
        d._queue = mock_queue

        d._check_paused_timeouts()

        # Atomic transition: paused → failed (no intermediate resume)
        mock_queue.fail_paused.assert_called_once()
        mock_queue.resume.assert_not_called()
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

    def test_sync_ignores_non_bool_truthy_values(self, dispatcher_setup):
        """Regression: anti-fabrication — strings like "pending" must not
        promote a criterion to met. Only the literal boolean True counts.

        Before the fix, ``bool(cs[cid])`` treated any non-empty string as
        met, so orchestrator notes such as ``"SC5": "pending full data"``
        silently flipped the canonical criteria file to ``met: True`` —
        which then triggered convergence without any data to back it up
        (see SCIENCE.md §10).
        """
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
            "criteria_status": {
                "SC1": "pending full data",
                "SC2": "met",            # string, not bool
                "SC3": 1,                 # int, not bool
                "SC4": {"note": "done"},  # dict
                "SC5": True,              # only this one is valid
            }
        }))
        (swarm / "success-criteria.json").write_text(json.dumps([
            {"id": "SC1", "description": "First", "met": False},
            {"id": "SC2", "description": "Second", "met": False},
            {"id": "SC3", "description": "Third", "met": False},
            {"id": "SC4", "description": "Fourth", "met": False},
            {"id": "SC5", "description": "Fifth", "met": False},
        ]))

        d._sync_criteria_from_checkpoint(run)

        result = json.loads((swarm / "success-criteria.json").read_text())
        assert result[0]["met"] is False  # "pending full data" — must not promote
        assert result[1]["met"] is False  # "met" string — must not promote
        assert result[2]["met"] is False  # 1 — must not promote
        assert result[3]["met"] is False  # dict — must not promote
        assert result[4]["met"] is True   # True — only valid promotion


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

    def test_swarm_session_from_config(self, dispatcher_setup):
        """Should read swarm session name from .swarm-config.json (BUG-002 fix)."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="voronoi-inv-1",
            question="test",
            mode="discover",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "active_workers": ["worker-1"]
        }))
        # Write config with a different session name than what the dispatcher would construct
        (tmp_path / ".swarm-config.json").write_text(json.dumps({
            "tmux_session": "inv-1-coupled-decisions-swarm"
        }))

        # tmux has-session succeeds, list-windows shows worker, list-panes shows copilot alive
        def side_effect(cmd, **kwargs):
            if cmd[0] == "tmux" and cmd[1] == "has-session":
                # Verify it's checking the name from config, not the constructed one
                assert cmd[3] == "inv-1-coupled-decisions-swarm"
                return MagicMock(returncode=0)
            if cmd[0] == "tmux" and cmd[1] == "list-windows":
                return MagicMock(returncode=0, stdout="worker-1\norchestrator\n")
            if cmd[0] == "tmux" and cmd[1] == "list-panes":
                return MagicMock(returncode=0, stdout="copilot\n")
            return MagicMock(returncode=1, stdout="")

        with patch("voronoi.server.dispatcher.subprocess.run", side_effect=side_effect):
            assert d._has_active_workers(run) is True

    def test_window_exists_but_process_dead(self, dispatcher_setup):
        """Window with worker name exists but copilot exited — dead bash shell.

        This is the critical production failure from inv-36: workers completed
        but tmux windows remained with bash prompts, causing _has_active_workers
        to return True forever and the orchestrator to never wake.
        """
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="voronoi-inv-1",
            question="test",
            mode="discover",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "active_workers": ["agent-scout", "agent-scengen"]
        }))
        (tmp_path / ".swarm-config.json").write_text(json.dumps({
            "tmux_session": "inv-1-coupled-decisions-swarm"
        }))

        def side_effect(cmd, **kwargs):
            if cmd[0] == "tmux" and cmd[1] == "has-session":
                return MagicMock(returncode=0)  # session exists
            if cmd[0] == "tmux" and cmd[1] == "list-windows":
                return MagicMock(returncode=0,
                                stdout="agent-scout\nagent-scengen\norchestrator\n")
            if cmd[0] == "tmux" and cmd[1] == "list-panes":
                # copilot exited, only bash shell remains
                return MagicMock(returncode=0, stdout="bash\n")
            if cmd[0] == "pgrep":
                return MagicMock(returncode=1, stdout="")  # no orphans
            return MagicMock(returncode=1, stdout="")

        with patch("voronoi.server.dispatcher.subprocess.run", side_effect=side_effect):
            assert d._has_active_workers(run) is False

    def test_swarm_session_fallback_when_no_config(self, dispatcher_setup):
        """Should fall back to tmux_session + '-swarm' when no config file."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="voronoi-inv-1",
            question="test",
            mode="discover",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "active_workers": ["worker-1"]
        }))
        # No .swarm-config.json — should fall back

        def side_effect(cmd, **kwargs):
            if cmd[0] == "tmux" and cmd[1] == "has-session":
                assert cmd[3] == "voronoi-inv-1-swarm"  # fallback name
                return MagicMock(returncode=1)
            if cmd[0] == "pgrep":
                return MagicMock(returncode=1, stdout="")
            return MagicMock(returncode=1, stdout="")

        with patch("voronoi.server.dispatcher.subprocess.run", side_effect=side_effect):
            assert d._has_active_workers(run) is False

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
        pgrep_pids = MagicMock(returncode=0, stdout="12345\n")
        ps_output = MagicMock(
            returncode=0,
            stdout=f"12345 copilot --allow-all -p @{tmp_path}/.swarm/prompt.txt\n",
        )

        with patch("voronoi.server.dispatcher.subprocess.run",
                    side_effect=[tmux_no_session, pgrep_pids, ps_output]):
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
        """Should return False when pgrep is not available (e.g. containers)."""
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

    def test_orphan_not_detected_when_ps_no_match(self, dispatcher_setup):
        """pgrep finds PIDs but ps shows they belong to a different workspace."""
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
        pgrep_pids = MagicMock(returncode=0, stdout="99999\n")
        ps_other_workspace = MagicMock(
            returncode=0,
            stdout="99999 copilot --allow-all -p @/some/other/workspace/.swarm/prompt.txt\n",
        )
        # argv didn't match; CWD fallback (lsof) also finds a CWD outside
        # this workspace — so no orphan should be reported.
        lsof_other_cwd = MagicMock(returncode=0, stdout="p99999\nn/some/other/workspace\n")

        with patch("voronoi.server.dispatcher.subprocess.run",
                    side_effect=[tmux_no_session, pgrep_pids,
                                 ps_other_workspace, lsof_other_cwd]):
            assert d._has_active_workers(run) is False

    def test_orphan_detected_by_cwd(self, dispatcher_setup):
        """BUG-004: worker with workspace as CWD (not in argv) is an orphan.

        Agents launched via ``tmux new-window -c <workspace>`` get the
        workspace as CWD only; argv does not contain the path. The
        fallback must fall through to an lsof-based CWD check.
        """
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
        pgrep_pids = MagicMock(returncode=0, stdout="12345\n")
        # argv has no workspace path reference
        ps_bare = MagicMock(returncode=0, stdout="12345 copilot --allow-all\n")
        # lsof reports CWD inside the workspace
        lsof_inside = MagicMock(returncode=0,
                                stdout=f"p12345\nn{tmp_path}\n")

        with patch("voronoi.server.dispatcher.subprocess.run",
                    side_effect=[tmux_no_session, pgrep_pids,
                                 ps_bare, lsof_inside]):
            assert d._has_active_workers(run) is True


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


# ---------------------------------------------------------------------------
# Cleanup tests
# ---------------------------------------------------------------------------

class TestCleanupTmux:
    """Tests for _cleanup_tmux session discovery."""

    def test_reads_swarm_config_session(self, dispatcher_setup):
        """Should try to kill the tmux_session from .swarm-config.json."""
        d, msgs, docs, tmp_path = dispatcher_setup
        config_path = tmp_path / ".swarm-config.json"
        config_path.write_text(json.dumps({"tmux_session": "my-custom-swarm"}))

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="voronoi-inv-1",
            question="test",
            mode="discover",
        )

        calls = []
        def fake_run(cmd, **kw):
            calls.append(cmd)
            result = MagicMock(returncode=1, stdout="", stderr="")
            # list-sessions returns empty
            if cmd[0] == "tmux" and cmd[1] == "list-sessions":
                result.returncode = 0
                result.stdout = ""
            return result

        with patch("voronoi.server.dispatcher.subprocess.run", side_effect=fake_run):
            d._cleanup_tmux(run)

        # Should have tried to kill "my-custom-swarm"
        killed = [c[3] for c in calls if len(c) >= 4 and c[1] == "kill-session"]
        assert "my-custom-swarm" in killed

    def test_kills_orchestrator_and_convention_sessions(self, dispatcher_setup):
        """Should kill voronoi-inv-{id} and {ws_name}-swarm."""
        d, msgs, docs, tmp_path = dispatcher_setup

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="voronoi-inv-1",
            question="test",
            mode="discover",
        )

        calls = []
        def fake_run(cmd, **kw):
            calls.append(cmd)
            result = MagicMock(returncode=1, stdout="", stderr="")
            if cmd[0] == "tmux" and cmd[1] == "list-sessions":
                result.returncode = 0
                result.stdout = ""
            return result

        with patch("voronoi.server.dispatcher.subprocess.run", side_effect=fake_run):
            d._cleanup_tmux(run)

        killed = [c[3] for c in calls if len(c) >= 4 and c[1] == "kill-session"]
        ws_name = tmp_path.name
        assert "voronoi-inv-1" in killed
        assert f"{ws_name}-swarm" in killed


class TestCleanupWorktrees:
    """Tests for _cleanup_worktrees on completion."""

    def test_removes_swarm_directory(self, dispatcher_setup):
        """Should remove the -swarm/ directory after completion."""
        d, msgs, docs, tmp_path = dispatcher_setup
        swarm_dir = tmp_path.parent / f"{tmp_path.name}-swarm"
        swarm_dir.mkdir()
        (swarm_dir / "agent-worker").mkdir()

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )

        with patch("voronoi.server.dispatcher.subprocess.run"):
            d._cleanup_worktrees(run)

        assert not swarm_dir.exists()

    def test_no_error_when_swarm_dir_missing(self, dispatcher_setup):
        """Should not fail if -swarm/ directory doesn't exist."""
        d, msgs, docs, tmp_path = dispatcher_setup

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )

        # Should not raise
        with patch("voronoi.server.dispatcher.subprocess.run"):
            d._cleanup_worktrees(run)

    def test_cleans_tmp_when_no_other_running(self, dispatcher_setup):
        """Should clean ~/.voronoi/tmp when this is the last investigation."""
        d, msgs, docs, tmp_path = dispatcher_setup
        tmp_dir = d.config.base_dir / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        (tmp_dir / "scratch.txt").write_text("test")

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        d.running = {}  # no running investigations

        with patch("voronoi.server.dispatcher.subprocess.run"):
            d._cleanup_worktrees(run)

        # tmp dir should exist but be empty
        assert tmp_dir.exists()
        assert not list(tmp_dir.iterdir())

    def test_removes_tmux_env_secrets(self, dispatcher_setup):
        """Should remove .swarm/.tmux-env on cleanup."""
        d, msgs, docs, tmp_path = dispatcher_setup
        swarm = tmp_path / ".swarm"
        swarm.mkdir(exist_ok=True)
        env_file = swarm / ".tmux-env"
        env_file.write_text("export GH_TOKEN=secret")

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )

        with patch("voronoi.server.dispatcher.subprocess.run"):
            d._cleanup_worktrees(run)

        assert not env_file.exists()


# ---------------------------------------------------------------------------
# Continuation dispatch tests
# ---------------------------------------------------------------------------


class TestContinuationDispatch:
    """Test that /voronoi continue reuses workspace and injects warm-start."""

    def test_prepare_continuation_archives_and_clears_stale_files(self, dispatcher_setup):
        """Archived artifacts should not remain live in the next round."""
        d, msgs, docs, tmp_path = dispatcher_setup

        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "deliverable.md").write_text("# Old deliverable\n")
        (swarm / "events.jsonl").write_text('{"event":"finding"}\n')
        (swarm / "convergence.json").write_text('{"status":"converged"}')
        (swarm / "state-digest.md").write_text("## Phase: Complete\n")

        mock_queue = MagicMock()
        mock_queue.get.return_value = SimpleNamespace(
            id=1,
            cycle_number=1,
            lineage_id=None,
        )
        d._queue = mock_queue

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )

        with patch("voronoi.server.dispatcher.subprocess.run"):
            d.prepare_continuation(run)

        archive_dir = swarm / "archive" / "run-1"
        assert (archive_dir / "deliverable.md").exists()
        assert (archive_dir / "events.jsonl").exists()
        assert (archive_dir / "state-digest.md").exists()
        assert not (swarm / "deliverable.md").exists()
        assert not (swarm / "events.jsonl").exists()
        assert not (swarm / "convergence.json").exists()
        # state-digest.md should be PRESERVED (not deleted) for continuation
        assert (swarm / "state-digest.md").exists()

    def test_prepare_continuation_prevents_stale_completion(self, dispatcher_setup):
        """A reused workspace must not look complete before the new round starts."""
        d, msgs, docs, tmp_path = dispatcher_setup

        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "deliverable.md").write_text("# Old deliverable\n")

        mock_queue = MagicMock()
        mock_queue.get.return_value = SimpleNamespace(
            id=1,
            cycle_number=1,
            lineage_id=None,
        )
        d._queue = mock_queue

        prior_run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
            rigor="adaptive",
        )

        with patch("voronoi.server.dispatcher.subprocess.run"):
            d.prepare_continuation(prior_run)

        continued_run = RunningInvestigation(
            investigation_id=2,
            workspace_path=tmp_path,
            tmux_session="test-2",
            question="test",
            mode="discover",
            rigor="adaptive",
        )

        assert d._is_complete(continued_run) is False

    def test_continue_reuses_workspace(self, dispatcher_setup):
        """Continuation with existing workspace should NOT provision a new one."""
        d, msgs, docs, tmp_path = dispatcher_setup

        # Create a fake existing workspace
        ws = tmp_path / "active" / "inv-1-test"
        ws.mkdir(parents=True)
        (ws / ".swarm").mkdir()

        mock_queue = MagicMock()
        inv = SimpleNamespace(
            id=2, chat_id="c1", question="Does X work?",
            slug="does-x-work", mode="discover", rigor="scientific",
            codename="Dopamine", workspace_path=str(ws),
            investigation_type="lab", parent_id=1, lineage_id=1,
            cycle_number=2, pi_feedback="test more cases",
        )
        parent_inv = SimpleNamespace(
            id=1, chat_id="c1", question="Does X work?",
            slug="does-x-work", mode="discover", rigor="scientific",
            codename="Dopamine", workspace_path=str(ws),
            investigation_type="lab", parent_id=None, lineage_id=1,
            cycle_number=1, pi_feedback="",
        )
        mock_queue.get.side_effect = lambda id: parent_inv if id == 1 else inv
        mock_queue.get_demo_source.return_value = None
        d._queue = mock_queue

        mock_ws_mgr = MagicMock()
        d._workspace_mgr = mock_ws_mgr

        with patch.object(d, '_launch_in_tmux'), \
             patch.object(d, '_build_prompt', return_value="prompt"), \
             patch.object(d, 'prepare_continuation') as mock_prep:
            d._launch_investigation(inv)

        # Should NOT have called provision_lab or provision_repo
        mock_ws_mgr.provision_lab.assert_not_called()
        mock_ws_mgr.provision_repo.assert_not_called()
        # Should call prepare_continuation
        mock_prep.assert_called_once()
        # Workspace path in queue.start should be the old one
        mock_queue.start.assert_called_once_with(2, str(ws))

    def test_continue_provisions_fresh_when_workspace_missing(self, dispatcher_setup):
        """If continuation workspace is gone, fall back to fresh provisioning."""
        d, msgs, docs, tmp_path = dispatcher_setup

        mock_queue = MagicMock()
        inv = SimpleNamespace(
            id=2, chat_id="c1", question="Does X work?",
            slug="does-x-work", mode="discover", rigor="scientific",
            codename="Dopamine", workspace_path="/nonexistent/path",
            investigation_type="lab", parent_id=1, lineage_id=1,
            cycle_number=2, pi_feedback="",
        )
        mock_queue.get.return_value = inv
        mock_queue.get_demo_source.return_value = None
        d._queue = mock_queue

        new_ws = tmp_path / "active" / "inv-2-does-x-work"
        new_ws.mkdir(parents=True)
        mock_ws_mgr = MagicMock()
        mock_ws_mgr.provision_lab.return_value = SimpleNamespace(path=str(new_ws))
        d._workspace_mgr = mock_ws_mgr

        with patch.object(d, '_launch_in_tmux'), \
             patch.object(d, '_build_prompt', return_value="prompt"), \
             patch.object(d, '_patch_swarm_config'):
            d._launch_investigation(inv)

        # Should provision fresh since workspace is missing
        mock_ws_mgr.provision_lab.assert_called_once()

    def test_continue_injects_warm_start_context(self, dispatcher_setup):
        """Continuation prompt should include warm-start context."""
        d, msgs, docs, tmp_path = dispatcher_setup

        # Create ledger for warm-start
        from voronoi.science.claims import ClaimLedger, save_ledger, PROVENANCE_RUN_EVIDENCE
        ledger = ClaimLedger()
        ledger.add_claim("L4 > L1", PROVENANCE_RUN_EVIDENCE, effect_summary="d=0.8")
        ledger.assert_claim("C1")
        save_ledger(1, ledger, base_dir=tmp_path)

        inv = SimpleNamespace(
            id=2, chat_id="c1", question="Does X work?",
            slug="does-x-work", mode="discover", rigor="scientific",
            codename="Dopamine", workspace_path=str(tmp_path),
            investigation_type="lab", parent_id=1, lineage_id=1,
            cycle_number=2, pi_feedback="Control for tokenizer differences",
        )

        mock_queue = MagicMock()
        mock_queue.get.return_value = inv
        d._queue = mock_queue

        prompt = d._build_prompt(inv, Path(tmp_path))

        assert "Round 2" in prompt
        assert "Continuation" in prompt
        assert "L4 > L1" in prompt
        assert "Control for tokenizer" in prompt

    def test_fresh_investigation_no_warm_start(self, dispatcher_setup):
        """Non-continuation should NOT include warm-start context."""
        d, msgs, docs, tmp_path = dispatcher_setup

        inv = SimpleNamespace(
            id=1, chat_id="c1", question="Does X work?",
            slug="does-x-work", mode="discover", rigor="scientific",
            codename="Dopamine", workspace_path=str(tmp_path),
            investigation_type="lab", parent_id=None, lineage_id=1,
            cycle_number=1, pi_feedback="",
        )

        mock_queue = MagicMock()
        mock_queue.get.return_value = inv
        d._queue = mock_queue

        prompt = d._build_prompt(inv, Path(tmp_path))

        assert "Continuation" not in prompt
        assert "PI Feedback" not in prompt

    def test_review_message_uses_cycle_number(self, dispatcher_setup):
        """Review message should show cycle_number, not improvement_rounds."""
        d, msgs, docs, tmp_path = dispatcher_setup

        mock_queue = MagicMock()
        inv = SimpleNamespace(
            id=1, codename="Dopamine", cycle_number=3,
            lineage_id=1,
        )
        mock_queue.get.return_value = inv
        d._queue = mock_queue

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
            codename="Dopamine",
        )
        run.improvement_rounds = 1  # Should NOT be used
        run.eval_score = 0.85

        from voronoi.science.claims import ClaimLedger
        ledger = ClaimLedger()

        msg = d._build_review_message(run, ledger)
        assert "Round 3" in msg
        assert "Round 1" not in msg


class TestOrchestratorParking:
    """Tests for the dispatcher-as-outer-loop parking mechanism."""

    def test_pending_events_field_exists(self):
        """RunningInvestigation should have pending_events and orchestrator_parked fields."""
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=Path("/tmp/test"),
            tmux_session="test",
            question="test",
            mode="discover",
        )
        assert run.pending_events == []
        assert run.orchestrator_parked is False
        assert run.last_parked_digest_at == 0
        # BUG-002: separate timestamp for park-timeout vs Telegram throttle
        assert run.park_entered_at == 0
        # BUG-003: watchdog strike counter defaults to 0
        assert run.polling_strike_count == 0

    def test_accumulate_parked_events(self, dispatcher_setup):
        """Events should be accumulated when orchestrator is parked."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        events = [
            {"type": "task_done", "msg": "✅ Finished: baseline"},
            {"type": "finding", "msg": "🔬 Effect size d=1.47"},
            {"type": "progress", "msg": "📊 5/10 tasks"},  # Should be filtered out
        ]
        d._accumulate_parked_events(run, events)
        assert len(run.pending_events) == 2
        assert run.pending_events[0]["type"] == "task_done"
        assert run.pending_events[1]["type"] == "finding"

    def test_accumulate_caps_at_50(self, dispatcher_setup):
        """Pending events should be capped at 50."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        events = [{"type": "task_done", "msg": f"task {i}"} for i in range(60)]
        d._accumulate_parked_events(run, events)
        assert len(run.pending_events) == 50

    def test_resume_prompt_includes_pending_events(self, dispatcher_setup):
        """Resume prompt should include pending events section."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test question",
            mode="discover",
        )
        run.pending_events = [
            {"type": "task_done", "msg": "✅ Finished: baseline"},
            {"type": "finding", "msg": "🔬 Effect size d=1.47"},
        ]

        prompt_file = tmp_path / ".swarm" / "orchestrator-prompt.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text("Original prompt")

        resume_file = d._build_resume_prompt(run)
        content = resume_file.read_text()
        assert "Events Since Your Last Session" in content
        assert "Effect size d=1.47" in content
        # Events should be drained after building prompt
        assert run.pending_events == []

    def test_resume_prompt_wake_label(self, dispatcher_setup):
        """Resume prompt should say WAKE when orchestrator was parked."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test question",
            mode="discover",
        )
        run.orchestrator_parked = True

        prompt_file = tmp_path / ".swarm" / "orchestrator-prompt.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text("Original prompt")

        resume_file = d._build_resume_prompt(run)
        content = resume_file.read_text()
        assert "WAKE" in content
        assert run.orchestrator_parked is False

    def test_needs_orchestrator_no_workers(self, dispatcher_setup):
        """Should wake when no active workers remain."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        # No checkpoint, no workers → _has_active_workers returns False → wake
        with patch.object(d, '_has_active_workers', return_value=False):
            assert d._needs_orchestrator(run) is True

    def test_needs_orchestrator_design_invalid(self, dispatcher_setup):
        """Should wake immediately on DESIGN_INVALID."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        # Workers still alive but DESIGN_INVALID found
        with patch.object(d, '_has_active_workers', return_value=True), \
             patch('voronoi.beads.run_bd_json',
                   return_value=(0, [{"id": "bd-5", "status": "open",
                                     "notes": "DESIGN_INVALID: bad design",
                                     "title": "test"}])):
            assert d._needs_orchestrator(run) is True

    def test_needs_orchestrator_workers_running_no_urgency(self, dispatcher_setup):
        """Should NOT wake when workers running and no urgent events."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        with patch.object(d, '_has_active_workers', return_value=True), \
             patch('voronoi.beads.run_bd_json',
                   return_value=(0, [{"id": "bd-5", "status": "in_progress",
                                     "notes": "running normally",
                                     "title": "experiment"}])):
            assert d._needs_orchestrator(run) is False

    def test_park_wake_does_not_consume_retry(self, dispatcher_setup):
        """When workers finish and orchestrator was parked, wake should
        NOT increment retry_count (BUG-001 regression test)."""
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "orchestrator-prompt.txt").write_text("original prompt")

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test question",
            mode="discover",
        )
        run.orchestrator_parked = True
        run.retry_count = 0
        d.running[1] = run

        with patch.object(d, "_check_abort_signal"), \
             patch.object(d, "check_human_gates"), \
             patch.object(d, "_refresh_eval_score"), \
             patch.object(d, "_sync_criteria_from_checkpoint"), \
             patch.object(d, "_check_progress", return_value=[]), \
             patch.object(d, "_check_event_log", return_value=[]), \
             patch.object(d, "_has_active_workers", return_value=False), \
             patch.object(d, "_launch_in_tmux"), \
             patch("voronoi.server.dispatcher.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)  # session dead
            d.poll_progress()

        # retry_count must remain 0 — wake is not a crash
        assert run.retry_count == 0
        assert run.orchestrator_parked is False
        # Should send a wake message, not a restart message
        assert any("workers finished" in m for m in msgs)
        assert not any("restarting" in m for m in msgs)

    def test_park_wake_uses_wake_from_park(self, dispatcher_setup):
        """poll_progress should call _wake_from_park when parked + workers done."""
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
        run.orchestrator_parked = True
        d.running[1] = run

        with patch.object(d, "_check_abort_signal"), \
             patch.object(d, "check_human_gates"), \
             patch.object(d, "_refresh_eval_score"), \
             patch.object(d, "_sync_criteria_from_checkpoint"), \
             patch.object(d, "_check_progress", return_value=[]), \
             patch.object(d, "_check_event_log", return_value=[]), \
             patch.object(d, "_has_active_workers", return_value=False), \
             patch.object(d, "_wake_from_park", return_value=True) as mock_wake, \
             patch("voronoi.server.dispatcher.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)  # session dead
            d.poll_progress()

        mock_wake.assert_called_once_with(run)
        # Should NOT have been removed from running
        assert 1 in d.running

    def test_parked_workers_still_running_stays_parked(self, dispatcher_setup):
        """When parked and workers still alive, should continue parking."""
        d, msgs, docs, tmp_path = dispatcher_setup

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        run.orchestrator_parked = True
        d.running[1] = run

        with patch.object(d, "_check_abort_signal"), \
             patch.object(d, "check_human_gates"), \
             patch.object(d, "_refresh_eval_score"), \
             patch.object(d, "_sync_criteria_from_checkpoint"), \
             patch.object(d, "_check_progress", return_value=[]), \
             patch.object(d, "_check_event_log", return_value=[]), \
             patch.object(d, "_has_active_workers", return_value=True), \
             patch.object(d, "_needs_orchestrator", return_value=False), \
             patch.object(d, "_try_restart") as mock_restart, \
             patch("voronoi.server.dispatcher.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)  # session dead
            d.poll_progress()

        # Should stay parked and NOT call _try_restart
        assert run.orchestrator_parked is True
        mock_restart.assert_not_called()
        assert 1 in d.running

    def test_park_timeout_force_wakes(self, dispatcher_setup):
        """Parked orchestrator should be force-woken after park_timeout_hours
        ONLY if workers are no longer alive.  If workers are still running,
        the park is extended instead (BUG-005 fix).
        """
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue
        d.config.park_timeout_hours = 4

        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "orchestrator-prompt.txt").write_text("original prompt")

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test question",
            mode="discover",
        )
        run.orchestrator_parked = True
        # Parked 5 hours ago (exceeds 4h limit)
        run.park_entered_at = time.time() - 5 * 3600
        d.running[1] = run

        # Workers dead → force-wake should fire
        with patch.object(d, "_check_abort_signal"), \
             patch.object(d, "check_human_gates"), \
             patch.object(d, "_refresh_eval_score"), \
             patch.object(d, "_sync_criteria_from_checkpoint"), \
             patch.object(d, "_check_progress", return_value=[]), \
             patch.object(d, "_check_event_log", return_value=[]), \
             patch.object(d, "_has_active_workers", return_value=False), \
             patch.object(d, "_wake_from_park", return_value=True) as mock_wake, \
             patch("voronoi.server.dispatcher.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)  # session dead
            d.poll_progress()

        mock_wake.assert_called_once_with(run)
        assert 1 in d.running

    def test_park_timeout_extends_when_workers_alive(self, dispatcher_setup):
        """When park timeout fires but workers are still alive, the park
        should be extended — NOT force-woken (BUG-005 fix).
        """
        d, msgs, docs, tmp_path = dispatcher_setup
        d.config.park_timeout_hours = 4

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test question",
            mode="discover",
        )
        run.orchestrator_parked = True
        old_park_at = time.time() - 5 * 3600
        run.park_entered_at = old_park_at
        run.last_parked_digest_at = old_park_at
        d.running[1] = run

        with patch.object(d, "_check_abort_signal"), \
             patch.object(d, "check_human_gates"), \
             patch.object(d, "_refresh_eval_score"), \
             patch.object(d, "_sync_criteria_from_checkpoint"), \
             patch.object(d, "_check_progress", return_value=[]), \
             patch.object(d, "_check_event_log", return_value=[]), \
             patch.object(d, "_has_active_workers", return_value=True), \
             patch.object(d, "_needs_orchestrator", return_value=False), \
             patch.object(d, "_wake_from_park") as mock_wake, \
             patch("voronoi.server.dispatcher.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            d.poll_progress()

        # Should NOT wake — workers still alive
        mock_wake.assert_not_called()
        assert run.orchestrator_parked is True
        # park_entered_at should have been reset (extended)
        assert run.park_entered_at > old_park_at

    def test_park_timeout_not_triggered_when_within_limit(self, dispatcher_setup):
        """Parked orchestrator should NOT be force-woken before timeout."""
        d, msgs, docs, tmp_path = dispatcher_setup

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        run.orchestrator_parked = True
        # Parked 1 hour ago (within 4h limit)
        run.park_entered_at = time.time() - 1 * 3600
        d.running[1] = run

        with patch.object(d, "_check_abort_signal"), \
             patch.object(d, "check_human_gates"), \
             patch.object(d, "_refresh_eval_score"), \
             patch.object(d, "_sync_criteria_from_checkpoint"), \
             patch.object(d, "_check_progress", return_value=[]), \
             patch.object(d, "_check_event_log", return_value=[]), \
             patch.object(d, "_has_active_workers", return_value=True), \
             patch.object(d, "_needs_orchestrator", return_value=False), \
             patch.object(d, "_try_restart") as mock_restart, \
             patch("voronoi.server.dispatcher.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)  # session dead
            d.poll_progress()

        # Should stay parked — timeout not reached
        assert run.orchestrator_parked is True
        mock_restart.assert_not_called()


# ---------------------------------------------------------------------------
# BUG-002/BUG-008: Resume prompt must contain anti-polling guidance
# ---------------------------------------------------------------------------

class TestResumePromptAntiPolling:
    """Resume prompt must forbid sleep/polling and use 'Check' not 'Poll'."""

    def test_resume_prompt_forbids_sleep_polling(self, dispatcher_setup):
        """Resume prompt should contain anti-polling guidance."""
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

        assert "Sleep, poll, or use `ps aux" in content
        assert "sleep 600" in content
        assert "active_workers" in content
        assert "EXIT immediately" in content

    def test_resume_prompt_uses_check_not_poll_for_directive(self, dispatcher_setup):
        """Resume prompt should say 'Check' not 'Poll' for directive file."""
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

        assert "Check `.swarm/dispatcher-directive.json`" in content
        assert "Poll `.swarm/dispatcher-directive.json`" not in content

    def test_context_refresh_prompt_also_forbids_polling(self, dispatcher_setup):
        """Context refresh resume prompt should also contain anti-polling."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test question",
            mode="discover",
        )
        run.context_restarts = 1
        run.retry_count = 0

        prompt_file = tmp_path / ".swarm" / "orchestrator-prompt.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text("Original prompt")

        resume_file = d._build_resume_prompt(run)
        content = resume_file.read_text()

        assert "Sleep, poll, or use `ps aux" in content
        assert "Check `.swarm/dispatcher-directive.json`" in content


# ---------------------------------------------------------------------------
# BUG-003: resume_investigation should park when workers still running
# ---------------------------------------------------------------------------

class TestResumeInvestigationParkAware:
    """resume_investigation() must enter park mode if workers are still alive."""

    def test_resume_parks_when_workers_alive(self, dispatcher_setup):
        """Resume with active workers should enter park mode, not launch."""
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        inv = MagicMock()
        inv.id = 1
        inv.status = "paused"
        inv.workspace_path = str(tmp_path)
        inv.question = "test question"
        inv.mode = "discover"
        inv.codename = "Cortex"
        inv.chat_id = "123"
        inv.rigor = "adaptive"
        mock_queue.get.return_value = inv
        mock_queue.resume.return_value = True

        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)
        (swarm / "orchestrator-prompt.txt").write_text("original prompt")

        with patch.object(d, "_has_active_workers", return_value=True), \
             patch.object(d, "_restore_task_snapshot"), \
             patch.object(d, "_launch_in_tmux") as mock_launch:
            result = d.resume_investigation(1)

        # Should NOT have launched
        mock_launch.assert_not_called()
        # Should be tracked as parked
        assert 1 in d.running
        assert d.running[1].orchestrator_parked is True
        assert "monitor mode" in result
        assert any("monitor mode" in m for m in msgs)

    def test_resume_launches_when_no_workers(self, dispatcher_setup):
        """Resume without active workers should launch normally."""
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        inv = MagicMock()
        inv.id = 1
        inv.status = "failed"
        inv.workspace_path = str(tmp_path)
        inv.question = "test question"
        inv.mode = "discover"
        inv.codename = "Cortex"
        inv.chat_id = "123"
        inv.rigor = "adaptive"
        mock_queue.get.return_value = inv
        mock_queue.resume.return_value = True

        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True, exist_ok=True)
        (swarm / "orchestrator-prompt.txt").write_text("original prompt")

        with patch.object(d, "_has_active_workers", return_value=False), \
             patch.object(d, "_restore_task_snapshot"), \
             patch.object(d, "_launch_in_tmux"):
            result = d.resume_investigation(1)

        # Should have launched normally
        assert 1 in d.running
        assert d.running[1].orchestrator_parked is False
        assert "resumed" in result
        assert "monitor" not in result
    """Tests for the updated prompt.py lifecycle framing."""

    def test_prompt_includes_lifecycle_contract(self):
        """Orchestrator prompt should mention episodic session lifecycle."""
        from voronoi.server.prompt import build_orchestrator_prompt
        prompt = build_orchestrator_prompt(
            question="test question",
            mode="discover",
            rigor="adaptive",
        )
        assert "strategist" in prompt.lower()
        assert "exit" in prompt.lower()
        assert "sleep" in prompt.lower() or "idle-loop" in prompt.lower()

    def test_prompt_forbids_sleep_polling(self):
        """Orchestrator prompt should explicitly forbid sleep and ps aux."""
        from voronoi.server.prompt import build_orchestrator_prompt
        prompt = build_orchestrator_prompt(
            question="test question",
            mode="discover",
            rigor="adaptive",
        )
        assert "Do NOT" in prompt
        assert "nohup" in prompt.lower() or "background subprocess" in prompt.lower()


# ---------------------------------------------------------------------------
# Bug fix tests: poll_progress TimeoutExpired (BUG-001)
# ---------------------------------------------------------------------------

class TestPollProgressTimeoutExpired:
    """BUG-001: tmux has-session in poll_progress must handle TimeoutExpired."""

    def test_tmux_timeout_skips_investigation(self, dispatcher_setup):
        """TimeoutExpired from tmux has-session should skip, not crash."""
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
             patch.object(d, "_sync_criteria_from_checkpoint"), \
             patch("voronoi.server.dispatcher.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="tmux", timeout=10)):
            # Should NOT raise — just skip
            d.poll_progress()

        # Investigation should still be running (not removed)
        assert 1 in d.running


# ---------------------------------------------------------------------------
# Bug fix tests: _check_sentinel checkpoint path (BUG-002)
# ---------------------------------------------------------------------------

class TestSentinelCheckpointPath:
    """BUG-002: _check_sentinel should use _find_checkpoint, not hardcoded path."""

    def test_sentinel_reads_canonical_checkpoint_name(self, dispatcher_setup):
        """Phase detection should work with orchestrator-checkpoint.json (canonical)."""
        d, msgs, docs, tmp_path = dispatcher_setup
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)

        # Write contract (minimal, will pass)
        (swarm / "experiment-contract.json").write_text(json.dumps({
            "experiment_id": "e1",
            "independent_variable": "x",
            "conditions": [],
            "manipulation_checks": [],
            "required_outputs": [],
            "degeneracy_checks": [],
            "phase_gates": [],
        }))

        # Write checkpoint using CANONICAL name (not the short one)
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "phase": "investigating",
        }))

        run = RunningInvestigation(
            investigation_id=1, workspace_path=tmp_path,
            tmux_session="test", question="test", mode="prove",
            rigor="scientific",
        )

        events = d._check_sentinel(run)

        # Verify audit was written and phase was captured
        audit_path = swarm / "sentinel-audit.json"
        assert audit_path.exists()
        audit_data = json.loads(audit_path.read_text())
        assert audit_data.get("_last_phase") == "investigating"


# ---------------------------------------------------------------------------
# Bug fix tests: Atomic fail_paused (BUG-003)
# ---------------------------------------------------------------------------

class TestFailPausedAtomic:
    """BUG-003: queue.fail_paused() atomic paused → failed transition."""

    def test_fail_paused_transitions_atomically(self, tmp_path):
        """fail_paused should transition paused → failed in one step."""
        from voronoi.server.queue import InvestigationQueue, Investigation
        q = InvestigationQueue(tmp_path / "test.db")
        inv = Investigation(
            id=0, chat_id="test", status="queued",
            investigation_type="lab", repo=None,
            question="test?", slug="test", mode="discover",
            rigor="adaptive", codename="Test",
            workspace_path=None, sandbox_id=None,
            github_url=None, parent_id=None, demo_source=None,
            lineage_id=None, cycle_number=1,
            created_at=time.time(), started_at=None,
            completed_at=None, error=None,
        )
        inv_id = q.enqueue(inv)

        # Transition to running then paused
        claimed = q.next_ready(5)
        assert claimed is not None
        q.pause(inv_id, "test pause")
        fetched = q.get(inv_id)
        assert fetched.status == "paused"

        # Atomic fail_paused
        result = q.fail_paused(inv_id, "timed out")
        assert result is True
        fetched = q.get(inv_id)
        assert fetched.status == "failed"
        assert fetched.error == "timed out"

    def test_fail_paused_only_affects_paused(self, tmp_path):
        """fail_paused should not affect non-paused investigations."""
        from voronoi.server.queue import InvestigationQueue, Investigation
        q = InvestigationQueue(tmp_path / "test.db")
        inv = Investigation(
            id=0, chat_id="test", status="queued",
            investigation_type="lab", repo=None,
            question="test?", slug="test", mode="discover",
            rigor="adaptive", codename="Test",
            workspace_path=None, sandbox_id=None,
            github_url=None, parent_id=None, demo_source=None,
            lineage_id=None, cycle_number=1,
            created_at=time.time(), started_at=None,
            completed_at=None, error=None,
        )
        inv_id = q.enqueue(inv)
        # Still queued — fail_paused should return False
        result = q.fail_paused(inv_id, "should not work")
        assert result is False
        assert q.get(inv_id).status == "queued"


# ---------------------------------------------------------------------------
# Bug fix tests: Effective rigor and completion gate (BUG-004 + BUG-005)
# ---------------------------------------------------------------------------

class TestEffectiveRigor:
    """BUG-004/005: Adaptive rigor completion must account for escalation."""

    def test_effective_rigor_returns_adaptive_when_not_escalated(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1, workspace_path=tmp_path,
            tmux_session="test", question="test",
            mode="discover", rigor="adaptive",
        )
        assert d._effective_rigor(run) == "adaptive"

    def test_effective_rigor_returns_escalated_level(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1, workspace_path=tmp_path,
            tmux_session="test", question="test",
            mode="discover", rigor="adaptive",
            last_rigor="scientific",
        )
        assert d._effective_rigor(run) == "scientific"

    def test_effective_rigor_non_adaptive_unchanged(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1, workspace_path=tmp_path,
            tmux_session="test", question="test",
            mode="prove", rigor="scientific",
        )
        assert d._effective_rigor(run) == "scientific"

    def test_escalated_adaptive_requires_convergence(self, dispatcher_setup):
        """Adaptive investigation that escalated should need convergence."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1, workspace_path=tmp_path,
            tmux_session="test", question="test",
            mode="discover", rigor="adaptive",
            last_rigor="scientific",  # escalated
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "deliverable.md").write_text("# Results\n")
        # No convergence.json → should NOT be complete
        assert d._is_complete(run) is False

    def test_non_escalated_adaptive_deliverable_only(self, dispatcher_setup):
        """Adaptive investigation NOT escalated should complete with deliverable only."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1, workspace_path=tmp_path,
            tmux_session="test", question="test",
            mode="discover", rigor="adaptive",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "deliverable.md").write_text("# Results\n")
        assert d._is_complete(run) is True

    def test_escalated_adaptive_completes_with_convergence(self, dispatcher_setup):
        """Escalated adaptive + deliverable + convergence → complete."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1, workspace_path=tmp_path,
            tmux_session="test", question="test",
            mode="discover", rigor="adaptive",
            last_rigor="scientific",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "deliverable.md").write_text("# Results\n")
        (swarm / "convergence.json").write_text(json.dumps({
            "status": "converged", "converged": True,
        }))
        assert d._is_complete(run) is True

    def test_detect_phase_logs_rigor_sync(self, dispatcher_setup):
        """_detect_phase should log when effective rigor is synced."""
        d, msgs, docs, tmp_path = dispatcher_setup
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)

        run = RunningInvestigation(
            investigation_id=1, workspace_path=tmp_path,
            tmux_session="test", question="test",
            mode="discover", rigor="adaptive",
            last_rigor="adaptive",
        )

        # Checkpoint shows rigor escalated to scientific
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "phase": "investigating",
            "rigor": "scientific",
        }))

        events = d._detect_phase(run)
        # Should fire a rigor_escalation event
        rigor_events = [e for e in events if e["type"] == "rigor_escalation"]
        assert len(rigor_events) == 1
        assert run.last_rigor == "scientific"

    def test_recover_running_restores_last_rigor(self, dispatcher_setup):
        """_recover_running should restore last_rigor from checkpoint."""
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        # Checkpoint shows rigor escalated
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "phase": "investigating",
            "rigor": "scientific",
        }))

        mock_queue.get_running.return_value = [
            SimpleNamespace(
                id=1,
                workspace_path=str(tmp_path),
                question="test",
                mode="discover",
                codename="Cortex",
                chat_id="123",
                rigor="adaptive",
                started_at=time.time(),
            )
        ]

        with patch("voronoi.server.dispatcher.subprocess.run",
                   return_value=MagicMock(returncode=0)):
            d._recover_running()

        assert 1 in d.running
        # _restore_task_snapshot is skipped for alive sessions (avoids
        # Dolt lock contention with the running agent's MCP server).
        assert d.running[1].last_rigor == "scientific"


# ---------------------------------------------------------------------------
# Bug-fix regression tests
# ---------------------------------------------------------------------------

class TestFix01RequeueUnprovisioned:
    """FIX-01: Claimed-but-not-launched investigations should be requeued, not failed."""

    def test_recover_running_requeues_no_workspace(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        mock_queue.get_running.return_value = [
            SimpleNamespace(
                id=42,
                workspace_path=None,
                question="test",
                mode="discover",
                codename="Cortex",
                chat_id="123",
                rigor="adaptive",
                started_at=time.time(),
            )
        ]

        with patch("voronoi.server.dispatcher.subprocess.run"):
            d._recover_running()

        # Should NOT have called fail
        mock_queue.fail.assert_not_called()
        # Should have been requeued (not tracked)
        assert 42 not in d.running


class TestFix03EffectiveRigorHumanGates:
    """FIX-03: Human gates must use effective rigor, not raw run.rigor."""

    def test_human_gate_fires_for_escalated_adaptive(self, dispatcher_setup):
        """check_human_gates should fire when adaptive escalated to scientific."""
        d, msgs, docs, tmp_path = dispatcher_setup

        ws = tmp_path / "ws"
        (ws / ".swarm").mkdir(parents=True)
        (ws / ".swarm" / "human-gate.json").write_text(
            '{"status":"pending","gate":"prereg","summary":"Need approval"}'
        )

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=ws,
            tmux_session="test-session",
            question="Q",
            mode="discover",
            rigor="adaptive",
            last_rigor="scientific",
            codename="Cortex",
        )
        d.running[1] = run

        with patch("voronoi.server.dispatcher.subprocess.run"):
            d.check_human_gates()

        assert len(msgs) == 1
        assert "Human Review" in msgs[0]

    def test_human_gate_skipped_for_pure_adaptive(self, dispatcher_setup):
        """check_human_gates should skip non-escalated adaptive investigations."""
        d, msgs, docs, tmp_path = dispatcher_setup

        ws = tmp_path / "ws"
        (ws / ".swarm").mkdir(parents=True)
        (ws / ".swarm" / "human-gate.json").write_text(
            '{"status":"pending","gate":"prereg","summary":"Need approval"}'
        )

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=ws,
            tmux_session="test-session",
            question="Q",
            mode="discover",
            rigor="adaptive",
            last_rigor="",
            codename="Cortex",
        )
        d.running[1] = run

        d.check_human_gates()

        assert len(msgs) == 0

    def test_resume_prompt_uses_effective_rigor(self, dispatcher_setup):
        """Resume prompt should use escalated rigor, not raw adaptive."""
        d, msgs, docs, tmp_path = dispatcher_setup

        ws = tmp_path / "ws"
        (ws / ".swarm").mkdir(parents=True)
        (ws / ".swarm" / "orchestrator-prompt.txt").write_text("original")

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=ws,
            tmux_session="test-session",
            question="Q",
            mode="discover",
            rigor="adaptive",
            last_rigor="scientific",
            codename="Cortex",
        )

        resume = d._build_resume_prompt(run).read_text()
        assert "**Rigor:** scientific" in resume
        assert "convergence-gate.sh . scientific" in resume


class TestFix04ScopedAbort:
    """FIX-04: Abort should scope to specific investigation + use cancelled status."""

    def test_abort_scoped_to_one_investigation(self, dispatcher_setup):
        """Aborting one investigation should not kill others."""
        d, msgs, docs, tmp_path = dispatcher_setup
        mock_queue = MagicMock()
        d._queue = mock_queue

        d.running[1] = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path / "ws1",
            tmux_session="s1",
            question="Q1",
            mode="discover",
        )
        d.running[2] = RunningInvestigation(
            investigation_id=2,
            workspace_path=tmp_path / "ws2",
            tmux_session="s2",
            question="Q2",
            mode="discover",
        )

        with patch("subprocess.run"):
            d._handle_abort(inv_id=1)

        assert 1 not in d.running
        assert 2 in d.running
        mock_queue.abort.assert_called_once_with(1, "Aborted by operator")


# ---------------------------------------------------------------------------
# Reversed hypothesis detection (Judgment Tribunal trigger)
# ---------------------------------------------------------------------------

class TestReversedHypothesisDetection:
    def test_detects_reversed_hypothesis(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        (tmp_path / ".swarm").mkdir(exist_ok=True)
        import json
        (tmp_path / ".swarm" / "belief-map.json").write_text(json.dumps({
            "hypotheses": [
                {"id": "H2", "name": "interaction", "status": "refuted_reversed",
                 "evidence": ["bd-42"]},
            ]
        }))
        events = d._check_reversed_hypotheses(run)
        assert len(events) == 1
        assert "Tribunal" in events[0]["msg"]

    def test_does_not_re_notify(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        (tmp_path / ".swarm").mkdir(exist_ok=True)
        import json
        (tmp_path / ".swarm" / "belief-map.json").write_text(json.dumps({
            "hypotheses": [
                {"id": "H2", "name": "interaction", "status": "refuted_reversed",
                 "evidence": ["bd-42"]},
            ]
        }))
        events1 = d._check_reversed_hypotheses(run)
        events2 = d._check_reversed_hypotheses(run)
        assert len(events1) == 1
        assert len(events2) == 0  # Already notified

    def test_writes_interpretation_request(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        (tmp_path / ".swarm").mkdir(exist_ok=True)
        import json
        (tmp_path / ".swarm" / "belief-map.json").write_text(json.dumps({
            "hypotheses": [
                {"id": "H2", "name": "interaction", "status": "refuted_reversed",
                 "evidence": ["bd-42"]},
            ]
        }))
        d._check_reversed_hypotheses(run)
        req_path = tmp_path / ".swarm" / "interpretation-request.json"
        assert req_path.exists()
        data = json.loads(req_path.read_text())
        assert data["trigger"] == "refuted_reversed"

    def test_no_events_without_reversals(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        (tmp_path / ".swarm").mkdir(exist_ok=True)
        import json
        (tmp_path / ".swarm" / "belief-map.json").write_text(json.dumps({
            "hypotheses": [
                {"id": "H1", "name": "encoding", "status": "confirmed"},
            ]
        }))
        events = d._check_reversed_hypotheses(run)
        assert len(events) == 0


class TestTimeoutCap:
    """Tests for BUG-005 — timeout override capped at _MAX_TIMEOUT_HOURS."""

    def test_timeout_override_capped(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        (tmp_path / ".swarm").mkdir(exist_ok=True)
        (tmp_path / ".swarm" / "timeout_hours").write_text("99999")
        result = d._effective_timeout(run)
        assert result == d._MAX_TIMEOUT_HOURS

    def test_timeout_override_within_cap(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        (tmp_path / ".swarm").mkdir(exist_ok=True)
        (tmp_path / ".swarm" / "timeout_hours").write_text("72")
        result = d._effective_timeout(run)
        assert result == 72

    def test_timeout_no_override(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        result = d._effective_timeout(run)
        assert result == d.config.timeout_hours


class TestNotificationStatePersistence:
    """Tests for BUG-003 — notification state survives dispatcher restart."""

    def test_save_and_restore_notification_state(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        (tmp_path / ".swarm").mkdir(exist_ok=True)

        run.notified_findings.add("finding-1")
        run.notified_findings.add("finding-2")
        run.notified_design_invalid.add("task-3")
        run._criteria_alerts.add("criteria_zero_4h")
        run._sentinel_missing_contract_warned = True
        run.notified_paradigm_stress = True

        run.save_notification_state()

        # Create a fresh run and restore state
        run2 = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        assert len(run2.notified_findings) == 0  # fresh
        run2.restore_notification_state()

        assert "finding-1" in run2.notified_findings
        assert "finding-2" in run2.notified_findings
        assert "task-3" in run2.notified_design_invalid
        assert "criteria_zero_4h" in run2._criteria_alerts
        assert run2._sentinel_missing_contract_warned is True
        assert run2.notified_paradigm_stress is True

    def test_restore_missing_file(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        # Should not raise — gracefully handles missing file
        run.restore_notification_state()
        assert len(run.notified_findings) == 0


class TestAuthThreshold:
    """Tests for BUG-006 — auth failure detection requires 3+ markers."""

    def test_two_markers_insufficient(self, dispatcher_setup):
        """Two auth markers should NOT trigger auth failure detection."""
        d, msgs, docs, tmp_path = dispatcher_setup
        # Only 2 markers: "authenticate" and "credentials"
        log_tail = "Need to authenticate with valid credentials"
        assert d._looks_like_auth_failure(log_tail) is False

    def test_three_markers_sufficient(self, dispatcher_setup):
        """Three auth markers should trigger."""
        d, msgs, docs, tmp_path = dispatcher_setup
        log_tail = (
            "Need to authenticate with valid credentials.\n"
            "Run gh auth login to fix."
        )
        assert d._looks_like_auth_failure(log_tail) is True


class TestConvergenceCheckThrottle:
    """BUG-003: _is_complete should throttle _try_convergence_check calls."""

    def test_convergence_check_throttled(self, dispatcher_setup):
        """_try_convergence_check should only run once per 5-minute window."""
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

        # First call should attempt convergence check (sets timestamp)
        with patch.object(d, "_try_convergence_check"):
            d._is_complete(run)

        # Second call within 5 minutes should NOT re-attempt
        with patch.object(d, "_try_convergence_check") as mock_conv2:
            d._is_complete(run)
            assert mock_conv2.call_count == 0

    def test_convergence_check_runs_after_cooldown(self, dispatcher_setup):
        """_try_convergence_check should run again after 5-minute cooldown."""
        import time as _time
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

        # Simulate a past attempt 6 minutes ago
        run.last_convergence_attempt_at = _time.time() - 360

        with patch.object(d, "_try_convergence_check") as mock_conv:
            d._is_complete(run)
            assert mock_conv.call_count == 1


class TestReviewTransitionCheck:
    """BUG-004: _transition_to_review should check queue.review() return value."""

    def test_review_transition_failure_aborts_notification(self, dispatcher_setup):
        """If queue.review() returns False, no review message should be sent."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        from voronoi.server.queue import Investigation
        inv = Investigation(
            id=1, chat_id="test", status="running", question="test",
            slug="test", lineage_id=1, cycle_number=1,
        )

        with patch.object(d.queue, "get", return_value=inv), \
             patch.object(d.queue, "review", return_value=False), \
             patch("voronoi.server.dispatcher.InvestigationDispatcher._sync_findings_to_ledger"):
            d._transition_to_review(run)

        # No review message should have been sent
        assert not any("review" in m.lower() or "converged" in m.lower() for m in msgs)


class TestEffortMappingSingleSource:
    """BUG-007: Dispatcher should use tmux module's EFFORT_BY_RIGOR."""

    def test_dispatcher_uses_tmux_mapping(self):
        """_EFFORT_BY_RIGOR on dispatcher should be the exact same object as tmux."""
        from voronoi.server.dispatcher import InvestigationDispatcher
        from voronoi.server.tmux import EFFORT_BY_RIGOR
        assert InvestigationDispatcher._EFFORT_BY_RIGOR is EFFORT_BY_RIGOR


class TestBug005EffectiveRigorInConvergence:
    """BUG-005: _try_convergence_check must use effective rigor, not run.rigor."""

    def test_try_convergence_uses_effective_rigor(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "deliverable.md").write_text("# Done")

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
            rigor="adaptive",
        )
        # Simulate escalation: adaptive → scientific
        run.last_rigor = "scientific"

        d._try_convergence_check(run)

        # With scientific rigor and no eval score, convergence should NOT
        # be written because check_convergence adds "No evaluator score" blocker.
        conv_path = tmp_path / ".swarm" / "convergence.json"
        if conv_path.exists():
            data = json.loads(conv_path.read_text())
            # If written, it must NOT be "converged" with zero eval_score
            # under scientific rigor.
            assert data.get("status") != "converged" or data.get("score", 0) >= 0.5


class TestBug007DesignInvalidDoesNotZombie:
    """BUG-007: _handle_completion with DESIGN_INVALID must not return early."""

    def test_design_invalid_transitions_to_failed(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        (tmp_path / ".swarm").mkdir()

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )
        run.task_snapshot = {
            "bd-1": {"status": "open", "title": "Exp",
                     "notes": "DESIGN_INVALID: bad setup"},
        }

        mock_queue = MagicMock()
        d._queue = mock_queue

        with patch("voronoi.server.dispatcher.cleanup_tmux"):
            d._handle_completion(run, failed=False)

        # Must have called fail() — not silently returned
        mock_queue.fail.assert_called_once()
        # Must have sent a message about the block
        assert any("DESIGN_INVALID" in m for m in msgs)


class TestBug008DirectivePriority:
    """BUG-008: Higher-priority directives must not be clobbered."""

    def test_sentinel_not_clobbered_by_context(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        swarm = tmp_path / ".swarm"
        swarm.mkdir()

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )

        # Write a sentinel directive first (highest priority)
        d._write_directive(run, "sentinel_violation", "Contract violated")
        data1 = json.loads((swarm / "dispatcher-directive.json").read_text())
        assert data1["directive"] == "sentinel_violation"

        # Context warning should NOT overwrite sentinel
        d._write_directive(run, "context_warning", "10h elapsed")
        data2 = json.loads((swarm / "dispatcher-directive.json").read_text())
        assert data2["directive"] == "sentinel_violation"

    def test_context_critical_overwrites_advisory(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        swarm = tmp_path / ".swarm"
        swarm.mkdir()

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )

        d._write_directive(run, "context_advisory", "6h elapsed")
        d._write_directive(run, "context_critical", "14h elapsed")
        data = json.loads((swarm / "dispatcher-directive.json").read_text())
        assert data["directive"] == "context_critical"


class TestBug009WorkerCheckpointExclusion:
    """BUG-009: _latest_checkpoint must not read 'checkpoint.json' from worktrees."""

    def test_ignores_worker_checkpoint_json(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        swarm = tmp_path / ".swarm"
        swarm.mkdir()

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="discover",
        )

        # Write orchestrator checkpoint in main workspace
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "cycle": 5, "phase": "investigating",
            "last_updated": "2026-01-01T00:00:00+00:00",
        }))

        # Create a fake worker worktree with a generic checkpoint.json
        swarm_dir = tmp_path.parent / f"{tmp_path.name}-swarm"
        worker = swarm_dir / "agent-explorer" / ".swarm"
        worker.mkdir(parents=True)
        (worker / "checkpoint.json").write_text(json.dumps({
            "cycle": 1, "phase": "complete",
            "last_updated": "2026-12-31T00:00:00+00:00",
        }))

        cp = d._latest_checkpoint(run)
        assert cp is not None
        # Must return the orchestrator's data, not the worker's
        assert cp["cycle"] == 5
        assert cp["phase"] == "investigating"


class TestBug012ResumePromptEffectiveRigor:
    """BUG-012: Near-convergence resume must use effective rigor."""

    def test_resume_prompt_uses_effective_rigor(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        swarm = tmp_path / ".swarm"
        swarm.mkdir()

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test question?",
            mode="discover",
            rigor="adaptive",
        )
        run.last_rigor = "scientific"

        # Write a near-convergence checkpoint
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "cycle": 10, "phase": "converging",
            "blockers": "", "remaining": [],
        }))
        # Write the original prompt file (required by _build_resume_prompt)
        (swarm / "orchestrator-prompt.txt").write_text("original prompt")

        resume_path = d._build_resume_prompt(run)
        content = resume_path.read_text()

        # Must reference "scientific" rigor, not "adaptive"
        assert "convergence-gate.sh . scientific" in content


class TestBug002ParkTimeoutField:
    """Regression: park-timeout must use park_entered_at, not the
    Telegram-throttle timestamp last_parked_digest_at (BUG-002)."""

    def test_park_timeout_uses_park_entered_at_not_digest(self, dispatcher_setup):
        """An investigation parked for >park_timeout_hours should force-wake
        even when frequent events have been rewriting last_parked_digest_at."""
        d, msgs, docs, tmp_path = dispatcher_setup
        d.config.park_timeout_hours = 4
        mock_queue = MagicMock()
        d._queue = mock_queue

        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "orchestrator-prompt.txt").write_text("orig prompt")

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="q",
            mode="discover",
        )
        now = time.time()
        run.orchestrator_parked = True
        # Parked 5h ago, but a Telegram digest just fired a minute ago.
        run.park_entered_at = now - 5 * 3600
        run.last_parked_digest_at = now - 60
        run.retry_count = 0
        d.running[1] = run

        with patch.object(d, "_check_abort_signal"), \
             patch.object(d, "check_human_gates"), \
             patch.object(d, "_refresh_eval_score"), \
             patch.object(d, "_sync_criteria_from_checkpoint"), \
             patch.object(d, "_check_progress", return_value=[]), \
             patch.object(d, "_check_event_log", return_value=[]), \
             patch.object(d, "_has_active_workers", return_value=False), \
             patch.object(d, "_wake_from_park", return_value=True) as wake, \
             patch("voronoi.server.dispatcher.subprocess.run",
                   return_value=MagicMock(returncode=1)):  # session dead
            d.poll_progress()

        wake.assert_called_once()

    def test_park_does_not_timeout_when_digests_fire_frequently(self, dispatcher_setup):
        """Pre-BUG-002 behavior would have kept parked_hours ~0 forever if
        digests reset the timestamp every 5 minutes. Confirm that separating
        the fields means a recently-entered park (short park_entered_at)
        does NOT force-wake even when last_parked_digest_at is stale."""
        d, msgs, docs, tmp_path = dispatcher_setup
        d.config.park_timeout_hours = 4

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="q",
            mode="discover",
        )
        now = time.time()
        run.orchestrator_parked = True
        run.park_entered_at = now - 300          # 5 min parked
        run.last_parked_digest_at = now - 7200   # stale (2h old)
        d.running[1] = run
        mock_queue = MagicMock()
        d._queue = mock_queue

        with patch.object(d, "_check_abort_signal"), \
             patch.object(d, "check_human_gates"), \
             patch.object(d, "_refresh_eval_score"), \
             patch.object(d, "_sync_criteria_from_checkpoint"), \
             patch.object(d, "_check_progress", return_value=[]), \
             patch.object(d, "_check_event_log", return_value=[]), \
             patch.object(d, "_has_active_workers", return_value=True), \
             patch.object(d, "_needs_orchestrator", return_value=False), \
             patch.object(d, "_wake_from_park") as wake, \
             patch("voronoi.server.dispatcher.subprocess.run",
                   return_value=MagicMock(returncode=1)):  # session dead
            d.poll_progress()

        wake.assert_not_called()

    def test_wake_from_park_clears_park_entered_at(self, dispatcher_setup):
        """Wake must reset park_entered_at and polling_strike_count so the
        next park starts from a clean slate."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="q",
            mode="discover",
        )
        run.orchestrator_parked = True
        run.park_entered_at = time.time() - 3600
        run.polling_strike_count = 2

        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "orchestrator-prompt.txt").write_text("orig prompt")

        with patch.object(d, "_launch_in_tmux"):
            assert d._wake_from_park(run) is True

        assert run.orchestrator_parked is False
        assert run.park_entered_at == 0
        assert run.polling_strike_count == 0


class TestBug003PollingWatchdog:
    """Regression: dispatcher must detect orchestrators stuck in sleep/poll
    loops inside the agent session and force a context refresh (BUG-003)."""

    def test_pane_sleep_increments_strike(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="voronoi-inv-1",
            question="q",
            mode="discover",
        )
        with patch.object(d, "_orchestrator_pane_command", return_value="sleep"):
            d._check_orchestrator_polling(run)
        assert run.polling_strike_count == 1

    def test_pane_non_sleep_resets_strike(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="voronoi-inv-1",
            question="q",
            mode="discover",
        )
        run.polling_strike_count = 2
        with patch.object(d, "_orchestrator_pane_command",
                          return_value="node"):
            d._check_orchestrator_polling(run)
        assert run.polling_strike_count == 0

    def test_pane_none_preserves_strike(self, dispatcher_setup):
        """A tmux error/timeout must not reset strikes (no signal != ok)."""
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="voronoi-inv-1",
            question="q",
            mode="discover",
        )
        run.polling_strike_count = 2
        with patch.object(d, "_orchestrator_pane_command", return_value=None):
            d._check_orchestrator_polling(run)
        assert run.polling_strike_count == 2

    def test_threshold_triggers_context_restart(self, dispatcher_setup):
        d, msgs, docs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="voronoi-inv-1",
            question="q",
            mode="discover",
        )
        run.polling_strike_count = d.POLLING_STRIKE_THRESHOLD - 1
        with patch.object(d, "_orchestrator_pane_command", return_value="sleep"), \
             patch.object(d, "_force_context_restart",
                          return_value=True) as force:
            d._check_orchestrator_polling(run)
        force.assert_called_once_with(run)
        # Counter reset so we don't re-fire every poll
        assert run.polling_strike_count == 0
        assert any("caught polling" in m.lower() for m in msgs)


class TestClaimDeltaSynthesis:
    """F5 — Claim-delta events synthesized into progress digests."""

    def _mk_run(self, tmp_path):
        return RunningInvestigation(
            investigation_id=42,
            workspace_path=tmp_path,
            tmux_session="voronoi-inv-42",
            question="q",
            mode="discover",
        )

    def test_first_poll_seeds_baseline_without_events(self, dispatcher_setup):
        from voronoi.science.claims import (
            ClaimLedger, PROVENANCE_RUN_EVIDENCE, save_ledger,
        )
        d, _, _, base = dispatcher_setup
        ledger = ClaimLedger()
        ledger.add_claim("A", PROVENANCE_RUN_EVIDENCE)
        save_ledger(42, ledger, base_dir=base)

        run = self._mk_run(base)
        fake_inv = SimpleNamespace(lineage_id=42)
        with patch.object(d.queue, "get", return_value=fake_inv):
            events = d._synthesize_claim_deltas(run)
        assert events == []
        assert run._ledger_baseline_seeded is True
        assert run.last_ledger_map == {"C1": "provisional"}

    def test_detects_new_claim(self, dispatcher_setup):
        from voronoi.science.claims import (
            ClaimLedger, PROVENANCE_RUN_EVIDENCE, save_ledger,
        )
        d, _, _, base = dispatcher_setup

        # First poll: baseline with 1 claim
        ledger = ClaimLedger()
        ledger.add_claim("A", PROVENANCE_RUN_EVIDENCE)
        save_ledger(42, ledger, base_dir=base)
        run = self._mk_run(base)
        fake_inv = SimpleNamespace(lineage_id=42)
        with patch.object(d.queue, "get", return_value=fake_inv):
            d._synthesize_claim_deltas(run)

            # Second poll: add a new claim
            ledger.add_claim("B", PROVENANCE_RUN_EVIDENCE)
            save_ledger(42, ledger, base_dir=base)
            events = d._synthesize_claim_deltas(run)

        assert len(events) == 1
        assert events[0]["type"] == "claim_delta"
        assert events[0]["kind"] == "new"
        assert events[0]["claim_id"] == "C2"
        assert events[0]["to_status"] == "provisional"

    def test_detects_status_transition(self, dispatcher_setup):
        from voronoi.science.claims import (
            ClaimLedger, PROVENANCE_RUN_EVIDENCE, save_ledger,
        )
        d, _, _, base = dispatcher_setup

        ledger = ClaimLedger()
        ledger.add_claim("A", PROVENANCE_RUN_EVIDENCE)
        save_ledger(42, ledger, base_dir=base)
        run = self._mk_run(base)
        fake_inv = SimpleNamespace(lineage_id=42)
        with patch.object(d.queue, "get", return_value=fake_inv):
            d._synthesize_claim_deltas(run)

            ledger.assert_claim("C1")
            ledger.lock_claim("C1")
            save_ledger(42, ledger, base_dir=base)
            events = d._synthesize_claim_deltas(run)

        assert len(events) == 1
        e = events[0]
        assert e["kind"] == "transition"
        assert e["from_status"] == "provisional"
        assert e["to_status"] == "locked"

    def test_missing_ledger_returns_no_events(self, dispatcher_setup):
        d, _, _, base = dispatcher_setup
        run = self._mk_run(base)
        fake_inv = SimpleNamespace(lineage_id=99)  # no ledger exists
        with patch.object(d.queue, "get", return_value=fake_inv):
            events = d._synthesize_claim_deltas(run)
        # Empty ledger seeds baseline with empty map — still no events
        assert events == []


class TestLearningStalled:
    """F2 — LEARNING_STALLED alert when no findings/claims for N minutes."""

    def _mk_active_run(self, tmp_path):
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="voronoi-inv-1",
            question="q",
            mode="discover",
            phase="investigating",
        )
        run.task_snapshot = {"bd-1": {"status": "in_progress", "title": "x"}}
        return run

    def test_finding_resets_activity(self, dispatcher_setup):
        d, msgs, _, base = dispatcher_setup
        run = self._mk_active_run(base)
        run.last_learning_activity_at = time.time() - 3600  # very stale
        d._update_learning_activity(run, [{"type": "finding", "msg": "x"}])
        assert not run.notified_learning_stalled
        assert not msgs

    def test_claim_transition_resets_activity(self, dispatcher_setup):
        d, msgs, _, base = dispatcher_setup
        run = self._mk_active_run(base)
        run.last_learning_activity_at = time.time() - 3600
        d._update_learning_activity(run, [
            {"type": "claim_delta", "kind": "transition",
             "from_status": "asserted", "to_status": "locked"},
        ])
        assert not run.notified_learning_stalled
        assert not msgs

    def test_new_claim_alone_does_not_reset(self, dispatcher_setup):
        d, msgs, _, base = dispatcher_setup
        run = self._mk_active_run(base)
        stale_ts = time.time() - (d.config.learning_stall_minutes * 60 + 300)
        run.last_learning_activity_at = stale_ts
        d._update_learning_activity(run, [
            {"type": "claim_delta", "kind": "new",
             "from_status": None, "to_status": "provisional"},
        ])
        assert run.notified_learning_stalled is True
        assert any("learning stalled" in m.lower() for m in msgs)

    def test_fires_once_after_stall_window(self, dispatcher_setup):
        d, msgs, _, base = dispatcher_setup
        run = self._mk_active_run(base)
        run.last_learning_activity_at = (
            time.time() - (d.config.learning_stall_minutes * 60 + 120)
        )
        d._update_learning_activity(run, [])
        d._update_learning_activity(run, [])  # second call: should NOT re-fire
        stalled_msgs = [m for m in msgs if "learning stalled" in m.lower()]
        assert len(stalled_msgs) == 1

    def test_does_not_fire_before_window(self, dispatcher_setup):
        d, msgs, _, base = dispatcher_setup
        run = self._mk_active_run(base)
        run.last_learning_activity_at = time.time() - 60  # 1 min ago
        d._update_learning_activity(run, [])
        assert not run.notified_learning_stalled
        assert not any("learning stalled" in m.lower() for m in msgs)

    def test_skips_initial_phases_with_no_tasks(self, dispatcher_setup):
        d, msgs, _, base = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1, workspace_path=base,
            tmux_session="s", question="q", mode="discover",
            phase="starting",
        )
        run.last_learning_activity_at = (
            time.time() - (d.config.learning_stall_minutes * 60 + 120)
        )
        d._update_learning_activity(run, [])
        assert not run.notified_learning_stalled

