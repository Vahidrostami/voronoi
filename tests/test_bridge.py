"""Tests for the refactored architecture.

Tests the gateway modules (config, router) which now own all business
logic.  The bridge script is a thin Telegram I/O layer that delegates
to these modules — it is not tested directly here.
"""

import asyncio
import importlib.util
import json
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from voronoi.gateway.config import load_config, save_chat_id
from voronoi.gateway.router import (
    CommandRouter,
    handle_status,
    handle_whatsup,
    handle_howsitgoing,
    handle_tasks,
    handle_ready,
    handle_health,
    handle_guide,
    handle_pivot,
    handle_abort,
    handle_discover,
    handle_prove,
    handle_recall,
    handle_belief,
    handle_journal,
    handle_finding,
    handle_complete,
    handle_complete_investigation,
    handle_review_investigation,
    handle_continue_investigation,
    handle_claims,
    handle_ask,
)


def _load_bridge_module():
    bridge_path = Path(__file__).resolve().parent.parent / "src" / "voronoi" / "data" / "scripts" / "telegram-bridge.py"
    spec = importlib.util.spec_from_file_location("voronoi_telegram_bridge", bridge_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class TestConfig:
    def test_load_config_defaults(self, tmp_path):
        config = load_config(str(tmp_path / "nonexistent.json"))
        assert config["bridge_enabled"] is True
        assert config["user_allowlist"] == []

    def test_load_config_with_user_allowlist(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VORONOI_TG_USER_ALLOWLIST", "112423044,vahidrostami")
        config_data = {
            "notifications": {
                "telegram": {
                    "bot_token": "test",
                    "bridge_enabled": True,
                }
            }
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config_data))
        config = load_config(str(config_path))
        assert "112423044" in config["user_allowlist"]
        assert "vahidrostami" in config["user_allowlist"]

    def test_save_chat_id(self, tmp_path):
        save_chat_id(str(tmp_path), 12345)
        chat_file = tmp_path / ".telegram-chat-id"
        assert chat_file.exists()
        assert chat_file.read_text().strip() == "12345"


class TestBridgeSupervision:
    def test_run_coro_threadsafe_returns_result_without_worker_event_loop(self):
        module = _load_bridge_module()
        loop = asyncio.new_event_loop()
        loop_ready = threading.Event()

        def run_loop() -> None:
            asyncio.set_event_loop(loop)
            loop_ready.set()
            loop.run_forever()

        loop_thread = threading.Thread(target=run_loop)
        loop_thread.start()
        loop_ready.wait(timeout=1)

        result_holder: dict[str, int] = {}
        error_holder: dict[str, BaseException] = {}

        async def sample() -> int:
            return 42

        def worker() -> None:
            try:
                result_holder["value"] = module._run_coro_threadsafe(loop, sample(), timeout=1.0)
            except BaseException as exc:
                error_holder["error"] = exc

        worker_thread = threading.Thread(target=worker)
        worker_thread.start()
        worker_thread.join(timeout=1)

        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=1)
        loop.close()

        assert "error" not in error_holder
        assert result_holder["value"] == 42

    def test_run_bot_forever_retries_transient_errors(self, monkeypatch):
        module = _load_bridge_module()
        calls = {"count": 0}
        sleeps = []

        def fake_run_bot(config):
            calls["count"] += 1
            if calls["count"] < 3:
                raise RuntimeError("temporary failure")
            raise KeyboardInterrupt()

        monkeypatch.setattr(module, "run_bot", fake_run_bot)
        monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

        module.run_bot_forever({"bot_token": "test"}, restart_delay=2, max_delay=10)

        assert calls["count"] == 3
        assert sleeps == [2, 4]

    def test_run_bot_forever_fails_fast_on_invalid_token(self, monkeypatch):
        module = _load_bridge_module()
        sleeps = []

        class InvalidToken(Exception):
            pass

        def fake_run_bot(config):
            raise InvalidToken("bad token")

        monkeypatch.setattr(module, "run_bot", fake_run_bot)
        monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

        with pytest.raises(InvalidToken):
            module.run_bot_forever({"bot_token": "test"}, restart_delay=2, max_delay=10)

        assert sleeps == []

    def test_run_bot_forever_fails_fast_on_conflict(self, monkeypatch):
        module = _load_bridge_module()
        sleeps = []

        class Conflict(Exception):
            pass

        def fake_run_bot(config):
            raise Conflict("terminated by other getUpdates request")

        monkeypatch.setattr(module, "run_bot", fake_run_bot)
        monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

        with pytest.raises(Conflict):
            module.run_bot_forever({"bot_token": "test"}, restart_delay=2, max_delay=10)

        assert sleeps == []


