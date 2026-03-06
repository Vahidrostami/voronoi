"""Tests for voronoi.server.sandbox — Sandbox Manager."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from voronoi.server.sandbox import (
    SandboxConfig,
    SandboxInfo,
    SandboxManager,
    exec_in_sandbox_or_host,
)


class TestSandboxConfig:
    def test_defaults(self):
        c = SandboxConfig()
        assert c.enabled is True
        assert c.cpus == 4
        assert c.memory == "8g"
        assert c.fallback_to_host is True

    def test_custom_config(self):
        c = SandboxConfig(enabled=False, cpus=2, memory="4g")
        assert c.enabled is False
        assert c.cpus == 2


class TestSandboxManager:
    def test_disabled_returns_none(self):
        sm = SandboxManager(SandboxConfig(enabled=False))
        result = sm.start(1, "/tmp/ws")
        assert result is None

    @patch("voronoi.server.sandbox.subprocess.run")
    def test_docker_unavailable_with_fallback(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        sm = SandboxManager(SandboxConfig(fallback_to_host=True))
        result = sm.start(1, "/tmp/ws")
        assert result is None

    @patch("voronoi.server.sandbox.subprocess.run")
    def test_docker_unavailable_no_fallback(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        sm = SandboxManager(SandboxConfig(fallback_to_host=False))
        with pytest.raises(RuntimeError):
            sm.start(1, "/tmp/ws")

    @patch("voronoi.server.sandbox.subprocess.run")
    def test_start_success(self, mock_run, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()

        def make_result(returncode=0, stdout="", stderr=""):
            r = MagicMock()
            r.returncode = returncode
            r.stdout = stdout
            r.stderr = stderr
            return r

        mock_run.side_effect = [
            make_result(0),                          # docker stop (cleanup)
            make_result(0),                          # docker rm (cleanup)
            make_result(0, stdout="abc123def456\n"),  # docker run
        ]
        sm = SandboxManager()
        sm._docker_available = True
        result = sm.start(1, str(ws))
        assert result is not None
        assert result.container_name == "voronoi-inv-1"
        sandbox_file = ws / ".sandbox-id"
        assert sandbox_file.exists()
        assert sandbox_file.read_text() == "abc123def456"

    @patch("voronoi.server.sandbox.subprocess.run")
    def test_exec(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="OK\n", stderr="")
        sm = SandboxManager()
        code, output = sm.exec("voronoi-inv-1", ["python", "-c", "print('hello')"])
        assert code == 0
        assert "OK" in output

    @patch("voronoi.server.sandbox.subprocess.run")
    def test_exec_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=10)
        sm = SandboxManager()
        code, output = sm.exec("voronoi-inv-1", ["sleep", "100"], timeout=10)
        assert code == 1
        assert "timed out" in output

    @patch("voronoi.server.sandbox.subprocess.run")
    def test_is_running(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="true\n", stderr="")
        sm = SandboxManager()
        assert sm.is_running(1) is True

    @patch("voronoi.server.sandbox.subprocess.run")
    def test_is_not_running(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        sm = SandboxManager()
        assert sm.is_running(999) is False


class TestExecInSandboxOrHost:
    def test_host_fallback_when_no_sandbox_file(self, tmp_path):
        # Create a simple script to run
        script = tmp_path / "test.sh"
        script.write_text("#!/bin/bash\necho hello")
        script.chmod(0o755)

        code, output = exec_in_sandbox_or_host(str(tmp_path), ["bash", str(script)])
        assert code == 0
        assert "hello" in output

    def test_host_fallback_with_empty_sandbox_id(self, tmp_path):
        (tmp_path / ".sandbox-id").write_text("")
        code, output = exec_in_sandbox_or_host(str(tmp_path), ["echo", "test"])
        assert code == 0

    @patch("voronoi.server.sandbox.subprocess.run")
    def test_uses_sandbox_when_id_exists(self, mock_run, tmp_path):
        (tmp_path / ".sandbox-id").write_text("abc123")
        mock_run.return_value = MagicMock(returncode=0, stdout="sandboxed\n", stderr="")
        code, output = exec_in_sandbox_or_host(str(tmp_path), ["echo", "test"])
        # Should have called docker exec
        call_args = mock_run.call_args[0][0]
        assert "docker" in call_args
        assert "abc123" in call_args
