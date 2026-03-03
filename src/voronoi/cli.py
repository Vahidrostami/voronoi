"""CLI entry point for voronoi."""

import argparse
import json
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


def _build_orchestrator_prompt(
    prompt_path: str, output_dir: str, safe: bool, max_agents: int = 4,
) -> str:
    """Build the prompt that makes Copilot the swarm orchestrator.

    Replaces the rigid 1000-line bash autopilot with Copilot's own judgment:
    it reads the project brief, plans tasks in Beads, spawns worker agents,
    monitors progress, merges completed work, and handles failures.
    """
    safe_flag = "--safe " if safe else ""
    return (
        "You are the Voronoi swarm orchestrator. Your job: read the project brief, "
        "plan tasks, spawn parallel worker agents, monitor their progress, merge "
        "completed work, and repeat until the project is done.\n\n"
        "## Personality — IMPORTANT\n\n"
        "Your Telegram notifications should be EXCITED, high-energy, and fun — like a hype crew "
        "that genuinely loves watching agents crush it. Use fire emojis, exclamation marks, "
        "celebrate wins, make science feel epic. But always stay INFORMATIVE — every message "
        "must include real numbers (task counts, progress, findings). Never fluff without facts.\n"
        "Examples of good messages:\n"
        '  \"🔥 Wave 2 DONE! 8/12 tasks crushed, 4 agents still cooking. LET\'S GO!\"\n'
        '  \"🧪 FINDING ALERT! Replay + EWC cuts forgetting by 34%% (d=0.82, p<.001) — HUGE if it replicates!\"\n'
        '  \"🏁 ALL DONE! 12/12 tasks, 3 waves, 18min. Science delivered. 🎉\"\n'
        '  \"💀 agent-validation gave up after 3 tries. Skill issue. Moving on.\"\n\n'
        f"PROJECT BRIEF: Read `{prompt_path}` completely before planning — every line matters.\n"
        f"OUTPUT DIR: All work scoped under `{output_dir}/` "
        f"(source in `{output_dir}/src/`, output in `{output_dir}/output/`).\n"
        f"MAX CONCURRENT AGENTS: {max_agents}.\n\n"
        "## Tools\n\n"
        "Task tracking (Beads):\n"
        "  bd prime                       # Load context at start\n"
        "  bd create \"title\" -t task -p <1-3> --description \"...\" --json\n"
        "  bd create \"title\" -t epic -p 1 --json\n"
        "  bd dep add <child-id> <parent-id>\n"
        "  bd ready --json                # Unblocked tasks\n"
        "  bd update <id> --notes \"PRODUCES:file1,file2\"  # Artifact contract\n"
        "  bd update <id> --notes \"REQUIRES:file1,file2\"  # Input contract\n"
        "  bd close <id> --reason \"summary\"\n"
        "  bd list --json / bd show <id> --json\n\n"
        "Spawn a worker agent:\n"
        "  1. Write the worker's prompt to a temp file, e.g. /tmp/prompt-<branch>.txt\n"
        "  2. Run: ./scripts/spawn-agent.sh "
        f"{safe_flag}<task-id> <branch-name> /tmp/prompt-<branch>.txt\n\n"
        "Merge completed work:\n"
        "  ./scripts/merge-agent.sh <branch-name> <task-id>\n\n"
        "Monitor agents:\n"
        "  bd show <id> --json                                    # Task status\n"
        "  git log main..<branch> --oneline                      # Commits\n"
        "  tmux capture-pane -t $(jq -r .tmux_session .swarm-config.json):<branch> -p 2>/dev/null | tail -20\n\n"
        "## Workflow\n\n"
        f"1. Read `{prompt_path}` completely — understand deliverables, success criteria, constraints\n"
        "2. Run `bd prime`, then create an epic + tasks with dependencies and artifact contracts\n"
        "   (each task: PRODUCES files it must create, REQUIRES files it needs, clear file scope)\n"
        "3. OODA loop:\n"
        "   - Observe:  `bd ready --json` for tasks to dispatch, check agent status\n"
        "   - Orient:   Any agents done? Failed? Stuck? New tasks unblocked?\n"
        "   - Decide:   What to spawn, merge, retry, or fix\n"
        "   - Act:      Spawn agents (with rich prompts), merge completed work, \n"
        "               diagnose failures, dispatch newly unblocked tasks\n"
        "   - Repeat until all tasks are done\n"
        "4. Verify deliverables exist, `git push origin main`, report results\n\n"
        "## Writing Worker Prompts — CRITICAL\n\n"
        "Each worker agent is autonomous — it only knows what you tell it. Include:\n"
        "- WHAT to build: specific files, functions, data structures, algorithms\n"
        "- FULL relevant context from the project brief (copy sections verbatim)\n"
        "- Input files with full paths, output files matching PRODUCES artifact contract\n"
        "- Acceptance criteria: how the agent knows it's done\n"
        "- Completion: `bd close <task-id> --reason \"...\"` then `git push origin <branch>`\n\n"
        "## Rules\n"
        "- Read the FULL project brief before planning\n"
        "- No overlapping file scopes between agents\n"
        "- Write detailed, context-rich worker prompts — agents can't infer what you don't provide\n"
        "- Diagnose failures (check git log, tmux output) before retrying\n"
        "- Push all completed work to remote when done\n\n"
        "## Telegram Notifications\n\n"
        "Spawn and merge scripts send per-agent notifications automatically.\n"
        "YOU are responsible for these additional notifications (use your Personality above!):\n\n"
        "  source ./scripts/notify-telegram.sh\n\n"
        "RIGHT AFTER planning tasks (before first spawn), send the kickoff message:\n"
        "  notify_telegram \"swarm_start\" \"🚀 <project name> LET'S GO! <N> tasks planned, <M> agents ready to cook!\"\n\n"
        "After completing each wave of merges, send a hype progress update:\n"
        "  notify_telegram \"wave_complete\" \"🔥 Wave N DONE! X/Y tasks crushed · Z agents still going\"\n\n"
        "When giving up on a task after repeated failures:\n"
        "  notify_telegram \"agent_exhausted\" \"💀 <branch> couldn't land it after N tries — <reason>\"\n\n"
        "When the swarm is fully complete:\n"
        "  notify_telegram \"swarm_complete\" \"🏁 ALL DONE! X/Y tasks · N waves · Mm runtime 🎉\"\n\n"
        "Also check `.swarm/inbox/` for operator commands from Telegram (JSON files).\n"
        "Process any pending commands before each dispatch round.\n"
    )


