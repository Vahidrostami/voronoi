"""Tests for the full demo pipeline: Telegram → router → queue → dispatcher → workspace.

Covers all fixes from the coupled-decisions debugging session:
1. /voronoi demo command in router (handle_demo + CommandRouter)
2. Full text passed to workflow handlers (not truncated summary)
3. eval_score propagation from workspace to dispatcher
4. tmux exit detection + timeout mechanism
5. Atomic queue claiming in next_ready
6. Demo file copying in dispatcher
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from voronoi.gateway.router import (
    CommandRouter,
    handle_demo,
)
from voronoi.server.dispatcher import (
    DispatcherConfig,
    InvestigationDispatcher,
    RunningInvestigation,
)
from voronoi.server.queue import Investigation, InvestigationQueue


# ---------------------------------------------------------------------------
# Fix 1: /voronoi demo command
# ---------------------------------------------------------------------------

class TestHandleDemo:
    """Test handle_demo routes demo investigations correctly."""

    @patch("voronoi.gateway.router._get_queue")
    @patch("voronoi.gateway.router.codename_for_id", return_value="Dopamine")
    def test_demo_enqueues_with_full_prompt(self, mock_cn, mock_gq, tmp_path):
        """The demo's full PROMPT.md content must be the investigation question."""
        # Create a fake demo
        demo_dir = tmp_path / "data" / "demos" / "test-demo"
        demo_dir.mkdir(parents=True)
        prompt_content = "# Test Demo\n\nThis is a long prompt with details.\n"
        (demo_dir / "PROMPT.md").write_text(prompt_content)

        mock_q = MagicMock()
        mock_q.enqueue.return_value = 1
        mock_q.get.return_value = Investigation(id=1, codename="Dopamine")
        mock_q.get_queued.return_value = []
        mock_q.get_running.return_value = []
        mock_gq.return_value = mock_q

        with patch("voronoi.cli.find_data_dir", return_value=tmp_path / "data"), \
             patch("voronoi.cli.list_demos", return_value=[{
                 "name": "test-demo",
                 "path": demo_dir,
                 "description": "Test",
                 "has_prompt": True,
             }]):
            result = handle_demo(str(tmp_path), "test-demo", "chat1")

        assert "DEMO LAUNCHED" in result
        assert "Dopamine" in result
        # Verify the full prompt was passed as the question
        call_args = mock_q.enqueue.call_args
        inv = call_args[0][0]
        assert inv.question == prompt_content
        assert inv.mode == "investigate"
        assert inv.rigor in ("analytical", "scientific", "experimental")
        mock_q.set_demo_source.assert_called_once()

    @patch("voronoi.cli.find_data_dir")
    @patch("voronoi.cli.list_demos", return_value=[])
    def test_demo_not_found(self, mock_list, mock_data, tmp_path):
        result = handle_demo(str(tmp_path), "nonexistent", "chat1")
        assert "not found" in result

    @patch("voronoi.cli.find_data_dir")
    @patch("voronoi.cli.list_demos")
    def test_demo_no_prompt(self, mock_list, mock_data, tmp_path):
        mock_list.return_value = [{"name": "broken", "path": tmp_path, "description": "", "has_prompt": False}]
        result = handle_demo(str(tmp_path), "broken", "chat1")
        assert "no PROMPT.md" in result


