"""Queue Runner — polls the investigation queue and executes investigations.

This is the main server loop: provision workspace → start sandbox →
launch orchestrator → stream progress → publish results.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from voronoi.server.queue import Investigation, InvestigationQueue
from voronoi.server.repo_url import RepoRef, extract_repo_url, strip_repo_url
from voronoi.server.sandbox import SandboxConfig, SandboxManager
from voronoi.server.workspace import WorkspaceManager


def make_slug(text: str, max_len: int = 40) -> str:
    """Create a filesystem-safe slug from text."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-")


class ServerConfig:
    """Server configuration loaded from ~/.voronoi/config.json."""

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir or Path.home() / ".voronoi")
        self.config_path = self.base_dir / "config.json"

        # Defaults
        self.max_concurrent = 2
        self.max_agents_per_investigation = 4
        self.agent_command = "copilot"
        self.agent_flags = "--allow-all"
        self.workspace_retention_days = 30
        self.github_lab_org = "voronoi-lab"
        self.github_visibility = "private"
        self.github_auto_publish = True
        self.sandbox = SandboxConfig()

        self._load()

    def _load(self) -> None:
        if not self.config_path.exists():
            return
        try:
            data = json.loads(self.config_path.read_text())
            self.max_concurrent = data.get("server", {}).get("max_concurrent", self.max_concurrent)
            self.max_agents_per_investigation = data.get("server", {}).get(
                "max_agents_per_investigation", self.max_agents_per_investigation
            )
            self.agent_command = data.get("server", {}).get("agent_command", self.agent_command)
            self.agent_flags = data.get("server", {}).get("agent_flags", self.agent_flags)
            self.workspace_retention_days = data.get("server", {}).get(
                "workspace_retention_days", self.workspace_retention_days
            )
            gh = data.get("github", {})
            self.github_lab_org = gh.get("lab_org", self.github_lab_org)
            self.github_visibility = gh.get("default_visibility", self.github_visibility)
            self.github_auto_publish = gh.get("auto_publish", self.github_auto_publish)

            sb = data.get("sandbox", {})
            self.sandbox = SandboxConfig(
                enabled=sb.get("enabled", True),
                image=sb.get("image", "voronoi-python:latest"),
                cpus=sb.get("cpus", 4),
                memory=sb.get("memory", "8g"),
                timeout_hours=sb.get("timeout_hours", 12),
                network=sb.get("network", True),
                fallback_to_host=sb.get("fallback_to_host", True),
            )
        except (json.JSONDecodeError, KeyError):
            pass

    def save(self) -> None:
        """Persist current config to disk."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "server": {
                "max_concurrent": self.max_concurrent,
                "max_agents_per_investigation": self.max_agents_per_investigation,
                "agent_command": self.agent_command,
                "agent_flags": self.agent_flags,
                "workspace_retention_days": self.workspace_retention_days,
            },
            "github": {
                "lab_org": self.github_lab_org,
                "default_visibility": self.github_visibility,
                "auto_publish": self.github_auto_publish,
            },
            "sandbox": {
                "enabled": self.sandbox.enabled,
                "image": self.sandbox.image,
                "cpus": self.sandbox.cpus,
                "memory": self.sandbox.memory,
                "timeout_hours": self.sandbox.timeout_hours,
                "network": self.sandbox.network,
                "fallback_to_host": self.sandbox.fallback_to_host,
            },
        }
        self.config_path.write_text(json.dumps(data, indent=2))


def create_investigation_from_text(
    text: str, chat_id: str, mode: str = "investigate", rigor: str = "scientific",
) -> Investigation:
    """Parse user text into an Investigation, extracting repo URL if present."""
    repo_ref = extract_repo_url(text)
    question = strip_repo_url(text) if repo_ref else text

    if repo_ref:
        slug = make_slug(f"{repo_ref.name}-{question[:20]}")
        inv_type = "repo"
        repo_str = repo_ref.full_name
    else:
        slug = make_slug(question[:40])
        inv_type = "lab"
        repo_str = None

    return Investigation(
        chat_id=chat_id,
        investigation_type=inv_type,
        repo=repo_str,
        question=question,
        slug=slug,
        mode=mode,
        rigor=rigor,
    )
