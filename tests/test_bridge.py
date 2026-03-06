"""Tests for the upgraded telegram-bridge.py handlers.

These tests import the handler functions directly from the bridge script
and verify them with mocked bd/subprocess.
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add scripts dir and src dir to path so we can import the bridge module
_scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
_src_dir = Path(__file__).resolve().parent.parent / "src"

sys.path.insert(0, str(_scripts_dir))
sys.path.insert(0, str(_src_dir))

# We need to set INBOX_DIR before importing bridge handlers
import importlib


@pytest.fixture(autouse=True)
def setup_bridge(tmp_path, monkeypatch):
    """Set up the bridge module with a temporary project directory."""
    # Import as a module from scripts/
    spec = importlib.util.spec_from_file_location(
        "telegram_bridge",
        str(_scripts_dir / "telegram-bridge.py"),
    )
    mod = importlib.util.module_from_spec(spec)

    # Set INBOX_DIR before loading
    monkeypatch.setattr("builtins.__import__", __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__)

    spec.loader.exec_module(mod)
    mod.INBOX_DIR = tmp_path / ".swarm" / "inbox"

    # Reset singletons
    mod._MEMORY_INSTANCE = None
    mod._KNOWLEDGE_INSTANCE = None

    return mod, tmp_path


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

class TestConfig:
    def test_load_config_defaults(self, setup_bridge):
        mod, tmp_path = setup_bridge
        config = mod.load_config(str(tmp_path / "nonexistent.json"))
        assert config["bridge_enabled"] is True
        assert config["user_allowlist"] == []

    def test_load_config_with_user_allowlist(self, setup_bridge, tmp_path, monkeypatch):
        mod, _ = setup_bridge
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
        config = mod.load_config(str(config_path))
        assert "112423044" in config["user_allowlist"]
        assert "vahidrostami" in config["user_allowlist"]


# ---------------------------------------------------------------------------
# Existing handlers still work (regression tests)
# ---------------------------------------------------------------------------

class TestExistingHandlers:
    @patch("subprocess.run")
    def test_handle_status(self, mock_run, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=json.dumps([{"id": "1"}]), stderr=""),
            MagicMock(returncode=0, stdout=json.dumps([{"id": "1"}, {"id": "2"}]), stderr=""),
        ]
        result = mod.handle_status(config)
        assert "Ready: 1" in result
        assert "Open: 2" in result

    @patch("subprocess.run")
    def test_handle_tasks(self, mock_run, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}

        tasks = [
            {"id": "bd-1", "title": "Task 1", "priority": 1, "status": "open"},
            {"id": "bd-2", "title": "Task 2", "priority": 2, "status": "open"},
        ]
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(tasks), stderr="")
        result = mod.handle_tasks(config)
        assert "Task 1" in result
        assert "Task 2" in result

    @patch("subprocess.run")
    def test_handle_ready(self, mock_run, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}

        tasks = [{"id": "bd-1", "title": "Ready task", "priority": 1}]
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(tasks), stderr="")
        result = mod.handle_ready(config)
        assert "Ready task" in result

    def test_handle_guide(self, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}
        (tmp_path / ".swarm").mkdir(parents=True)

        result = mod.handle_guide(config, "focus on H1")
        assert "Guidance noted" in result
        assert (tmp_path / ".swarm" / "operator-guidance.md").exists()

    def test_handle_pivot(self, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}
        (tmp_path / ".swarm").mkdir(parents=True)

        result = mod.handle_pivot(config, "new direction")
        assert "Pivot recorded" in result

    def test_handle_abort(self, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}

        result = mod.handle_abort(config)
        assert "Abort requested" in result
        # Should write inbox command
        inbox_files = list((tmp_path / ".swarm" / "inbox").glob("*.json"))
        assert len(inbox_files) == 1


# ---------------------------------------------------------------------------
# NEW: Science workflow handlers
# ---------------------------------------------------------------------------

class TestScienceHandlers:
    def test_handle_investigate(self, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}

        result = mod.handle_investigate(config, "Why is latency high?")
        assert "INVESTIGATE" in result
        assert "Workflow ID" in result
        # Inbox command written
        inbox_files = list((tmp_path / ".swarm" / "inbox").glob("*.json"))
        assert len(inbox_files) == 1
        cmd = json.loads(inbox_files[0].read_text())
        assert cmd["action"] == "investigate"
        assert cmd["params"]["rigor"] == "scientific"

    def test_handle_explore(self, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}

        result = mod.handle_explore(config, "Redis vs Memcached")
        assert "EXPLORE" in result
        inbox_files = list((tmp_path / ".swarm" / "inbox").glob("*.json"))
        cmd = json.loads(inbox_files[0].read_text())
        assert cmd["action"] == "explore"

    def test_handle_build(self, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}

        result = mod.handle_build(config, "Build REST API")
        assert "BUILD" in result
        inbox_files = list((tmp_path / ".swarm" / "inbox").glob("*.json"))
        cmd = json.loads(inbox_files[0].read_text())
        assert cmd["action"] == "build"

    def test_handle_experiment(self, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}

        result = mod.handle_experiment(config, "test batch size effect")
        assert "EXPERIMENT" in result or "INVESTIGATE" in result
        inbox_files = list((tmp_path / ".swarm" / "inbox").glob("*.json"))
        cmd = json.loads(inbox_files[0].read_text())
        assert cmd["params"]["rigor"] == "experimental"


# ---------------------------------------------------------------------------
# NEW: Knowledge handlers
# ---------------------------------------------------------------------------

class TestKnowledgeHandlers:
    def test_handle_belief_no_file(self, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}

        result = mod.handle_belief(config)
        assert "No belief map" in result

    def test_handle_belief_with_file(self, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}

        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "belief-map.md").write_text("H1: P=0.7")

        result = mod.handle_belief(config)
        assert "H1" in result

    def test_handle_journal_no_file(self, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}

        result = mod.handle_journal(config)
        assert "No journal" in result

    def test_handle_journal_with_file(self, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}

        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "journal.md").write_text("## Round 1\nFound something interesting")

        result = mod.handle_journal(config)
        assert "Found something" in result

    @patch("subprocess.run")
    def test_handle_finding(self, mock_run, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}

        task = {"id": "bd-42", "title": "FINDING: Cache works", "status": "closed",
                "priority": 1, "notes": "EFFECT_SIZE:d=1.5"}
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(task), stderr="")

        result = mod.handle_finding(config, "bd-42")
        assert "bd-42" in result
        assert "Cache works" in result

    @patch("subprocess.run")
    def test_handle_finding_not_found(self, mock_run, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}

        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
        result = mod.handle_finding(config, "bd-999")
        assert "not found" in result


# ---------------------------------------------------------------------------
# NEW: Free-text science intent detection
# ---------------------------------------------------------------------------

class TestFreeTextScience:
    def test_science_question_detected(self, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}

        result = mod.handle_free_text_science(config, "Why is our model accuracy dropping?", "chat1")
        assert result is not None
        assert "INVESTIGATE" in result

    def test_non_science_returns_none(self, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}

        result = mod.handle_free_text_science(config, "hello how are you", "chat1")
        assert result is None

    def test_explore_question_detected(self, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}

        result = mod.handle_free_text_science(
            config, "Which database should we use — Postgres vs MySQL?", "chat1"
        )
        assert result is not None
        assert "EXPLORE" in result

    def test_recall_question_detected(self, setup_bridge):
        mod, tmp_path = setup_bridge
        config = {"project_dir": str(tmp_path)}

        result = mod.handle_free_text_science(
            config, "What did we learn about caching?", "chat1"
        )
        assert result is not None
        # Should trigger recall, not investigate


# ---------------------------------------------------------------------------
# Inbox command writing
# ---------------------------------------------------------------------------

class TestInboxCommands:
    def test_write_inbox_command(self, setup_bridge):
        mod, tmp_path = setup_bridge

        cmd_id = mod.write_inbox_command("test_action", {"key": "value"}, "test message")
        assert cmd_id  # non-empty

        inbox_files = list((tmp_path / ".swarm" / "inbox").glob("*.json"))
        assert len(inbox_files) == 1

        cmd = json.loads(inbox_files[0].read_text())
        assert cmd["action"] == "test_action"
        assert cmd["params"]["key"] == "value"
        assert cmd["source"] == "telegram"