class TestCommandRouterDemo:
    """Test that CommandRouter routes /voronoi demo commands."""

    def test_route_demo_run(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        with patch("voronoi.gateway.router.handle_demo", return_value="OK") as mock_hd:
            text, _ = router.route("demo", ["run", "coupled-decisions"], "chat1")
        mock_hd.assert_called_once_with(str(tmp_path), "coupled-decisions", "chat1")
        assert text == "OK"

    def test_route_demo_list(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        with patch.object(router, "_list_demos", return_value="demos") as mock_ld:
            text, _ = router.route("demo", ["list"], "chat1")
        mock_ld.assert_called_once()
        assert text == "demos"

    def test_route_demo_no_args(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.route("demo", [], "chat1")
        assert "Unknown command" in text

    def test_route_demo_run_no_name(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.route("demo", ["run"], "chat1")
        assert "Usage" in text


# ---------------------------------------------------------------------------
# Fix 2: Full text passed (not truncated summary)
# ---------------------------------------------------------------------------

class TestFullTextPassthrough:
    """Verify that free-text handler passes the full message, not a truncated summary."""

    def test_long_question_not_truncated(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        long_question = "Why is our model accuracy " + "dropping " * 20 + "after each retrain cycle?"
        assert len(long_question) > 80  # longer than the old summary limit

        with patch("voronoi.gateway.router.handle_investigate") as mock_inv:
            mock_inv.return_value = "OK"
            router.handle_free_text(long_question, "chat1", True)

        # The full text must have been passed, not a truncated summary
        call_args = mock_inv.call_args[0]
        assert call_args[1] == long_question  # second arg is the question text

    def test_explicit_command_passes_full_args(self, tmp_path):
        """Explicit /voronoi investigate passes full args even if long."""
        router = CommandRouter(str(tmp_path))
        long_args = ["Why", "is", "our", "model"] + ["very"] * 30 + ["slow?"]
        with patch("voronoi.gateway.router.handle_investigate") as mock_inv:
            mock_inv.return_value = "OK"
            router.route("investigate", long_args, "chat1")
        call_args = mock_inv.call_args[0]
        assert "very" in call_args[1]
        assert call_args[1] == " ".join(long_args)


# ---------------------------------------------------------------------------
# Fix 3: eval_score propagation
# ---------------------------------------------------------------------------

class TestEvalScorePropagation:
    """Verify dispatcher reads eval_score from workspace file."""

    @pytest.fixture
    def dispatcher_setup(self, tmp_path):
        config = DispatcherConfig(base_dir=tmp_path, max_concurrent=2, agent_command="echo")
        messages = []
        d = InvestigationDispatcher(config, lambda msg: messages.append(msg))
        return d, messages, tmp_path

    def test_refresh_eval_score_reads_file(self, dispatcher_setup):
        d, msgs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="investigate",
        )
        assert run.eval_score == 0.0

        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "eval-score.json").write_text(json.dumps({"score": 0.82, "rounds": 1}))

        d._refresh_eval_score(run)
        assert run.eval_score == 0.82
        assert run.improvement_rounds == 1

    def test_refresh_eval_score_missing_file(self, dispatcher_setup):
        d, msgs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="investigate",
        )
        d._refresh_eval_score(run)
        assert run.eval_score == 0.0  # unchanged

    def test_refresh_eval_score_corrupt_file(self, dispatcher_setup):
        d, msgs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="investigate",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "eval-score.json").write_text("not json")

        d._refresh_eval_score(run)
        assert run.eval_score == 0.0  # unchanged, no crash

    def test_is_complete_with_eval_score_and_deliverable(self, dispatcher_setup):
        """With standard rigor, deliverable alone is sufficient."""
        d, msgs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="build",
            rigor="standard",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "deliverable.md").write_text("# Done")
        assert d._is_complete(run) is True

    def test_is_complete_analytical_needs_convergence(self, dispatcher_setup):
        """Analytical rigor requires convergence.json even with deliverable."""
        d, msgs, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="investigate",
            rigor="analytical",
        )
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "deliverable.md").write_text("# Done")
        # Without convergence.json, not complete
        assert d._is_complete(run) is False

        # With convergence.json showing converged, complete
        (swarm / "convergence.json").write_text(json.dumps({"converged": True, "status": "converged"}))
        assert d._is_complete(run) is True


# ---------------------------------------------------------------------------
# Fix 4: Timeout detection
# ---------------------------------------------------------------------------

