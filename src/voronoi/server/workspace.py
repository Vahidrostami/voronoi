"""Workspace Manager — provision investigation workspaces.

Handles auto-cloning repos (with --reference for deduplication),
creating fresh lab workspaces for pure science, and voronoi init.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("voronoi.workspace")

from voronoi.server.repo_url import RepoRef


@dataclass
class WorkspaceInfo:
    """Metadata about a provisioned workspace."""
    investigation_id: int
    path: str                    # absolute path to workspace
    workspace_type: str          # "repo" | "lab"
    repo: Optional[str] = None  # owner/repo if repo-bound
    slug: str = ""               # filesystem-safe name
    created_at: float = field(default_factory=time.time)
    sandbox_id: Optional[str] = None  # Docker container ID


class WorkspaceManager:
    """Provisions and manages investigation workspaces.

    Layout:
        base_dir/
        ├── objects/           # bare git repos (shared object store)
        │   └── owner--repo.git
        ├── active/            # one directory per active investigation
        │   ├── inv-12-slug/   # workspace with voronoi init'd
        │   └── inv-12-slug-swarm/  # worktrees for agents
        └── config.json
    """

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.objects_dir = self.base_dir / "objects"
        self.active_dir = self.base_dir / "active"
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.active_dir.mkdir(parents=True, exist_ok=True)

    def provision_repo(
        self, investigation_id: int, repo: RepoRef, slug: str,
    ) -> WorkspaceInfo:
        """Provision a workspace for a repo-bound investigation.

        Uses git clone --reference to share objects across investigations
        on the same repo.
        """
        bare_path = self.objects_dir / f"{repo.slug}.git"
        workspace_path = self.active_dir / f"inv-{investigation_id}-{slug}"

        # 1. Ensure bare repo exists (shared object store)
        if not bare_path.exists():
            self._run_git(
                ["git", "clone", "--bare", repo.clone_url, str(bare_path)],
                cwd=str(self.base_dir),
            )
        else:
            # Update existing bare repo
            self._run_git(["git", "fetch", "--all"], cwd=str(bare_path))

        # 2. Clone with --reference for deduplication
        if workspace_path.exists():
            shutil.rmtree(workspace_path)

        self._run_git([
            "git", "clone",
            "--reference", str(bare_path),
            repo.clone_url,
            str(workspace_path),
        ], cwd=str(self.base_dir))

        # 3. Run voronoi init in the workspace
        self._voronoi_init(workspace_path)

        return WorkspaceInfo(
            investigation_id=investigation_id,
            path=str(workspace_path),
            workspace_type="repo",
            repo=repo.full_name,
            slug=slug,
        )

    def provision_lab(
        self, investigation_id: int, slug: str, question: str,
    ) -> WorkspaceInfo:
        """Provision a fresh workspace for pure science (no existing repo)."""
        workspace_path = self.active_dir / f"inv-{investigation_id}-{slug}"

        if workspace_path.exists():
            shutil.rmtree(workspace_path)

        workspace_path.mkdir(parents=True)

        # 1. git init + initial commit
        self._run_git(["git", "init"], cwd=str(workspace_path))
        self._run_git(
            ["git", "commit", "--allow-empty", "-m", "voronoi: lab workspace"],
            cwd=str(workspace_path),
        )

        # 2. Write the question as PROMPT.md
        prompt_path = workspace_path / "PROMPT.md"
        prompt_path.write_text(f"# Investigation\n\n{question}\n")
        self._run_git(["git", "add", "PROMPT.md"], cwd=str(workspace_path))
        self._run_git(
            ["git", "commit", "-m", "voronoi: investigation prompt"],
            cwd=str(workspace_path),
        )

        # 3. voronoi init
        self._voronoi_init(workspace_path)

        return WorkspaceInfo(
            investigation_id=investigation_id,
            path=str(workspace_path),
            workspace_type="lab",
            slug=slug,
        )

    def get_workspace_path(self, investigation_id: int, slug: str) -> Optional[Path]:
        """Check if a workspace exists and return its path."""
        workspace_path = self.active_dir / f"inv-{investigation_id}-{slug}"
        if workspace_path.exists():
            return workspace_path
        return None

    def cleanup(self, investigation_id: int, slug: str) -> bool:
        """Remove a workspace and its worktrees."""
        workspace_path = self.active_dir / f"inv-{investigation_id}-{slug}"
        swarm_path = self.active_dir / f"inv-{investigation_id}-{slug}-swarm"

        removed = False
        for p in [swarm_path, workspace_path]:
            if p.exists():
                shutil.rmtree(p)
                removed = True
        return removed

    def list_active(self) -> list[str]:
        """List active investigation directories (excludes -swarm worktree dirs)."""
        if not self.active_dir.exists():
            return []
        return [
            d.name for d in sorted(self.active_dir.iterdir())
            if d.is_dir() and d.name.startswith("inv-") and not d.name.endswith("-swarm")
        ]

    def _voronoi_init(self, workspace_path: Path) -> None:
        """Run voronoi init in a workspace, with fallback for .github/ files."""
        try:
            subprocess.run(
                ["voronoi", "init"],
                cwd=str(workspace_path),
                capture_output=True, text=True, timeout=60,
                input="Y\n",  # auto-confirm bd init prompt
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass  # voronoi CLI may not be on PATH in all environments

        # Ensure .github/agents, prompts, skills always exist — even if
        # voronoi init failed (e.g. CLI not on PATH).  These are critical
        # for the orchestrator and worker agents to use role definitions.
        self._ensure_github_files(workspace_path)

        # Ensure Beads is initialized in the workspace — required for task
        # tracking.  voronoi init delegates to swarm-init.sh which runs
        # `bd init`, but that may have been skipped if the CLI or script
        # wasn't available.  Run it explicitly as a safety net.
        self._ensure_beads(workspace_path)

    def _ensure_beads(self, workspace_path: Path) -> None:
        """Initialize Beads (bd) in a workspace if not already present."""
        beads_dir = workspace_path / ".beads"
        if beads_dir.is_dir():
            return
        if not shutil.which("bd"):
            return
        try:
            subprocess.run(
                ["bd", "init", "--quiet"],
                cwd=str(workspace_path),
                capture_output=True, text=True, timeout=30,
                input="Y\n",
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.debug("voronoi init failed in %s", workspace_path, exc_info=True)

    def _ensure_github_files(self, workspace_path: Path) -> None:
        """Copy .github/{agents,prompts,skills}, scripts/, and runtime CLAUDE.md if missing."""
        try:
            from voronoi.cli import find_data_dir, _resolve_github_src, _resolve_templates_dir

            data = find_data_dir()

            # Copy .github/ subdirectories if missing
            github_dst = workspace_path / ".github"
            if not (github_dst / "agents").is_dir():
                github_src = _resolve_github_src(data)
                github_dst.mkdir(exist_ok=True)
                for subdir in ("agents", "prompts", "skills"):
                    src = github_src / subdir
                    dst = github_dst / subdir
                    if src.is_dir() and not dst.is_dir():
                        shutil.copytree(src, dst)

            # Copy runtime scripts if missing
            scripts_dst = workspace_path / "scripts"
            if not scripts_dst.is_dir():
                scripts_src = data / "scripts"
                if scripts_src.is_dir():
                    shutil.copytree(scripts_src, scripts_dst)
                    # Make .sh files executable
                    for sh in scripts_dst.rglob("*.sh"):
                        sh.chmod(sh.stat().st_mode | 0o755)

            # Always ensure runtime CLAUDE.md + AGENTS.md exist
            templates = _resolve_templates_dir(data)
            for fname in ("CLAUDE.md", "AGENTS.md"):
                src = templates / fname
                dst = workspace_path / fname
                if src.is_file() and not dst.exists():
                    shutil.copy2(src, dst)
        except Exception:
            logger.debug("Failed to copy framework files to %s", workspace_path, exc_info=True)

    def _run_git(self, cmd: list[str], cwd: str) -> subprocess.CompletedProcess:
        """Run a git command."""
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=300, cwd=cwd
        )
