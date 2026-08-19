"""Tests for voronoi.server.workspace — Workspace Manager."""

from contextlib import contextmanager
import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from voronoi.server.repo_url import RepoRef
from voronoi.server.workspace import (
    PENDING_CLEANUP_FILE,
    WorkspaceManager,
    WorkspaceInfo,
    read_pending_cleanup,
    record_pending_cleanup,
    remove_tree_with_retry,
    sweep_pending_cleanup,
)


@pytest.fixture
def wm(tmp_path):
    return WorkspaceManager(tmp_path / "voronoi")


class TestProvisionLab:
    """Tests for lab workspace provisioning.

    _voronoi_init is mocked to prevent swarm-init.sh from creating
    orphaned tmux sessions.  The tests verify workspace structure
    (git, PROMPT.md, directories) which is all set up before init runs.
    """

    @pytest.fixture(autouse=True)
    def _skip_voronoi_init(self):
        with patch.object(WorkspaceManager, "_voronoi_init"):
            yield

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

    @patch.object(WorkspaceManager, "_voronoi_init")
    def test_uses_workspace_lock(self, mock_init, wm):
        entered: list[str] = []

        @contextmanager
        def fake_lock(name, timeout=120.0, poll_interval=0.1):
            entered.append(name)
            yield

        with patch.object(wm, "_exclusive_lock", side_effect=fake_lock):
            wm.provision_lab(1, "test", "question")

        assert len(entered) == 1
        assert entered[0].startswith("workspace-")


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

    @patch.object(WorkspaceManager, "_run_git")
    @patch.object(WorkspaceManager, "_voronoi_init")
    def test_uses_repo_and_workspace_locks(self, mock_init, mock_git, wm):
        entered: list[str] = []

        @contextmanager
        def fake_lock(name, timeout=120.0, poll_interval=0.1):
            entered.append(name)
            yield

        mock_git.return_value = subprocess.CompletedProcess([], 0)
        repo = RepoRef(owner="acme", name="api")

        with patch.object(wm, "_exclusive_lock", side_effect=fake_lock):
            wm.provision_repo(1, repo, "test")

        assert len(entered) == 2
        assert entered[0].startswith("repo-")
        assert entered[1].startswith("workspace-")


class TestWorkspaceManagement:
    """Tests for workspace listing, cleanup, and path resolution.

    These tests only exercise directory management — _voronoi_init
    (which runs swarm-init.sh → creates tmux sessions) is mocked to
    prevent orphaned tmux sessions from accumulating.
    """

    @pytest.fixture(autouse=True)
    def _skip_voronoi_init(self):
        with patch.object(WorkspaceManager, "_voronoi_init"):
            yield

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

    def test_cleanup_path_rejects_outside_active_dir(self, wm, tmp_path):
        outside = tmp_path / "outside-workspace"
        outside.mkdir()
        diagnostics: list[str] = []

        assert wm.cleanup_path(outside, diagnostics=diagnostics) is False

        assert outside.exists()
        assert any("Refusing cleanup" in message for message in diagnostics)

    def test_cleanup_path_rejects_nested_inv_path(self, wm):
        nested = wm.active_dir / "some-parent" / "inv-1-nested"
        nested.mkdir(parents=True)
        diagnostics: list[str] = []

        assert wm.cleanup_path(nested, diagnostics=diagnostics) is False

        assert nested.exists()
        assert any("Refusing cleanup" in message for message in diagnostics)

    def test_cleanup_path_rejects_direct_swarm_target(self, wm):
        swarm = wm.active_dir / "inv-1-test-swarm"
        swarm.mkdir(parents=True)
        diagnostics: list[str] = []

        assert wm.cleanup_path(swarm, diagnostics=diagnostics) is False

        assert swarm.exists()
        assert any("Refusing cleanup" in message for message in diagnostics)

    def test_cleanup_removes_swarm_without_workspace(self, wm):
        swarm = wm.active_dir / "inv-1-test-swarm"
        (swarm / "agent-worker").mkdir(parents=True)

        assert wm.cleanup(1, "test") is True
        assert not swarm.exists()

    def test_cleanup_reports_live_lock_holders(self, wm):
        workspace = wm.active_dir / "inv-1-test"
        swarm = wm.active_dir / "inv-1-test-swarm"
        workspace.mkdir(parents=True)
        swarm.mkdir()
        diagnostics: list[str] = []

        def fake_rmtree(path, *args, **kwargs):
            if ".locks" in Path(path).parts:
                return None
            raise OSError("busy")

        with patch("voronoi.server.workspace.shutil.rmtree", side_effect=fake_rmtree), \
             patch("voronoi.server.workspace.time.sleep"), \
             patch("voronoi.server.workspace.describe_live_file_holders", return_value=["123 (bd)"]):
            assert wm.cleanup(1, "test", diagnostics=diagnostics) is False

        assert any("123 (bd)" in message for message in diagnostics)

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


