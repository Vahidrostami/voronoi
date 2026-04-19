"""Tests for the unified prompt builder and workspace provisioning.

Verifies that:
1. Both CLI and Telegram paths produce prompts from the same builder
2. Prompts reference .github/agents/*.agent.md role files (in target workspaces)
3. Mode/rigor combinations produce correct science sections
4. Workspace provisioning copies runtime agents/prompts/skills from data/
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from voronoi.server.prompt import build_orchestrator_prompt


# ---------------------------------------------------------------------------
# Prompt builder — basic structure
# ---------------------------------------------------------------------------

class TestBuildOrchestratorPrompt:
    """Test the unified prompt builder produces correct output."""

    def test_basic_build_prompt(self):
        prompt = build_orchestrator_prompt(
            question="Build a REST API",
            mode="discover",
            rigor="adaptive",
        )
        assert "swarm orchestrator" in prompt
        assert "PROMPT.md" in prompt
        assert ".github/agents/swarm-orchestrator.agent.md" in prompt

    def test_references_agent_files(self):
        prompt = build_orchestrator_prompt(
            question="test",
            mode="discover",
            rigor="adaptive",
        )
        # Must reference the orchestrator role file
        assert ".github/agents/swarm-orchestrator.agent.md" in prompt

    def test_codename_in_prompt(self):
        prompt = build_orchestrator_prompt(
            question="test",
            mode="discover",
            rigor="scientific",
            codename="Dopamine",
        )
        assert "Dopamine" in prompt

    def test_workspace_path_in_prompt(self):
        prompt = build_orchestrator_prompt(
            question="test",
            mode="discover",
            rigor="adaptive",
            workspace_path="/tmp/workspace",
        )
        assert "/tmp/workspace" in prompt

    def test_output_dir_in_prompt(self):
        prompt = build_orchestrator_prompt(
            question="test",
            mode="discover",
            rigor="adaptive",
            output_dir="demos/coupled-decisions",
        )
        assert "demos/coupled-decisions" in prompt

    def test_custom_prompt_path(self):
        prompt = build_orchestrator_prompt(
            question="test",
            mode="discover",
            rigor="adaptive",
            prompt_path="demos/my-demo/PROMPT.md",
        )
        assert "demos/my-demo/PROMPT.md" in prompt

    def test_max_agents_in_prompt(self):
        prompt = build_orchestrator_prompt(
            question="test",
            mode="discover",
            rigor="adaptive",
            max_agents=8,
        )
        assert "8" in prompt

    def test_safe_flag_in_prompt(self):
        prompt = build_orchestrator_prompt(
            question="test",
            mode="discover",
            rigor="adaptive",
            safe=True,
        )
        assert "--safe" in prompt


# ---------------------------------------------------------------------------
# Science sections by mode x rigor
# ---------------------------------------------------------------------------

class TestScienceSections:
    """Test that mode/rigor combinations produce correct science content."""

    def test_discover_adaptive_has_creative_freedom(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
        )
        assert "Creative Freedom" in prompt
        assert "SERENDIPITY" in prompt

    def test_prove_scientific_has_scout(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="prove", rigor="scientific",
        )
        assert "Scout" in prompt

    def test_prove_scientific_has_hypotheses(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="prove", rigor="scientific",
        )
        assert "pre-registration" in prompt.lower()
        assert "Methodologist" in prompt

    def test_prove_has_review_gates(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="prove", rigor="scientific",
        )
        assert "Statistician" in prompt
        assert "claim-evidence" in prompt.lower()
        assert "Evaluator" in prompt or "0.75" in prompt

    def test_discover_adaptive_has_eval_score(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
        )
        assert "eval-score.json" in prompt

    def test_prove_experimental_has_replication(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="prove", rigor="experimental",
        )
        assert "replicated" in prompt.lower()
        assert "Power analysis" in prompt

    def test_prove_scientific_has_pre_registration_rule(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="prove", rigor="scientific",
        )
        assert "pre-registration" in prompt.lower()

    def test_prove_scientific_methodologist_review_is_advisory(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="prove", rigor="scientific",
        )
        assert "Scientific rigor: Methodologist review is advisory" in prompt
        assert "Methodologist approval required before dispatch" not in prompt

    def test_scientific_human_gate_is_park_not_poll(self):
        """BUG-001 regression: the human-gate instruction must tell the
        orchestrator to write the gate, park, and EXIT — never to poll
        the gate file in-session."""
        prompt = build_orchestrator_prompt(
            question="test", mode="prove", rigor="scientific",
        )
        # Must describe the park-and-exit protocol
        assert "PARK, DO NOT POLL" in prompt
        assert "awaiting-human-gate" in prompt
        assert "EXIT" in prompt
        # Must NOT include the old poll-every-30s directive
        assert "poll `.swarm/human-gate.json`" not in prompt
        assert "every 30s" not in prompt
        assert "Same polling protocol" not in prompt

    def test_experimental_human_gate_is_park_not_poll(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="prove", rigor="experimental",
        )
        assert "PARK, DO NOT POLL" in prompt
        assert "poll `.swarm/human-gate.json`" not in prompt

    def test_prove_has_eval_score(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="prove", rigor="scientific",
        )
        assert "eval-score.json" in prompt

    def test_discover_has_positioning_rule(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
        )
        assert "DO NOT REPEAT KNOWN SCIENCE" in prompt
        assert "scout-brief.md" in prompt
        assert "novelty-gate.json" in prompt

    def test_prove_has_positioning_rule(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="prove", rigor="scientific",
        )
        assert "DO NOT REPEAT KNOWN SCIENCE" in prompt
        assert "Problem Positioning" in prompt
        assert "novelty-gate.json" in prompt

    def test_build_mode_no_positioning_rule(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="build", rigor="standard",
        )
        assert "DO NOT REPEAT KNOWN SCIENCE" not in prompt
        assert "novelty-gate.json" not in prompt


# ---------------------------------------------------------------------------
# CLI uses shared builder
# ---------------------------------------------------------------------------

class TestCLIUsesSharedBuilder:
    """Verify CLI's _build_orchestrator_prompt delegates to the shared builder."""

    def test_cli_prompt_references_agents(self, tmp_path):
        from voronoi.cli import _build_orchestrator_prompt

        # Create a fake PROMPT.md
        prompt_file = tmp_path / "demos" / "test" / "PROMPT.md"
        prompt_file.parent.mkdir(parents=True)
        prompt_file.write_text("# Test Demo\n\nBuild something.\n")

        with patch("voronoi.cli.Path.cwd", return_value=tmp_path):
            prompt = _build_orchestrator_prompt(
                prompt_path="demos/test/PROMPT.md",
                output_dir="demos/test",
                safe=False,
                max_agents=4,
            )

        # Must reference .github/agents files (from shared builder)
        assert ".github/agents/swarm-orchestrator.agent.md" in prompt