# ---------------------------------------------------------------------------
# Existing handlers (regression)
# ---------------------------------------------------------------------------

class TestHandlers:
    def test_handle_status(self, tmp_path):
        # status is now an alias for whatsup — conversational
        swarm_dir = tmp_path / ".swarm"
        swarm_dir.mkdir(parents=True, exist_ok=True)
        mock_q = MagicMock()
        mock_q.get_running.return_value = []
        mock_q.get_queued.return_value = []
        with patch("voronoi.gateway.handlers_query._get_queue", return_value=mock_q):
            result = handle_status(str(tmp_path))
        # Should return something (buddy style - no running = simple msg)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_handle_whatsup_no_running(self, tmp_path):
        mock_q = MagicMock()
        mock_q.get_running.return_value = []
        mock_q.get_queued.return_value = []
        with patch("voronoi.gateway.handlers_query._get_queue", return_value=mock_q):
            result = handle_whatsup(str(tmp_path))
        # Either nothing or queued items — both are valid
        assert isinstance(result, str)
        assert len(result) > 0

    def test_handle_howsitgoing_no_running(self, tmp_path):
        with patch("voronoi.gateway.handlers_query._get_active_workspaces", return_value=[]):
            result = handle_howsitgoing(str(tmp_path))
        assert "Nothing running" in result

    def test_handle_tasks_no_running(self, tmp_path):
        mock_q = MagicMock()
        mock_q.get_running.return_value = []
        with patch("voronoi.gateway.handlers_query._get_queue", return_value=mock_q):
            result = handle_tasks(str(tmp_path))
        assert "No running investigations" in result

    def test_handle_ready_no_running(self, tmp_path):
        mock_q = MagicMock()
        mock_q.get_running.return_value = []
        with patch("voronoi.gateway.handlers_query._get_queue", return_value=mock_q):
            result = handle_ready(str(tmp_path))
        assert "No unblocked tasks ready" in result

    def test_handle_health_no_sessions(self, tmp_path):
        result = handle_health(str(tmp_path))
        # Should return a message — either health data or a graceful "not found"
        assert isinstance(result, str)
        assert len(result) > 0

    def test_handle_guide(self, tmp_path):
        (tmp_path / ".swarm").mkdir(parents=True)
        with patch("voronoi.gateway.handlers_mutate._get_active_workspaces", return_value=[]):
            result = handle_guide(str(tmp_path), "focus on H1")
        assert "Guidance noted" in result
        assert (tmp_path / ".swarm" / "operator-guidance.md").exists()

    def test_handle_pivot(self, tmp_path):
        (tmp_path / ".swarm").mkdir(parents=True)
        with patch("voronoi.gateway.handlers_mutate._get_active_workspaces", return_value=[]):
            result = handle_pivot(str(tmp_path), "new direction")
        assert "Pivot recorded" in result

    def test_handle_abort(self, tmp_path):
        mock_q = MagicMock()
        mock_q.get_queued.return_value = []
        with patch("voronoi.gateway.handlers_mutate._get_queue", return_value=mock_q), \
             patch("voronoi.gateway.handlers_mutate._get_active_workspaces", return_value=[]):
            result = handle_abort(str(tmp_path))
        assert "Abort requested" in result
        # Should write abort signal to global fallback
        assert (Path.home() / ".voronoi" / ".swarm" / "abort-signal").exists()
        # Clean up
        (Path.home() / ".voronoi" / ".swarm" / "abort-signal").unlink(missing_ok=True)

    def test_handle_abort_cancels_queued(self, tmp_path):
        """Abort should cancel queued investigations via the queue."""
        from voronoi.server.queue import InvestigationQueue, Investigation
        q = InvestigationQueue(tmp_path / "test-queue.db")
        inv = Investigation(chat_id="test", question="test q", slug="abort-test",
                            mode="discover", rigor="adaptive")
        inv_id = q.enqueue(inv)
        with patch("voronoi.gateway.handlers_mutate._get_queue", return_value=q), \
             patch("voronoi.gateway.handlers_mutate._get_active_workspaces", return_value=[]):
            result = handle_abort(str(tmp_path))
        assert "Abort requested" in result
        assert "Cancelled 1" in result
        # Clean up global abort signal
        (Path.home() / ".voronoi" / ".swarm" / "abort-signal").unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Science workflow handlers
