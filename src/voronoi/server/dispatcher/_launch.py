"""Launch mixin for InvestigationDispatcher.

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




class _LaunchMixin:
    def _launch_investigation_safe(self, inv) -> None:
        """Wrapper around _launch_investigation that cleans up _launching and
        handles errors.  Runs in a background thread so dispatch_next returns
        immediately after claiming the investigation."""
        try:
            self._launch_investigation(inv)
        except Exception as e:
            logger.error("Failed to launch investigation #%d: %s", inv.id, e, exc_info=True)
            self.queue.fail(inv.id, str(e))
            label = inv.codename or f"#{inv.id}"
            self.send_message(
                f"💀 *Voronoi · {label} failed to launch*\n\nError: `{e}`"
            )
        finally:
            self._launching.discard(inv.id)

    def _launch_investigation(self, inv) -> None:
        from voronoi.server.repo_url import extract_repo_url

        # --- Continuation detection: reuse workspace from prior round ---
        is_continuation = (
            inv.parent_id is not None
            and inv.workspace_path
            and Path(inv.workspace_path).is_dir()
        )

        if is_continuation:
            workspace_path = Path(inv.workspace_path)
            logger.info("Continuation round %d for #%d — reusing workspace %s",
                        inv.cycle_number, inv.id, workspace_path)

            # Build the warm-start prompt BEFORE prepare_continuation()
            # deletes the checkpoint — the prompt needs checkpoint data (BUG-004).
            prompt = self._build_prompt(inv, workspace_path)

            # Prepare workspace: archive .swarm/, tag boundary, prune worktrees
            parent_inv = self.queue.get(inv.parent_id)
            if parent_inv:
                parent_run = RunningInvestigation(
                    investigation_id=parent_inv.id,
                    workspace_path=workspace_path,
                    tmux_session="",
                    question=parent_inv.question,
                    mode=parent_inv.mode,
                    codename=parent_inv.codename,
                    chat_id=parent_inv.chat_id,
                    rigor=parent_inv.rigor or "adaptive",
                )
                self.prepare_continuation(parent_run)

            # Refresh templates (agents, skills, scripts)
            self.workspace_mgr._voronoi_init(workspace_path)

            # Update queue with confirmed workspace path
            self.queue.start(inv.id, str(workspace_path))
        else:
            # Fresh workspace — normal provisioning
            if is_continuation is False and inv.parent_id is not None and inv.workspace_path:
                # Workspace was expected but is missing — warn and provision fresh
                logger.warning(
                    "Continuation workspace missing for #%d (expected %s) — provisioning fresh",
                    inv.id, inv.workspace_path,
                )

            repo_ref = extract_repo_url(inv.question) if inv.investigation_type == "repo" else None
            if repo_ref:
                ws = self.workspace_mgr.provision_repo(inv.id, repo_ref, inv.slug)
            else:
                ws = self.workspace_mgr.provision_lab(inv.id, inv.slug, inv.question)

            workspace_path = Path(ws.path)

            # Copy demo files into workspace if this investigation originated from a demo
            demo_info = self.queue.get_demo_source(inv.id)
            if demo_info:
                self._copy_demo_files(demo_info, workspace_path)

            self.queue.start(inv.id, ws.path)

        # Resolve rigor once — Investigation.rigor is always a non-empty str
        # (coerced by _row_to_investigation), no getattr/fallback needed.
        rigor = inv.rigor

        # Patch .swarm-config.json with rigor-mapped effort level
        self._patch_swarm_config(workspace_path, rigor)

        # For non-continuation launches, build the prompt now (continuations
        # built it earlier, before prepare_continuation deleted the checkpoint).
        if not is_continuation:
            prompt = self._build_prompt(inv, workspace_path)
        prompt_file = workspace_path / ".swarm" / "orchestrator-prompt.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(prompt)

        tmux_session = f"voronoi-inv-{inv.id}"
        self._launch_in_tmux(tmux_session, workspace_path, rigor=rigor)

        self.running[inv.id] = RunningInvestigation(
            investigation_id=inv.id,
            workspace_path=workspace_path,
            tmux_session=tmux_session,
            question=inv.question,
            mode=inv.mode,
            codename=inv.codename,
            chat_id=inv.chat_id,
            rigor=rigor,
        )

        logger.info("Investigation %s (#%d) LIVE in tmux=%s workspace=%s",
                    inv.codename, inv.id, tmux_session, workspace_path)

        label = inv.codename or f"#{inv.id}"
        self.send_message(format_launch(
            codename=label,
            mode=inv.mode,
            rigor=rigor,
            question=inv.question,
        ))

    def _build_prompt(self, inv, workspace_path: Path) -> str:
        from voronoi.server.prompt import build_orchestrator_prompt

        rigor = inv.rigor
        label = inv.codename or f"#{inv.id}"

        prior_context = None
        if inv.parent_id is not None:
            from voronoi.server.prompt import build_warm_start_context
            pi_feedback = inv.pi_feedback or ''
            lineage_id = inv.lineage_id or inv.parent_id
            prior_context = build_warm_start_context(
                lineage_id=lineage_id,
                cycle_number=inv.cycle_number,
                pi_feedback=pi_feedback,
                base_dir=self.config.base_dir,
                workspace=workspace_path,
            )

        return build_orchestrator_prompt(
            question=inv.question,
            mode=inv.mode,
            rigor=rigor,
            workspace_path=str(workspace_path),
            codename=label,
            max_agents=self.config.max_agents,
            prior_context=prior_context,
        )

    def _patch_swarm_config(self, workspace_path: Path, rigor: str) -> None:
        """Patch .swarm-config.json with rigor-derived effort and role permissions."""
        config_path = workspace_path / ".swarm-config.json"
        try:
            if config_path.exists():
                data = json.loads(config_path.read_text())
            else:
                data = {}
            effort = self._EFFORT_BY_RIGOR.get(rigor, "medium")
            data["effort"] = effort
            data.setdefault("role_permissions", {
                "scout": "--allow-all --deny-tool=write",
                "review_critic": "--allow-all --deny-tool=write",
                "review_stats": "--allow-all --deny-tool=write",
                "review_method": "--allow-all --deny-tool=write",
            })
            if self.config.worker_model:
                data["worker_model"] = self.config.worker_model
            config_path.write_text(json.dumps(data, indent=2))

            # Write .github/mcp-config.json for Copilot CLI MCP auto-discovery
            mcp_config_path = workspace_path / ".github" / "mcp-config.json"
            mcp_config_path.parent.mkdir(parents=True, exist_ok=True)
            mcp_config = {
                "mcpServers": {
                    "voronoi": {
                        "command": sys.executable or shutil.which("python3") or "python3",
                        "args": ["-m", "voronoi.mcp"],
                        "env": {"VORONOI_WORKSPACE": "."},
                    }
                }
            }
            mcp_config_path.write_text(json.dumps(mcp_config, indent=2))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to patch .swarm-config.json: %s", e)

    def _ensure_copilot_auth(self) -> None:
        """Delegate to tmux module."""
        ensure_copilot_auth()

    def _launch_in_tmux(self, session: str, workspace_path: Path,
                        prompt_file: Path | None = None,
                        rigor: str = "") -> None:
        """Delegate to tmux module."""
        launch_in_tmux(
            session=session,
            workspace_path=workspace_path,
            agent_command=self.config.agent_command,
            agent_flags=self.config.agent_flags,
            orchestrator_model=self.config.orchestrator_model,
            prompt_file=prompt_file,
            rigor=rigor,
        )

    def _copy_demo_files(self, demo_info: tuple[str, str], workspace_path: Path) -> None:
        """Copy demo directory contents into the workspace."""
        demo_name, demo_src_path = demo_info
        demo_src = Path(demo_src_path)
        if not demo_src.is_dir():
            logger.warning("Demo source not found: %s", demo_src)
            return
        demo_dst = workspace_path / "demos" / demo_name
        if demo_dst.exists():
            shutil.rmtree(demo_dst)
        shutil.copytree(demo_src, demo_dst)
        logger.info("Copied demo files from %s to %s", demo_src, demo_dst)

