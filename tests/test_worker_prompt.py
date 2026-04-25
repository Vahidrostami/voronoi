"""Tests for code-assembled worker prompts — context management."""

from voronoi.server.prompt import build_worker_prompt, ROLE_MAP, SKILL_MAP


class TestBuildWorkerPrompt:
    def test_basic_build_task(self):
        prompt = build_worker_prompt(
            task_type="build",
            task_id="bd-42",
            branch="agent-auth",
            briefing="Implement JWT-based authentication.",
        )
        assert "bd-42" in prompt
        assert "agent-auth" in prompt
        assert "JWT" in prompt
        assert "git" in prompt.lower()  # Git discipline included

    def test_investigation_task_includes_skills(self):
        prompt = build_worker_prompt(
            task_type="investigation",
            task_id="bd-55",
            branch="agent-pilot",
            briefing="Run pilot experiment on scenarios 1-2.",
            strategic_context="Tests whether encoding helps discovery.",
            produces="output/pilot_results.json",
            metric_contract="PRIMARY=MBRS, higher_is_better, baseline=0.0",
        )
        assert "bd-55" in prompt
        assert "pilot" in prompt.lower()
        assert "investigation-protocol" in prompt
        assert "evidence-system" in prompt
        assert "MBRS" in prompt
        assert "pilot_results.json" in prompt

    def test_produces_and_requires(self):
        prompt = build_worker_prompt(
            task_type="build",
            task_id="bd-10",
            branch="agent-data",
            briefing="Generate synthetic data.",
            produces="data/scenarios.csv",
            requires="demos/coupled-decisions/PROMPT.md",
        )
        assert "scenarios.csv" in prompt
        assert "PROMPT.md" in prompt
        assert "PRODUCES" in prompt
        assert "REQUIRES" in prompt

    def test_strategic_context_included(self):
        prompt = build_worker_prompt(
            task_type="exploration",
            task_id="bd-20",
            branch="agent-explore",
            briefing="Compare encoding strategies.",
            strategic_context="High impact — determines the paper's main claim.",
        )
        assert "Strategic Context" in prompt
        assert "main claim" in prompt

    def test_prompt_sections_included(self):
        prompt = build_worker_prompt(
            task_type="investigation",
            task_id="bd-30",
            branch="agent-exp",
            briefing="Run experiment.",
            prompt_sections="### Factorial Design\nL1 vs L4, 2x2 design",
        )
        assert "Factorial Design" in prompt
        assert "2x2" in prompt

    def test_prompt_path_reference(self):
        prompt = build_worker_prompt(
            task_type="build",
            task_id="bd-40",
            branch="agent-build",
            briefing="Build encoder.",
            prompt_path="demos/coupled-decisions/PROMPT.md",
        )
        assert "demos/coupled-decisions/PROMPT.md" in prompt

    def test_git_discipline_always_present(self):
        prompt = build_worker_prompt(
            task_type="build",
            task_id="bd-1",
            branch="agent-test",
            briefing="Test task.",
        )
        assert "git add" in prompt
        assert "git push" in prompt
        assert "bd close bd-1" in prompt

    def test_git_discipline_only_pushes_when_origin_exists(self):
        prompt = build_worker_prompt(
            task_type="build",
            task_id="bd-3",
            branch="agent-conditional",
            briefing="Test task.",
        )

        assert "git commit -m '[msg]'`" in prompt
        assert "If `origin` exists: `git push origin agent-conditional`" in prompt
        assert "git commit -m '[msg]' && git push origin agent-conditional" not in prompt

    def test_git_discipline_handles_local_only_workspace(self, tmp_path):
        workspace = tmp_path / "local-only"
        workspace.mkdir()

        prompt = build_worker_prompt(
            task_type="build",
            task_id="bd-2",
            branch="agent-local",
            briefing="Test local-only git policy.",
            workspace_path=str(workspace),
        )

        assert "no `origin` exists" in prompt
        assert "NO_REMOTE" in prompt
        assert "commit locally" in prompt

    def test_extra_instructions(self):
        prompt = build_worker_prompt(
            task_type="build",
            task_id="bd-1",
            branch="agent-test",
            briefing="Test.",
            extra_instructions="Use Python 3.11 only.",
        )
        assert "Python 3.11" in prompt

    def test_compilation_task_skills(self):
        prompt = build_worker_prompt(
            task_type="compilation",
            task_id="bd-99",
            branch="agent-compile",
            briefing="Compile the paper.",
        )
        assert "figure-generation" in prompt
        assert "compilation-protocol" in prompt

    def test_methodologist_prompt_excludes_already_reviewed_designs(self):
        prompt = build_worker_prompt(
            task_type="review_method",
            task_id="bd-77",
            branch="agent-method",
            briefing="Review pending experiment designs.",
        )

        assert 'notes=PRE_REG AND notes!=METHODOLOGIST_REVIEW AND status!=closed' in prompt