# ---------------------------------------------------------------------------

class TestScienceHandlers:
    @patch("voronoi.gateway.handlers_workflow.InvestigationQueue", autospec=True)
    @patch("voronoi.gateway.handlers_workflow.make_slug", return_value="test-slug")
    def test_handle_discover(self, mock_slug, mock_queue_cls, tmp_path):
        mock_q = MagicMock()
        mock_q.enqueue.return_value = 1
        mock_q.get_queued.return_value = []
        mock_q.get_running.return_value = []
        mock_queue_cls.return_value = mock_q

        result = handle_discover(str(tmp_path), "Why is latency high?", "chat1")
        assert "is live" in result
        assert "discovery" in result

    @patch("voronoi.gateway.handlers_workflow.InvestigationQueue", autospec=True)
    @patch("voronoi.gateway.handlers_workflow.make_slug", return_value="test-slug")
    def test_handle_prove(self, mock_slug, mock_queue_cls, tmp_path):
        mock_q = MagicMock()
        mock_q.enqueue.return_value = 2
        mock_q.get_queued.return_value = []
        mock_q.get_running.return_value = []
        mock_queue_cls.return_value = mock_q

        result = handle_prove(str(tmp_path), "test batch size effect", "chat1")
        assert "is live" in result
        assert "proof" in result


# ---------------------------------------------------------------------------
# Knowledge handlers
# ---------------------------------------------------------------------------

