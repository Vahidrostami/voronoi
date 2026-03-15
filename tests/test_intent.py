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

    def test_investigate_command(self):
        r = classify("/voronoi investigate why is our API slow?")
        assert r.mode == WorkflowMode.INVESTIGATE
        assert r.rigor == RigorLevel.SCIENTIFIC
        assert r.confidence == 1.0
        assert "why is our API slow?" in r.summary

    def test_explore_command(self):
        r = classify("/voronoi explore Redis vs Memcached for our workload")
        assert r.mode == WorkflowMode.EXPLORE
        assert r.rigor == RigorLevel.ANALYTICAL
        assert r.confidence == 1.0

    def test_build_command(self):
        r = classify("/voronoi build a REST API with auth")
        assert r.mode == WorkflowMode.BUILD
        assert r.rigor == RigorLevel.STANDARD
        assert r.confidence == 1.0

    def test_experiment_command(self):
        r = classify("/voronoi experiment test whether batch size > 64 improves convergence")
        assert r.mode == WorkflowMode.INVESTIGATE
        assert r.rigor == RigorLevel.EXPERIMENTAL
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
    """Test free-text detection of scientific intent."""

    def test_why_question_classifies_investigate(self):
        r = classify("Why is our model accuracy dropping after each retrain?")
        assert r.mode == WorkflowMode.INVESTIGATE
        assert r.rigor == RigorLevel.SCIENTIFIC
        assert r.confidence >= 0.5

    def test_root_cause_classifies_investigate(self):
        r = classify("What is the root cause of the latency spike?")
        assert r.mode == WorkflowMode.INVESTIGATE

    def test_comparison_classifies_explore(self):
        r = classify("Which database should we migrate to — Postgres or DynamoDB?")
        assert r.mode == WorkflowMode.EXPLORE
        assert r.rigor == RigorLevel.ANALYTICAL

    def test_benchmark_classifies_explore(self):
        r = classify("Benchmark our current cache vs Redis cluster")
        assert r.mode == WorkflowMode.EXPLORE

    def test_build_signals(self):
        r = classify("Build a recommendation engine with collaborative filtering")
        assert r.mode == WorkflowMode.BUILD
        assert r.rigor == RigorLevel.STANDARD

    def test_hybrid_signals(self):
        r = classify("Figure out why latency is high and then fix it")
        assert r.mode == WorkflowMode.HYBRID

    def test_debug_and_fix_is_hybrid(self):
        r = classify("Debug and fix the authentication timeout")
        assert r.mode == WorkflowMode.HYBRID

    def test_experimental_signals(self):
        r = classify("Test whether increasing sample size from 500 to 5000 improves significance")
        assert r.rigor == RigorLevel.EXPERIMENTAL

    def test_ab_test_is_experimental(self):
        r = classify("Run an A/B test on the new recommendation algorithm")
        assert r.rigor == RigorLevel.EXPERIMENTAL

    def test_recall_from_freetext(self):
        r = classify("What did we learn about caching strategies last time?")
        assert r.mode == WorkflowMode.RECALL

    def test_what_do_we_know(self):
        r = classify("What do we know about the user churn problem?")
        assert r.mode == WorkflowMode.RECALL

    def test_analytical_build(self):
        r = classify("Build and optimize the search indexer for performance")
        assert r.rigor in (RigorLevel.ANALYTICAL, RigorLevel.STANDARD)

    def test_low_confidence_goes_to_guide(self):
        r = classify("hello, how are you?")
        assert r.mode == WorkflowMode.GUIDE
        assert r.confidence < 0.5


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
        r = classify("/VORONOI INVESTIGATE something")
        assert r.mode == WorkflowMode.INVESTIGATE

    def test_original_text_preserved(self):
        text = "/voronoi investigate why is latency high?"
        r = classify(text)
        assert r.original_text == text

    def test_summary_truncation(self):
        long_text = "X" * 200
        r = classify(long_text)
        assert len(r.summary) <= 83  # 80 + "..."

    def test_is_science_property(self):
        r = classify("/voronoi investigate something")
        assert r.is_science is True

    def test_is_meta_property(self):
        r = classify("/voronoi status")
        assert r.is_meta is True

    def test_build_is_not_science(self):
        r = classify("/voronoi build something")
        assert r.is_science is False

    def test_frozen_dataclass(self):
        r = classify("test")
        with pytest.raises(AttributeError):
            r.mode = WorkflowMode.BUILD  # type: ignore

    def test_paper_request_classified_as_hybrid(self):
        r = classify("Write a paper on catastrophic forgetting mitigation strategies")
        assert r.mode == WorkflowMode.HYBRID

    def test_paper_about_classified_as_hybrid(self):
        r = classify("paper on the effects of replay buffer size")
        assert r.mode == WorkflowMode.HYBRID


# ---------------------------------------------------------------------------
# Compound intent detection
# ---------------------------------------------------------------------------

class TestCompoundIntent:
    """Test multi-phase prompt detection."""

    def test_single_phase_returns_one(self):
        phases = classify_compound("Build a REST API")
        assert len(phases) == 1
        assert phases[0].mode == WorkflowMode.BUILD

    def test_empty_returns_empty(self):
        assert classify_compound("") == []

    def test_two_phases_with_then(self):
        text = (
            "Build the data generation pipeline with synthetic scenarios. "
            "Then investigate whether encoding level affects discovery recall."
        )
        phases = classify_compound(text)
        assert len(phases) >= 2
        modes = [p.mode for p in phases]
        assert WorkflowMode.BUILD in modes
        assert WorkflowMode.INVESTIGATE in modes

    def test_numbered_steps(self):
        text = (
            "1. Create synthetic data with planted effects.\n"
            "2. Investigate whether encoding level affects discovery recall.\n"
            "3. Build an interactive webapp showing results."
        )
        phases = classify_compound(text)
        assert len(phases) >= 2

    def test_section_headers(self):
        text = (
            "## Data Generation\nBuild synthetic datasets with planted effects.\n"
            "## Experiment\nInvestigate encoding ablation across four levels.\n"
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
        # Consecutive BUILD phases should be merged
        modes = [p.mode for p in phases]
        for i in range(1, len(modes)):
            assert not (modes[i] == modes[i - 1] and
                        phases[i].rigor == phases[i - 1].rigor)