class TestRoleMappings:
    def test_all_task_types_have_roles(self):
        for task_type, filename in ROLE_MAP.items():
            assert filename.endswith(".agent.md"), f"{task_type} has bad role file: {filename}"

    def test_investigation_maps_to_investigator(self):
        assert "investigator" in ROLE_MAP["investigation"]

    def test_scout_maps_to_scout(self):
        assert "scout" in ROLE_MAP["scout"]


class TestSkillMappings:
    def test_investigation_has_skills(self):
        assert len(SKILL_MAP["investigation"]) >= 2

    def test_investigation_has_context_management(self):
        skills = SKILL_MAP["investigation"]
        assert any("context-management" in s for s in skills)

    def test_scout_has_deep_research(self):
        assert "scout" in SKILL_MAP
        skills = SKILL_MAP["scout"]
        assert any("deep-research" in s for s in skills)

    def test_exploration_has_deep_research_and_context(self):
        assert "exploration" in SKILL_MAP
        skills = SKILL_MAP["exploration"]
        assert any("deep-research" in s for s in skills)
        assert any("context-management" in s for s in skills)

    def test_build_has_no_skills(self):
        assert "build" not in SKILL_MAP


class TestScoutResearch:
    def test_scout_prompt_includes_deep_research_skill(self):
        """Scout worker prompt references the deep-research skill."""
        prompt = build_worker_prompt(
            task_type="scout",
            task_id="bd-1",
            branch="agent-scout",
            briefing="Research prior art for test investigation.",
        )
        assert "deep-research/SKILL.md" in prompt

    def test_scout_prompt_requires_novelty_gate_output(self):
        """Scout worker prompt requires both brief and novelty gate artifacts."""
        prompt = build_worker_prompt(
            task_type="scout",
            task_id="bd-1",
            branch="agent-scout",
            briefing="Research prior art for test investigation.",
        )
        assert "Scout Output Contract" in prompt
        assert ".swarm/scout-brief.md" in prompt
        assert ".swarm/novelty-gate.json" in prompt
        assert "status` (`clear` or `blocked`)" in prompt
        assert "assessment` (`novel`, `incremental`, or `redundant`)" in prompt

    def test_scout_role_verify_loop_checks_novelty_gate(self):
        """Scout role content must verify novelty-gate existence and shape."""
        prompt = build_worker_prompt(
            task_type="scout",
            task_id="bd-1",
            branch="agent-scout",
            briefing="Research prior art for test investigation.",
        )
        assert "does .swarm/novelty-gate.json exist?" in prompt
        assert "status clear|blocked" in prompt
        assert "assessment novel|incremental|redundant" in prompt

    def test_non_scout_prompt_excludes_deep_research(self):
        """Non-scout tasks without deep-research in SKILL_MAP should not reference it."""
        prompt = build_worker_prompt(
            task_type="build",
            task_id="bd-2",
            branch="agent-build",
            briefing="Implement feature X.",
        )
        assert "deep-research" not in prompt


class TestScribeLatex:
    def test_scribe_has_compilation_skills(self):
        assert "scribe" in SKILL_MAP
        skills = SKILL_MAP["scribe"]
        assert any("compilation-protocol" in s for s in skills)
        assert any("figure-generation" in s for s in skills)

    def test_scribe_prompt_enforces_latex(self):
        """Scribe worker prompt must explicitly require LaTeX output."""
        prompt = build_worker_prompt(
            task_type="scribe",
            task_id="bd-50",
            branch="agent-scribe",
            briefing="Write the paper.",
        )
        assert "paper.tex" in prompt
        assert "NOT Markdown" in prompt
        assert "Output Format" in prompt

    def test_scribe_prompt_includes_skills(self):
        """Scribe prompt references compilation + figure skills."""
        prompt = build_worker_prompt(
            task_type="scribe",
            task_id="bd-50",
            branch="agent-scribe",
            briefing="Write the paper.",
        )
        assert "compilation-protocol" in prompt
        assert "figure-generation" in prompt

    def test_non_scribe_no_latex_enforcement(self):
        """Non-scribe tasks should NOT get the latex enforcement section."""
        prompt = build_worker_prompt(
            task_type="investigation",
            task_id="bd-10",
            branch="agent-inv",
            briefing="Run experiment.",
        )
        assert "Output Format" not in prompt