class TestKnowledgeHandlers:
    @patch("voronoi.gateway.handlers_query._get_federated_knowledge")
    @patch("voronoi.gateway.handlers_query._get_knowledge")
    def test_handle_recall_uses_federated_results(self, mock_get_knowledge, mock_get_federated, tmp_path):
        local_store = MagicMock()
        local_store.search_findings.return_value = []
        local_store.format_recall_response.return_value = "📚 No findings match: _cache_"
        mock_get_knowledge.return_value = local_store

        federated_store = MagicMock()
        federated_finding = MagicMock()
        federated_finding.title = "FINDING: Cache improves throughput"
        federated_finding.format_telegram.return_value = "*Beta:bd-2*: Cache improves throughput"
        federated_store.search.return_value = [federated_finding]
        mock_get_federated.return_value = federated_store

        result = handle_recall(str(tmp_path), "cache")

        assert "cross-investigation" in result
        assert "Cache improves throughput" in result
        assert "No findings match" not in result

    @patch("voronoi.gateway.handlers_query._get_federated_knowledge")
    @patch("voronoi.gateway.handlers_query._get_knowledge")
    def test_handle_recall_deduplicates_federated_titles(self, mock_get_knowledge, mock_get_federated, tmp_path):
        local_store = MagicMock()
        local_finding = MagicMock()
        local_finding.title = "FINDING: Cache improves throughput"
        local_store.search_findings.return_value = [local_finding]
        local_store.format_recall_response.return_value = "📚 *1 finding(s)* for: _cache_\n\n1. local"
        mock_get_knowledge.return_value = local_store

        federated_store = MagicMock()
        federated_finding = MagicMock()
        federated_finding.title = "FINDING: Cache improves throughput"
        federated_finding.format_telegram.return_value = "*Beta:bd-2*: Cache improves throughput"
        federated_store.search.return_value = [federated_finding]
        mock_get_federated.return_value = federated_store

        result = handle_recall(str(tmp_path), "cache")

        assert "cross-investigation" not in result
        assert "1. local" in result

    def test_handle_belief_no_file(self, tmp_path):
        with patch("voronoi.gateway.handlers_query._get_active_workspaces", return_value=[]):
            result = handle_belief(str(tmp_path))
        assert "No belief map" in result

    def test_handle_belief_with_file(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "belief-map.md").write_text("H1: P=0.7")
        with patch("voronoi.gateway.handlers_query._get_active_workspaces", return_value=[]):
            result = handle_belief(str(tmp_path))
        assert "H1" in result

    def test_handle_belief_dict_keyed_hypotheses(self, tmp_path):
        """handle_belief should not crash with dict-keyed hypotheses."""
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "belief-map.json").write_text(json.dumps({
            "hypotheses": {
                "H1": {"name": "Encoding helps", "prior": 0.6, "status": "confirmed"},
                "H2": "Just a string",
            },
        }))
        with patch("voronoi.gateway.handlers_query._get_active_workspaces", return_value=[]):
            result = handle_belief(str(tmp_path))
        assert "Encoding helps" in result
        assert "Just a string" in result
        assert "Belief Map" in result

    def test_handle_journal_no_file(self, tmp_path):
        with patch("voronoi.gateway.handlers_query._get_active_workspaces", return_value=[]):
            result = handle_journal(str(tmp_path))
        assert "No journal" in result

    def test_handle_journal_with_file(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "journal.md").write_text("## Round 1\nFound something interesting")
        with patch("voronoi.gateway.handlers_query._get_active_workspaces", return_value=[]):
            result = handle_journal(str(tmp_path))
        assert "Found something" in result

    @patch("voronoi.gateway.handlers_query._run_bd")
    def test_handle_finding(self, mock_bd, tmp_path):
        (tmp_path / ".beads").mkdir()
        task = {"id": "bd-42", "title": "FINDING: Cache works", "status": "closed",
                "priority": 1, "notes": "EFFECT_SIZE:d=1.5"}
        mock_bd.return_value = (0, json.dumps(task))
        result = handle_finding(str(tmp_path), "bd-42")
        assert "bd-42" in result
        assert "Cache works" in result

    @patch("voronoi.gateway.handlers_query._run_bd")
    def test_handle_finding_not_found(self, mock_bd, tmp_path):
        (tmp_path / ".beads").mkdir()
        mock_bd.return_value = (1, "not found")
        result = handle_finding(str(tmp_path), "bd-999")
        assert "not found" in result


# ---------------------------------------------------------------------------
# CommandRouter
# ---------------------------------------------------------------------------

