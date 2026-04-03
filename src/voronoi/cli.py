"""CLI entry point for voronoi."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from voronoi import __version__
from voronoi.utils import git_init_main

# Framework files to copy into user projects
FRAMEWORK_DIRS = ["scripts"]

# Top-level template files (written from data/templates/)
TEMPLATE_FILES = ["CLAUDE.md", "AGENTS.md"]

# Runtime subdirectories to copy into target .github/ (agent definitions, prompts, skills, instructions, hooks)
GITHUB_SUBDIRS = ["agents", "prompts", "skills", "instructions", "hooks"]

# Files that should never be overwritten during upgrade
USER_OWNED = {"CLAUDE.md", "AGENTS.md"}


def find_data_dir() -> Path:
    """Locate the framework data files.

    All runtime content (agents, prompts, skills, scripts, demos, templates)
    lives under src/voronoi/data/ — the single canonical location for both
    editable and packaged installs.
    """
    bundled = Path(__file__).resolve().parent / "data"
    if bundled.is_dir() and (bundled / "agents").is_dir():
        return bundled

    print("Error: cannot find voronoi framework files.", file=sys.stderr)
    print("  Ensure src/voronoi/data/ contains agents/, scripts/, demos/.", file=sys.stderr)
    sys.exit(1)


def _resolve_github_src(data: Path) -> Path:
    """Resolve the source directory for runtime agents/prompts/skills."""
    return data


def _resolve_templates_dir(data: Path) -> Path:
    """Resolve the templates directory for CLAUDE.md and AGENTS.md."""
    templates = data / "templates"
    if templates.is_dir():
        return templates
    return data  # fallback


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


def _current_python_command() -> str:
    """Return the Python interpreter that should launch the MCP sidecar."""
    return sys.executable or shutil.which("python3") or "python3"


def _write_mcp_config(github_dst: Path) -> None:
    """Write Copilot CLI MCP auto-discovery config for the current environment."""
    mcp_config_path = github_dst / "mcp-config.json"
    mcp_config = {
        "mcpServers": {
            "voronoi": {
                "command": _current_python_command(),
                "args": ["-m", "voronoi.mcp"],
                "env": {"VORONOI_WORKSPACE": "."},
            }
        }
    }
    mcp_config_path.write_text(json.dumps(mcp_config, indent=2))


def _server_tmp_dir(base_dir: Path) -> Path:
    """Return the dedicated temp root for server subprocesses."""
    return base_dir / "tmp"


def _server_runtime_env(base_dir: Path) -> dict[str, str]:
    """Build a subprocess environment rooted in the server temp directory."""
    tmp_dir = _server_tmp_dir(base_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    for var in ("TMPDIR", "TMP", "TEMP"):
        env[var] = str(tmp_dir)
    return env


def _build_orchestrator_prompt(
    prompt_path: str, output_dir: str, safe: bool, max_agents: int = 4,
) -> str:
    """Build the orchestrator prompt via the shared builder."""
    from voronoi.server.prompt import build_orchestrator_prompt

    # Read the PROMPT.md content as the question
    prompt_file = Path.cwd() / prompt_path
    question = prompt_file.read_text() if prompt_file.exists() else prompt_path

    return build_orchestrator_prompt(
        question=question,
        mode="discover",
        rigor="adaptive",
        workspace_path=str(Path.cwd()),
        prompt_path=prompt_path,
        output_dir=output_dir,
        max_agents=max_agents,
        safe=safe,
    )


def cmd_init(args: argparse.Namespace) -> None:
    """Scaffold voronoi into the current directory."""
    target = Path.cwd()
    data = find_data_dir()

    # Guard: don't init inside the framework repo itself
    if (target / "pyproject.toml").exists() and (target / "src" / "voronoi").is_dir():
        print("Error: you're inside the voronoi source repo. cd to your project first.")
        sys.exit(1)

    print(f"Initializing voronoi v{__version__} in {target}")

    # Ensure it's a git repo with at least one commit (agents use git worktrees)
    if not (target / ".git").is_dir():
        print("  Initializing git repository...")
        git_init_main(target)
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

    # Copy runtime agents/prompts/skills into target's .github/
    github_src = _resolve_github_src(data)
    github_dst = target / ".github"
    github_dst.mkdir(exist_ok=True)
    for subdir in GITHUB_SUBDIRS:
        src = github_src / subdir
        if src.is_dir():
            _copy_dir(src, github_dst / subdir)

    _write_mcp_config(github_dst)
    # Make hook scripts executable
    hooks_dst = github_dst / "hooks"
    _ensure_executable(hooks_dst)
    print("  ✓ .github/ (agents, prompts, skills, instructions, hooks, mcp)")

    # Copy runtime constitution templates
    templates_dir = _resolve_templates_dir(data)
    for filename in TEMPLATE_FILES:
        src = templates_dir / filename
        dst = target / filename
        if src.is_file():
            shutil.copy2(src, dst)
            print(f"  ✓ {filename} (runtime constitution)")

    # Copy .env.example if available
    env_src = data / ".env.example"
    if env_src.is_file():
        shutil.copy2(env_src, target / ".env.example")
        print("  ✓ .env.example")

    # Run swarm-init.sh if present
    init_script = target / "scripts" / "swarm-init.sh"
    if init_script.exists():
        print("\nRunning swarm-init.sh...")
        subprocess.run(["bash", str(init_script)], cwd=str(target))

    # Re-copy AGENTS.md after swarm-init.sh — bd init overwrites it with
    # its own template that unconditionally mandates git push. The Voronoi
    # template redirects to CLAUDE.md which has the correct policy.
    agents_src = templates_dir / "AGENTS.md"
    agents_dst = target / "AGENTS.md"
    if agents_src.is_file():
        shutil.copy2(agents_src, agents_dst)

    print("\nDone! Next steps:")
    print("  voronoi demo list            # see available demos")
    print("  voronoi demo run <name>      # run a demo")
    print("  copilot                      # start an agent and use /swarm")


def cmd_upgrade(args: argparse.Namespace) -> None:
    """Upgrade framework files, preserving user-edited files."""
    target = Path.cwd()
    data = find_data_dir()

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

    # Overwrite runtime agents/prompts/skills in target's .github/
    github_src = _resolve_github_src(data)
    github_dst = target / ".github"
    github_dst.mkdir(exist_ok=True)
    for subdir in GITHUB_SUBDIRS:
        src = github_src / subdir
        dst = github_dst / subdir
        if src.is_dir():
            _copy_dir(src, dst)
    _write_mcp_config(github_dst)
    # Make hook scripts executable
    hooks_dst = github_dst / "hooks"
    _ensure_executable(hooks_dst)
    print("  ✓ .github/ (agents, prompts, skills, instructions, hooks, mcp replaced)")

    # User-owned files: only copy if missing
    templates_dir = _resolve_templates_dir(data)
    for filename in TEMPLATE_FILES:
        src = templates_dir / filename
        dst = target / filename
        if not dst.exists() and src.is_file():
            shutil.copy2(src, dst)
            print(f"  ✓ {filename} (created)")
        else:
            print(f"  ⊘ {filename} (kept your version)")

    print("\nUpgrade complete.")


def list_demos(data: Path) -> list[dict]:
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
    data = find_data_dir()
    target = Path.cwd()

    if args.demo_action == "list":
        demos = list_demos(data)
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
        demos = list_demos(data)
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
        orchestrator_model = config.get("orchestrator_model", "")

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
        cmd = [agent_cmd] + agent_flags.split()
        if orchestrator_model:
            cmd += ["--model", orchestrator_model]
        cmd += ["-p", prompt]

        project_name = target.name
        print(f"\nLaunching orchestrator...\n")
        print(f"  Agent:  {agent_cmd}")
        if orchestrator_model:
            print(f"  Model:  {orchestrator_model}")
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
    for filename in TEMPLATE_FILES:
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


# ---------------------------------------------------------------------------
# Server commands
# ---------------------------------------------------------------------------

def cmd_server(args: argparse.Namespace) -> None:
    """Handle server subcommands."""
    from voronoi.server.runner import ServerConfig

    if args.server_action == "init":
        _server_init(args)
    elif args.server_action == "start":
        _server_start(args)
    elif args.server_action == "status":
        _server_status(args)
    elif args.server_action == "prune":
        _server_prune(args)
    elif args.server_action == "config":
        _server_config(args)
    elif args.server_action == "extend-timeout":
        _server_extend_timeout(args)
    else:
        print("Usage: voronoi server {init|start|status|prune|config|extend-timeout}")
        sys.exit(1)


def _server_init(args: argparse.Namespace) -> None:
    """Initialize the Voronoi server at ~/.voronoi/."""
    from voronoi.server.runner import ServerConfig

    base_dir = getattr(args, "base_dir", None)
    config = ServerConfig(base_dir=base_dir)

    print(f"Initializing Voronoi server at {config.base_dir}")

    config.base_dir.mkdir(parents=True, exist_ok=True)
    (config.base_dir / "objects").mkdir(exist_ok=True)
    (config.base_dir / "active").mkdir(exist_ok=True)
    _server_tmp_dir(config.base_dir).mkdir(exist_ok=True)

    if not config.config_path.exists():
        config.save()
        print(f"  ✓ Config written to {config.config_path}")
    else:
        print(f"  ⊘ Config already exists at {config.config_path}")

    # Check dependencies
    for cmd, label in [("docker", "Docker"), ("gh", "GitHub CLI"), ("git", "Git"),
                        ("tmux", "tmux"), ("bd", "Beads")]:
        if shutil.which(cmd):
            print(f"  ✓ {label} found")
        else:
            print(f"  ⚠ {label} not found ({cmd})")

    # Check GitHub auth
    gh_token = os.environ.get("GH_TOKEN", "")
    if gh_token:
        print(f"  ✓ GH_TOKEN set")
    elif shutil.which("gh"):
        result = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"  ✓ GitHub authenticated via gh CLI")
        else:
            print(f"  ⚠ gh not authenticated — run: gh auth login")
    else:
        print(f"  ⚠ No GitHub auth — set GH_TOKEN in .env or run: gh auth login")

    # Check agent CLI
    agent_cmd = os.environ.get("VORONOI_AGENT_COMMAND", config.agent_command)
    agent_bin = agent_cmd.split()[0]
    if shutil.which(agent_bin):
        print(f"  ✓ Agent CLI found: {agent_bin}")
    else:
        print(f"  ⚠ Agent CLI not found: {agent_bin}")
        # Try fallbacks
        for alt in ["copilot", "claude"]:
            if alt != agent_bin and shutil.which(alt):
                print(f"    → Found {alt} instead. Set VORONOI_AGENT_COMMAND={alt} in .env")
                break

    # Copy .env.example into ~/.voronoi/ for easy editing
    env_example_src = find_data_dir() / ".env.example"
    env_example_dst = config.base_dir / ".env.example"
    env_dst = config.base_dir / ".env"
    if env_example_src.is_file() and not env_example_dst.exists():
        shutil.copy2(env_example_src, env_example_dst)
        print(f"  ✓ .env.example copied to {env_example_dst}")

    # Initialize Beads in the server directory
    beads_dir = config.base_dir / ".beads"
    if not beads_dir.is_dir() and shutil.which("bd"):
        result = subprocess.run(
            ["bd", "init"],
            cwd=str(config.base_dir),
            capture_output=True,
            input="Y\n",
            text=True,
            timeout=30,
        )
        if beads_dir.is_dir():
            print(f"  ✓ Beads initialized")
        else:
            print(f"  ⚠ Beads init may have failed: {result.stderr.strip()}")
    elif beads_dir.is_dir():
        print(f"  ✓ Beads already initialized")

    print(f"\nServer ready.")
    print(f"  1. Edit {config.base_dir / '.env'} with your credentials")
    if not env_dst.exists():
        print(f"     cp {env_example_dst} {env_dst}")
    print(f"  2. voronoi server start          # launch Telegram bridge")


def _server_start(args: argparse.Namespace) -> None:
    """Start the Telegram bridge using server config."""
    import logging
    from voronoi.server.runner import ServerConfig

    # Configure logging so all voronoi activity is visible in the terminal
    log_level = os.environ.get("VORONOI_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # Also let python-telegram-bot's own logs through at WARNING+
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)

    config = ServerConfig()

    if not config.base_dir.exists():
        print("Server not initialized. Run: voronoi server init")
        sys.exit(1)

    # Load .env from ~/.voronoi/ if it exists
    env_file = config.base_dir / ".env"
    if env_file.exists():
        from voronoi.gateway.config import load_dotenv
        load_dotenv(env_file)
        print(f"  ✓ Loaded {env_file}")

    # Verify bot token is available
    bot_token = os.environ.get("VORONOI_TG_BOT_TOKEN", "")
    if not bot_token:
        print("Error: No Telegram bot token configured.", file=sys.stderr)
        print(f"  Set VORONOI_TG_BOT_TOKEN in {env_file}", file=sys.stderr)
        sys.exit(1)

    # Find the bridge script
    bridge_script = _find_bridge_script()
    if bridge_script is None:
        print("Error: telegram-bridge.py not found.", file=sys.stderr)
        sys.exit(1)

    # Create a minimal .swarm config pointing to the server base dir
    server_config = {
        "project_name": "voronoi-server",
        "project_dir": str(config.base_dir),
        "agent_command": config.agent_command,
        "notifications": {
            "telegram": {
                "bot_token": bot_token,
                "user_allowlist": os.environ.get("VORONOI_TG_USER_ALLOWLIST", ""),
                "bridge_enabled": True,
            }
        },
    }

    # Write server swarm config
    server_swarm_config = config.base_dir / ".swarm-config.json"
    server_swarm_config.write_text(json.dumps(server_config, indent=2))

    # Ensure inbox directory exists
    (config.base_dir / ".swarm" / "inbox").mkdir(parents=True, exist_ok=True)

    # Ensure Beads is initialized in the server directory
    beads_dir = config.base_dir / ".beads"
    if not beads_dir.is_dir() and shutil.which("bd"):
        result = subprocess.run(
            ["bd", "init"],
            cwd=str(config.base_dir),
            capture_output=True,
            input="Y\n",
            text=True,
            timeout=30,
        )
        if (beads_dir).is_dir():
            print(f"  ✓ Beads initialized in {config.base_dir}")
        else:
            print(f"  ⚠ Beads init may have failed: {result.stderr.strip()}", file=sys.stderr)
    elif beads_dir.is_dir():
        print(f"  ✓ Beads already initialized in {config.base_dir}")

    print(f"\n🤖 Starting Telegram bridge...")
    print(f"   Server: {config.base_dir}")
    print(f"   Press Ctrl+C to stop\n")

    # Pass log level to the bridge subprocess via environment
    env = _server_runtime_env(config.base_dir)
    env.setdefault("VORONOI_LOG_LEVEL", log_level)

    try:
        bridge_cmd = [sys.executable, str(bridge_script), "--config", str(server_swarm_config)]
        if getattr(args, "daemon", False):
            logs_dir = config.base_dir / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_path = Path(args.log_file).expanduser() if getattr(args, "log_file", None) else logs_dir / "telegram-bridge.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("ab") as log_handle:
                proc = subprocess.Popen(
                    bridge_cmd,
                    cwd=str(config.base_dir),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            time.sleep(2)
            return_code = proc.poll()
            if return_code is not None:
                print("Error: Telegram bridge exited immediately.", file=sys.stderr)
                print(f"  Check logs: {log_path}", file=sys.stderr)
                sys.exit(return_code or 1)
            print("Telegram bridge started in background.")
            print(f"  PID: {proc.pid}")
            print(f"  Logs: {log_path}")
            return

        result = subprocess.run(
            bridge_cmd,
            cwd=str(config.base_dir),
            env=env,
        )
    except KeyboardInterrupt:
        print("\nTelegram bridge stopped.")
        return

    if result.returncode != 0:
        sys.exit(result.returncode)


def _find_bridge_script() -> Path | None:
    """Locate telegram-bridge.py in data dir."""
    data = find_data_dir()
    candidates = [
        data / "scripts" / "telegram-bridge.py",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _server_status(args: argparse.Namespace) -> None:
    """Show server status."""
    from voronoi.server.queue import InvestigationQueue
    from voronoi.server.runner import ServerConfig
    from voronoi.server.workspace import WorkspaceManager

    config = ServerConfig()
    queue_path = config.base_dir / "queue.db"

    if not config.base_dir.exists():
        print("Server not initialized. Run: voronoi server init")
        sys.exit(1)

    wm = WorkspaceManager(config.base_dir)
    active = wm.list_active()

    print(f"Voronoi Server — {config.base_dir}")
    print(f"  Active workspaces: {len(active)}")
    print(f"  Max concurrent: {config.max_concurrent}")
    print(f"  Sandbox: {'enabled' if config.sandbox.enabled else 'disabled'}")

    if queue_path.exists():
        queue = InvestigationQueue(queue_path)
        running = queue.get_running()
        queued = queue.get_queued()
        print(f"\n  Running: {len(running)}")
        for inv in running:
            elapsed = (time.time() - (inv.started_at or inv.created_at)) / 60
            label = inv.repo or inv.slug
            print(f"    ⚡ #{inv.id} {label} ({elapsed:.0f}min)")
        print(f"  Queued: {len(queued)}")
        for inv in queued:
            label = inv.repo or inv.slug
            print(f"    ⏳ #{inv.id} {label}")


def _server_prune(args: argparse.Namespace) -> None:
    """Clean up old investigation workspaces."""
    from voronoi.server.runner import ServerConfig
    from voronoi.server.workspace import WorkspaceManager

    config = ServerConfig()
    wm = WorkspaceManager(config.base_dir)
    active = wm.list_active()

    if not active:
        print("No workspaces to prune.")
        return

    print(f"Active workspaces: {len(active)}")
    for name in active:
        print(f"  {name}")

    if not getattr(args, "force", False):
        print(f"\nRun with --force to remove all workspaces.")
        return

    for name in active:
        p = config.base_dir / "active" / name
        if p.exists():
            shutil.rmtree(p)
            print(f"  ✓ Removed {name}")

    print("Done.")


def _server_config(args: argparse.Namespace) -> None:
    """Show server configuration."""
    from voronoi.server.runner import ServerConfig

    config = ServerConfig()
    if not config.config_path.exists():
        print("No config found. Run: voronoi server init")
        sys.exit(1)

    print(config.config_path.read_text())


def _server_extend_timeout(args: argparse.Namespace) -> None:
    """Extend (or set) the timeout for a running investigation.

    Writes the new total timeout to <workspace>/.swarm/timeout_hours so the
    dispatcher picks it up on the next poll cycle — no restart required.
    """
    from voronoi.server.runner import ServerConfig
    from voronoi.server.workspace import WorkspaceManager

    config = ServerConfig()
    if not config.base_dir.exists():
        print("Server not initialized. Run: voronoi server init")
        sys.exit(1)

    hours = args.hours
    if hours <= 0:
        print("Error: hours must be a positive integer.", file=sys.stderr)
        sys.exit(1)

    wm = WorkspaceManager(config.base_dir)
    active = wm.list_active()

    target = args.investigation

    # Match by investigation ID ("#3" or "3") or by workspace name substring
    matched: list[Path] = []
    target_clean = target.lstrip("#")
    for name in active:
        ws_path = config.base_dir / "active" / name
        # Match numeric ID against queue.db investigation ID stored in .swarm/
        inv_id_path = ws_path / ".swarm" / "investigation_id"
        if inv_id_path.exists():
            try:
                if inv_id_path.read_text().strip() == target_clean:
                    matched.append(ws_path)
                    continue
            except OSError:
                pass
        # Fallback: match workspace directory name
        if target_clean in name:
            matched.append(ws_path)

    if not matched:
        print(f"No active workspace matching '{target}'.", file=sys.stderr)
        print("Active workspaces:")
        for name in active:
            print(f"  {name}")
        sys.exit(1)
    if len(matched) > 1:
        print(f"Ambiguous — '{target}' matches multiple workspaces:", file=sys.stderr)
        for ws in matched:
            print(f"  {ws.name}", file=sys.stderr)
        sys.exit(1)

    ws_path = matched[0]
    swarm_dir = ws_path / ".swarm"
    swarm_dir.mkdir(parents=True, exist_ok=True)
    override_file = swarm_dir / "timeout_hours"
    override_file.write_text(str(hours))
    print(f"Timeout for {ws_path.name} set to {hours}h (was {config.sandbox.timeout_hours}h default).")
    print("The dispatcher will pick this up on the next poll cycle.")


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

    # Server subcommand
    server_parser = sub.add_parser("server", help="Manage the Voronoi server")
    server_sub = server_parser.add_subparsers(dest="server_action")
    server_init = server_sub.add_parser("init", help="Initialize server at ~/.voronoi/")
    server_init.add_argument("--base-dir", dest="base_dir", help="Custom base directory")
    server_start = server_sub.add_parser("start", help="Start Telegram bridge")
    server_start.add_argument("--daemon", action="store_true", help="Run the Telegram bridge in the background")
    server_start.add_argument("--log-file", help="Path to the bridge log file when using --daemon")
    server_sub.add_parser("status", help="Show server status")
    server_prune = server_sub.add_parser("prune", help="Clean up old workspaces")
    server_prune.add_argument("--force", action="store_true", help="Actually remove workspaces")
    server_sub.add_parser("config", help="Show server configuration")
    ext_parser = server_sub.add_parser("extend-timeout", help="Extend timeout for a running investigation")
    ext_parser.add_argument("investigation", help="Investigation ID or workspace name")
    ext_parser.add_argument("hours", type=int, help="New total timeout in hours")

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
    elif args.command == "server":
        if not hasattr(args, "server_action") or args.server_action is None:
            server_parser.print_help()
        else:
            cmd_server(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
