"""Tests for voronoi server CLI commands."""

import argparse
import subprocess
import sys
import time

import pytest

from voronoi.server.queue import Investigation, InvestigationQueue


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


def test_server_prune_removes_terminal_workspace_and_swarm(tmp_path, monkeypatch):
    """server prune should preserve active work and remove eligible swarms."""
    from voronoi import cli

    monkeypatch.setenv("HOME", str(tmp_path))
    base_dir = tmp_path / ".voronoi"
    active_dir = base_dir / "active"
    active_dir.mkdir(parents=True)
    (base_dir / "config.json").write_text(
        '{"server": {"workspace_retention_days": 0}}'
    )

    queue = InvestigationQueue(base_dir / "queue.db")

    done_id = queue.enqueue(Investigation(
        chat_id="c", question="done", slug="done",
        created_at=time.time() - 60,
    ))
    done_ws = active_dir / f"inv-{done_id}-done"
    done_swarm = active_dir / f"inv-{done_id}-done-swarm"
    done_ws.mkdir()
    done_swarm.mkdir()
    queue.start(done_id, str(done_ws))
    queue.complete(done_id)

    running_id = queue.enqueue(Investigation(
        chat_id="c", question="running", slug="running",
        created_at=time.time() - 60,
    ))
    running_ws = active_dir / f"inv-{running_id}-running"
    running_swarm = active_dir / f"inv-{running_id}-running-swarm"
    running_ws.mkdir()
    running_swarm.mkdir()
    queue.start(running_id, str(running_ws))

    orphan_swarm = active_dir / "inv-999-orphan-swarm"
    orphan_swarm.mkdir()

    cli._server_prune(argparse.Namespace(force=True))

    assert not done_ws.exists()
    assert not done_swarm.exists()
    assert running_ws.exists()
    assert running_swarm.exists()
    assert not orphan_swarm.exists()


def test_server_prune_preserves_workspace_reused_by_active_round(tmp_path, monkeypatch):
    """A completed parent must not be pruned while a child reuses its workspace."""
    from voronoi import cli

    monkeypatch.setenv("HOME", str(tmp_path))
    base_dir = tmp_path / ".voronoi"
    active_dir = base_dir / "active"
    active_dir.mkdir(parents=True)
    (base_dir / "config.json").write_text(
        '{"server": {"workspace_retention_days": 0}}'
    )

    queue = InvestigationQueue(base_dir / "queue.db")
    parent_id = queue.enqueue(Investigation(
        chat_id="c", question="parent", slug="parent",
        created_at=time.time() - 60,
    ))
    parent_ws = active_dir / f"inv-{parent_id}-parent"
    parent_swarm = active_dir / f"inv-{parent_id}-parent-swarm"
    parent_ws.mkdir()
    parent_swarm.mkdir()
    queue.start(parent_id, str(parent_ws))
    queue.complete(parent_id)

    child_id = queue.enqueue(Investigation(
        chat_id="c", question="child", slug="child",
        created_at=time.time() - 30,
    ))
    queue.start(child_id, str(parent_ws))

    cli._server_prune(argparse.Namespace(force=True))

    assert parent_ws.exists()
    assert parent_swarm.exists()
