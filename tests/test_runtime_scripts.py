"""Tests for shipped runtime shell scripts."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "src" / "voronoi" / "data" / "scripts"


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o755)


def _write_fake_jq(bin_dir: Path) -> None:
    _write_executable(
        bin_dir / "jq",
        """#!/usr/bin/env python3
import json
import sys

expr = sys.argv[-1]
data = json.load(sys.stdin)

if expr == '.project_dir':
    print(data.get('project_dir', ''))
elif expr == '.swarm_dir':
    print(data.get('swarm_dir', ''))
elif expr == '.tmux_session':
    print(data.get('tmux_session', ''))
elif expr == '.agent_command // "copilot"':
    print(data.get('agent_command') or 'copilot')
elif expr == '.worker_model // ""':
    print(data.get('worker_model') or '')
elif expr == '.effort // "medium"':
    print(data.get('effort') or 'medium')
elif expr == '.agent_flags // "--allow-all"':
    print(data.get('agent_flags') or '--allow-all')
elif expr == '(.agent_flags_safe // []) | join(" ")':
    print(' '.join(data.get('agent_flags_safe') or []))
else:
    print('')
""",
    )


def _write_fake_timeout(bin_dir: Path) -> None:
    _write_executable(bin_dir / "timeout", "#!/bin/sh\nshift\nexec \"$@\"\n")


def _write_fake_bd(bin_dir: Path, task_notes: str) -> None:
    task_json = json.dumps({"notes": task_notes})
    _write_executable(
        bin_dir / "bd",
        f"""#!/bin/sh
if [ "$1" = "show" ]; then
    printf '%s\n' {json.dumps(task_json)}
    exit 0
fi
if [ "$1" = "list" ]; then
    printf '%s\n' '[]'
    exit 0
fi
exit 0
""",
    )


def _script_env(bin_dir: Path) -> dict[str, str]:
    return {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}


def _write_swarm_config(project: Path, swarm_dir: Path) -> None:
    (project / ".swarm-config.json").write_text(json.dumps({
        "project_dir": str(project),
        "swarm_dir": str(swarm_dir),
        "tmux_session": "test-swarm",
        "agent_command": "true",
        "agent_flags": "--allow-all",
        "effort": "medium",
    }))


def test_spawn_agent_rejects_requires_path_escape(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "outside.txt").write_text("secret")
    swarm_dir = tmp_path / "project-swarm"
    _write_swarm_config(project, swarm_dir)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_jq(bin_dir)
    _write_fake_timeout(bin_dir)
    _write_fake_bd(bin_dir, "REQUIRES:../outside.txt")

    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "spawn-agent.sh"), "bd-1", "agent-test"],
        cwd=project,
        capture_output=True,
        text=True,
        env=_script_env(bin_dir),
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "REQUIRES path escapes workspace" in output


def test_spawn_agent_rejects_absolute_gate_path(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    gate = tmp_path / "gate.json"
    gate.write_text('{"status":"pass"}')
    swarm_dir = tmp_path / "project-swarm"
    _write_swarm_config(project, swarm_dir)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_jq(bin_dir)
    _write_fake_timeout(bin_dir)
    _write_fake_bd(bin_dir, f"GATE:{gate}")

    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "spawn-agent.sh"), "bd-1", "agent-test"],
        cwd=project,
        capture_output=True,
        text=True,
        env=_script_env(bin_dir),
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "GATE path must be workspace-relative" in output


def test_merge_agent_rejects_produces_path_escape(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "scripts").mkdir()
    (project / "scripts" / "notify-telegram.sh").write_text(
        "notify_telegram() { return 0; }\n"
    )
    (tmp_path / "outside.txt").write_text("secret")
    swarm_dir = tmp_path / "project-swarm"
    _write_swarm_config(project, swarm_dir)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_jq(bin_dir)
    _write_fake_bd(bin_dir, "PRODUCES:../outside.txt")

    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "merge-agent.sh"), "agent-test", "bd-1"],
        cwd=project,
        capture_output=True,
        text=True,
        env=_script_env(bin_dir),
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "PRODUCES path escapes workspace" in output
