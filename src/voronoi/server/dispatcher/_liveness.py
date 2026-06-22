"""Liveness mixin for InvestigationDispatcher.

Auto-extracted from dispatcher.py by scripts/split_dispatcher.py.
Do not edit method signatures here without updating tests."""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from voronoi.gateway.progress import (
    MODE_EMOJI, MODE_VERB,
    MSG_TYPE_MILESTONE, MSG_TYPE_STATUS,
    format_launch, format_complete, format_failure, format_alert,
    format_negative_result, format_restart, format_wake, format_pause,
    format_duration, phase_description,
    format_learning_stalled,
    build_digest,
)
from voronoi.server.tmux import (
    ensure_copilot_auth,
    launch_in_tmux,
    cleanup_tmux,
    EFFORT_BY_RIGOR,
)

logger = logging.getLogger("voronoi.dispatcher")


def _find_checkpoint(workspace: Path) -> Path | None:
    """Find the orchestrator checkpoint file.

    Delegates to the canonical ``voronoi.utils.find_checkpoint``.
    Kept as a module-level function for backward compatibility with
    internal callers.
    """
    from voronoi.utils import find_checkpoint
    return find_checkpoint(workspace)


from voronoi.utils import extract_field, is_finding_title  # noqa: E402


@dataclass
class DispatcherConfig:
    """Configuration for the dispatcher."""
    base_dir: Path = field(default_factory=lambda: Path.home() / ".voronoi")
    max_concurrent: int = 2
    max_agents: int = 6
    agent_command: str = "copilot"
    agent_flags: str = "--allow-all"
    orchestrator_model: str = ""  # e.g. "claude-opus-4.6", "" = CLI default
    worker_model: str = ""        # e.g. "claude-sonnet-4.6", "" = CLI default
    progress_interval: int = 30  # seconds between progress updates
    timeout_hours: int | None = None  # no default wall-clock kill; positive values are review budgets
    max_retries: int = 2         # max times to restart a dead agent
    stall_minutes: int = 45      # warn/restart if 0 tasks after this long
    pause_timeout_hours: int | None = None  # no default missed-message expiry
    context_advisory_hours: int = 6    # "prioritize convergence" directive
    context_warning_hours: int = 10    # "delegate remaining work" directive
    context_critical_hours: int = 14   # "dispatch Scribe NOW" directive
    compact_interval_hours: int = 6    # workspace state compaction interval
    max_context_restarts: int = 2      # max proactive context refreshes
    park_timeout_hours: int = 4        # force-wake parked orchestrator after this
    learning_stall_minutes: int = 20   # alert if no new findings/claims for this long
    # Self-steer stall escalation (cumulative minutes without learning).
    # Each strike writes a richer directive + belief-snapshot into
    # .swarm/stall-signal.json which the next orchestrator prompt injects.
    # Strike 1: directive = "diagnose_and_steer" (self-steer prompt #1)
    # Strike 2: directive = "pivot_or_declare" (self-steer prompt #2)
    # Strike 3: directive = "final_steer" (last self-steer, grace before partial review)
    # Strike 4: directive = "partial_review" (durable PI decision point)
    stall_strike1_minutes: int = 30
    stall_strike2_minutes: int = 60
    stall_strike3_minutes: int = 90
    stall_final_grace_minutes: int = 20