class TestCommandRouter:
    def test_route_help(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.route("", [], "chat1")
        assert "Voronoi" in text

    def test_route_status(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.route("status", [], "chat1")
        # Now returns conversational buddy-style response
        assert isinstance(text, str)
        assert len(text) > 0

    def test_route_progress(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.route("progress", [], "chat1")
        assert isinstance(text, str)

    def test_route_whatsup(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.route("whatsup", [], "chat1")
        assert isinstance(text, str)

    def test_route_howsitgoing(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.route("howsitgoing", [], "chat1")
        assert isinstance(text, str)

    def test_route_unknown(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.route("xyzzy", [], "chat1")
        assert "Unknown command" in text

    def test_route_complete(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        with patch("voronoi.gateway.handlers_mutate._run_bd") as mock_bd:
            mock_bd.return_value = (0, "")
            text, _ = router.route("complete", ["bd-42", "Done", "work"], "chat1")
        assert "bd-42" in text
        assert "closed" in text

    def test_handle_complete_with_default_reason(self, tmp_path):
        with patch("voronoi.gateway.handlers_mutate._run_bd") as mock_bd:
            mock_bd.return_value = (0, "")
            result = handle_complete(str(tmp_path), "bd-1")
        assert "Completed" in result
        assert "bd-1" in result

    def test_handle_complete_failure(self, tmp_path):
        with patch("voronoi.gateway.handlers_mutate._run_bd") as mock_bd:
            mock_bd.return_value = (1, "not found")
            result = handle_complete(str(tmp_path), "bd-99")
        assert "Failed" in result


class TestHumanGateBridgeCommands:
    def test_approve_command_calls_dispatcher(self):
        bridge = _load_bridge_module()
        dispatcher = MagicMock()
        dispatcher.approve_human_gate.return_value = True

        text = bridge.format_human_gate_command_reply("approve", ["42"], dispatcher)

        dispatcher.approve_human_gate.assert_called_once_with(42, "")
        assert "Approved human gate" in text

    def test_revise_requires_feedback(self):
        bridge = _load_bridge_module()
        dispatcher = MagicMock()

        text = bridge.format_human_gate_command_reply("revise", ["42"], dispatcher)

        dispatcher.revise_human_gate.assert_not_called()
        assert text == "Usage: /revise <investigation-id> <feedback>"

    def test_revise_command_calls_dispatcher(self):
        bridge = _load_bridge_module()
        dispatcher = MagicMock()
        dispatcher.revise_human_gate.return_value = True

        text = bridge.format_human_gate_command_reply(
            "revise", ["42", "needs", "more", "controls"], dispatcher
        )

        dispatcher.revise_human_gate.assert_called_once_with(42, "needs more controls")
        assert "Requested revision" in text

    def test_invalid_human_gate_id(self):
        bridge = _load_bridge_module()
        dispatcher = MagicMock()

        text = bridge.format_human_gate_command_reply("approve", ["abc"], dispatcher)

        dispatcher.approve_human_gate.assert_not_called()
        assert "Invalid investigation ID" in text

    def test_dispatcher_unavailable(self):
        bridge = _load_bridge_module()

        text = bridge.format_human_gate_command_reply("approve", ["42"], None)

        assert "Dispatcher unavailable" in text


# ---------------------------------------------------------------------------
# ASK handler — mid-investigation Q&A
# ---------------------------------------------------------------------------

class TestAskHandler:
    """Test handle_ask for mid-investigation questions."""

    def test_ask_no_running(self, tmp_path):
        """When nothing is running, ask returns a helpful message."""
        mock_q = MagicMock()
        mock_q.get_running.return_value = []
        with patch("voronoi.gateway.handlers_query._get_queue", return_value=mock_q):
            result = handle_ask(str(tmp_path), "what are the results?")
        assert "Nothing running" in result or "nothing to ask" in result.lower()

    def test_ask_with_experiments(self, tmp_path):
        """Ask about experiments when experiments.tsv exists."""
        from voronoi.server.queue import InvestigationQueue, Investigation

        q = InvestigationQueue(tmp_path / "queue.db")
        ws = tmp_path / "workspace"
        (ws / ".swarm").mkdir(parents=True)
        (ws / ".swarm" / "experiments.tsv").write_text(
            "timestamp\ttask_id\tbranch\tmetric_name\tmetric_value\tstatus\tdescription\n"
            "2026-01-01\tbd-1\tagent-1\tacc\t0.92\tkeep\tk-NN baseline\n"
            "2026-01-01\tbd-2\tagent-1\tacc\t0.45\tdiscard\tlogistic broken\n"
        )
        inv_id = q.enqueue(Investigation(
            chat_id="c1", question="Test Q", slug="ask-test",
            codename="Melatonin", mode="discover",
        ))
        q.start(inv_id, str(ws))

        with patch("voronoi.gateway.handlers_query._get_queue", return_value=q):
            result = handle_ask(str(tmp_path), "What have the experiments found?")

        assert "Melatonin" in result
        assert "2 experiments" in result
        assert "passed" in result or "✓" in result

    def test_ask_about_hypotheses(self, tmp_path):
        """Ask about hypotheses with belief-map.json."""
        from voronoi.server.queue import InvestigationQueue, Investigation

        q = InvestigationQueue(tmp_path / "queue.db")
        ws = tmp_path / "workspace"
        (ws / ".swarm").mkdir(parents=True)
        (ws / ".swarm" / "belief-map.json").write_text(json.dumps({
            "hypotheses": [
                {"name": "GABA encoding", "prior": 0.3, "posterior": 0.85, "status": "tested"},
                {"name": "Random baseline", "prior": 0.5, "posterior": 0.15, "status": "tested"},
            ]
        }))
        inv_id = q.enqueue(Investigation(
            chat_id="c1", question="Test Q", slug="ask-hyp",
            codename="Dopamine", mode="discover",
        ))
        q.start(inv_id, str(ws))

        with patch("voronoi.gateway.handlers_query._get_queue", return_value=q):
            result = handle_ask(str(tmp_path), "Which hypothesis is leading?")

        assert "Dopamine" in result
        assert "GABA" in result

    def test_ask_about_failures(self, tmp_path):
        """Ask about failures when experiments crashed."""
        from voronoi.server.queue import InvestigationQueue, Investigation

        q = InvestigationQueue(tmp_path / "queue.db")
        ws = tmp_path / "workspace"
        (ws / ".swarm").mkdir(parents=True)
        (ws / ".swarm" / "experiments.tsv").write_text(
            "timestamp\ttask_id\tbranch\tmetric_name\tmetric_value\tstatus\tdescription\n"
            "2026-01-01\tbd-1\tagent-1\tacc\t0.0\tcrash\tSVM experiment\n"
        )
        inv_id = q.enqueue(Investigation(
            chat_id="c1", question="Test Q", slug="ask-fail",
            codename="Cortisol", mode="discover",
        ))
        q.start(inv_id, str(ws))

        with patch("voronoi.gateway.handlers_query._get_queue", return_value=q):
            result = handle_ask(str(tmp_path), "Why did any experiments fail?")

        assert "Cortisol" in result
        assert "crash" in result.lower()

    def test_ask_about_criteria(self, tmp_path):
        """Ask about success criteria."""
        from voronoi.server.queue import InvestigationQueue, Investigation

        q = InvestigationQueue(tmp_path / "queue.db")
        ws = tmp_path / "workspace"
        (ws / ".swarm").mkdir(parents=True)
        (ws / ".swarm" / "success-criteria.json").write_text(json.dumps([
            {"id": "SC1", "description": "Find critical noise %", "met": True},
            {"id": "SC2", "description": "Determine universality", "met": False},
        ]))
        inv_id = q.enqueue(Investigation(
            chat_id="c1", question="Test Q", slug="ask-crit",
            codename="Serotonin", mode="discover",
        ))
        q.start(inv_id, str(ws))

        with patch("voronoi.gateway.handlers_query._get_queue", return_value=q):
            result = handle_ask(str(tmp_path), "How is the progress on success criteria?")

        assert "Serotonin" in result
        assert "1/2" in result

    def test_ask_via_router(self, tmp_path):
        """Router should route /voronoi ask to handle_ask."""
        router = CommandRouter(str(tmp_path))
        text, _ = router.route("ask", ["What", "results", "so", "far?"], "chat1")
        assert isinstance(text, str)


# ---------------------------------------------------------------------------
# Free-text intent detection
# ---------------------------------------------------------------------------

class TestFreeText:
    def test_greeting(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.handle_free_text("hello", "chat1", True)
        assert "Voronoi" in text

    def test_science_question(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.handle_free_text("Why is our model accuracy dropping?", "chat1", True)
        assert "discover" in text.lower()
        assert "is live" in text

    def test_explore_question(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.handle_free_text("Which database should we use — Postgres vs MySQL?", "chat1", True)
        assert "discover" in text.lower()
        assert "is live" in text


# ---------------------------------------------------------------------------
# Review / Continue / Claims
# ---------------------------------------------------------------------------

class TestReviewContinueClaims:
    def _setup_investigation(self, tmp_path):
        """Create a queue with a review-status investigation and a claim ledger."""
        from voronoi.server.queue import InvestigationQueue, Investigation
        from voronoi.science.claims import ClaimLedger, save_ledger, PROVENANCE_RUN_EVIDENCE

        q = InvestigationQueue(tmp_path / "queue.db")
        inv_id = q.enqueue(Investigation(
            chat_id="c1", question="Does L4 beat L1?",
            slug="l4-vs-l1", codename="Synapse", mode="discover",
        ))
        q.start(inv_id, str(tmp_path / "workspace"))
        q.review(inv_id)

        # Create claim ledger
        ledger = ClaimLedger()
        ledger.add_claim("L4 outperforms L1", PROVENANCE_RUN_EVIDENCE,
                         effect_summary="d=0.8", supporting_findings=["bd-17"])
        ledger.assert_claim("C1")
        ledger.add_claim("No effect for conversational text", PROVENANCE_RUN_EVIDENCE,
                         supporting_findings=["bd-19"])
        save_ledger(inv_id, ledger, base_dir=tmp_path)

        return q, inv_id

    def test_review_shows_claims(self, tmp_path):
        q, inv_id = self._setup_investigation(tmp_path)
        with patch("voronoi.gateway.handlers_mutate._get_queue", return_value=q):
            result = handle_review_investigation(str(tmp_path), "Synapse")
        assert "Synapse" in result
        assert "C1" in result
        assert "L4 outperforms" in result

    def test_review_not_found(self, tmp_path):
        q = MagicMock()
        q.get.return_value = None
        q.get_recent.return_value = []
        with patch("voronoi.gateway.handlers_mutate._get_queue", return_value=q):
            result = handle_review_investigation(str(tmp_path), "Nonexistent")
        assert "not found" in result

    def test_claims_shows_ledger(self, tmp_path):
        q, inv_id = self._setup_investigation(tmp_path)
        with patch("voronoi.gateway.handlers_query._get_queue", return_value=q):
            result = handle_claims(str(tmp_path), "Synapse")
        assert "C1" in result
        assert "C2" in result

    def test_continue_creates_new_run(self, tmp_path):
        q, inv_id = self._setup_investigation(tmp_path)
        with patch("voronoi.gateway.handlers_mutate._get_queue", return_value=q):
            result = handle_continue_investigation(str(tmp_path), "Synapse",
                                                    "Test multilingual")
        assert "Round 2" in result
        assert "queued" in result.lower()

    def test_continue_wrong_status(self, tmp_path):
        from voronoi.server.queue import InvestigationQueue, Investigation
        q = InvestigationQueue(tmp_path / "queue.db")
        inv_id = q.enqueue(Investigation(
            chat_id="c1", question="Q", slug="q", codename="Test", mode="discover",
        ))
        q.start(inv_id, str(tmp_path))
        # Still running, can't continue
        with patch("voronoi.gateway.handlers_mutate._get_queue", return_value=q):
            result = handle_continue_investigation(str(tmp_path), "Test")
        assert "running" in result.lower()

    def test_router_dispatches_review(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        with patch("voronoi.gateway.router.handle_review_investigation",
                    return_value="review result") as mock:
            text, _ = router.route("review", ["Synapse"], "c1")
        assert text == "review result"
        mock.assert_called_once_with(str(tmp_path), "Synapse")

    def test_router_dispatches_continue(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        with patch("voronoi.gateway.router.handle_continue_investigation",
                    return_value="continue result") as mock:
            text, _ = router.route("continue", ["Synapse", "more", "data", "please"], "c1")
        assert text == "continue result"
        mock.assert_called_once_with(str(tmp_path), "Synapse", "more data please")

    def test_router_dispatches_claims(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        with patch("voronoi.gateway.router.handle_claims",
                    return_value="claims result") as mock:
            text, _ = router.route("claims", ["Synapse"], "c1")
        assert text == "claims result"
        mock.assert_called_once_with(str(tmp_path), "Synapse")


# ---------------------------------------------------------------------------
# Complete investigation (accept from review)
# ---------------------------------------------------------------------------

class TestCompleteInvestigation:
    def _setup_reviewed(self, tmp_path):
        from voronoi.server.queue import InvestigationQueue, Investigation
        q = InvestigationQueue(tmp_path / "queue.db")
        inv_id = q.enqueue(Investigation(
            chat_id="c1", question="Does L4 beat L1?",
            slug="l4", codename="Serotonin", mode="discover",
        ))
        q.start(inv_id, str(tmp_path / "workspace"))
        q.review(inv_id)
        return q, inv_id

    def test_accept_from_review(self, tmp_path):
        q, inv_id = self._setup_reviewed(tmp_path)
        with patch("voronoi.gateway.handlers_mutate._get_queue", return_value=q):
            result = handle_complete_investigation(str(tmp_path), "Serotonin")
        assert "accepted" in result
        assert "closed" in result
        inv = q.get(inv_id)
        assert inv.status == "complete"

    def test_already_complete(self, tmp_path):
        from voronoi.server.queue import InvestigationQueue, Investigation
        q = InvestigationQueue(tmp_path / "queue.db")
        inv_id = q.enqueue(Investigation(
            chat_id="c1", question="Q", slug="q", codename="Alpha", mode="discover",
        ))
        q.start(inv_id, str(tmp_path / "ws"))
        q.complete(inv_id)
        with patch("voronoi.gateway.handlers_mutate._get_queue", return_value=q):
            result = handle_complete_investigation(str(tmp_path), "Alpha")
        assert "already complete" in result

    def test_wrong_status(self, tmp_path):
        from voronoi.server.queue import InvestigationQueue, Investigation
        q = InvestigationQueue(tmp_path / "queue.db")
        inv_id = q.enqueue(Investigation(
            chat_id="c1", question="Q", slug="q", codename="Beta", mode="discover",
        ))
        q.start(inv_id, str(tmp_path / "ws"))
        with patch("voronoi.gateway.handlers_mutate._get_queue", return_value=q):
            result = handle_complete_investigation(str(tmp_path), "Beta")
        assert "running" in result

    def test_not_found(self, tmp_path):
        from voronoi.server.queue import InvestigationQueue
        q = InvestigationQueue(tmp_path / "queue.db")
        with patch("voronoi.gateway.handlers_mutate._get_queue", return_value=q):
            result = handle_complete_investigation(str(tmp_path), "Ghost")
        assert "not found" in result

    def test_router_dispatches_complete_investigation(self, tmp_path):
        """complete with a codename routes to handle_complete_investigation."""
        router = CommandRouter(str(tmp_path))
        with patch("voronoi.gateway.router.handle_complete_investigation",
                    return_value="accepted") as mock:
            text, _ = router.route("complete", ["Serotonin"], "c1")
        assert text == "accepted"
        mock.assert_called_once_with(str(tmp_path), "Serotonin")

    def test_router_dispatches_complete_task(self, tmp_path):
        """complete with a bd- id routes to handle_complete (task close)."""
        router = CommandRouter(str(tmp_path))
        with patch("voronoi.gateway.router.handle_complete",
                    return_value="closed") as mock:
            text, _ = router.route("complete", ["bd-42", "Done"], "c1")
        assert text == "closed"
        mock.assert_called_once_with(str(tmp_path), "bd-42", "Done")
