#!/usr/bin/env python3
"""
dashboard.py — Live terminal dashboard for swarm monitoring.

Displays real-time agent status, task DAG, and progress metrics.
Supports keyboard shortcuts for intervention.

Usage:
    python3 scripts/dashboard.py [--refresh N]

Requires: pip install rich  (only external dependency)
"""

import json
import subprocess
import sys
import os
import time
import signal
from pathlib import Path
from datetime import datetime, timedelta

try:
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    from rich.layout import Layout
    from rich.text import Text
    from rich.console import Console, Group
    from rich.columns import Columns
except ImportError:
    print("Dashboard requires 'rich' library. Install with:")
    print("  pip install rich")
    sys.exit(1)


def load_config():
    """Load .swarm-config.json from project root."""
    config_path = Path(".swarm-config.json")
    if not config_path.exists():
        # Try parent dirs
        for parent in Path.cwd().parents:
            p = parent / ".swarm-config.json"
            if p.exists():
                config_path = p
                break
    if not config_path.exists():
        print("✗ .swarm-config.json not found. Run swarm-init.sh first.")
        sys.exit(1)
    return json.loads(config_path.read_text())


def run_cmd(cmd, timeout=10):
    """Run a shell command and return stdout."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return ""


def get_beads_tasks():
    """Get all tasks from beads as structured data."""
    raw = run_cmd("bd list --json 2>/dev/null")
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def get_ready_tasks():
    """Get ready (unblocked) task count."""
    raw = run_cmd("bd ready --json 2>/dev/null")
    if not raw:
        return 0
    try:
        return len(json.loads(raw))
    except (json.JSONDecodeError, TypeError):
        return 0


def get_agent_branches(config):
    """Get info about active agent worktrees."""
    swarm_dir = Path(config["swarm_dir"])
    project_dir = config["project_dir"]
    agents = []

    if not swarm_dir.exists():
        return agents

    for wt in sorted(swarm_dir.iterdir()):
        if not wt.is_dir() or not wt.name.startswith("agent-"):
            continue

        branch = wt.name

        # Get commit count and last commit
        commits = run_cmd(
            f"cd {project_dir} && git log main..{branch} --oneline 2>/dev/null"
        )
        commit_count = len(commits.splitlines()) if commits else 0

        # Get last activity
        last_activity = run_cmd(
            f"cd {project_dir} && git log {branch} -1 --format='%ar' 2>/dev/null"
        )

        # Get diff stats
        stat = run_cmd(
            f"cd {project_dir} && git diff main..{branch} --stat 2>/dev/null | tail -1"
        )

        # Check tmux window
        tmux_session = config.get("tmux_session", "")
        tmux_alive = bool(
            run_cmd(
                f"tmux list-windows -t {tmux_session} 2>/dev/null | grep -q {branch} && echo yes"
            )
        )

        # Try to get last line of agent output
        last_output = ""
        if tmux_alive:
            raw_output = run_cmd(
                f"tmux capture-pane -t {tmux_session}:{branch} -p 2>/dev/null | grep -v '^$' | tail -1"
            )
            if raw_output:
                last_output = raw_output[:80]

        agents.append({
            "branch": branch,
            "commits": commit_count,
            "last_activity": last_activity or "unknown",
            "stat": stat or "no changes",
            "tmux_alive": tmux_alive,
            "last_output": last_output,
        })

    return agents


def get_tmux_pane_output(config, branch, lines=5):
    """Capture recent output from an agent's tmux pane."""
    tmux_session = config.get("tmux_session", "")
    raw = run_cmd(
        f"tmux capture-pane -t {tmux_session}:{branch} -p 2>/dev/null | tail -{lines}"
    )
    return raw


STATUS_ICONS = {
    "open": "○",
    "in_progress": "◐",
    "closed": "✓",
    "blocked": "●",
    "deferred": "❄",
}

STATUS_COLORS = {
    "open": "white",
    "in_progress": "yellow",
    "closed": "green",
    "blocked": "red",
    "deferred": "dim",
}

PRIORITY_COLORS = {
    0: "red bold",
    1: "red",
    2: "yellow",
    3: "blue",
    4: "dim",
}