class TestTimeoutDetection:
    @pytest.fixture
    def dispatcher_setup(self, tmp_path):
        config = DispatcherConfig(
            base_dir=tmp_path, max_concurrent=2,
            agent_command="echo", timeout_hours=2,
        )
        messages = []
        d = InvestigationDispatcher(config, lambda msg: messages.append(msg))
        d._queue = MagicMock()
        return d, messages, tmp_path

    def test_write_timeout_convergence(self, dispatcher_setup):
        d, msgs, tmp_path = dispatcher_setup
        (tmp_path / ".swarm").mkdir()
        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test",
            mode="investigate",
        )
        d._write_timeout_convergence(run)
        conv = tmp_path / ".swarm" / "convergence.json"
        assert conv.exists()
        data = json.loads(conv.read_text())
        assert data["status"] == "exhausted"
        assert "timeout" in data["blockers"]

    def test_timeout_triggers_completion(self, dispatcher_setup):
        d, msgs, tmp_path = dispatcher_setup
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "deliverable.md").write_text("# Partial")

        run = RunningInvestigation(
            investigation_id=1,
            workspace_path=tmp_path,
            tmux_session="test",
            question="test q",
            mode="build",
            started_at=time.time() - 3 * 3600,  # 3h ago, timeout is 2h
        )
        run.last_update_at = 0  # force progress check
        d.running[1] = run

        def _mock_run(cmd, **kwargs):
            m = MagicMock()
            if "has-session" in cmd:
                m.returncode = 0  # session alive
            elif "kill-session" in cmd:
                m.returncode = 0
            elif "bd" in cmd:
                m.returncode = 0
                m.stdout = "[]"
                m.stderr = ""
            else:
                m.returncode = 0
                m.stdout = ""
                m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=_mock_run), \
             patch("voronoi.server.dispatcher.subprocess.run", side_effect=_mock_run):
            d.poll_progress()

        # Should have been completed via timeout
        assert 1 not in d.running
        d._queue.complete.assert_called_once_with(1)

    def test_effective_timeout_default(self, dispatcher_setup):
        """Without override file, uses config default."""
        d, _, tmp_path = dispatcher_setup
        run = RunningInvestigation(
            investigation_id=1, workspace_path=tmp_path,
            tmux_session="t", question="q", mode="investigate",
        )
        assert d._effective_timeout(run) == 2  # config default

    def test_effective_timeout_override(self, dispatcher_setup):
        """Override file in .swarm/timeout_hours takes precedence."""
        d, _, tmp_path = dispatcher_setup
        swarm = tmp_path / ".swarm"
        swarm.mkdir(exist_ok=True)
        (swarm / "timeout_hours").write_text("72")
        run = RunningInvestigation(
            investigation_id=1, workspace_path=tmp_path,
            tmux_session="t", question="q", mode="investigate",
        )
        assert d._effective_timeout(run) == 72

    def test_effective_timeout_bad_value_falls_back(self, dispatcher_setup):
        """Non-integer or non-positive values fall back to config default."""
        d, _, tmp_path = dispatcher_setup
        swarm = tmp_path / ".swarm"
        swarm.mkdir(exist_ok=True)
        (swarm / "timeout_hours").write_text("not-a-number")
        run = RunningInvestigation(
            investigation_id=1, workspace_path=tmp_path,
            tmux_session="t", question="q", mode="investigate",
        )
        assert d._effective_timeout(run) == 2  # falls back to config

    def test_timeout_override_prevents_timeout(self, dispatcher_setup):
        """Extending timeout prevents a running investigation from timing out."""
        d, msgs, tmp_path = dispatcher_setup
        swarm = tmp_path / ".swarm"
        swarm.mkdir(exist_ok=True)

        run = RunningInvestigation(
            investigation_id=1, workspace_path=tmp_path,
            tmux_session="test", question="test q", mode="build",
            started_at=time.time() - 3 * 3600,  # 3h ago, config timeout is 2h
        )
        # Extend to 6h — should NOT time out at 3h elapsed
        (swarm / "timeout_hours").write_text("6")
        run.last_update_at = 0
        d.running[1] = run

        def _mock_run(cmd, **kwargs):
            m = MagicMock()
            if "has-session" in cmd:
                m.returncode = 0  # session alive
            elif "bd" in cmd:
                m.returncode = 0
                m.stdout = "[]"
                m.stderr = ""
            else:
                m.returncode = 0
                m.stdout = ""
                m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=_mock_run), \
             patch("voronoi.server.dispatcher.subprocess.run", side_effect=_mock_run):
            d.poll_progress()

        # Should still be running — timeout extended past 3h
        assert 1 in d.running


# ---------------------------------------------------------------------------
# Fix 5: Atomic queue claiming
# ---------------------------------------------------------------------------