@dataclass
class RunningInvestigation:
    """Tracks a running investigation for progress monitoring."""
    investigation_id: int
    workspace_path: Path
    tmux_session: str
    question: str
    mode: str
    codename: str = ""
    chat_id: str = ""
    rigor: str = "adaptive"
    started_at: float = field(default_factory=time.time)
    last_update_at: float = 0
    task_snapshot: dict = field(default_factory=dict)
    notified_findings: set = field(default_factory=set)
    notified_paradigm_stress: bool = False
    phase: str = "starting"
    improvement_rounds: int = 0
    eval_score: float = 0.0
    retry_count: int = 0
    stall_warned: bool = False
    notified_design_invalid: set = field(default_factory=set)
    last_event_ts: float = 0  # For event log polling
    last_event_ts_by_path: dict[str, float] = field(default_factory=dict)
    last_digest_events: list[dict] = field(default_factory=list)  # For detail retrieval
    last_compact_at: float = 0  # Last workspace compaction timestamp
    context_directive_level: str = ""  # Last directive level sent
    context_restarts: int = 0  # Proactive context refreshes (separate from retry_count)
    status_message_id: int | None = None  # Telegram message ID for edit-in-place
    last_rigor: str = ""  # Track rigor escalation in DISCOVER mode
    pending_events: list[dict] = field(default_factory=list)  # Events accumulated while orchestrator is parked
    orchestrator_parked: bool = False  # True when orchestrator exited intentionally with active workers
    park_entered_at: float = 0  # When the current park began (for park_timeout_hours safety net)
    last_parked_digest_at: float = 0  # Last Telegram digest while parked (throttle to 5min)
    polling_strike_count: int = 0  # Consecutive polls where orchestrator pane was sleeping (BUG-003 watchdog)
    _criteria_alerts: set = field(default_factory=set)  # Track which criteria-progress alerts have fired
    _last_graph_health_verdict: str = ""  # Last graph-health verdict (INV-58); fire event only on transition
    _sentinel_missing_contract_warned: bool = False  # Track sentinel missing-contract warning
    notified_reversed_hypotheses: set = field(default_factory=set)  # Track which reversed hypotheses have been alerted
    last_convergence_attempt_at: float = 0  # Throttle _try_convergence_check() calls
    last_ledger_map: dict[str, str] = field(default_factory=dict)  # claim_id → status for delta detection
    _ledger_baseline_seeded: bool = False  # First poll seeds baseline without emitting deltas
    last_learning_activity_at: float = 0  # Last time a new finding/claim transition was observed
    stall_strike_level: int = 0  # Self-steer escalation: 0/1/2/3/4 (4 = partial review)
    stall_extension_expires_at: float = 0  # /extend grants stall immunity until this timestamp
    # Evidence-gated scaling: belief-map snapshot for detecting moves
    _prior_belief_snapshot: dict[str, str] = field(default_factory=dict)  # hypothesis_id → confidence tier

    @property
    def label(self) -> str:
        return self.codename or f"#{self.investigation_id}"

    @property
    def log_path(self) -> Path:
        return self.workspace_path / ".swarm" / "agent.log"

    def save_notification_state(self) -> None:
        """Persist notification tracking sets so they survive dispatcher restart."""
        state_path = self.workspace_path / ".swarm" / "dispatcher-notify-state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "notified_findings": sorted(self.notified_findings),
            "notified_design_invalid": sorted(self.notified_design_invalid),
            "notified_reversed_hypotheses": sorted(self.notified_reversed_hypotheses),
            "criteria_alerts": sorted(self._criteria_alerts),
            "sentinel_missing_contract_warned": self._sentinel_missing_contract_warned,
            "notified_paradigm_stress": self.notified_paradigm_stress,
        }
        try:
            state_path.write_text(json.dumps(data, indent=2))
        except OSError:
            pass

    def restore_notification_state(self) -> None:
        """Restore notification tracking sets from disk after dispatcher restart."""
        state_path = self.workspace_path / ".swarm" / "dispatcher-notify-state.json"
        if not state_path.exists():
            return
        try:
            data = json.loads(state_path.read_text())
            if not isinstance(data, dict):
                return
            self.notified_findings = set(data.get("notified_findings", []))
            self.notified_design_invalid = set(data.get("notified_design_invalid", []))
            self.notified_reversed_hypotheses = set(data.get("notified_reversed_hypotheses", []))
            self._criteria_alerts = set(data.get("criteria_alerts", []))
            self._sentinel_missing_contract_warned = bool(data.get("sentinel_missing_contract_warned"))
            self.notified_paradigm_stress = bool(data.get("notified_paradigm_stress"))
        except (json.JSONDecodeError, OSError):
            pass


# Module-level weak reference to the active dispatcher, used by
# handle_resume_investigation in the router to reach the dispatcher's
# resume_investigation() method without circular imports.
_active_dispatcher_ref: Optional["InvestigationDispatcher"] = None


def _active_dispatcher() -> Optional["InvestigationDispatcher"]:
    """Return the active dispatcher instance, or None."""
    return _active_dispatcher_ref




