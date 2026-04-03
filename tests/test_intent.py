"""Tests for voronoi.gateway.intent — intent classifier."""

import pytest

from voronoi.gateway.intent import (
    ClassifiedIntent,
    ClassifiedPhase,
    RigorLevel,
    WorkflowMode,
    classify,
    classify_compound,
)


# ---------------------------------------------------------------------------
# Explicit /voronoi commands
# ---------------------------------------------------------------------------

class TestExplicitCommands:
    """Test that explicit /voronoi <cmd> patterns are recognized at confidence 1.0."""

    def test_discover_command(self):
        r = classify("/voronoi discover why is our API slow?")
        assert r.mode == WorkflowMode.DISCOVER
        assert r.rigor == RigorLevel.ADAPTIVE
        assert r.confidence == 1.0
        assert "why is our API slow?" in r.summary

    def test_prove_command(self):
        r = classify("/voronoi prove encoding improves discovery recall")
        assert r.mode == WorkflowMode.PROVE
        assert r.rigor == RigorLevel.SCIENTIFIC
        assert r.confidence == 1.0

    def test_recall_command(self):
        r = classify("/voronoi recall what did we learn about caching?")
        assert r.mode == WorkflowMode.RECALL
        assert r.confidence == 1.0

    def test_status_command(self):
        r = classify("/voronoi status")
        assert r.mode == WorkflowMode.STATUS
        assert r.confidence == 1.0

    def test_tasks_command(self):
        r = classify("/voronoi tasks")
        assert r.mode == WorkflowMode.STATUS

    def test_ready_command(self):
        r = classify("/voronoi ready")
        assert r.mode == WorkflowMode.STATUS

    def test_guide_command(self):
        r = classify("/voronoi guide focus on hypothesis 2")
        assert r.mode == WorkflowMode.GUIDE
        assert r.confidence == 1.0

    def test_pivot_command(self):
        r = classify("/voronoi pivot drop approach A, try B instead")
        assert r.mode == WorkflowMode.GUIDE


# ---------------------------------------------------------------------------
# Free-text scientific questions (no /voronoi prefix)
# ---------------------------------------------------------------------------

class TestFreeTextScience:
    """Test free-text classification into DISCOVER or PROVE."""

    def test_why_question_classifies_discover(self):
        r = classify("Why is our model accuracy dropping after each retrain?")
        assert r.mode == WorkflowMode.DISCOVER
        assert r.rigor == RigorLevel.ADAPTIVE
        assert r.confidence >= 0.5

    def test_root_cause_classifies_discover(self):
        r = classify("What is the root cause of the latency spike?")
        assert r.mode == WorkflowMode.DISCOVER

    def test_comparison_classifies_discover(self):
        r = classify("Which database should we migrate to — Postgres or DynamoDB?")
        assert r.mode == WorkflowMode.DISCOVER

    def test_benchmark_classifies_discover(self):
        r = classify("Benchmark our current cache vs Redis cluster")
        assert r.mode == WorkflowMode.DISCOVER

    def test_build_signals_classify_discover(self):
        r = classify("Build a recommendation engine with collaborative filtering")
        assert r.mode == WorkflowMode.DISCOVER
        assert r.rigor == RigorLevel.ADAPTIVE

    def test_figure_out_and_fix_classifies_discover(self):
        r = classify("Figure out why latency is high and then fix it")
        assert r.mode == WorkflowMode.DISCOVER

    def test_debug_and_fix_classifies_discover(self):
        r = classify("Debug and fix the authentication timeout")
        assert r.mode == WorkflowMode.DISCOVER

    def test_controlled_experiment_classifies_prove(self):
        r = classify("Test whether increasing sample size from 500 to 5000 improves significance")
        assert r.mode == WorkflowMode.PROVE
        assert r.rigor in (RigorLevel.SCIENTIFIC, RigorLevel.EXPERIMENTAL)

    def test_ab_test_classifies_prove(self):
        r = classify("Run an A/B test on the new recommendation algorithm")
        assert r.mode == WorkflowMode.PROVE

    def test_recall_from_freetext(self):
        r = classify("What did we learn about caching strategies last time?")
        assert r.mode == WorkflowMode.RECALL

    def test_what_do_we_know(self):
        r = classify("What do we know about the user churn problem?")
        assert r.mode == WorkflowMode.RECALL

    def test_build_and_optimize_classifies_discover(self):
        r = classify("Build and optimize the search indexer for performance")
        assert r.mode == WorkflowMode.DISCOVER
        assert r.rigor == RigorLevel.ADAPTIVE

    def test_equal_recall_discover_prefers_discover(self):
        """Bug fix: when recall and discover signals tie, DISCOVER should win."""
        # "what" triggers recall, "why" triggers discover — should prefer discover
        r = classify("What happened and why is the accuracy dropping?")
        assert r.mode in (WorkflowMode.DISCOVER, WorkflowMode.PROVE), (
            f"Expected DISCOVER or PROVE on tie, got {r.mode}"
        )

    def test_low_confidence_goes_to_guide(self):
        r = classify("hello, how are you?")
        assert r.mode == WorkflowMode.GUIDE
        assert r.confidence < 0.5