def cmd_init(args: argparse.Namespace) -> None:
    """Scaffold voronoi into the current directory."""
    target = Path.cwd()
    data = _find_data_dir()

    # Guard: don't init inside the framework repo itself
    if (target / "pyproject.toml").exists() and (target / "src" / "voronoi").is_dir():
        print("Error: you're inside the voronoi source repo. cd to your project first.")
        sys.exit(1)

    print(f"Initializing voronoi v{__version__} in {target}")

    # Ensure it's a git repo with at least one commit (agents use git worktrees)
    if not (target / ".git").is_dir():
        print("  Initializing git repository...")
        subprocess.run(["git", "init"], cwd=str(target), capture_output=True)
        print("  ✓ git init")

    # Ensure at least one commit exists (git worktree requires it)
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(target), capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("  Creating initial commit (required for agent worktrees)...")
        subprocess.run(["git", "add", "-A"], cwd=str(target), capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "voronoi: initial commit"],
            cwd=str(target), capture_output=True,
        )
        print("  ✓ initial commit")

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
            print(f"  copilot --allow-all -p \"$(cat .swarm/orchestrator-prompt.txt)\"")
            return

        # Read config for agent settings
        config = {}
        config_path = target / ".swarm-config.json"
        if config_path.exists():
            config = json.loads(config_path.read_text())

        agent_cmd = config.get("agent_command", "copilot")
        max_agents = config.get("max_agents", 4)

        # Verify agent CLI exists
        agent_bin = agent_cmd.split()[0]
        if not shutil.which(agent_bin):
            print(f"Error: agent CLI not found: {agent_bin}", file=sys.stderr)
            print("  Install Copilot CLI or update agent_command in .swarm-config.json", file=sys.stderr)
            sys.exit(1)

        # Build orchestrator prompt
        prompt = _build_orchestrator_prompt(
            prompt_path=prompt_path,
            output_dir=f"demos/{name}",
            safe=args.safe,
            max_agents=max_agents,
        )

        # Write prompt to file for reference/debugging
        swarm_dir = target / ".swarm"
        swarm_dir.mkdir(parents=True, exist_ok=True)
        (swarm_dir / "orchestrator-prompt.txt").write_text(prompt)

        # Launch orchestrator — Copilot IS the autopilot now
        agent_flags = "--allow-all"
        cmd = [agent_cmd] + agent_flags.split() + ["-p", prompt]

        project_name = target.name
        print(f"\nLaunching orchestrator...\n")
        print(f"  Agent:  {agent_cmd}")
        print(f"  Prompt: .swarm/orchestrator-prompt.txt")
        print(f"  Agents: tmux attach -t {project_name}-swarm")
        print()

        try:
            subprocess.run(cmd, cwd=str(target))
        except KeyboardInterrupt:
            print(f"\n\nOrchestrator interrupted.")
            print(f"  Agent work preserved in tmux: tmux attach -t {project_name}-swarm")
            print(f"  Re-run: voronoi demo run {name}")

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