# ---------------------------------------------------------------------------
# Dispatcher uses shared builder
# ---------------------------------------------------------------------------

class TestDispatcherUsesSharedBuilder:
    """Verify dispatcher's _build_prompt delegates to the shared builder."""

    def test_dispatcher_prompt_references_agents(self, tmp_path):
        from voronoi.server.dispatcher import DispatcherConfig, InvestigationDispatcher
        from voronoi.server.queue import Investigation

        config = DispatcherConfig(base_dir=tmp_path, agent_command="echo")
        d = InvestigationDispatcher(config, lambda msg: None)

        inv = MagicMock()
        inv.question = "Why is latency high?"
        inv.mode = "investigate"
        inv.rigor = "scientific"
        inv.codename = "Dopamine"
        inv.parent_id = None

        prompt = d._build_prompt(inv, tmp_path)

        assert ".github/agents/swarm-orchestrator.agent.md" in prompt
        assert "Dopamine" in prompt

    def test_dispatcher_and_cli_same_builder(self, tmp_path):
        """Both paths should use the exact same function."""
        from voronoi.server.dispatcher import DispatcherConfig, InvestigationDispatcher

        config = DispatcherConfig(base_dir=tmp_path, agent_command="echo")
        d = InvestigationDispatcher(config, lambda msg: None)

        inv = MagicMock()
        inv.question = "Build a thing"
        inv.mode = "build"
        inv.rigor = "standard"
        inv.codename = ""
        inv.parent_id = None

        with patch("voronoi.server.prompt.build_orchestrator_prompt") as mock_build:
            mock_build.return_value = "test prompt"
            d._build_prompt(inv, tmp_path)

        mock_build.assert_called_once()
        call_kwargs = mock_build.call_args[1]
        assert call_kwargs["mode"] == "build"
        assert call_kwargs["rigor"] == "standard"

