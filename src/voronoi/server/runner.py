"""Queue Runner — polls the investigation queue and executes investigations.

This is the main server loop: provision workspace → start sandbox →
launch orchestrator → stream progress → publish results.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("voronoi.runner")

from voronoi.server.queue import Investigation, InvestigationQueue
from voronoi.server.repo_url import RepoRef, extract_repo_url, strip_repo_url
from voronoi.server.sandbox import SandboxConfig
from voronoi.server.workspace import WorkspaceManager


def make_slug(text: str, max_len: int = 40) -> str:
    """Create a filesystem-safe slug from text."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-")


class ServerConfig:
    """Server configuration loaded from ~/.voronoi/config.json."""

    def __init__(self, base_dir: Optional[str] = None):
        selected_base = base_dir if base_dir is not None else os.environ.get("VORONOI_BASE_DIR")
        self.base_dir = Path(selected_base).expanduser() if selected_base else Path.home() / ".voronoi"
        self.config_path = self.base_dir / "config.json"

        # Defaults
        self.max_concurrent = 2
        self.max_agents_per_investigation = 6
        self.agent_command = "copilot"
        self.agent_flags = "--allow-all"
        self.orchestrator_model = ""  # e.g. "claude-opus-4.6"
        self.worker_model = ""        # e.g. "claude-sonnet-4.6"
        self.workspace_retention_days = 30
        self.context_advisory_hours = 6
        self.context_warning_hours = 10
        self.context_critical_hours = 14
        self.compact_interval_hours = 6
        self.github_lab_org = "voronoi-lab"
        self.github_visibility = "private"
        self.github_auto_publish = True
        self.sandbox = SandboxConfig()

        self._load()

    def _load(self) -> None:
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text())
                self.max_concurrent = data.get("server", {}).get("max_concurrent", self.max_concurrent)
                self.max_agents_per_investigation = data.get("server", {}).get(
                    "max_agents_per_investigation", self.max_agents_per_investigation
                )
                self.agent_command = data.get("server", {}).get("agent_command", self.agent_command)
                self.agent_flags = data.get("server", {}).get("agent_flags", self.agent_flags)
                self.orchestrator_model = data.get("server", {}).get(
                    "orchestrator_model", self.orchestrator_model
                )
                self.worker_model = data.get("server", {}).get(
                    "worker_model", self.worker_model
                )
                self.workspace_retention_days = data.get("server", {}).get(
                    "workspace_retention_days", self.workspace_retention_days
                )
                srv = data.get("server", {})
                self.context_advisory_hours = srv.get(
                    "context_advisory_hours", self.context_advisory_hours
                )
                self.context_warning_hours = srv.get(
                    "context_warning_hours", self.context_warning_hours
                )
                self.context_critical_hours = srv.get(
                    "context_critical_hours", self.context_critical_hours
                )
                self.compact_interval_hours = srv.get(
                    "compact_interval_hours", self.compact_interval_hours
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

        # Environment variables override config file values
        self._apply_env_overrides()

    def _apply_env_overrides(self) -> None:
        """Apply VORONOI_* environment variable overrides."""
        env = os.environ.get

        if env("VORONOI_AGENT_COMMAND"):
            self.agent_command = env("VORONOI_AGENT_COMMAND")
        if env("VORONOI_AGENT_FLAGS"):
            self.agent_flags = env("VORONOI_AGENT_FLAGS")
        if env("VORONOI_ORCHESTRATOR_MODEL"):
            self.orchestrator_model = env("VORONOI_ORCHESTRATOR_MODEL")
        if env("VORONOI_WORKER_MODEL"):
            self.worker_model = env("VORONOI_WORKER_MODEL")
        for attr, var in [
            ("max_concurrent", "VORONOI_MAX_CONCURRENT"),
            ("max_agents_per_investigation", "VORONOI_MAX_AGENTS"),
            ("workspace_retention_days", "VORONOI_WORKSPACE_RETENTION_DAYS"),
            ("context_advisory_hours", "VORONOI_CONTEXT_ADVISORY_HOURS"),
            ("context_warning_hours", "VORONOI_CONTEXT_WARNING_HOURS"),
            ("context_critical_hours", "VORONOI_CONTEXT_CRITICAL_HOURS"),
            ("compact_interval_hours", "VORONOI_COMPACT_INTERVAL_HOURS"),
        ]:
            val = env(var)
            if val:
                try:
                    setattr(self, attr, int(val))
                except ValueError:
                    logger.warning("Invalid integer for %s: %r — using default", var, val)

        if env("VORONOI_GITHUB_LAB_ORG"):
            self.github_lab_org = env("VORONOI_GITHUB_LAB_ORG")
        if env("VORONOI_GITHUB_VISIBILITY"):
            self.github_visibility = env("VORONOI_GITHUB_VISIBILITY")
        if env("VORONOI_GITHUB_AUTO_PUBLISH") is not None:
            self.github_auto_publish = env("VORONOI_GITHUB_AUTO_PUBLISH").lower() in ("true", "1", "yes")

        if env("VORONOI_SANDBOX_ENABLED") is not None:
            self.sandbox.enabled = env("VORONOI_SANDBOX_ENABLED").lower() in ("true", "1", "yes")
        if env("VORONOI_SANDBOX_IMAGE"):
            self.sandbox.image = env("VORONOI_SANDBOX_IMAGE")
        for sb_attr, sb_var in [
            ("cpus", "VORONOI_SANDBOX_CPUS"),
            ("timeout_hours", "VORONOI_SANDBOX_TIMEOUT_HOURS"),
        ]:
            val = env(sb_var)
            if val:
                try:
                    setattr(self.sandbox, sb_attr, int(val))
                except ValueError:
                    pass
        if env("VORONOI_SANDBOX_MEMORY"):
            self.sandbox.memory = env("VORONOI_SANDBOX_MEMORY")
        if env("VORONOI_SANDBOX_NETWORK") is not None:
            self.sandbox.network = env("VORONOI_SANDBOX_NETWORK").lower() in ("true", "1", "yes")
        if env("VORONOI_SANDBOX_FALLBACK_TO_HOST") is not None:
            self.sandbox.fallback_to_host = env("VORONOI_SANDBOX_FALLBACK_TO_HOST").lower() in ("true", "1", "yes")

    def save(self) -> None:
        """Persist current config to disk."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "server": {
                "max_concurrent": self.max_concurrent,
                "max_agents_per_investigation": self.max_agents_per_investigation,
                "agent_command": self.agent_command,
                "agent_flags": self.agent_flags,
                "orchestrator_model": self.orchestrator_model,
                "worker_model": self.worker_model,
                "workspace_retention_days": self.workspace_retention_days,
                "context_advisory_hours": self.context_advisory_hours,
                "context_warning_hours": self.context_warning_hours,
                "context_critical_hours": self.context_critical_hours,
                "compact_interval_hours": self.compact_interval_hours,
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
    text: str, chat_id: str, mode: str = "discover", rigor: str = "adaptive",
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
