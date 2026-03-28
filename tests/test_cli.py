"""Tests for voronoi CLI."""

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from voronoi import __version__
from voronoi.cli import find_data_dir


def test_version():
    """Package version is consistent."""
    assert __version__ == "0.4.0"


def test_cli_version():
    """CLI --version flag works."""
    result = subprocess.run(
        [sys.executable, "-m", "voronoi.cli", "--version"],
        capture_output=True,
        text=True,
    )
    # argparse --version exits with 0
    assert result.returncode == 0
    assert "0.4.0" in result.stdout


def test_cli_help():
    """CLI shows help without error."""
    result = subprocess.run(
        [sys.executable, "-m", "voronoi.cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "voronoi" in result.stdout.lower()


def testfind_data_dir():
    """find_data_dir locates the data directory with agents."""
    data_dir = find_data_dir()
    # Should return the data/ directory containing agents (canonical location)
    assert (data_dir / "agents").is_dir()


def test_init_creates_files():
    """voronoi init scaffolds expected files into target directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [sys.executable, "-m", "voronoi.cli", "init"],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )

        target = Path(tmpdir)
        # Core framework dirs should exist
        assert (target / "scripts").is_dir()
        # Framework files should exist
        assert (target / "CLAUDE.md").is_file()
        assert (target / "AGENTS.md").is_file()

        # Key scripts should be present (plumbing only — orchestration is Copilot's job)
        assert (target / "scripts" / "spawn-agent.sh").is_file()
        assert (target / "scripts" / "merge-agent.sh").is_file()
        assert (target / "scripts" / "swarm-init.sh").is_file()

        # .github agents, prompts, skills should be present
        assert (target / ".github" / "agents").is_dir()
        assert (target / ".github" / "prompts").is_dir()
        assert (target / ".github" / "skills").is_dir()

        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )
        assert branch.stdout.strip() == "main"


def test_init_blocks_inside_source_repo():
    """voronoi init refuses to run inside its own source repo."""
    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-m", "voronoi.cli", "init"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "source repo" in result.stderr or "source repo" in result.stdout


def test_upgrade_requires_existing_project():
    """voronoi upgrade fails if no scripts/ dir exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [sys.executable, "-m", "voronoi.cli", "upgrade"],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0


def test_upgrade_preserves_user_files():
    """voronoi upgrade keeps user-edited CLAUDE.md."""
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)

        # First init
        subprocess.run(
            [sys.executable, "-m", "voronoi.cli", "init"],
            cwd=tmpdir,
            capture_output=True,
        )

        # Modify CLAUDE.md
        claude_path = Path(tmpdir) / "CLAUDE.md"
        claude_path.write_text("# My Custom Config\n")

        # Upgrade
        result = subprocess.run(
            [sys.executable, "-m", "voronoi.cli", "upgrade"],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

        # CLAUDE.md should be preserved
        assert claude_path.read_text() == "# My Custom Config\n"

        # But scripts should be refreshed
        assert (Path(tmpdir) / "scripts" / "spawn-agent.sh").is_file()