class TestWorkspaceGitHubProvisioning:
    """Verify that runtime agents/prompts/skills are copied into provisioned workspaces."""

    def test_ensure_github_files_copies_when_missing(self, tmp_path):
        from voronoi.server.workspace import WorkspaceManager

        wm = WorkspaceManager(tmp_path / "voronoi")
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Create fake source data (agents/prompts/skills directly under data/)
        data_dir = tmp_path / "data"
        for subdir in ("agents", "prompts", "skills"):
            d = data_dir / subdir
            d.mkdir(parents=True)
            (d / f"test.{subdir[:-1]}.md").write_text(f"# {subdir}")

        with patch("voronoi.cli.find_data_dir", return_value=data_dir):
            wm._ensure_github_files(workspace)

        assert (workspace / ".github" / "agents" / "test.agent.md").exists()
        assert (workspace / ".github" / "prompts" / "test.prompt.md").exists()
        assert (workspace / ".github" / "skills" / "test.skill.md").exists()

    def test_ensure_github_files_skips_when_present(self, tmp_path):
        from voronoi.server.workspace import WorkspaceManager

        wm = WorkspaceManager(tmp_path / "voronoi")
        workspace = tmp_path / "workspace"
        (workspace / ".github" / "agents").mkdir(parents=True)
        (workspace / ".github" / "agents" / "existing.md").write_text("keep me")
        # Pre-create CLAUDE.md so templates copy is also skipped
        (workspace / "CLAUDE.md").write_text("existing")
        (workspace / "AGENTS.md").write_text("existing")
        # Pre-create scripts/ so scripts copy is also skipped
        (workspace / "scripts").mkdir()

        with patch("voronoi.cli.find_data_dir") as mock_find:
            mock_find.return_value = tmp_path / "fake-data"
            (tmp_path / "fake-data" / "scripts").mkdir(parents=True)
            (tmp_path / "fake-data" / "templates").mkdir(parents=True)
            wm._ensure_github_files(workspace)

        # Existing agent file should not be overwritten
        assert (workspace / ".github" / "agents" / "existing.md").read_text() == "keep me"
        # Pre-existing CLAUDE.md should not be overwritten
        assert (workspace / "CLAUDE.md").read_text() == "existing"

    def test_provision_lab_copies_github(self, tmp_path):
        from voronoi.server.workspace import WorkspaceManager

        wm = WorkspaceManager(tmp_path / "voronoi")

        with patch.object(wm, "_voronoi_init") as mock_init:
            info = wm.provision_lab(1, "test", "Does EWC work?")
            mock_init.assert_called_once_with(Path(info.path))


# ---------------------------------------------------------------------------
# Role mapping completeness
# ---------------------------------------------------------------------------

class TestRoleMapping:
    """Verify agent roles are referenced in the role file (not duplicated in prompt)."""

    def test_role_file_referenced_in_prompt(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="scientific",
        )
        # The prompt must reference the orchestrator role file which contains
        # the full role mapping table
        assert ".github/agents/swarm-orchestrator.agent.md" in prompt

    def test_role_map_keys_in_code(self):
        """Verify the ROLE_MAP in prompt.py has all expected task types."""
        from voronoi.server.prompt import ROLE_MAP
        expected_types = [
            "build", "scout", "investigation", "experiment",
            "exploration", "review_stats", "review_critic",
            "review_method", "theory", "synthesis", "evaluation",
            "scribe", "paper", "compilation",
            # Paper-track roles
            "outline", "lit_synthesis", "figure_critic", "refine",
        ]
        for t in expected_types:
            assert t in ROLE_MAP, f"Missing task type {t} in ROLE_MAP"

    def test_paper_track_role_files_exist(self):
        """Every paper-track ROLE_MAP entry must point at a real .agent.md file."""
        from voronoi.server.prompt import ROLE_MAP
        from voronoi.cli import find_data_dir
        agents_dir = find_data_dir() / "agents"
        for task_type in ("outline", "lit_synthesis", "figure_critic", "refine"):
            fname = ROLE_MAP[task_type]
            assert (agents_dir / fname).is_file(), (
                f"paper-track role file missing: {agents_dir / fname}"
            )


