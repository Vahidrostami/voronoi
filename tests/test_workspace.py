"""Tests for voronoi.server.workspace — Workspace Manager."""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from voronoi.server.repo_url import RepoRef
from voronoi.server.workspace import WorkspaceManager, WorkspaceInfo


@pytest.fixture
def wm(tmp_path):
    return WorkspaceManager(tmp_path / "voronoi")


class TestProvisionLab:
    def test_creates_workspace(self, wm):
        info = wm.provision_lab(1, "ewc-test", "Does EWC work?")
        assert Path(info.path).exists()
        assert info.workspace_type == "lab"
        assert info.investigation_id == 1

    def test_creates_prompt_md(self, wm):
        info = wm.provision_lab(1, "ewc-test", "Does EWC work?")
        prompt = Path(info.path) / "PROMPT.md"
        assert prompt.exists()
        assert "Does EWC work?" in prompt.read_text()

    def test_has_git_repo(self, wm):
        info = wm.provision_lab(1, "test", "question")
        assert (Path(info.path) / ".git").exists()

    def test_uses_main_as_default_branch(self, wm):
        info = wm.provision_lab(1, "branch-test", "question")
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=info.path,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "main"

    def test_overwrites_existing(self, wm):
        wm.provision_lab(1, "test", "question 1")
        info = wm.provision_lab(1, "test", "question 2")
        prompt = Path(info.path) / "PROMPT.md"
        assert "question 2" in prompt.read_text()


class TestProvisionRepo:
    @patch.object(WorkspaceManager, "_run_git")
    @patch.object(WorkspaceManager, "_voronoi_init")
    def test_creates_workspace(self, mock_init, mock_git, wm):
        mock_git.return_value = subprocess.CompletedProcess([], 0)
        repo = RepoRef(owner="acme", name="api")
        info = wm.provision_repo(1, repo, "acme-api-test")
        assert info.workspace_type == "repo"
        assert info.repo == "acme/api"

    @patch.object(WorkspaceManager, "_run_git")
    @patch.object(WorkspaceManager, "_voronoi_init")
    def test_uses_reference_clone(self, mock_init, mock_git, wm):
        mock_git.return_value = subprocess.CompletedProcess([], 0)
        repo = RepoRef(owner="acme", name="api")
        wm.provision_repo(1, repo, "test")

        # Check that --reference was used in clone command
        calls = mock_git.call_args_list
        clone_calls = [c for c in calls if "--reference" in str(c)]
        assert len(clone_calls) > 0


class TestWorkspaceManagement:
    def test_list_active_empty(self, wm):
        assert wm.list_active() == []

    def test_list_active_after_provision(self, wm):
        wm.provision_lab(1, "test", "q")
        active = wm.list_active()
        assert len(active) == 1
        assert "inv-1-test" in active[0]

    def test_cleanup(self, wm):
        wm.provision_lab(1, "test", "q")
        assert wm.cleanup(1, "test") is True
        assert wm.list_active() == []

    def test_cleanup_nonexistent(self, wm):
        assert wm.cleanup(999, "nope") is False

    def test_get_workspace_path(self, wm):
        wm.provision_lab(1, "test", "q")
        path = wm.get_workspace_path(1, "test")
        assert path is not None
        assert path.exists()

    def test_get_workspace_path_nonexistent(self, wm):
        assert wm.get_workspace_path(999, "nope") is None

    def test_multiple_investigations(self, wm):
        wm.provision_lab(1, "ewc", "EWC question")
        wm.provision_lab(2, "replay", "Replay question")
        active = wm.list_active()
        assert len(active) == 2
