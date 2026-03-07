"""Tests for the refactored architecture.

Tests the gateway modules (config, router) which now own all business
logic.  The bridge script is a thin Telegram I/O layer that delegates
to these modules — it is not tested directly here.
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from voronoi.gateway.config import load_config, save_chat_id
from voronoi.gateway.router import (
    CommandRouter,
    handle_status,
    handle_tasks,
    handle_ready,
    handle_guide,
    handle_pivot,
    handle_abort,
    handle_investigate,
    handle_explore,
    handle_build,
    handle_experiment,
    handle_belief,
    handle_journal,
    handle_finding,
)


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


# ---------------------------------------------------------------------------
# Existing handlers (regression)
# ---------------------------------------------------------------------------

class TestHandlers:
    @patch("voronoi.gateway.router.subprocess.run")
    def test_handle_status(self, mock_run, tmp_path):
        # Create queue.db so _get_queue works
        swarm_dir = tmp_path / ".swarm"
        swarm_dir.mkdir(parents=True, exist_ok=True)
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=json.dumps([{"id": "1"}]), stderr=""),
            MagicMock(returncode=0, stdout=json.dumps([{"id": "1"}, {"id": "2"}]), stderr=""),
        ]
        result = handle_status(str(tmp_path))
        assert "Swarm Status" in result
        # With no running investigations, falls back to server-level beads
        assert "open" in result.lower() or "ready" in result.lower()

    @patch("voronoi.gateway.router.subprocess.run")
    def test_handle_tasks(self, mock_run, tmp_path):
        tasks = [
            {"id": "bd-1", "title": "Task 1", "priority": 1, "status": "open"},
            {"id": "bd-2", "title": "Task 2", "priority": 2, "status": "open"},
        ]
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(tasks), stderr="")
        result = handle_tasks(str(tmp_path))
        assert "Task 1" in result
        assert "Task 2" in result

    @patch("voronoi.gateway.router.subprocess.run")
    def test_handle_ready(self, mock_run, tmp_path):
        tasks = [{"id": "bd-1", "title": "Ready task", "priority": 1}]
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(tasks), stderr="")
        result = handle_ready(str(tmp_path))
        assert "Ready task" in result

    def test_handle_guide(self, tmp_path):
        (tmp_path / ".swarm").mkdir(parents=True)
        result = handle_guide(str(tmp_path), "focus on H1")
        assert "Guidance noted" in result
        assert (tmp_path / ".swarm" / "operator-guidance.md").exists()

    def test_handle_pivot(self, tmp_path):
        (tmp_path / ".swarm").mkdir(parents=True)
        result = handle_pivot(str(tmp_path), "new direction")
        assert "Pivot recorded" in result

    def test_handle_abort(self, tmp_path):
        result = handle_abort(str(tmp_path))
        assert "Abort requested" in result


# ---------------------------------------------------------------------------
# Science workflow handlers
# ---------------------------------------------------------------------------

class TestScienceHandlers:
    @patch("voronoi.gateway.router.InvestigationQueue", autospec=True)
    @patch("voronoi.gateway.router.make_slug", return_value="test-slug")
    def test_handle_investigate(self, mock_slug, mock_queue_cls, tmp_path):
        mock_q = MagicMock()
        mock_q.enqueue.return_value = 1
        mock_q.get_queued.return_value = []
        mock_q.get_running.return_value = []
        mock_queue_cls.return_value = mock_q

        result = handle_investigate(str(tmp_path), "Why is latency high?", "chat1")
        assert "Voronoi" in result
        assert "LAUNCHED" in result
        assert "investigation" in result

    @patch("voronoi.gateway.router.InvestigationQueue", autospec=True)
    @patch("voronoi.gateway.router.make_slug", return_value="test-slug")
    def test_handle_explore(self, mock_slug, mock_queue_cls, tmp_path):
        mock_q = MagicMock()
        mock_q.enqueue.return_value = 2
        mock_q.get_queued.return_value = []
        mock_q.get_running.return_value = []
        mock_queue_cls.return_value = mock_q

        result = handle_explore(str(tmp_path), "Redis vs Memcached", "chat1")
        assert "Voronoi" in result
        assert "exploration" in result

    @patch("voronoi.gateway.router.InvestigationQueue", autospec=True)
    @patch("voronoi.gateway.router.make_slug", return_value="test-slug")
    def test_handle_build(self, mock_slug, mock_queue_cls, tmp_path):
        mock_q = MagicMock()
        mock_q.enqueue.return_value = 3
        mock_q.get_queued.return_value = []
        mock_q.get_running.return_value = []
        mock_queue_cls.return_value = mock_q

        result = handle_build(str(tmp_path), "Build REST API", "chat1")
        assert "Voronoi" in result
        assert "build" in result

    @patch("voronoi.gateway.router.InvestigationQueue", autospec=True)
    @patch("voronoi.gateway.router.make_slug", return_value="test-slug")
    def test_handle_experiment(self, mock_slug, mock_queue_cls, tmp_path):
        mock_q = MagicMock()
        mock_q.enqueue.return_value = 4
        mock_q.get_queued.return_value = []
        mock_q.get_running.return_value = []
        mock_queue_cls.return_value = mock_q

        result = handle_experiment(str(tmp_path), "test batch size effect", "chat1")
        assert "Voronoi" in result
        assert "LAUNCHED" in result


# ---------------------------------------------------------------------------
# Knowledge handlers
# ---------------------------------------------------------------------------

class TestKnowledgeHandlers:
    def test_handle_belief_no_file(self, tmp_path):
        result = handle_belief(str(tmp_path))
        assert "No belief map" in result

    def test_handle_belief_with_file(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "belief-map.md").write_text("H1: P=0.7")
        result = handle_belief(str(tmp_path))
        assert "H1" in result

    def test_handle_journal_no_file(self, tmp_path):
        result = handle_journal(str(tmp_path))
        assert "No journal" in result

    def test_handle_journal_with_file(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "journal.md").write_text("## Round 1\nFound something interesting")
        result = handle_journal(str(tmp_path))
        assert "Found something" in result

    @patch("voronoi.gateway.router.subprocess.run")
    def test_handle_finding(self, mock_run, tmp_path):
        task = {"id": "bd-42", "title": "FINDING: Cache works", "status": "closed",
                "priority": 1, "notes": "EFFECT_SIZE:d=1.5"}
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(task), stderr="")
        result = handle_finding(str(tmp_path), "bd-42")
        assert "bd-42" in result
        assert "Cache works" in result

    @patch("voronoi.gateway.router.subprocess.run")
    def test_handle_finding_not_found(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
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

    @patch("voronoi.gateway.router.subprocess.run")
    def test_route_status(self, mock_run, tmp_path):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="[]", stderr=""),
            MagicMock(returncode=0, stdout="[]", stderr=""),
        ]
        router = CommandRouter(str(tmp_path))
        text, _ = router.route("status", [], "chat1")
        assert "Swarm Status" in text

    def test_route_unknown(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.route("xyzzy", [], "chat1")
        assert "Unknown command" in text


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
        assert "investigate" in text.lower()
        assert "Voronoi" in text

    def test_explore_question(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.handle_free_text("Which database should we use — Postgres vs MySQL?", "chat1", True)
        assert "explore" in text.lower()
        assert "Voronoi" in text
