"""Tests for voronoi.science.interpretation — scientific judgment layer."""

import json
from pathlib import Path

import pytest

from voronoi.science.interpretation import (
    ContinuationProposal,
    DirectionMatch,
    DirectionResult,
    Explanation,
    InterpretationRequest,
    TribunalResult,
    TribunalVerdict,
    TrivialityClass,
    TrivialityResult,
    check_tribunal_clear,
    classify_direction,
    generate_continuation_proposals,
    generate_interpretation_request,
    has_reversed_hypotheses,
    load_continuation_proposals,
    load_interpretation_request,
    load_tribunal_results,
    save_continuation_proposals,
    save_interpretation_request,
    save_tribunal_result,
    screen_triviality,
)
from voronoi.science.claims import ClaimLedger


# ---------------------------------------------------------------------------
# Directional Hypothesis Verification
# ---------------------------------------------------------------------------

class TestDirectionClassification:
    def test_confirmed_when_directions_match_and_significant(self):
        result = classify_direction("higher_is_better", "higher_is_better", significant=True)
        assert result == DirectionMatch.CONFIRMED

    def test_refuted_reversed_when_directions_oppose_and_significant(self):
        result = classify_direction("higher_is_better", "lower_is_better", significant=True)
        assert result == DirectionMatch.REFUTED_REVERSED

    def test_inconclusive_when_not_significant(self):
        result = classify_direction("higher_is_better", "lower_is_better", significant=False)
        assert result == DirectionMatch.INCONCLUSIVE

    def test_normalises_positive_signals(self):
        result = classify_direction("increase", "improves", significant=True)
        assert result == DirectionMatch.CONFIRMED

    def test_normalises_negative_signals(self):
        result = classify_direction("decrease", "reduces", significant=True)
        assert result == DirectionMatch.CONFIRMED

    def test_cross_direction_positive_vs_negative(self):
        result = classify_direction("increase", "decrease", significant=True)
        assert result == DirectionMatch.REFUTED_REVERSED

    def test_unknown_directions_compared_as_text(self):
        result = classify_direction("L4_A < L4_D", "L4_A < L4_D", significant=True)
        assert result == DirectionMatch.CONFIRMED

    def test_unknown_directions_different_text(self):
        result = classify_direction("L4_A < L4_D", "L4_D < L4_A", significant=True)
        assert result == DirectionMatch.REFUTED_REVERSED

    def test_direction_match_is_valid(self):
        assert DirectionMatch.is_valid("confirmed")
        assert DirectionMatch.is_valid("refuted_reversed")
        assert DirectionMatch.is_valid("inconclusive")
        assert not DirectionMatch.is_valid("unknown")


# ---------------------------------------------------------------------------
# Triviality Screening
# ---------------------------------------------------------------------------

class TestTrivialityScreening:
    def test_novel_by_default(self):
        result = screen_triviality("H1", "Encoding reduces decision regret")
        assert result.classification == TrivialityClass.NOVEL
        assert result.suggested_action == "full_experiment"

    def test_detects_trivial_hypothesis(self):
        result = screen_triviality("H1", "More data improves accuracy")
        assert result.classification == TrivialityClass.TRIVIAL
        assert result.suggested_action == "skip"

    def test_detects_expected_hypothesis(self):
        result = screen_triviality("H1", "Result is consistent with prior work")
        assert result.classification == TrivialityClass.EXPECTED
        assert result.suggested_action == "sanity_check"

    def test_triviality_class_is_valid(self):
        assert TrivialityClass.is_valid("novel")
        assert TrivialityClass.is_valid("expected")
        assert TrivialityClass.is_valid("trivial")
        assert not TrivialityClass.is_valid("boring")


# ---------------------------------------------------------------------------
# Interpretation Requests
# ---------------------------------------------------------------------------

class TestInterpretationRequest:
    def test_generate_request(self):
        req = generate_interpretation_request(
            "bd-42",
            "refuted_reversed",
            hypothesis_id="H2",
            expected="L4_A outperforms L4_D",
            observed="L4_D outperforms L4_A",
            causal_edges_violated=["source_condition → reasoning_quality"],
        )
        assert req.finding_id == "bd-42"
        assert req.trigger == "refuted_reversed"
        assert req.hypothesis_id == "H2"
        assert len(req.causal_edges_violated) == 1
        assert req.timestamp  # non-empty

    def test_save_and_load_request(self, tmp_path):
        req = generate_interpretation_request("bd-10", "surprising")
        save_interpretation_request(tmp_path, req)
        loaded = load_interpretation_request(tmp_path)
        assert loaded is not None
        assert loaded.finding_id == "bd-10"
        assert loaded.trigger == "surprising"

    def test_load_missing_request(self, tmp_path):
        assert load_interpretation_request(tmp_path) is None