class TestDeferredCleanup:
    """Retrying removal and the deferred-cleanup queue consumed by prune."""

    def test_retry_succeeds_after_transient_failure(self, tmp_path):
        """NFS silly-rename files make the first rmtree fail; the retry wins."""
        target = tmp_path / "swarm"
        target.mkdir()
        real_rmtree = shutil.rmtree
        calls: list[int] = []

        def flaky(path, *args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise OSError("directory not empty")
            real_rmtree(path, *args, **kwargs)

        with patch("voronoi.server.workspace.shutil.rmtree", side_effect=flaky), \
             patch("voronoi.server.workspace.time.sleep"):
            assert remove_tree_with_retry(target) is True

        assert len(calls) == 2
        assert not target.exists()

    def test_retry_gives_up_and_reports_failure(self, tmp_path):
        target = tmp_path / "swarm"
        target.mkdir()

        with patch("voronoi.server.workspace.shutil.rmtree", side_effect=OSError("busy")), \
             patch("voronoi.server.workspace.time.sleep"):
            assert remove_tree_with_retry(target) is False

        assert target.exists()

    def test_record_then_sweep_removes_and_clears_registry(self, tmp_path):
        base = tmp_path / "base"
        blocked = base / "active" / "inv-1-test-swarm"
        blocked.mkdir(parents=True)

        record_pending_cleanup(base, blocked)
        assert read_pending_cleanup(base) == [str(blocked)]

        removed, still_blocked = sweep_pending_cleanup(base)

        assert removed == [str(blocked)]
        assert still_blocked == []
        assert not blocked.exists()
        assert not (base / PENDING_CLEANUP_FILE).exists()

    def test_sweep_keeps_blocked_entries_queued(self, tmp_path):
        base = tmp_path / "base"
        blocked = base / "active" / "inv-1-test-swarm"
        blocked.mkdir(parents=True)
        record_pending_cleanup(base, blocked)

        with patch("voronoi.server.workspace.shutil.rmtree", side_effect=OSError("busy")), \
             patch("voronoi.server.workspace.time.sleep"):
            removed, still_blocked = sweep_pending_cleanup(base)

        assert removed == []
        assert still_blocked == [str(blocked)]
        assert read_pending_cleanup(base) == [str(blocked)]

    def test_record_refuses_paths_outside_active_root(self, tmp_path):
        base = tmp_path / "base"
        base.mkdir()
        outside = tmp_path / "elsewhere"
        outside.mkdir()

        record_pending_cleanup(base, outside)

        assert read_pending_cleanup(base) == []
        assert outside.exists()

    def test_sweep_drops_tampered_entries_outside_active_root(self, tmp_path):
        """A doctored registry must not turn prune into arbitrary deletion."""
        base = tmp_path / "base"
        base.mkdir()
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        (base / PENDING_CLEANUP_FILE).write_text(json.dumps([str(outside)]))

        removed, still_blocked = sweep_pending_cleanup(base)

        assert removed == []
        assert still_blocked == []
        assert outside.exists()


class TestEnsureBeads:
    """Tests for _ensure_beads — server-mode initialization."""

    def test_ensure_beads_passes_server_flag(self, tmp_path):
        wm = WorkspaceManager(tmp_path / "voronoi")
        ws = tmp_path / "workspace"
        ws.mkdir()

        def fake_run(*args, **kwargs):
            (ws / ".beads").mkdir()
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("shutil.which", return_value="/usr/local/bin/bd"), \
             patch("subprocess.run") as mock_run:
            mock_run.side_effect = fake_run
            wm._ensure_beads(ws)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "--server" in cmd
        assert "--quiet" in cmd

    def test_ensure_beads_requires_server_mode_success(self, tmp_path):
        wm = WorkspaceManager(tmp_path / "voronoi")
        ws = tmp_path / "workspace"
        ws.mkdir()

        with patch("shutil.which", return_value="/usr/local/bin/bd"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="unknown flag: --server",
            )
            with pytest.raises(RuntimeError, match="bd init --server"):
                wm._ensure_beads(ws)

    def test_ensure_beads_requires_bd_cli(self, tmp_path):
        wm = WorkspaceManager(tmp_path / "voronoi")
        ws = tmp_path / "workspace"
        ws.mkdir()

        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="Beads CLI"):
                wm._ensure_beads(ws)

    def test_ensure_beads_skips_when_dir_exists(self, tmp_path):
        wm = WorkspaceManager(tmp_path / "voronoi")
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / ".beads").mkdir()

        with patch("subprocess.run") as mock_run:
            wm._ensure_beads(ws)

        mock_run.assert_not_called()