def build_task_table(tasks):
    """Build a rich table of all tasks."""
    table = Table(
        title="📋 Task Graph",
        show_header=True,
        header_style="bold cyan",
        expand=True,
        padding=(0, 1),
    )
    table.add_column("Status", width=3, justify="center")
    table.add_column("ID", style="dim", max_width=30)
    table.add_column("P", width=2, justify="center")
    table.add_column("Title", ratio=2)
    table.add_column("Type", width=6)
    table.add_column("Assignee", width=12)

    for t in tasks:
        status = t.get("status", "open")
        priority = t.get("priority", 2)
        icon = STATUS_ICONS.get(status, "?")
        color = STATUS_COLORS.get(status, "white")
        p_color = PRIORITY_COLORS.get(priority, "white")

        table.add_row(
            Text(icon, style=color),
            t.get("id", "?"),
            Text(f"P{priority}", style=p_color),
            Text(t.get("title", "?"), style=color),
            t.get("issue_type", "task"),
            t.get("assignee", "—"),
        )

    return table


def build_agent_table(agents):
    """Build a rich table of active agents."""
    table = Table(
        title="🤖 Active Agents",
        show_header=True,
        header_style="bold green",
        expand=True,
        padding=(0, 1),
    )
    table.add_column("Agent", style="bold", ratio=1)
    table.add_column("Commits", width=8, justify="center")
    table.add_column("Last Activity", width=16)
    table.add_column("Changes", ratio=1)
    table.add_column("Process", width=8, justify="center")
    table.add_column("Latest Output", ratio=2, style="dim")

    for a in agents:
        process_icon = "🟢" if a["tmux_alive"] else "⚫"
        table.add_row(
            a["branch"],
            str(a["commits"]),
            a["last_activity"],
            a["stat"],
            process_icon,
            a["last_output"],
        )

    if not agents:
        table.add_row("—", "—", "—", "—", "—", "No active agents")

    return table


def build_status_bar(config, tasks, agents, ready_count, start_time):
    """Build the top status bar."""
    elapsed = int(time.time() - start_time)
    elapsed_str = str(timedelta(seconds=elapsed))

    open_count = sum(1 for t in tasks if t.get("status") == "open")
    in_progress = sum(1 for t in tasks if t.get("status") == "in_progress")
    closed_count = sum(1 for t in tasks if t.get("status") == "closed")
    total = len(tasks)

    # Progress bar
    progress_pct = (closed_count / total * 100) if total > 0 else 0
    bar_width = 30
    filled = int(bar_width * closed_count / total) if total > 0 else 0
    progress_bar = "█" * filled + "░" * (bar_width - filled)

    status_text = (
        f"[bold]{config.get('project_name', '?')}[/bold]  "
        f"[green]{progress_bar}[/green] {progress_pct:.0f}%  "
        f"[green]✓{closed_count}[/green] "
        f"[yellow]◐{in_progress}[/yellow] "
        f"[white]○{open_count}[/white] "
        f"[cyan]⚡{ready_count}[/cyan] ready  "
        f"[dim]🤖{len(agents)} agents  "
        f"⏱ {elapsed_str}[/dim]"
    )
    return Panel(status_text, title="🐝 Swarm Dashboard", border_style="cyan")


def build_help_bar():
    """Build the bottom help bar."""
    return Text(
        "  [q]uit  [r]efresh  │  Use autopilot.sh for autonomous operation",
        style="dim",
    )


def build_dashboard(config, start_time):
    """Build the complete dashboard layout."""
    tasks = get_beads_tasks()
    agents = get_agent_branches(config)
    ready_count = get_ready_tasks()

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=1),
    )

    layout["header"].update(
        build_status_bar(config, tasks, agents, ready_count, start_time)
    )

    # Body: tasks on left, agents on right
    layout["body"].split_row(
        Layout(name="tasks", ratio=1),
        Layout(name="agents", ratio=1),
    )
    layout["tasks"].update(build_task_table(tasks))
    layout["agents"].update(build_agent_table(agents))

    layout["footer"].update(build_help_bar())

    return layout


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Swarm Dashboard")
    parser.add_argument(
        "--refresh", type=int, default=5, help="Refresh interval in seconds"
    )
    args = parser.parse_args()

    config = load_config()
    start_time = time.time()
    console = Console()

    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        console.print("\n[dim]Dashboard closed.[/dim]")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    console.print("[bold cyan]Starting swarm dashboard...[/bold cyan]")
    console.print(f"[dim]Refresh: {args.refresh}s  Project: {config.get('project_name', '?')}[/dim]")
    console.print()

    try:
        with Live(
            build_dashboard(config, start_time),
            refresh_per_second=1,
            console=console,
            screen=True,
        ) as live:
            while True:
                time.sleep(args.refresh)
                live.update(build_dashboard(config, start_time))
    except KeyboardInterrupt:
        pass

    console.print("\n[dim]Dashboard closed.[/dim]")


if __name__ == "__main__":
    main()
