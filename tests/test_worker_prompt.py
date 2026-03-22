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

    def test_build_has_no_skills(self):
        assert "build" not in SKILL_MAP