class TestAtomicQueueClaiming:
    @pytest.fixture
    def queue(self, tmp_path):
        return InvestigationQueue(tmp_path / "queue.db")

    def test_next_ready_claims_atomically(self, queue):
        """next_ready should mark the investigation as running atomically."""
        queue.enqueue(Investigation(chat_id="c1", question="Q1", slug="q1"))
        inv = queue.next_ready(max_concurrent=2)
        assert inv is not None

        # The investigation should now be running
        result = queue.get(inv.id)
        assert result.status == "running"
        assert result.started_at is not None

    def test_next_ready_concurrent_safety(self, queue):
        """Two concurrent next_ready calls should not both get the same investigation."""
        queue.enqueue(Investigation(chat_id="c1", question="Q1", slug="q1"))

        inv1 = queue.next_ready(max_concurrent=2)
        inv2 = queue.next_ready(max_concurrent=2)  # already running

        assert inv1 is not None
        assert inv2 is None  # no more queued items

    def test_start_works_on_already_running(self, queue):
        """start() should still set workspace_path even if already running."""
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q1", slug="q1"))
        queue.next_ready(max_concurrent=2)  # claims it
        queue.start(inv_id, "/tmp/workspace")

        result = queue.get(inv_id)
        assert result.status == "running"
        assert result.workspace_path == "/tmp/workspace"


# ---------------------------------------------------------------------------
# Fix 6: Demo file copying in dispatcher
# ---------------------------------------------------------------------------

class TestDemoFileCopying:
    @pytest.fixture
    def dispatcher_setup(self, tmp_path):
        config = DispatcherConfig(base_dir=tmp_path, max_concurrent=2, agent_command="echo")
        messages = []
        d = InvestigationDispatcher(config, lambda msg: messages.append(msg))
        return d, messages, tmp_path

    def test_copy_demo_files(self, dispatcher_setup):
        d, msgs, tmp_path = dispatcher_setup
        # Create fake demo source
        demo_src = tmp_path / "demo-source" / "my-demo"
        demo_src.mkdir(parents=True)
        (demo_src / "PROMPT.md").write_text("# Demo Prompt\n")
        (demo_src / "README.md").write_text("# Demo Readme\n")

        # Create workspace
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        d._copy_demo_files(("my-demo", str(demo_src)), workspace)

        demo_dst = workspace / "demos" / "my-demo"
        assert demo_dst.exists()
        assert (demo_dst / "PROMPT.md").exists()
        assert "Demo Prompt" in (demo_dst / "PROMPT.md").read_text()

    def test_copy_demo_files_missing_source(self, dispatcher_setup):
        d, msgs, tmp_path = dispatcher_setup
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        # Should not crash
        d._copy_demo_files(("missing", str(tmp_path / "nonexistent")), workspace)
        assert not (workspace / "demos" / "missing").exists()


# ---------------------------------------------------------------------------
# Queue: demo_source column
# ---------------------------------------------------------------------------

class TestQueueDemoSource:
    @pytest.fixture
    def queue(self, tmp_path):
        return InvestigationQueue(tmp_path / "queue.db")

    def test_set_and_get_demo_source(self, queue):
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.set_demo_source(inv_id, "coupled-decisions", "/path/to/demo")
        result = queue.get_demo_source(inv_id)
        assert result is not None
        assert result == ("coupled-decisions", "/path/to/demo")

    def test_get_demo_source_none(self, queue):
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        assert queue.get_demo_source(inv_id) is None

    def test_demo_source_in_investigation(self, queue):
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.set_demo_source(inv_id, "test", "/tmp/test")
        inv = queue.get(inv_id)
        assert inv.demo_source == "test:/tmp/test"


# ---------------------------------------------------------------------------
# Integration: tmux exit command
# ---------------------------------------------------------------------------

class TestTmuxExitCommand:
    """Verify the tmux launch command includes '; exit' so the session dies when the agent finishes."""

    def test_launch_command_includes_exit(self, tmp_path):
        config = DispatcherConfig(base_dir=tmp_path, agent_command="echo", agent_flags="--test")
        d = InvestigationDispatcher(config, lambda msg: None)

        with patch("shutil.which", return_value="/usr/bin/echo"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            d._launch_in_tmux("test-session", tmp_path)

        # Find the send-keys call
        send_calls = [c for c in mock_run.call_args_list if "send-keys" in str(c)]
        assert len(send_calls) == 1
        cmd_str = str(send_calls[0])
        assert "; exit" in cmd_str
