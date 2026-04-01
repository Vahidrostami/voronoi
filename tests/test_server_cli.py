"""Tests for voronoi server CLI commands."""

import argparse
import subprocess
import sys

import pytest


def test_server_help():
    """voronoi server shows help."""
    result = subprocess.run(
        [sys.executable, "-m", "voronoi.cli", "server"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "init" in result.stdout or "status" in result.stdout or "server" in result.stdout


def test_server_init(tmp_path):
    """voronoi server init creates ~/.voronoi/ structure."""
    result = subprocess.run(
        [sys.executable, "-m", "voronoi.cli", "server", "init",
         "--base-dir", str(tmp_path / "voronoi-test")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert (tmp_path / "voronoi-test" / "config.json").exists()
    assert (tmp_path / "voronoi-test" / "objects").is_dir()
    assert (tmp_path / "voronoi-test" / "active").is_dir()
    assert (tmp_path / "voronoi-test" / "tmp").is_dir()


def test_server_status_before_init(tmp_path):
    """voronoi server status fails gracefully before init."""
    result = subprocess.run(
        [sys.executable, "-m", "voronoi.cli", "server", "status"],
        capture_output=True, text=True,
        env={**__import__("os").environ, "HOME": str(tmp_path)},
    )
    # Should fail with message about not initialized
    assert result.returncode != 0 or "not initialized" in result.stderr + result.stdout


def test_server_start_help_mentions_daemon():
    """voronoi server start documents background mode."""
    result = subprocess.run(
        [sys.executable, "-m", "voronoi.cli", "server", "start", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "--daemon" in result.stdout


def test_server_start_passes_temp_env_to_bridge(tmp_path, monkeypatch):
    """server start should route temp files through ~/.voronoi/tmp."""
    from voronoi import cli

    base_dir = tmp_path / ".voronoi"
    base_dir.mkdir()
    (base_dir / "config.json").write_text("{}")

    bridge_script = tmp_path / "telegram-bridge.py"
    bridge_script.write_text("#!/usr/bin/env python3\n")

    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("VORONOI_TG_BOT_TOKEN", "test-token")
    monkeypatch.setattr(cli, "_find_bridge_script", lambda: bridge_script)
    monkeypatch.setattr(cli.shutil, "which", lambda cmd: None)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    cli._server_start(argparse.Namespace(daemon=False, log_file=None))

    env = captured["env"]
    assert isinstance(env, dict)
    temp_dir = base_dir / "tmp"
    assert temp_dir.is_dir()
    assert env["TMPDIR"] == str(temp_dir)
    assert env["TMP"] == str(temp_dir)
    assert env["TEMP"] == str(temp_dir)
