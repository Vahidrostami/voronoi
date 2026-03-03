"""CLI entry point for voronoi."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from voronoi import __version__

# Framework files to copy into user projects
FRAMEWORK_DIRS = ["scripts"]
FRAMEWORK_FILES = ["CLAUDE.md", "AGENTS.md", ".env.example"]

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
    print("  If you installed with pip, rebuild with: ./scripts/sync-package-data.sh && pip install .", file=sys.stderr)
    sys.exit(1)


def _copy_dir(src: Path, dst: Path) -> None:
    """Copy a directory, overwriting existing files."""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _ensure_executable(directory: Path) -> None:
    """Make all .sh files in a directory executable."""
    if not directory.is_dir():
        return
    for sh_file in directory.rglob("*.sh"):
        sh_file.chmod(sh_file.stat().st_mode | 0o755)


def cmd_init(args: argparse.Namespace) -> None:
    """Scaffold voronoi into the current directory."""
    target = Path.cwd()
    data = _find_data_dir()

    # Guard: don't init inside the framework repo itself
    if (target / "pyproject.toml").exists() and (target / "src" / "voronoi").is_dir():
        print("Error: you're inside the voronoi source repo. cd to your project first.")
        sys.exit(1)

    print(f"Initializing voronoi v{__version__} in {target}")

    # Ensure it's a git repo (swarm-init.sh and agents expect git)
    if not (target / ".git").is_dir():
        print("  Initializing git repository...")
        subprocess.run(["git", "init"], cwd=str(target), capture_output=True)
        print("  ✓ git init")

    # Copy directories
    for dirname in FRAMEWORK_DIRS:
        src = data / dirname
        if src.is_dir():
            _copy_dir(src, target / dirname)
            _ensure_executable(target / dirname)
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
        print("  ✓ .github/ (agents, prompts, skills)")

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
    print("  voronoi demo list            # see available demos")
    print("  voronoi demo run <name>      # run a demo")
    print("  copilot                      # start an agent and use /swarm")


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
            _ensure_executable(target / dirname)
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
        print("  ✓ .github/ (agents, prompts, skills replaced)")

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


def _list_demos(data: Path) -> list[dict]:
    """Return list of available demos with metadata."""
    demos_dir = data / "demos"
    if not demos_dir.is_dir():
        return []

    demos = []
    for entry in sorted(demos_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        prompt = entry / "PROMPT.md"
        readme = entry / "README.md"
        # Extract first line of PROMPT.md as description
        desc = ""
        if prompt.is_file():
            first_line = prompt.read_text().strip().split("\n")[0]
            desc = first_line.lstrip("# ").strip()
        elif readme.is_file():
            first_line = readme.read_text().strip().split("\n")[0]
            desc = first_line.lstrip("# ").strip()
        demos.append({"name": entry.name, "path": entry, "description": desc, "has_prompt": prompt.is_file()})
    return demos


def cmd_demo(args: argparse.Namespace) -> None:
    """Handle demo subcommands: list, run, clean."""
    data = _find_data_dir()
    target = Path.cwd()

    if args.demo_action == "list":
        demos = _list_demos(data)
        if not demos:
            print("No demos found.")
            return
        print(f"Available demos (voronoi v{__version__}):\n")
        for d in demos:
            marker = "✓" if d["has_prompt"] else "○"
            print(f"  {marker} {d['name']:<25} {d['description']}")
        print(f"\nRun one with: voronoi demo run <name>")
        print(f"Options:      --safe (restrict agent tools)  --dry-run (copy only, don't run)")

    elif args.demo_action == "run":
        name = args.name
        demos = _list_demos(data)
        demo = next((d for d in demos if d["name"] == name), None)
        if demo is None:
            print(f"Error: demo '{name}' not found.", file=sys.stderr)
            print(f"Available: {', '.join(d['name'] for d in demos)}", file=sys.stderr)
            sys.exit(1)
        if not demo["has_prompt"]:
            print(f"Error: demo '{name}' has no PROMPT.md.", file=sys.stderr)
            sys.exit(1)

        # Ensure voronoi is initialized in the target directory
        if not (target / "scripts").is_dir():
            print("No voronoi project found here. Running 'voronoi init' first...\n")
            # Fake args for init
            cmd_init(argparse.Namespace())

        # Copy demo files into target
        demo_dst = target / "demos" / name
        print(f"\nSetting up demo: {name}")
        _copy_dir(demo["path"], demo_dst)
        print(f"  ✓ Copied demo to demos/{name}/")

        # Copy demos README and __init__.py if not present
        demos_root_src = data / "demos"
        demos_root_dst = target / "demos"
        demos_root_dst.mkdir(exist_ok=True)
        for fname in ["README.md", "__init__.py"]:
            src = demos_root_src / fname
            dst = demos_root_dst / fname
            if src.is_file() and not dst.exists():
                shutil.copy2(src, dst)

        prompt_path = f"demos/{name}/PROMPT.md"

        if args.dry_run:
            print(f"\n--dry-run: demo copied but not started.")
            print(f"To run manually:")
            print(f"  ./scripts/autopilot.sh --prompt {prompt_path} --safe")
            return

        # Build the autopilot command
        autopilot = target / "scripts" / "autopilot.sh"
        if not autopilot.exists():
            print(f"Error: scripts/autopilot.sh not found.", file=sys.stderr)
            sys.exit(1)

        cmd = ["bash", str(autopilot), "--prompt", prompt_path]
        if args.safe:
            cmd.append("--safe")

        print(f"\nLaunching autopilot...\n")
        print(f"  Command: {' '.join(cmd)}")
        print(f"  Monitor: python3 scripts/dashboard.py")
        print(f"  Agents:  tmux attach -t $(basename $(pwd))-swarm")
        print()

        try:
            subprocess.run(cmd, cwd=str(target))
        except KeyboardInterrupt:
            print("\n\nAutopilot interrupted. Resume with:")
            print(f"  ./scripts/autopilot.sh --resume")

    elif args.demo_action == "clean":
        name = args.name
        demo_dir = target / "demos" / name
        output_dir = target / "demos" / name / "output"
        src_dir = target / "demos" / name / "src"

        if not demo_dir.is_dir():
            print(f"No demo '{name}' found in this project.")
            sys.exit(1)

        # Remove output and src from the demo
        removed = []
        for d in [output_dir, src_dir]:
            if d.is_dir():
                shutil.rmtree(d)
                removed.append(d.name)

        if removed:
            print(f"  ✓ Removed: {', '.join(removed)}")
        else:
            print(f"  No generated output found for demo '{name}'.")

        if args.all:
            shutil.rmtree(demo_dir)
            print(f"  ✓ Removed demos/{name}/ entirely")

    else:
        print("Usage: voronoi demo {list|run|clean} [name]")
        sys.exit(1)


def cmd_clean(args: argparse.Namespace) -> None:
    """Remove all voronoi artifacts from the current directory."""
    target = Path.cwd()

    # Safety: don't clean the voronoi source repo
    if (target / "pyproject.toml").exists() and (target / "src" / "voronoi").is_dir():
        print("Error: you're inside the voronoi source repo. Not cleaning.")
        sys.exit(1)

    artifacts = [
        ".swarm",
        ".swarm-config.json",
        ".beads",
        "scripts",
        "demos",
        ".github/agents",
        ".github/prompts",
        ".github/skills",
    ]

    # Also clean the worktree directory
    project_name = target.name
    swarm_dir = target.parent / f"{project_name}-swarm"

    print(f"Removing voronoi artifacts from {target}")

    for name in artifacts:
        p = target / name
        if p.is_file():
            p.unlink()
            print(f"  ✓ {name}")
        elif p.is_dir():
            shutil.rmtree(p)
            print(f"  ✓ {name}/")

    # Remove framework files (only if they look like ours)
    for filename in FRAMEWORK_FILES:
        p = target / filename
        if p.is_file():
            p.unlink()
            print(f"  ✓ {filename}")

    if swarm_dir.is_dir():
        shutil.rmtree(swarm_dir)
        print(f"  ✓ ../{swarm_dir.name}/")

    # Prune git worktrees
    if (target / ".git").is_dir():
        subprocess.run(["git", "worktree", "prune"], cwd=str(target), capture_output=True)
        print("  ✓ git worktree prune")

    print("\nClean. You can delete this directory if you're done.")


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

    # Demo subcommand with its own subparser
    demo_parser = sub.add_parser("demo", help="List, run, or clean demos")
    demo_sub = demo_parser.add_subparsers(dest="demo_action")

    demo_sub.add_parser("list", help="List available demos")

    run_parser = demo_sub.add_parser("run", help="Run a demo")
    run_parser.add_argument("name", help="Demo name (e.g. coupled-decisions)")
    run_parser.add_argument("--safe", action="store_true", help="Restrict agent tools (no curl, ssh, sudo)")
    run_parser.add_argument("--dry-run", action="store_true", help="Copy demo files but don't launch autopilot")

    clean_parser = demo_sub.add_parser("clean", help="Remove generated output from a demo")
    clean_parser.add_argument("name", help="Demo name")
    clean_parser.add_argument("--all", action="store_true", help="Remove the entire demo directory, not just output")

    sub.add_parser("clean", help="Remove all voronoi artifacts from this directory")
    sub.add_parser("version", help="Print version")

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "upgrade":
        cmd_upgrade(args)
    elif args.command == "demo":
        if not hasattr(args, "demo_action") or args.demo_action is None:
            demo_parser.print_help()
        else:
            cmd_demo(args)
    elif args.command == "clean":
        cmd_clean(args)
    elif args.command == "version":
        cmd_version(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
