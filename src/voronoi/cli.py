"""CLI entry point for voronoi."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from voronoi import __version__

# Framework files to copy into user projects
FRAMEWORK_DIRS = ["scripts"]
FRAMEWORK_FILES = ["CLAUDE.md", "AGENTS.md"]

# .github/ subdirectories to copy (agent definitions, prompts, skills)
GITHUB_SUBDIRS = ["agents", "prompts", "skills"]

# Files that should never be overwritten during upgrade
USER_OWNED = {"CLAUDE.md", "AGENTS.md"}


def _find_data_dir() -> Path:
    """Locate the framework data files.

    Works for both editable installs (repo root) and normal pip installs
    (bundled in package data).
    """
    # Editable install: data lives at repo root
    repo_root = Path(__file__).resolve().parent.parent.parent
    if (repo_root / "scripts").is_dir() and (repo_root / "pyproject.toml").is_file():
        return repo_root

    # Normal install: data bundled inside the package
    bundled = Path(__file__).resolve().parent / "data"
    if bundled.is_dir():
        return bundled

    print("Error: cannot find voronoi framework files.", file=sys.stderr)
    sys.exit(1)


def _copy_dir(src: Path, dst: Path) -> None:
    """Copy a directory, overwriting existing files."""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def cmd_init(args: argparse.Namespace) -> None:
    """Scaffold voronoi into the current directory."""
    target = Path.cwd()
    data = _find_data_dir()

    # Guard: don't init inside the framework repo itself
    if (target / "pyproject.toml").exists() and (target / "src" / "voronoi").is_dir():
        print("Error: you're inside the voronoi source repo. cd to your project first.")
        sys.exit(1)

    print(f"Initializing voronoi v{__version__} in {target}")

    # Copy directories
    for dirname in FRAMEWORK_DIRS:
        src = data / dirname
        if src.is_dir():
            _copy_dir(src, target / dirname)
            print(f"  ✓ {dirname}/")

    # Copy .github/ subdirectories (agents, prompts, skills)
    github_src = data / ".github"
    if github_src.is_dir():
        github_dst = target / ".github"
        github_dst.mkdir(exist_ok=True)
        for subdir in GITHUB_SUBDIRS:
            src = github_src / subdir
            if src.is_dir():
                _copy_dir(src, github_dst / subdir)
        print(f"  ✓ .github/ (agents, prompts, skills)")

    # Copy top-level framework files
    for filename in FRAMEWORK_FILES:
        src = data / filename
        dst = target / filename
        if src.is_file():
            shutil.copy2(src, dst)
            print(f"  ✓ {filename}")

    # Run swarm-init.sh if present
    init_script = target / "scripts" / "swarm-init.sh"
    if init_script.exists():
        print("\nRunning swarm-init.sh...")
        subprocess.run(["bash", str(init_script)], cwd=str(target))

    print("\nDone! Next steps:")
    print("  1. Start your AI coding agent: copilot")
    print("  2. Run: /swarm <describe your task>")


def cmd_upgrade(args: argparse.Namespace) -> None:
    """Upgrade framework files, preserving user-edited files."""
    target = Path.cwd()
    data = _find_data_dir()

    if not (target / "scripts").is_dir():
        print("Error: no voronoi project here. Run 'voronoi init' first.")
        sys.exit(1)

    print(f"Upgrading voronoi to v{__version__}")

    # Overwrite scripts (framework-owned)
    for dirname in FRAMEWORK_DIRS:
        src = data / dirname
        if src.is_dir():
            _copy_dir(src, target / dirname)
            print(f"  ✓ {dirname}/ (replaced)")


    # Overwrite .github/ subdirectories (agents, prompts, skills)
    github_src = data / ".github"
    if github_src.is_dir():
        github_dst = target / ".github"
        github_dst.mkdir(exist_ok=True)
        for subdir in GITHUB_SUBDIRS:
            src = github_src / subdir
            if src.is_dir():
                _copy_dir(src, github_dst / subdir)
        print(f"  ✓ .github/ (agents, prompts, skills replaced)")

    # User-owned files: only copy if missing
    for filename in FRAMEWORK_FILES:
        src = data / filename
        dst = target / filename
        if not dst.exists() and src.is_file():
            shutil.copy2(src, dst)
            print(f"  ✓ {filename} (created)")
        else:
            print(f"  ⊘ {filename} (kept your version)")

    print("\nUpgrade complete.")


def cmd_version(args: argparse.Namespace) -> None:
    print(f"voronoi {__version__}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="voronoi",
        description="Orchestrate multiple AI coding agents in parallel",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Scaffold voronoi into the current directory")
    sub.add_parser("upgrade", help="Upgrade framework files (keeps your CLAUDE.md)")
    sub.add_parser("version", help="Print version")

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "upgrade":
        cmd_upgrade(args)
    elif args.command == "version":
        cmd_version(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