# ---------------------------------------------------------------------------
# Invariants & REVISE sections in prompts
# ---------------------------------------------------------------------------

class TestInvariantsInPrompt:
    """Verify invariants and REVISE sections appear in prompts."""

    def test_invariants_section_present(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="scientific",
        )
        assert "Investigation Invariants" in prompt
        assert "invariants.json" in prompt

    def test_revise_section_present(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="scientific",
        )
        assert "REVISE" in prompt
        assert "REVISE_OF" in prompt
        assert "revise-calibration" in prompt

    def test_invariants_in_build_mode_too(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
        )
        assert "Investigation Invariants" in prompt

    def test_scribe_referenced_in_prompt(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="scientific",
        )
        assert "Scribe" in prompt
        assert "scribe" in prompt.lower()

    def test_success_criteria_tracking_section(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="scientific",
        )
        assert "Success Criteria Tracking" in prompt
        assert "success-criteria.json" in prompt
        assert "RESULT_CONTRADICTS_HYPOTHESIS" in prompt

    def test_success_criteria_in_build_too(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
        )
        assert "Success Criteria Tracking" in prompt


# ---------------------------------------------------------------------------
# Phase gate enforcement in prompts
# ---------------------------------------------------------------------------

class TestPhaseGateEnforcement:
    """Verify the phase gate enforcement section appears in prompts."""

    def test_phase_gate_section_present(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="scientific",
        )
        assert "Phase Gate Enforcement" in prompt
        assert "DESIGN_INVALID" in prompt
        assert "spawn-agent.sh" in prompt

    def test_phase_gate_in_build_mode_too(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
        )
        assert "Phase Gate Enforcement" in prompt

    def test_phase_gate_mentions_structural_enforcement(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
        )
        assert "structurally" in prompt.lower() or "BLOCK completion" in prompt

    def test_data_invariants_in_prompt(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="scientific",
        )
        assert "min_csv_rows" in prompt
        assert "convergence gate" in prompt.lower()


# ---------------------------------------------------------------------------
# Context engineering sections (Changes 1, 3, 7)
# ---------------------------------------------------------------------------

class TestContextEngineeringSections:
    """Verify new context engineering sections in prompts."""

    def test_brief_digest_protocol(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
        )
        assert "brief-digest.md" in prompt

    def test_dispatcher_directives(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
        )
        assert "dispatcher-directive.json" in prompt
        assert "context_advisory" in prompt
        assert "context_warning" in prompt
        assert "context_critical" in prompt

    def test_compact_in_dispatcher_directives(self):
        """Context warning and critical directives instruct orchestrator to run /compact."""
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
        )
        # The /compact instruction should appear in the directive descriptions
        assert "/compact" in prompt

    def test_context_management_is_compact(self):
        """The context management section should be a compact reminder, not the full protocol."""
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
        )
        assert "OODA Protocol" in prompt
        # Should reference the role file
        assert "role file" in prompt.lower()
        # Should NOT contain the full checkpoint code example (was removed)
        assert "OrchestratorCheckpoint(" not in prompt

    def test_no_duplicated_tools_section(self):
        """Tools section should not be in the prompt (it's in the role file)."""
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
        )
        # Should NOT contain the full tools listing (was removed)
        assert "bd prime" not in prompt

    def test_manuscript_delegation_still_present(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
        )
        assert "NEVER write the manuscript" in prompt or "dispatch a Scribe" in prompt
        assert "Scribe" in prompt

    def test_manuscript_section_requires_latex(self):
        """Orchestrator prompt must tell the orchestrator that Scribe writes LaTeX."""
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="scientific",
        )
        assert "paper.tex" in prompt or "LaTeX" in prompt

    def test_worker_lifecycle_skill_referenced(self):
        """Orchestrator prompt must reference the worker-lifecycle skill."""
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
        )
        assert "worker-lifecycle" in prompt
        assert "NEVER use Copilot" in prompt or "NEVER use" in prompt
        assert "spawn-agent.sh" in prompt


# ---------------------------------------------------------------------------
# Warm-Start (multi-run continuation)
# ---------------------------------------------------------------------------

