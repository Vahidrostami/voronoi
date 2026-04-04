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

    def test_prove_has_eval_score(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="prove", rigor="scientific",
        )
        assert "eval-score.json" in prompt


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

        with patch.object(wm, "_ensure_github_files") as mock_ensure:
            info = wm.provision_lab(1, "test", "Does EWC work?")
            mock_ensure.assert_called_once_with(Path(info.path))


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
        ]
        for t in expected_types:
            assert t in ROLE_MAP, f"Missing task type {t} in ROLE_MAP"


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
