"""Tests for voronoi server CLI commands."""

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