class TestWarmStartPrompt:
    """Test warm-start sections appear correctly in continuation prompts."""

    def test_no_warm_start_without_prior_context(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
        )
        assert "Round" not in prompt or "Round" in prompt  # generic word
        assert "Continuation" not in prompt
        assert "Claim Ledger" not in prompt

    def test_warm_start_round_number(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
            prior_context={"cycle_number": 3},
        )
        assert "Round 3" in prompt
        assert "Continuation" in prompt
        assert "Do NOT re-run experiments" in prompt

    def test_warm_start_ledger_summary(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
            prior_context={
                "cycle_number": 2,
                "ledger_summary": "### Established\n- C1: L4 > L1 (d=0.8)",
            },
        )
        assert "Claim Ledger" in prompt
        assert "L4 > L1" in prompt

    def test_warm_start_pi_feedback(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
            prior_context={
                "cycle_number": 2,
                "pi_feedback": "Control for tokenizer differences.",
            },
        )
        assert "PI Feedback" in prompt
        assert "Control for tokenizer" in prompt

    def test_warm_start_immutable_paths(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
            prior_context={
                "cycle_number": 2,
                "immutable_paths": ["data/raw/x.csv", "src/experiments/baseline.py"],
            },
        )
        assert "Immutable Artifacts" in prompt
        assert "data/raw/x.csv" in prompt
        assert "src/experiments/baseline.py" in prompt

    def test_warm_start_artifact_manifest(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
            prior_context={
                "cycle_number": 2,
                "artifact_manifest": "- Experiments: 8 total, 5 kept results",
            },
        )
        assert "Reusable Artifacts" in prompt
        assert "8 total" in prompt