class TestFrameworkFilesReachWorkers:
    """Regression: spawn-agent.sh branches worker worktrees off the default
    branch, and a worktree materializes committed tree state only.  If the
    framework payload stays untracked, every worker starts without skills,
    role definitions, scripts/ or CLAUDE.md.
    """

    @pytest.fixture
    def workspace(self, wm):
        with patch.object(WorkspaceManager, "_voronoi_init"):
            info = wm.provision_lab(1, "skills", "question")
        return Path(info.path)

    def test_worktree_contains_framework(self, wm, workspace, tmp_path, monkeypatch):
        real_run = subprocess.run

        def without_voronoi_cli(cmd, *args, **kwargs):
            if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "voronoi":
                raise FileNotFoundError("voronoi")
            return real_run(cmd, *args, **kwargs)

        monkeypatch.setattr("voronoi.server.workspace.subprocess.run", without_voronoi_cli)

        with patch.object(WorkspaceManager, "_ensure_beads"):
            wm._voronoi_init(workspace)

        worktree = tmp_path / "swarm" / "agent-scout"
        result = real_run(
            ["git", "worktree", "add", str(worktree), "-b", "agent-scout", "main"],
            cwd=str(workspace), capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert (worktree / ".github" / "skills" / "investigation-protocol" / "SKILL.md").is_file()
        assert (worktree / ".github" / "agents").is_dir()
        assert (worktree / ".github" / "hooks").is_dir()
        assert (worktree / "scripts" / "spawn-agent.sh").is_file()
        assert (worktree / "CLAUDE.md").is_file()

    def test_ensure_github_files_restores_missing_subdir(self, wm, workspace):
        wm._ensure_github_files(workspace)
        skills = workspace / ".github" / "skills"
        assert skills.is_dir()

        # agents/ survives but skills/ is gone — the repair must not be gated
        # on agents/ being absent.
        shutil.rmtree(skills)
        wm._ensure_github_files(workspace)

        assert (skills / "investigation-protocol" / "SKILL.md").is_file()
        assert (workspace / ".github" / "agents").is_dir()
