"""Tests for voronoi.gateway.config — configuration loading."""

import json
import os
from pathlib import Path

import pytest

from voronoi.gateway.config import (
    get_chat_id,
    load_config,
    load_dotenv,
    save_chat_id,
)


class TestLoadDotenv:
    def test_loads_env_vars(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_VAR_VORONOI=hello\n")
        monkeypatch.delenv("TEST_VAR_VORONOI", raising=False)
        load_dotenv(env_file)
        assert os.environ.get("TEST_VAR_VORONOI") == "hello"
        monkeypatch.delenv("TEST_VAR_VORONOI")

    def test_does_not_overwrite(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_VAR_VORONOI=new\n")
        monkeypatch.setenv("TEST_VAR_VORONOI", "existing")
        load_dotenv(env_file)
        assert os.environ.get("TEST_VAR_VORONOI") == "existing"

    def test_skips_comments(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\nTEST_VAR_VORONOI=value\n")
        monkeypatch.delenv("TEST_VAR_VORONOI", raising=False)
        load_dotenv(env_file)
        assert os.environ.get("TEST_VAR_VORONOI") == "value"
        monkeypatch.delenv("TEST_VAR_VORONOI")

    def test_strips_inline_comments(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_VAR_VORONOI=value  # comment\n")
        monkeypatch.delenv("TEST_VAR_VORONOI", raising=False)
        load_dotenv(env_file)
        assert os.environ.get("TEST_VAR_VORONOI") == "value"
        monkeypatch.delenv("TEST_VAR_VORONOI")

    def test_nonexistent_file(self):
        load_dotenv(Path("/nonexistent/.env"))  # Should not raise


class TestSaveChatId:
    def test_save_and_get(self, tmp_path):
        save_chat_id(str(tmp_path), "12345")
        assert get_chat_id(str(tmp_path)) == "12345"

    def test_get_nonexistent(self, tmp_path):
        assert get_chat_id(str(tmp_path)) is None

    def test_overwrites(self, tmp_path):
        save_chat_id(str(tmp_path), "111")
        save_chat_id(str(tmp_path), "222")
        assert get_chat_id(str(tmp_path)) == "222"


class TestLoadConfig:
    def test_defaults(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VORONOI_TG_BOT_TOKEN", raising=False)
        monkeypatch.delenv("VORONOI_AGENT_COMMAND", raising=False)
        monkeypatch.delenv("VORONOI_TG_USER_ALLOWLIST", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("VORONOI_ORCHESTRATOR_MODEL", raising=False)
        monkeypatch.delenv("VORONOI_WORKER_MODEL", raising=False)
        config = load_config(str(tmp_path / "nonexistent.json"))
        assert config["agent_command"] == "copilot"

    def test_env_override(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("VORONOI_TG_BOT_TOKEN", "test-token")
        config = load_config(str(tmp_path / "nonexistent.json"))
        assert config["bot_token"] == "test-token"

    def test_json_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VORONOI_TG_BOT_TOKEN", raising=False)
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "project_name": "my-project",
            "agent_command": "claude",
        }))
        config = load_config(str(config_file))
        assert config["project_name"] == "my-project"