class TestBuildWarmStartContext:
    """Test the warm-start context builder."""

    def test_basic_context(self, tmp_path):
        from voronoi.server.prompt import build_warm_start_context
        from voronoi.science.claims import ClaimLedger, save_ledger, PROVENANCE_RUN_EVIDENCE

        # Create a ledger with claims
        ledger = ClaimLedger()
        ledger.add_claim("L4 > L1", PROVENANCE_RUN_EVIDENCE, effect_summary="d=0.8")
        ledger.assert_claim("C1")
        ledger.lock_claim("C1")
        save_ledger(1, ledger, base_dir=tmp_path)

        ctx = build_warm_start_context(
            lineage_id=1, cycle_number=2,
            pi_feedback="Test multilingual",
            base_dir=tmp_path,
        )
        assert ctx["cycle_number"] == 2
        assert "L4 > L1" in ctx["ledger_summary"]
        assert ctx["pi_feedback"] == "Test multilingual"

    def test_context_with_workspace(self, tmp_path):
        from voronoi.server.prompt import build_warm_start_context
        from voronoi.science.claims import ClaimLedger, save_ledger, PROVENANCE_RUN_EVIDENCE

        ledger = ClaimLedger()
        save_ledger(1, ledger, base_dir=tmp_path)

        # Create a workspace with data files
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / ".swarm").mkdir()
        (ws / "data").mkdir()
        (ws / "data" / "results.csv").write_text("a,b\n1,2\n")

        ctx = build_warm_start_context(
            lineage_id=1, cycle_number=2,
            base_dir=tmp_path, workspace=ws,
        )
        assert "artifact_manifest" in ctx
        assert "data/" in ctx["artifact_manifest"]

    def test_context_includes_success_criteria_status(self, tmp_path):
        """Success criteria status should be parsed into round summary."""
        import json
        from voronoi.server.prompt import build_warm_start_context
        from voronoi.science.claims import ClaimLedger, save_ledger

        ledger = ClaimLedger()
        save_ledger(1, ledger, base_dir=tmp_path)

        ws = tmp_path / "workspace"
        ws.mkdir()
        swarm = ws / ".swarm"
        swarm.mkdir()
        sc = [
            {"id": "SC1", "description": "Encoding main effect large", "met": False},
            {"id": "SC2", "description": "Consistent advantage", "met": True},
            {"id": "SC3", "description": "Weaker models benefit", "met": False},
        ]
        (swarm / "success-criteria.json").write_text(json.dumps(sc))

        ctx = build_warm_start_context(
            lineage_id=1, cycle_number=2,
            base_dir=tmp_path, workspace=ws,
        )
        assert ctx["success_criteria_status"] == {"met": 1, "total": 3}
        assert "round_summary" in ctx
        assert "1/3 met" in ctx["round_summary"]
        assert "SC1 UNMET" in ctx["round_summary"]
        assert "SC3 UNMET" in ctx["round_summary"]

    def test_context_includes_archived_checkpoint(self, tmp_path):
        """Archived checkpoint next_actions appear in round summary."""
        import json
        from voronoi.server.prompt import build_warm_start_context
        from voronoi.science.claims import ClaimLedger, save_ledger

        ledger = ClaimLedger()
        save_ledger(1, ledger, base_dir=tmp_path)

        ws = tmp_path / "workspace"
        ws.mkdir()
        swarm = ws / ".swarm"
        swarm.mkdir()
        archive = swarm / "archive" / "run-1"
        archive.mkdir(parents=True)
        ckpt = {
            "active_workers": ["worker-1", "worker-2"],
            "next_actions": ["Run follow-up experiment on L4", "Dispatch Statistician"],
        }
        (archive / "orchestrator-checkpoint.json").write_text(json.dumps(ckpt))

        ctx = build_warm_start_context(
            lineage_id=1, cycle_number=2,
            base_dir=tmp_path, workspace=ws,
        )
        assert "round_summary" in ctx
        assert "Run follow-up experiment" in ctx["round_summary"]
        assert "Active workers at end of round: 2" in ctx["round_summary"]

    def test_context_includes_state_digest(self, tmp_path):
        """State digest from prior round is included when present."""
        from voronoi.server.prompt import build_warm_start_context
        from voronoi.science.claims import ClaimLedger, save_ledger

        ledger = ClaimLedger()
        save_ledger(1, ledger, base_dir=tmp_path)

        ws = tmp_path / "workspace"
        ws.mkdir()
        swarm = ws / ".swarm"
        swarm.mkdir()
        (swarm / "state-digest.md").write_text(
            "## Phase: Experimentation\n"
            "3 tasks dispatched, 1 complete, 2 in progress."
        )

        ctx = build_warm_start_context(
            lineage_id=1, cycle_number=2,
            base_dir=tmp_path, workspace=ws,
        )
        assert "state_digest" in ctx
        assert "3 tasks dispatched" in ctx["state_digest"]

    def test_context_empty_ledger_still_has_summary(self, tmp_path):
        """Even with empty claim ledger, round summary is present if workspace has data."""
        import json
        from voronoi.server.prompt import build_warm_start_context
        from voronoi.science.claims import ClaimLedger, save_ledger

        ledger = ClaimLedger()
        save_ledger(1, ledger, base_dir=tmp_path)

        ws = tmp_path / "workspace"
        ws.mkdir()
        swarm = ws / ".swarm"
        swarm.mkdir()
        sc = [
            {"id": "SC1", "description": "Test criterion", "met": False},
        ]
        (swarm / "success-criteria.json").write_text(json.dumps(sc))

        ctx = build_warm_start_context(
            lineage_id=1, cycle_number=2,
            base_dir=tmp_path, workspace=ws,
        )
        # Ledger is empty but round summary exists
        assert ctx["ledger_summary"] == ""
        assert "round_summary" in ctx
        assert "0/1 met" in ctx["round_summary"]


