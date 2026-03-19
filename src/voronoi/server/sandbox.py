"""Sandbox Manager — Docker-based execution isolation for investigations.

One container per investigation, workspace mounted read-write.
Orchestrator stays on host; agent code execution goes through Docker.
Graceful fallback to host when Docker is unavailable.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class SandboxConfig:
    """Configuration for sandbox containers."""
    enabled: bool = True
    image: str = "voronoi-python:latest"
    cpus: int = 4
    memory: str = "8g"
    timeout_hours: int = 48
    network: bool = True
    fallback_to_host: bool = True


@dataclass
class SandboxInfo:
    """Running sandbox container info."""
    container_id: str
    container_name: str
    workspace_path: str
    status: str = "running"


class SandboxManager:
    """Manages Docker sandboxes for investigation code execution."""

    def __init__(self, config: Optional[SandboxConfig] = None):
        self.config = config or SandboxConfig()
        self._docker_available: Optional[bool] = None

    def is_docker_available(self) -> bool:
        """Check if Docker daemon is running."""
        if self._docker_available is not None:
            return self._docker_available
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True, text=True, timeout=10,
            )
            self._docker_available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._docker_available = False
        return self._docker_available

    def start(self, investigation_id: int, workspace_path: str) -> Optional[SandboxInfo]:
        """Start a sandbox container for an investigation.

        Returns SandboxInfo if started, None if Docker unavailable and fallback enabled.
        Raises RuntimeError if Docker unavailable and fallback disabled.
        """
        if not self.config.enabled:
            return None

        if not self.is_docker_available():
            if self.config.fallback_to_host:
                return None
            raise RuntimeError("Docker is not available and fallback_to_host is disabled")

        container_name = f"voronoi-inv-{investigation_id}"

        # Stop existing container with same name (cleanup)
        self._stop_container(container_name)

        # Build docker run command
        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--cpus", str(self.config.cpus),
            "--memory", self.config.memory,
            "--mount", f"type=bind,src={workspace_path},dst=/workspace",
            "--workdir", "/workspace",
        ]

        if not self.config.network:
            cmd.extend(["--network", "none"])

        cmd.extend([self.config.image, "sleep", "infinity"])

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                if self.config.fallback_to_host:
                    return None
                raise RuntimeError(f"Failed to start sandbox: {result.stderr}")

            container_id = result.stdout.strip()[:12]

            # Write sandbox ID to workspace
            sandbox_file = Path(workspace_path) / ".sandbox-id"
            sandbox_file.write_text(container_id)

            return SandboxInfo(
                container_id=container_id,
                container_name=container_name,
                workspace_path=workspace_path,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            if self.config.fallback_to_host:
                return None
            raise

    def exec(self, container_name: str, command: list[str], timeout: int = 120) -> tuple[int, str]:
        """Execute a command in a sandbox container.

        Returns (exit_code, output).
        """
        try:
            result = subprocess.run(
                ["docker", "exec", "-w", "/workspace", container_name] + command,
                capture_output=True, text=True, timeout=timeout,
            )
            return result.returncode, (result.stdout + result.stderr).strip()
        except subprocess.TimeoutExpired:
            return 1, f"Command timed out after {timeout}s"
        except FileNotFoundError:
            return 1, "Docker not found"

    def stop(self, investigation_id: int) -> bool:
        """Stop and remove a sandbox container."""
        container_name = f"voronoi-inv-{investigation_id}"
        return self._stop_container(container_name)

    def is_running(self, investigation_id: int) -> bool:
        """Check if a sandbox container is running."""
        container_name = f"voronoi-inv-{investigation_id}"
        try:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Running}}", container_name],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0 and "true" in result.stdout.lower()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _stop_container(self, container_name: str) -> bool:
        """Stop and remove a container by name."""
        try:
            subprocess.run(
                ["docker", "stop", container_name],
                capture_output=True, timeout=30,
            )
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True, timeout=15,
            )
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False


def exec_in_sandbox_or_host(
    workspace_path: str, command: list[str], timeout: int = 120,
) -> tuple[int, str]:
    """Execute a command in sandbox if available, otherwise on host.

    Reads .sandbox-id from workspace to determine container.
    """
    sandbox_file = Path(workspace_path) / ".sandbox-id"
    if sandbox_file.exists():
        container_id = sandbox_file.read_text().strip()
        if container_id:
            try:
                result = subprocess.run(
                    ["docker", "exec", "-w", "/workspace", container_id] + command,
                    capture_output=True, text=True, timeout=timeout,
                )
                return result.returncode, (result.stdout + result.stderr).strip()
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass  # Fall through to host execution

    # Host fallback
    try:
        result = subprocess.run(
            command, capture_output=True, text=True,
            timeout=timeout, cwd=workspace_path,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return 1, f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return 1, f"Command not found: {command[0]}"