class _LivenessMixin:
    def _read_log_tail(self, run: RunningInvestigation, *, lines: int = 20) -> str:
        """Return the last N log lines for diagnostics."""
        if not run.log_path.exists():
            return ""
        try:
            raw = run.log_path.read_text(errors="replace")
        except OSError:
            return ""
        return "\n".join(raw.strip().splitlines()[-lines:])

    def _normalize_log_tail(self, log_tail: str) -> str:
        """Normalize tmux/copilot log output for heuristic matching."""
        if not log_tail:
            return ""

        normalized = log_tail.lower().replace("\r", "\n")
        normalized = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", " ", normalized)
        normalized = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", " ", normalized)
        normalized = re.sub(r"\[\?[0-9;]*[a-z]", " ", normalized)
        normalized = re.sub(r"\[<[^\s]+", " ", normalized)
        normalized = "".join(
            ch if ch.isprintable() or ch.isspace() else " "
            for ch in normalized
        )
        normalized = re.sub(r"[^a-z0-9/_:+.-]+", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    def _looks_like_clean_agent_exit(self, log_tail: str) -> bool:
        """Heuristically detect a normal Copilot CLI shutdown."""
        lowered = self._normalize_log_tail(log_tail)
        if not lowered:
            return False
        # Legacy markers (pre-2026 CLI) + current markers.
        # Require >= 2 hits to avoid false positives from random log lines.
        markers = (
            "logout",
            "total session time",
            "total usage est",
            "breakdown by ai model",
            # Current Copilot CLI (2026+) output format
            "session exported to",
            "requests",
            "tokens",
        )
        return sum(marker in lowered for marker in markers) >= 2

    def _bd_in_progress_task_ids(self, workspace: Path) -> list[str]:
        """Return Beads task IDs currently marked ``in_progress``.

        Used by ``_has_active_workers`` to reconcile a possibly-stale
        ``orchestrator-checkpoint.json`` against ground-truth task state
        (BUG-002).  Returns an empty list on any failure — the caller
        treats absence of bd data as "no extra workers to track".
        """
        try:
            from voronoi.beads import has_beads_dir, run_bd_json
            if not has_beads_dir(str(workspace)):
                return []
            code, parsed = run_bd_json(
                "list", "--status", "in_progress", "--json",
                cwd=str(workspace),
            )
        except Exception:  # pragma: no cover — beads module optional
            return []
        if code != 0 or not isinstance(parsed, list):
            return []
        ids: list[str] = []
        for task in parsed:
            if not isinstance(task, dict):
                continue
            tid = task.get("id")
            if isinstance(tid, str) and tid:
                ids.append(tid)
        return ids

    def _has_active_workers(self, run: RunningInvestigation) -> bool:
        """Check if the orchestrator exited with workers still running.

        Reads the checkpoint for ``active_workers`` and checks if any of
        those tmux windows are still alive in the swarm session.  Also
        checks for orphaned copilot processes whose cwd is inside the
        workspace (workers that survived after tmux cleanup).  If so,
        the orchestrator intentionally exited to conserve context and
        should NOT be restarted until the workers finish.

        Reconciles the checkpoint against Beads in-progress tasks
        (BUG-002): a stale checkpoint with ``active_workers=[]`` while
        bd reports ``in_progress`` tasks used to produce duplicate
        worker dispatch on restart.  We now cross-check both sources.
        """
        cp_path = _find_checkpoint(run.workspace_path)
        if cp_path is None:
            return False
        try:
            cp = json.loads(cp_path.read_text())
            if not isinstance(cp, dict):
                return False
        except (json.JSONDecodeError, OSError):
            return False

        # Coerce active_workers to list[str].  The spec types this as a list
        # of task-id strings, but the orchestrator writes the checkpoint
        # directly (bypassing MCP validation), and has been observed emitting
        # list[dict] entries like [{"id": "bd-123", "branch": "..."}].  Such
        # values would crash the downstream `worker in w` substring match
        # with "'in <string>' requires string as left operand, not dict".
        # Extract a string identifier from dict entries; drop anything else.
        raw_workers = cp.get("active_workers", [])
        workers: list[str] = []
        if isinstance(raw_workers, list):
            for item in raw_workers:
                if isinstance(item, str) and item:
                    workers.append(item)
                elif isinstance(item, dict):
                    for key in ("id", "task_id", "branch", "worker", "name"):
                        v = item.get(key)
                        if isinstance(v, str) and v:
                            workers.append(v)
                            break
        if workers and not all(isinstance(w, str)
                               for w in raw_workers if w is not None):
            logger.warning(
                "Investigation %s: checkpoint active_workers contained "
                "non-string entries; coerced to %r",
                run.label, workers,
            )

        # Reconcile with Beads: any in_progress task whose ID isn't already
        # covered by the checkpoint means a worker was dispatched but the
        # checkpoint is stale.  We add the task ID as a potential worker
        # identifier — tmux window names typically encode the task ID, so
        # the downstream substring match ("worker in w") will find it.
        for tid in self._bd_in_progress_task_ids(run.workspace_path):
            if tid and not any(tid in w for w in workers):
                workers.append(tid)

        if not workers:
            return False

        # Read the actual swarm session name from .swarm-config.json
        # (swarm-init.sh writes it as ${PROJECT_NAME}-swarm, which differs
        # from the dispatcher's session naming).
        swarm_session = None
        config_path = run.workspace_path / ".swarm-config.json"
        try:
            cfg = json.loads(config_path.read_text())
            if isinstance(cfg, dict):
                swarm_session = cfg.get("tmux_session")
        except (json.JSONDecodeError, OSError):
            pass
        if not swarm_session:
            swarm_session = run.tmux_session + "-swarm"
        # Check if the swarm tmux session exists at all (once, not per-worker)
        try:
            result = subprocess.run(
                ["tmux", "has-session", "-t", swarm_session],
                capture_output=True, timeout=5,
            )
            if result.returncode != 0:
                # Session gone — skip to orphan check
                workers = []
        except (subprocess.TimeoutExpired, OSError):
            workers = []

        for worker in workers:
            try:
                # BUG-003 FIX: Check for a window matching this worker AND
                # verify the process inside the pane is still a copilot/agent
                # process, not a dead shell. tmux windows survive after the
                # foreground process exits, leaving an idle bash prompt — we
                # must not treat those as "alive".
                #
                # Previous bug: `worker` is the short Beads ID like "bd-66",
                # but `list-windows` returns the full window name like
                # "agent-scribe-bd-66". The substring check `worker in w`
                # finds a match, but then `list-panes -t :bd-66` fails
                # because tmux needs the full window name. Fix: preserve the
                # matched window name and use tmux exact-match syntax.
                result = subprocess.run(
                    ["tmux", "list-windows", "-t", swarm_session, "-F",
                     "#{window_name}"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode != 0:
                    continue
                windows = result.stdout.strip().splitlines()
                
                # Find the full window name that matches this worker
                matched_window = None
                for w in windows:
                    if worker in w:
                        matched_window = w
                        break
                
                if not matched_window:
                    continue
                
                # Window exists — now check if the pane process is still
                # an agent (not just a leftover shell). Use tmux exact-match
                # syntax to target the specific window by its full name.
                pane_result = subprocess.run(
                    ["tmux", "list-panes", "-t",
                     f"{swarm_session}:={matched_window}", "-F",
                     "#{pane_current_command}"],
                    capture_output=True, text=True, timeout=5,
                )
                if pane_result.returncode == 0:
                    cmds = pane_result.stdout.strip().splitlines()
                    # A live worker has an agent process (copilot, claude,
                    # node, python, etc.) — not a bare shell
                    shell_names = {"bash", "zsh", "sh", "fish", "dash",
                                   "csh", "tcsh", "ksh", "login"}
                    if any(c.strip() and c.strip() not in shell_names
                           for c in cmds):
                        logger.debug("Worker %s still alive for %s "
                                     "(window=%s, pane_cmd=%s)",
                                     worker, run.label, matched_window,
                                     cmds[0] if cmds else "?")
                        return True
                    else:
                        logger.debug("Worker %s window exists but process "
                                     "exited (window=%s, pane_cmd=%s) for %s",
                                     worker, matched_window,
                                     cmds[0] if cmds else "?",
                                     run.label)
            except (subprocess.TimeoutExpired, OSError):
                continue

        # Fallback: check for orphaned copilot processes associated with
        # this workspace (workers that outlived their tmux window).  We
        # first grep argv for the workspace path, then fall back to
        # inspecting each PID's CWD via ``lsof`` — many agent CLIs
        # (copilot, claude, gemini) get the workspace as CWD, not argv,
        # so the argv-only check silently misses them (BUG-004).
        # ``pgrep -f`` (not ``-fa``) — macOS BSD pgrep lacks the ``-a`` flag.
        ws_str = str(run.workspace_path)
        try:
            result = subprocess.run(
                ["pgrep", "-f", self.config.agent_command],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                pids = [p.strip() for p in result.stdout.strip().splitlines()
                        if p.strip()]
                if pids:
                    ps_result = subprocess.run(
                        ["ps", "-p", ",".join(pids), "-o", "pid=,command="],
                        capture_output=True, text=True, timeout=10,
                    )
                    if ps_result.returncode == 0:
                        candidate_pids: list[str] = []
                        for line in ps_result.stdout.strip().splitlines():
                            parts = line.strip().split(None, 1)
                            if not parts:
                                continue
                            pid_str = parts[0]
                            cmdline = parts[1] if len(parts) > 1 else ""
                            if ws_str in cmdline:
                                logger.debug("Orphaned worker process "
                                             "(argv match) for %s: %s",
                                             run.label, line[:120])
                                return True
                            candidate_pids.append(pid_str)
                        # argv didn't match — check CWD for each candidate.
                        if candidate_pids and self._any_pid_cwd_in_workspace(
                                candidate_pids, run.workspace_path):
                            return True
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

        # No live workers found — workers finished, proceed with restart
        logger.info("All active_workers done for %s, proceeding with restart",
                    run.label)
        return False

    def _any_pid_cwd_in_workspace(self, pids: list[str],
                                   workspace_path: Path) -> bool:
        """Return True if any PID's current working directory is inside
        ``workspace_path`` (or a subdirectory, e.g. a worktree).

        Uses ``lsof -a -p <pid> -d cwd -Fn`` which works on macOS and Linux
        and emits ``n<path>`` lines for the CWD entry.  Missing ``lsof`` or
        any per-PID failure is treated as "no match" — callers should
        already have covered the common case via argv substring matching.
        """
        if not pids:
            return False
        ws_resolved = workspace_path.resolve()
        for pid in pids:
            try:
                result = subprocess.run(
                    ["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"],
                    capture_output=True, text=True, timeout=5,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                return False  # lsof unavailable — bail out of the fallback
            if result.returncode != 0:
                continue
            for line in result.stdout.splitlines():
                if not line.startswith("n"):
                    continue
                cwd_str = line[1:].strip()
                if not cwd_str:
                    continue
                try:
                    cwd = Path(cwd_str).resolve()
                except OSError:
                    continue
                if cwd == ws_resolved or ws_resolved in cwd.parents:
                    logger.debug("Orphaned worker process (cwd match) "
                                 "pid=%s cwd=%s workspace=%s",
                                 pid, cwd, ws_resolved)
                    return True
        return False

    def _looks_like_auth_failure(self, log_tail: str) -> bool:
        """Detect auth-related failures in agent log output."""
        lowered = self._normalize_log_tail(log_tail)
        if not lowered:
            return False
        auth_markers = (
            "authenticate",
            "copilot login",
            "gh auth login",
            "copilot_github_token",
            "gh_token",
            "github_token",
            "oauth token",
            "fine-grained personal access token",
            "authentication required",
            "credentials",
            "/login",
        )
        return sum(marker in lowered for marker in auth_markers) >= 3

    def _classify_incomplete_exit(self, run: RunningInvestigation) -> str:
        """Describe why a dead agent session is incomplete."""
        log_tail = self._read_log_tail(run)
        if not self._looks_like_clean_agent_exit(log_tail):
            return "Agent exited unexpectedly"

        blockers: list[str] = []
        deliverable = run.workspace_path / ".swarm" / "deliverable.md"
        if not deliverable.exists():
            blockers.append("no deliverable produced")

        try:
            from voronoi.science import check_convergence

            effective_rigor = self._effective_rigor(run)
            result = check_convergence(
                run.workspace_path,
                effective_rigor,
                eval_score=run.eval_score,
                improvement_rounds=run.improvement_rounds,
            )
            if result.reason:
                blockers.append(result.reason)
        except Exception as e:
            logger.debug("Failed to classify incomplete exit for %s: %s",
                         run.label, e)

        unique_blockers: list[str] = []
        seen: set[str] = set()
        for blocker in blockers:
            normalized = blocker.strip().rstrip(".")
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            unique_blockers.append(normalized)

        if unique_blockers:
            return "Agent exited cleanly before convergence: " + "; ".join(unique_blockers)
        return "Agent exited cleanly before completion"

    def _needs_orchestrator(self, run: RunningInvestigation) -> bool:
        """Decide whether to wake the parked orchestrator.

        Called each poll cycle while the orchestrator is parked (exited
        intentionally with ``active_workers``).  Returns True if an event
        has occurred that requires the orchestrator's scientific judgment:

        - All active workers have finished (normal wake)
        - DESIGN_INVALID detected in any open task (urgent)
        - Workers are no longer alive (process died)

        Findings and serendipity are accumulated in ``pending_events`` and
        delivered in the resume prompt — they do NOT trigger an immediate
        wake because they are not time-sensitive.
        """
        # 1. Are any workers still alive?
        if not self._has_active_workers(run):
            logger.info("All workers done for %s, waking orchestrator", run.label)
            return True

        # 2. DESIGN_INVALID in any open task (urgent — needs strategic response)
        from voronoi.beads import run_bd_json
        code, tasks = run_bd_json("list", "--json", cwd=str(run.workspace_path))
        if code == 0 and isinstance(tasks, list):
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                tid = task.get("id", "")
                notes = task.get("notes", "")
                status = task.get("status", "")
                if (status != "closed"
                        and "DESIGN_INVALID" in notes.upper()
                        and tid not in run.notified_design_invalid):
                    logger.warning("DESIGN_INVALID detected in %s while parked — "
                                   "waking orchestrator", tid)
                    return True

        return False