# ---------------------------------------------------------------------------
# Tribunal Results
# ---------------------------------------------------------------------------

class TestTribunalResult:
    def test_save_and_load_single(self, tmp_path):
        result = TribunalResult(
            finding_id="bd-42",
            verdict=TribunalVerdict.ANOMALY_UNRESOLVED,
            explanations=[
                Explanation(id="E1", theory="Assembly burden", test="Correlate token count"),
                Explanation(id="E2", theory="Attention dilution", test="Fixed-length control"),
            ],
            recommended_action="test_E1_before_convergence",
            tribunal_agents=["theorist", "statistician", "methodologist"],
        )
        save_tribunal_result(tmp_path, result)
        loaded = load_tribunal_results(tmp_path)
        assert len(loaded) == 1
        assert loaded[0].finding_id == "bd-42"
        assert loaded[0].verdict == TribunalVerdict.ANOMALY_UNRESOLVED
        assert len(loaded[0].explanations) == 2
        assert loaded[0].explanations[0].id == "E1"

    def test_save_appends_results(self, tmp_path):
        r1 = TribunalResult(finding_id="bd-10", verdict=TribunalVerdict.EXPLAINED)
        r2 = TribunalResult(finding_id="bd-20", verdict=TribunalVerdict.TRIVIAL)
        save_tribunal_result(tmp_path, r1)
        save_tribunal_result(tmp_path, r2)
        loaded = load_tribunal_results(tmp_path)
        assert len(loaded) == 2

    def test_load_empty(self, tmp_path):
        assert load_tribunal_results(tmp_path) == []


# ---------------------------------------------------------------------------
# Tribunal Clear (convergence gate)
# ---------------------------------------------------------------------------

class TestTribunalClear:
    def test_clear_when_no_verdicts(self, tmp_path):
        clear, blockers = check_tribunal_clear(tmp_path)
        assert clear is True
        assert blockers == []

    def test_clear_when_all_explained(self, tmp_path):
        result = TribunalResult(finding_id="bd-1", verdict=TribunalVerdict.EXPLAINED)
        save_tribunal_result(tmp_path, result)
        clear, blockers = check_tribunal_clear(tmp_path)
        assert clear is True

    def test_blocked_when_anomaly_unresolved(self, tmp_path):
        result = TribunalResult(finding_id="bd-42", verdict=TribunalVerdict.ANOMALY_UNRESOLVED)
        save_tribunal_result(tmp_path, result)
        clear, blockers = check_tribunal_clear(tmp_path)
        assert clear is False
        assert len(blockers) == 1
        assert "bd-42" in blockers[0]

    def test_blocked_when_artifact(self, tmp_path):
        result = TribunalResult(finding_id="bd-99", verdict=TribunalVerdict.ARTIFACT)
        save_tribunal_result(tmp_path, result)
        clear, blockers = check_tribunal_clear(tmp_path)
        assert clear is False


# ---------------------------------------------------------------------------
# Reversed Hypotheses Check
# ---------------------------------------------------------------------------

class TestReversedHypotheses:
    def test_no_reversed_in_empty_workspace(self, tmp_path):
        has, descs = has_reversed_hypotheses(tmp_path)
        assert has is False

    def test_detects_reversed_hypothesis(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "belief-map.json").write_text(json.dumps({
            "hypotheses": [
                {"id": "H1", "name": "test", "status": "confirmed"},
                {"id": "H2", "name": "interaction", "status": "refuted_reversed",
                 "evidence": ["bd-42"]},
            ]
        }))
        has, descs = has_reversed_hypotheses(tmp_path)
        assert has is True
        assert len(descs) == 1
        assert "H2" in descs[0]

    def test_reversed_explained_by_tribunal(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "belief-map.json").write_text(json.dumps({
            "hypotheses": [
                {"id": "H2", "name": "interaction", "status": "refuted_reversed",
                 "evidence": ["bd-42"]},
            ]
        }))
        # Tribunal explains the finding
        result = TribunalResult(finding_id="bd-42", verdict=TribunalVerdict.EXPLAINED)
        save_tribunal_result(tmp_path, result)

        has, descs = has_reversed_hypotheses(tmp_path)
        assert has is False  # No longer blocked