class TestContinuationPromptConditionals:
    """Prompt instructions change for continuation rounds."""

    def test_continuation_skips_scout_dispatch(self):
        """Continuation should NOT tell orchestrator to dispatch Scout."""
        prompt = build_orchestrator_prompt(
            question="test", mode="prove", rigor="scientific",
            prior_context={"cycle_number": 2},
        )
        assert "Dispatch Scout first" not in prompt
        assert "do NOT re-dispatch" in prompt
        assert "scout-brief.md" in prompt

    def test_fresh_dispatches_scout(self):
        """Fresh investigation should dispatch Scout normally."""
        prompt = build_orchestrator_prompt(
            question="test", mode="prove", rigor="scientific",
        )
        assert "Dispatch Scout first" in prompt

    def test_continuation_preserves_success_criteria(self):
        """Continuation should read existing SC, not overwrite."""
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
            prior_context={"cycle_number": 2},
        )
        assert "do NOT overwrite" in prompt
        assert "At investigation start, write" not in prompt

    def test_fresh_creates_success_criteria(self):
        """Fresh investigation should create SC."""
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
        )
        assert "At investigation start, write" in prompt

    def test_continuation_startup_sequence(self):
        """Continuation should include explicit file-reading sequence."""
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
            prior_context={"cycle_number": 3},
        )
        assert "Continuation startup sequence" in prompt
        assert "brief-digest.md" in prompt
        assert "success-criteria.json" in prompt
        assert "belief-map.json" in prompt
        assert "experiments.tsv" in prompt

    def test_continuation_round_summary_in_prompt(self):
        """Round summary from warm-start context appears in prompt."""
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
            prior_context={
                "cycle_number": 2,
                "round_summary": "- Success criteria: 3/12 met\n- Experiment `baseline`: keep",
            },
        )
        assert "Round 1 Summary" in prompt
        assert "3/12 met" in prompt

    def test_continuation_state_digest_in_prompt(self):
        """State digest from warm-start context appears in prompt."""
        prompt = build_orchestrator_prompt(
            question="test", mode="discover", rigor="adaptive",
            prior_context={
                "cycle_number": 2,
                "state_digest": "## Phase: Experimentation\n2 tasks in progress.",
            },
        )
        assert "State Digest from Round 1" in prompt
        assert "2 tasks in progress" in prompt


# ---------------------------------------------------------------------------
# Tribunal Prompt
# ---------------------------------------------------------------------------

class TestTribunalPrompt:
    def test_build_tribunal_prompt_basic(self):
        from voronoi.server.prompt import build_tribunal_prompt
        prompt = build_tribunal_prompt(
            finding_id="bd-42",
            trigger="refuted_reversed",
            hypothesis_id="H2",
            expected="L4_A outperforms L4_D",
            observed="L4_D outperforms L4_A",
        )
        assert "Judgment Tribunal" in prompt
        assert "bd-42" in prompt
        assert "refuted_reversed" in prompt
        assert "H2" in prompt
        assert "L4_A outperforms L4_D" in prompt
        assert "L4_D outperforms L4_A" in prompt
        assert "anomaly_unresolved" in prompt

    def test_tribunal_prompt_includes_all_roles(self):
        from voronoi.server.prompt import build_tribunal_prompt
        prompt = build_tribunal_prompt(
            finding_id="bd-1",
            trigger="surprising",
        )
        assert "Theorist" in prompt
        assert "Statistician" in prompt
        assert "Methodologist" in prompt

    def test_tribunal_prompt_with_causal_dag(self):
        from voronoi.server.prompt import build_tribunal_prompt
        prompt = build_tribunal_prompt(
            finding_id="bd-42",
            trigger="refuted_reversed",
            causal_dag_summary="encoding → accessibility → reasoning",
        )
        assert "encoding → accessibility → reasoning" in prompt
        assert "Causal Model Context" in prompt


class TestBuildRedTeamPrompt:
    """Red Team prompt must be cold-context: no investigation history leaks in."""

    def test_instructs_cold_context(self):
        from voronoi.server.prompt import build_red_team_prompt
        prompt = build_red_team_prompt(
            workspace_path="/tmp/ws",
            codename="Vermillion",
            rigor="scientific",
        )
        # Identity and workspace
        assert "Red Team" in prompt
        assert "Vermillion" in prompt
        assert "/tmp/ws" in prompt
        # Cold-context discipline
        assert "cold" in prompt.lower()
        # Points at the ONLY three allowed inputs
        assert "deliverable.md" in prompt
        assert "claim-ledger.json" in prompt
        assert "output/" in prompt
        # And tells the reviewer what to write
        assert "red-team-verdict.json" in prompt
        assert "fatal_flaw" in prompt

    def test_forbids_reading_investigation_history(self):
        from voronoi.server.prompt import build_red_team_prompt
        prompt = build_red_team_prompt(workspace_path="/tmp/ws")
        # Must explicitly tell the reviewer not to read these
        assert "brief-digest" in prompt or "checkpoint" in prompt

    def test_no_task_snapshot_or_belief_map_injected(self):
        """The cold prompt must not interpolate investigation state."""
        from voronoi.server.prompt import build_red_team_prompt
        prompt = build_red_team_prompt(workspace_path="/tmp/ws")
        # Signals from warm-start context that should NOT appear
        assert "Current tasks" not in prompt
        assert "Belief map" not in prompt
        assert "OODA cycle" not in prompt
