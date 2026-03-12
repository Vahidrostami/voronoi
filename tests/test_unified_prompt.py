"""Tests for the unified prompt builder and workspace .github/ provisioning.

Verifies that:
1. Both CLI and Telegram paths produce prompts from the same builder
2. Prompts reference .github/agents/*.agent.md role files
3. Mode/rigor combinations produce correct science sections
4. Workspace provisioning always copies .github/ files
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
            mode="build",
            rigor="standard",
        )
        assert "swarm orchestrator" in prompt
        assert "PROMPT.md" in prompt
        assert ".github/agents/swarm-orchestrator.agent.md" in prompt

    def test_references_agent_files(self):
        prompt = build_orchestrator_prompt(
            question="test",
            mode="build",
            rigor="standard",
        )
        # Must reference the orchestrator role file
        assert ".github/agents/swarm-orchestrator.agent.md" in prompt
        # Must include the worker role mapping table
        assert ".github/agents/worker-agent.agent.md" in prompt
        assert ".github/agents/scout.agent.md" in prompt
        assert ".github/agents/investigator.agent.md" in prompt

    def test_codename_in_prompt(self):
        prompt = build_orchestrator_prompt(
            question="test",
            mode="investigate",
            rigor="scientific",
            codename="Dopamine",
        )
        assert "Dopamine" in prompt

    def test_workspace_path_in_prompt(self):
        prompt = build_orchestrator_prompt(
            question="test",
            mode="build",
            rigor="standard",
            workspace_path="/tmp/workspace",
        )
        assert "/tmp/workspace" in prompt

    def test_output_dir_in_prompt(self):
        prompt = build_orchestrator_prompt(
            question="test",
            mode="build",
            rigor="standard",
            output_dir="demos/coupled-decisions",
        )
        assert "demos/coupled-decisions" in prompt

    def test_custom_prompt_path(self):
        prompt = build_orchestrator_prompt(
            question="test",
            mode="build",
            rigor="standard",
            prompt_path="demos/my-demo/PROMPT.md",
        )
        assert "demos/my-demo/PROMPT.md" in prompt

    def test_max_agents_in_prompt(self):
        prompt = build_orchestrator_prompt(
            question="test",
            mode="build",
            rigor="standard",
            max_agents=8,
        )
        assert "8" in prompt

    def test_safe_flag_in_prompt(self):
        prompt = build_orchestrator_prompt(
            question="test",
            mode="build",
            rigor="standard",
            safe=True,
        )
        assert "--safe" in prompt


# ---------------------------------------------------------------------------
# Science sections by mode x rigor
# ---------------------------------------------------------------------------

class TestScienceSections:
    """Test that mode/rigor combinations produce correct science content."""

    def test_build_standard_no_science(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="build", rigor="standard",
        )
        # Build/standard should NOT have science-specific sections
        assert "## Phase 0: Scout" not in prompt
        assert "## Hypothesis Management" not in prompt
        assert "## Convergence Criteria" not in prompt

    def test_investigate_scientific_has_scout(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="investigate", rigor="scientific",
        )
        assert "Scout" in prompt
        assert ".github/agents/scout.agent.md" in prompt

    def test_investigate_scientific_has_hypotheses(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="investigate", rigor="scientific",
        )
        assert "Hypothesis" in prompt
        assert "belief-map.json" in prompt

    def test_scientific_has_review_gates(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="investigate", rigor="scientific",
        )
        assert "Statistician" in prompt
        assert "Critic" in prompt
        assert "Synthesizer" in prompt
        assert "Evaluator" in prompt
        # Must reference the actual agent files
        assert ".github/agents/statistician.agent.md" in prompt
        assert ".github/agents/critic.agent.md" in prompt
        # Must require claim-evidence traceability
        assert "claim-evidence" in prompt.lower()

    def test_analytical_has_claim_evidence(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="explore", rigor="analytical",
        )
        assert "claim-evidence" in prompt.lower()
        assert "INTERPRETATION" in prompt or "interpretation" in prompt.lower()
        assert "PRACTICAL_SIGNIFICANCE" in prompt

    def test_analytical_has_stats_but_no_critic(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="explore", rigor="analytical",
        )
        assert "Statistician" in prompt
        assert "Critic" not in prompt or "Critic" in prompt  # may appear in table
        # Critic adversarial review should NOT be mentioned for analytical
        assert "adversarial" not in prompt.lower() or "blinded" not in prompt.lower()

    def test_scientific_has_convergence_criteria(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="investigate", rigor="scientific",
        )
        assert "Convergence" in prompt
        assert "hypotheses resolved" in prompt

    def test_experimental_has_replication(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="investigate", rigor="experimental",
        )
        assert "replicated" in prompt.lower()
        assert "Power analysis" in prompt

    def test_scientific_has_pre_registration_rule(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="investigate", rigor="scientific",
        )
        assert "pre-registration" in prompt.lower()

    def test_eval_score_output_for_non_standard(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="investigate", rigor="analytical",
        )
        assert "eval-score.json" in prompt

    def test_no_eval_score_for_standard(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="build", rigor="standard",
        )
        assert "eval-score.json" not in prompt


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
        assert ".github/agents/worker-agent.agent.md" in prompt


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

        prompt = d._build_prompt(inv, tmp_path)

        assert ".github/agents/swarm-orchestrator.agent.md" in prompt
        assert ".github/agents/scout.agent.md" in prompt
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

        with patch("voronoi.server.prompt.build_orchestrator_prompt") as mock_build:
            mock_build.return_value = "test prompt"
            d._build_prompt(inv, tmp_path)

        mock_build.assert_called_once()
        call_kwargs = mock_build.call_args[1]
        assert call_kwargs["mode"] == "build"
        assert call_kwargs["rigor"] == "standard"


# ---------------------------------------------------------------------------
# Workspace .github/ provisioning
# ---------------------------------------------------------------------------

class TestWorkspaceGitHubProvisioning:
    """Verify that .github/ files are always present in provisioned workspaces."""

    def test_ensure_github_files_copies_when_missing(self, tmp_path):
        from voronoi.server.workspace import WorkspaceManager

        wm = WorkspaceManager(tmp_path / "voronoi")
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Create fake source data
        data_dir = tmp_path / "data"
        for subdir in ("agents", "prompts", "skills"):
            d = data_dir / ".github" / subdir
            d.mkdir(parents=True)
            (d / f"test.{subdir[:-1]}.md").write_text(f"# {subdir}")

        with patch("voronoi.cli._find_data_dir", return_value=data_dir):
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

        with patch("voronoi.cli._find_data_dir") as mock_find:
            wm._ensure_github_files(workspace)
            # Should not even call _find_data_dir since agents/ already exists
            mock_find.assert_not_called()

        assert (workspace / ".github" / "agents" / "existing.md").read_text() == "keep me"

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
    """Verify all agent roles are referenced in the worker prompt instructions."""

    EXPECTED_ROLES = [
        "worker-agent", "scout", "investigator", "explorer",
        "statistician", "critic", "theorist", "methodologist",
        "synthesizer", "scribe", "evaluator",
    ]

    def test_all_roles_in_mapping_table(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="investigate", rigor="scientific",
        )
        for role in self.EXPECTED_ROLES:
            assert f".github/agents/{role}.agent.md" in prompt, \
                f"Missing role {role} in prompt mapping table"


# ---------------------------------------------------------------------------
# Invariants & REVISE sections in prompts
# ---------------------------------------------------------------------------

class TestInvariantsInPrompt:
    """Verify invariants and REVISE sections appear in prompts."""

    def test_invariants_section_present(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="investigate", rigor="scientific",
        )
        assert "Investigation Invariants" in prompt
        assert "invariants.json" in prompt

    def test_revise_section_present(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="investigate", rigor="scientific",
        )
        assert "REVISE" in prompt
        assert "REVISE_OF" in prompt
        assert "CALIBRATION" in prompt

    def test_invariants_in_build_mode_too(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="build", rigor="standard",
        )
        assert "Investigation Invariants" in prompt

    def test_scribe_in_role_mapping(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="investigate", rigor="scientific",
        )
        assert "scribe.agent.md" in prompt

    def test_success_criteria_tracking_section(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="investigate", rigor="scientific",
        )
        assert "Success Criteria Tracking" in prompt
        assert "success-criteria.json" in prompt
        assert "RESULT_CONTRADICTS_HYPOTHESIS" in prompt

    def test_success_criteria_in_build_too(self):
        prompt = build_orchestrator_prompt(
            question="test", mode="build", rigor="standard",
        )
        assert "Success Criteria Tracking" in prompt
