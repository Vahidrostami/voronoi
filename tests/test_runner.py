"""Tests for voronoi.server.runner — Queue Runner utilities."""

import pytest

from voronoi.server.runner import (
    ServerConfig,
    create_investigation_from_text,
    make_slug,
)
from voronoi.server.queue import Investigation


class TestMakeSlug:
    def test_simple(self):
        assert make_slug("Hello World") == "hello-world"

    def test_special_chars(self):
        assert make_slug("Why is accuracy dropping?") == "why-is-accuracy-dropping"

    def test_truncation(self):
        slug = make_slug("a" * 100, max_len=20)
        assert len(slug) <= 20

    def test_trailing_dash_stripped(self):
        slug = make_slug("test---", max_len=6)
        assert not slug.endswith("-")


class TestCreateInvestigationFromText:
    def test_repo_bound(self):
        inv = create_investigation_from_text(
            "Why is accuracy low in github.com/acme/ml-model?",
            chat_id="c1",
        )
        assert inv.investigation_type == "repo"
        assert inv.repo == "acme/ml-model"
        assert "accuracy" in inv.question.lower()
        assert inv.chat_id == "c1"

    def test_pure_science(self):
        inv = create_investigation_from_text(
            "Does EWC prevent catastrophic forgetting better than replay?",
            chat_id="c1",
        )
        assert inv.investigation_type == "lab"
        assert inv.repo is None
        assert "EWC" in inv.question

    def test_mode_and_rigor(self):
        inv = create_investigation_from_text(
            "test something",
            chat_id="c1",
            mode="explore",
            rigor="analytical",
        )
        assert inv.mode == "explore"
        assert inv.rigor == "analytical"

    def test_slug_is_safe(self):
        inv = create_investigation_from_text(
            "What's the optimal learning rate?!?!",
            chat_id="c1",
        )
        assert "/" not in inv.slug
        assert "!" not in inv.slug
        assert "'" not in inv.slug


class TestServerConfig:
    def test_defaults(self, tmp_path):
        config = ServerConfig(base_dir=str(tmp_path / "voronoi"))
        assert config.max_concurrent == 2
        assert config.max_agents_per_investigation == 4
        assert config.sandbox.enabled is True

    def test_save_and_load(self, tmp_path):
        base = tmp_path / "voronoi"
        config = ServerConfig(base_dir=str(base))
        config.max_concurrent = 5
        config.github_lab_org = "my-lab"
        config.save()

        # Reload
        config2 = ServerConfig(base_dir=str(base))
        assert config2.max_concurrent == 5
        assert config2.github_lab_org == "my-lab"

    def test_load_missing_file(self, tmp_path):
        config = ServerConfig(base_dir=str(tmp_path / "nonexistent"))
        assert config.max_concurrent == 2  # defaults

    def test_save_creates_dirs(self, tmp_path):
        base = tmp_path / "deep" / "nested" / "voronoi"
        config = ServerConfig(base_dir=str(base))
        config.save()
        assert config.config_path.exists()

    def test_model_defaults_empty(self, tmp_path):
        config = ServerConfig(base_dir=str(tmp_path / "voronoi"))
        assert config.orchestrator_model == ""
        assert config.worker_model == ""

    def test_model_save_and_load(self, tmp_path):
        base = tmp_path / "voronoi"
        config = ServerConfig(base_dir=str(base))
        config.orchestrator_model = "claude-opus-4.6"
        config.worker_model = "claude-sonnet-4.6"
        config.save()

        config2 = ServerConfig(base_dir=str(base))
        assert config2.orchestrator_model == "claude-opus-4.6"
        assert config2.worker_model == "claude-sonnet-4.6"

    def test_model_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VORONOI_ORCHESTRATOR_MODEL", "gpt-5.4")
        monkeypatch.setenv("VORONOI_WORKER_MODEL", "claude-haiku-4.5")
        config = ServerConfig(base_dir=str(tmp_path / "voronoi"))
        assert config.orchestrator_model == "gpt-5.4"
        assert config.worker_model == "claude-haiku-4.5"