# ---------------------------------------------------------------------------
# ASK intent — mid-investigation questions
# ---------------------------------------------------------------------------

class TestAskIntent:
    """Test ASK intent classification for mid-investigation questions."""

    def test_ask_command(self):
        r = classify("/voronoi ask what have the agents found so far?")
        assert r.mode == WorkflowMode.ASK
        assert r.confidence == 1.0

    def test_what_have_agents_found(self):
        r = classify("What have the agents found so far?")
        assert r.mode == WorkflowMode.ASK

    def test_any_results_yet(self):
        r = classify("Any results yet?")
        assert r.mode == WorkflowMode.ASK

    def test_what_does_the_data_show(self):
        r = classify("What does the data show about the experiments?")
        assert r.mode == WorkflowMode.ASK

    def test_how_is_it_going(self):
        r = classify("How are things going so far?")
        assert r.mode == WorkflowMode.ASK

    def test_update_me_on_progress(self):
        r = classify("Update me on the progress")
        assert r.mode == WorkflowMode.ASK

    def test_which_classifiers_are_best(self):
        r = classify("Which classifiers are showing the best results so far?")
        assert r.mode == WorkflowMode.ASK

    def test_can_you_summarize_findings(self):
        r = classify("Can you summarize the findings so far?")
        assert r.mode == WorkflowMode.ASK

    def test_ask_is_meta(self):
        r = classify("What have we found so far?")
        assert r.is_meta is True
        assert r.is_science is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_string(self):
        r = classify("")
        assert r.mode == WorkflowMode.GUIDE
        assert r.confidence == 0.0

    def test_whitespace_only(self):
        r = classify("   ")
        assert r.mode == WorkflowMode.GUIDE
        assert r.confidence == 0.0

    def test_case_insensitive_commands(self):
        r = classify("/VORONOI DISCOVER something")
        assert r.mode == WorkflowMode.DISCOVER

    def test_original_text_preserved(self):
        text = "/voronoi discover why is latency high?"
        r = classify(text)
        assert r.original_text == text

    def test_summary_truncation(self):
        long_text = "X" * 200
        r = classify(long_text)
        assert len(r.summary) <= 83  # 80 + "..."

    def test_is_science_property(self):
        r = classify("/voronoi discover something")
        assert r.is_science is True

    def test_prove_is_science(self):
        r = classify("/voronoi prove hypothesis X")
        assert r.is_science is True

    def test_is_meta_property(self):
        r = classify("/voronoi status")
        assert r.is_meta is True

    def test_guide_is_not_science(self):
        r = classify("hello")
        assert r.is_science is False

    def test_frozen_dataclass(self):
        r = classify("test")
        with pytest.raises(AttributeError):
            r.mode = WorkflowMode.DISCOVER  # type: ignore

    def test_paper_request_classified_as_discover(self):
        r = classify("Write a paper on catastrophic forgetting mitigation strategies")
        assert r.mode == WorkflowMode.DISCOVER

    def test_paper_about_classified_as_discover(self):
        r = classify("paper on the effects of replay buffer size")
        assert r.mode == WorkflowMode.DISCOVER


# ---------------------------------------------------------------------------
# Compound intent detection
# ---------------------------------------------------------------------------

class TestCompoundIntent:
    """Test multi-phase prompt detection."""

    def test_single_phase_returns_one(self):
        phases = classify_compound("Build a REST API")
        assert len(phases) == 1
        assert phases[0].mode == WorkflowMode.DISCOVER

    def test_empty_returns_empty(self):
        assert classify_compound("") == []

    def test_two_phases_with_then(self):
        text = (
            "Build the data generation pipeline with synthetic scenarios. "
            "Then prove whether encoding level affects discovery recall."
        )
        phases = classify_compound(text)
        assert len(phases) >= 2
        modes = [p.mode for p in phases]
        assert WorkflowMode.DISCOVER in modes
        assert WorkflowMode.PROVE in modes

    def test_numbered_steps(self):
        text = (
            "1. Create synthetic data with planted effects.\n"
            "2. Investigate whether encoding level affects discovery recall.\n"
            "3. Build an interactive webapp showing results."
        )
        phases = classify_compound(text)
        assert len(phases) >= 1

    def test_section_headers(self):
        text = (
            "## Data Generation\nBuild synthetic datasets with planted effects.\n"
            "## Experiment\nTest whether encoding ablation affects detection across four levels.\n"
            "## Deliverables\nWrite a paper and deploy a webapp."
        )
        phases = classify_compound(text)
        assert len(phases) >= 2

    def test_phases_are_ordered(self):
        text = (
            "Build the infrastructure first. "
            "Then investigate the hypothesis. "
            "Finally, create the paper and webapp."
        )
        phases = classify_compound(text)
        for i in range(1, len(phases)):
            assert phases[i].order > phases[i - 1].order

    def test_deduplicates_consecutive_same_mode(self):
        text = (
            "Build module A. Then build module B. "
            "Then investigate the root cause."
        )
        phases = classify_compound(text)
        modes = [p.mode for p in phases]
        for i in range(1, len(modes)):
            assert not (modes[i] == modes[i - 1] and
                        phases[i].rigor == phases[i - 1].rigor)