# ---------------------------------------------------------------------------
# Continuation Proposals
# ---------------------------------------------------------------------------

class TestContinuationProposals:
    def test_from_tribunal_unresolved(self):
        ledger = ClaimLedger()
        tribunal_results = [
            TribunalResult(
                finding_id="bd-42",
                verdict=TribunalVerdict.ANOMALY_UNRESOLVED,
                explanations=[
                    Explanation(id="E1", theory="Assembly burden", test="Correlate token count"),
                    Explanation(id="E2", theory="Attention dilution", test="Fixed-length control"),
                ],
            )
        ]
        proposals = generate_continuation_proposals(ledger, tribunal_results)
        assert len(proposals) == 2
        assert proposals[0].information_gain == 0.9  # High for unresolved
        assert "Assembly burden" in proposals[0].description

    def test_from_challenged_claims(self):
        ledger = ClaimLedger()
        claim = ledger.add_claim("Encoding helps", "run_evidence")
        ledger.challenge_claim(claim.id, "N too small", "power")
        proposals = generate_continuation_proposals(ledger)
        assert len(proposals) >= 1
        assert any("N too small" in p.description for p in proposals)

    def test_from_single_evidence_claims(self):
        ledger = ClaimLedger()
        ledger.add_claim("Encoding helps", "run_evidence",
                         supporting_findings=["bd-1"])
        proposals = generate_continuation_proposals(ledger)
        assert len(proposals) >= 1
        assert any(p.experiment_type == "replication" for p in proposals)

    def test_sorted_by_information_gain(self):
        ledger = ClaimLedger()
        ledger.add_claim("Weak claim", "run_evidence",
                         supporting_findings=["bd-1"])
        tribunal_results = [
            TribunalResult(
                finding_id="bd-42",
                verdict=TribunalVerdict.ANOMALY_UNRESOLVED,
                explanations=[Explanation(id="E1", theory="Test", test="Run it")],
            )
        ]
        proposals = generate_continuation_proposals(ledger, tribunal_results)
        # Tribunal proposals (0.9) should come before replication (0.5)
        assert proposals[0].information_gain >= proposals[-1].information_gain

    def test_save_and_load_proposals(self, tmp_path):
        proposals = [
            ContinuationProposal(
                id="P1", target_claim="C1",
                description="Test attention dilution",
                rationale="Token count correlation",
                information_gain=0.9,
            )
        ]
        save_continuation_proposals(tmp_path, proposals)
        loaded = load_continuation_proposals(tmp_path)
        assert len(loaded) == 1
        assert loaded[0].id == "P1"
        assert loaded[0].information_gain == 0.9

    def test_load_empty(self, tmp_path):
        assert load_continuation_proposals(tmp_path) == []


# ---------------------------------------------------------------------------
# Pre-registration expected_direction field
# ---------------------------------------------------------------------------

class TestPreRegExpectedDirection:
    def test_parse_expected_direction(self):
        from voronoi.science import parse_pre_registration
        notes = (
            "PRE_REG: HYPOTHESIS=[encoding outperforms raw] | "
            "METHOD=[ablation] | CONTROLS=[same LLM] | "
            "EXPECTED_RESULT=[d>=0.5] | CONFOUNDS=[prompt variation] | "
            "STAT_TEST=[t-test] | SAMPLE_SIZE=[100] | "
            "EXPECTED_DIRECTION=[higher_is_better]"
        )
        pr = parse_pre_registration(notes)
        assert pr.expected_direction == "higher_is_better"

    def test_parse_without_expected_direction(self):
        from voronoi.science import parse_pre_registration
        notes = (
            "PRE_REG: HYPOTHESIS=[h] | METHOD=[m] | CONTROLS=[c] | "
            "EXPECTED_RESULT=[e] | CONFOUNDS=[cf] | STAT_TEST=[t] | SAMPLE_SIZE=[10]"
        )
        pr = parse_pre_registration(notes)
        assert pr.expected_direction == ""
