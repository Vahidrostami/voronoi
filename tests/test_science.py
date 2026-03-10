"""Tests for voronoi.science — science gate enforcement layer."""

import json
from pathlib import Path

import pytest

from voronoi.science import (
    BeliefMap,
    ConsistencyConflict,
    ConvergenceResult,
    Hypothesis,
    LabNotebookEntry,
    PreRegistration,
    ReplicationNeed,
    append_lab_notebook,
    check_consistency,
    check_convergence,
    check_dispatch_gates,
    check_merge_gates,
    check_paradigm_stress,
    load_belief_map,
    load_lab_notebook,
    parse_pre_registration,
    save_belief_map,
    validate_pre_registration,
    verify_data_hash,
    write_convergence,
)


# ---------------------------------------------------------------------------
# Pre-registration
# ---------------------------------------------------------------------------

class TestPreRegistration:
    def test_parse_complete(self):
        notes = (
            "PRE_REG: HYPOTHESIS=[encoding outperforms raw] | "
            "METHOD=[ablation ladder] | CONTROLS=[same LLM, same data] | "
            "EXPECTED_RESULT=[full encoding > raw by d=0.5] | "
            "CONFOUNDS=[prompt variation] | STAT_TEST=[Welch t-test] | "
            "SAMPLE_SIZE=[100]"
        )
        pr = parse_pre_registration(notes)
        assert pr.hypothesis == "encoding outperforms raw"
        assert pr.method == "ablation ladder"
        assert pr.controls == "same LLM, same data"
        assert pr.stat_test == "Welch t-test"
        assert pr.sample_size == "100"
        assert pr.is_complete is True

    def test_parse_incomplete(self):
        notes = "PRE_REG: HYPOTHESIS=[test something] | METHOD=[run it]"
        pr = parse_pre_registration(notes)
        assert pr.hypothesis == "test something"
        assert pr.is_complete is False

    def test_parse_scientific_with_power(self):
        notes = (
            "PRE_REG: HYPOTHESIS=[h1] | METHOD=[m1] | CONTROLS=[c1] | "
            "EXPECTED_RESULT=[e1] | CONFOUNDS=[cf1] | STAT_TEST=[t1] | SAMPLE_SIZE=[50]\n"
            "PRE_REG_POWER: EFFECT_SIZE=[0.5d] | POWER=[0.80] | MIN_N=[64]\n"
            "PRE_REG_SENSITIVITY: PARAM1=[noise, 0.5-1.5] | PARAM2=[N, 50-200]"
        )
        pr = parse_pre_registration(notes)
        assert pr.is_complete is True
        assert pr.power_analysis == "0.5d"
        assert "PARAM1" in pr.sensitivity_plan

    def test_validate_standard_ok(self):
        notes = (
            "PRE_REG: HYPOTHESIS=[h] | METHOD=[m] | CONTROLS=[c] | "
            "EXPECTED_RESULT=[e] | CONFOUNDS=[cf] | STAT_TEST=[t] | SAMPLE_SIZE=[10]"
        )
        valid, missing = validate_pre_registration(notes, "analytical")
        assert valid is True
        assert missing == []

    def test_validate_scientific_missing_power(self):
        notes = (
            "PRE_REG: HYPOTHESIS=[h] | METHOD=[m] | CONTROLS=[c] | "
            "EXPECTED_RESULT=[e] | CONFOUNDS=[cf] | STAT_TEST=[t] | SAMPLE_SIZE=[10]"
        )
        valid, missing = validate_pre_registration(notes, "scientific")
        assert valid is False
        assert "POWER_ANALYSIS" in missing
        assert "SENSITIVITY_PLAN" in missing

    def test_validate_empty(self):
        valid, missing = validate_pre_registration("", "analytical")
        assert valid is False
        assert len(missing) > 0

    def test_parse_deviation(self):
        notes = (
            "PRE_REG: HYPOTHESIS=[h] | METHOD=[m] | CONTROLS=[c] | "
            "EXPECTED_RESULT=[e] | CONFOUNDS=[cf] | STAT_TEST=[t] | SAMPLE_SIZE=[10]\n"
            "PRE_REG_DEVIATION: WHAT=[changed N] | WHY=[insufficient power]"
        )
        pr = parse_pre_registration(notes)
        assert len(pr.deviations) == 1
        assert "changed N" in pr.deviations[0]


# ---------------------------------------------------------------------------
# Belief Map
# ---------------------------------------------------------------------------

class TestBeliefMap:
    def test_create_and_add(self):
        bm = BeliefMap()
        h = Hypothesis(id="H1", name="Encoding helps", prior=0.7, posterior=0.7)
        bm.add_hypothesis(h)
        assert len(bm.hypotheses) == 1
        assert bm.hypotheses[0].name == "Encoding helps"

    def test_uncertainty_at_half(self):
        h = Hypothesis(id="H1", name="test", prior=0.5, posterior=0.5)
        assert h.uncertainty == pytest.approx(1.0)

    def test_uncertainty_at_extreme(self):
        h = Hypothesis(id="H1", name="test", prior=0.5, posterior=0.0)
        assert h.uncertainty == pytest.approx(0.0)

    def test_uncertainty_at_one(self):
        h = Hypothesis(id="H1", name="test", prior=0.5, posterior=1.0)
        assert h.uncertainty == pytest.approx(0.0)

    def test_information_gain(self):
        h = Hypothesis(id="H1", name="test", prior=0.5, posterior=0.5,
                       impact=0.8, testability=0.9)
        assert h.information_gain == pytest.approx(1.0 * 0.8 * 0.9)

    def test_update_hypothesis(self):
        bm = BeliefMap()
        bm.add_hypothesis(Hypothesis(id="H1", name="test", prior=0.5, posterior=0.5))
        assert bm.update_hypothesis("H1", 0.9, "confirmed", "bd-42") is True
        assert bm.hypotheses[0].posterior == 0.9
        assert bm.hypotheses[0].status == "confirmed"
        assert "bd-42" in bm.hypotheses[0].evidence

    def test_update_nonexistent(self):
        bm = BeliefMap()
        assert bm.update_hypothesis("H99", 0.5, "testing") is False

    def test_priority_order(self):
        bm = BeliefMap()
        bm.add_hypothesis(Hypothesis(id="H1", name="low info", prior=0.5, posterior=0.1,
                                      impact=0.5, testability=0.5))
        bm.add_hypothesis(Hypothesis(id="H2", name="high info", prior=0.5, posterior=0.5,
                                      impact=0.9, testability=0.9))
        order = bm.get_priority_order()
        assert order[0].id == "H2"  # Higher info gain first

    def test_all_resolved(self):
        bm = BeliefMap()
        bm.add_hypothesis(Hypothesis(id="H1", name="a", prior=0.5, posterior=0.9,
                                      status="confirmed"))
        bm.add_hypothesis(Hypothesis(id="H2", name="b", prior=0.5, posterior=0.1,
                                      status="refuted"))
        assert bm.all_resolved() is True

    def test_not_all_resolved(self):
        bm = BeliefMap()
        bm.add_hypothesis(Hypothesis(id="H1", name="a", prior=0.5, posterior=0.9,
                                      status="confirmed"))
        bm.add_hypothesis(Hypothesis(id="H2", name="b", prior=0.5, posterior=0.5,
                                      status="untested"))
        assert bm.all_resolved() is False

    def test_save_and_load(self, tmp_path):
        bm = BeliefMap(cycle=3)
        bm.add_hypothesis(Hypothesis(
            id="H1", name="test", prior=0.6, posterior=0.8,
            status="confirmed", evidence=["bd-1", "bd-2"],
            testability=0.7, impact=0.9,
        ))
        save_belief_map(tmp_path, bm)
        loaded = load_belief_map(tmp_path)
        assert loaded.cycle == 3
        assert len(loaded.hypotheses) == 1
        assert loaded.hypotheses[0].posterior == 0.8
        assert loaded.hypotheses[0].status == "confirmed"

    def test_load_missing(self, tmp_path):
        bm = load_belief_map(tmp_path)
        assert bm.hypotheses == []

    def test_load_corrupt(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "belief-map.json").write_text("not json{")
        bm = load_belief_map(tmp_path)
        assert bm.hypotheses == []

    def test_summary(self):
        bm = BeliefMap(cycle=2)
        bm.add_hypothesis(Hypothesis(id="H1", name="a", prior=0.5, posterior=0.9,
                                      status="confirmed"))
        bm.add_hypothesis(Hypothesis(id="H2", name="b", prior=0.5, posterior=0.1,
                                      status="refuted"))
        s = bm.summary()
        assert s["total"] == 2
        assert s["by_status"]["confirmed"] == 1
        assert s["by_status"]["refuted"] == 1


# ---------------------------------------------------------------------------
# Convergence
# ---------------------------------------------------------------------------

class TestConvergence:
    def test_standard_with_deliverable(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "deliverable.md").write_text("# Done")
        result = check_convergence(tmp_path, "standard")
        assert result.converged is True
        assert result.status == "converged"

    def test_standard_no_deliverable(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        result = check_convergence(tmp_path, "standard")
        assert result.converged is False

    def test_analytical_high_score(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        result = check_convergence(tmp_path, "analytical", eval_score=0.80)
        assert result.converged is True

    def test_analytical_low_score_needs_improvement(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        result = check_convergence(tmp_path, "analytical", eval_score=0.60,
                                    improvement_rounds=0)
        assert result.converged is False
        assert result.status == "not_ready"

    def test_analytical_max_improvement_rounds(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        result = check_convergence(tmp_path, "analytical", eval_score=0.60,
                                    improvement_rounds=2)
        assert result.converged is True
        assert result.status == "diminishing_returns"

    def test_write_convergence(self, tmp_path):
        result = ConvergenceResult(True, "converged", "All done", score=0.85)
        path = write_convergence(tmp_path, result)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["converged"] is True
        assert data["status"] == "converged"
        assert data["score"] == 0.85


# ---------------------------------------------------------------------------
# Paradigm Stress
# ---------------------------------------------------------------------------

class TestParadigmStress:
    def test_no_stress(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        result = check_paradigm_stress(tmp_path)
        assert result.stressed is False

    # Note: Full paradigm stress testing requires bd to be available,
    # so we test the logic via the data structures instead.
    def test_stress_result_structure(self):
        from voronoi.science import ParadigmStressResult
        r = ParadigmStressResult(
            stressed=True,
            contradiction_count=3,
            contradicting_findings=["bd-1", "bd-2", "bd-3"],
            message="test",
        )
        assert r.stressed is True
        assert r.contradiction_count == 3


# ---------------------------------------------------------------------------
# Consistency Gate
# ---------------------------------------------------------------------------

class TestConsistencyGate:
    def test_no_conflict_different_topics(self):
        findings = [
            {"id": "bd-1", "title": "FINDING: cache improves throughput",
             "notes": "STAT_REVIEW: APPROVED\nVALENCE:positive"},
            {"id": "bd-2", "title": "FINDING: auth module works correctly",
             "notes": "STAT_REVIEW: APPROVED\nVALENCE:positive"},
        ]
        conflicts = check_consistency(findings)
        assert len(conflicts) == 0

    def test_conflict_opposing_valence(self):
        findings = [
            {"id": "bd-1", "title": "FINDING: encoding helps cross lever discovery",
             "notes": "STAT_REVIEW: APPROVED\nVALENCE:positive"},
            {"id": "bd-2", "title": "FINDING: encoding hurts cross lever analysis",
             "notes": "STAT_REVIEW: APPROVED\nVALENCE:negative"},
        ]
        conflicts = check_consistency(findings)
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == "direction"

    def test_no_conflict_same_valence(self):
        findings = [
            {"id": "bd-1", "title": "FINDING: encoding helps cross lever discovery",
             "notes": "STAT_REVIEW: APPROVED\nVALENCE:positive"},
            {"id": "bd-2", "title": "FINDING: encoding boost cross lever detection",
             "notes": "STAT_REVIEW: APPROVED\nVALENCE:positive"},
        ]
        conflicts = check_consistency(findings)
        assert len(conflicts) == 0

    def test_skip_non_approved(self):
        findings = [
            {"id": "bd-1", "title": "FINDING: encoding helps cross lever discovery",
             "notes": "STAT_REVIEW: APPROVED\nVALENCE:positive"},
            {"id": "bd-2", "title": "FINDING: encoding hurts cross lever analysis",
             "notes": "VALENCE:negative"},  # Not approved
        ]
        conflicts = check_consistency(findings)
        assert len(conflicts) == 0


# ---------------------------------------------------------------------------
# Lab Notebook
# ---------------------------------------------------------------------------

class TestLabNotebook:
    def test_append_and_load(self, tmp_path):
        entry = LabNotebookEntry(
            cycle=1, phase="investigating", verdict="iterate",
            metrics={"score": 0.65}, failures=["hypothesis H2 refuted"],
            next_steps=["test H3"],
        )
        append_lab_notebook(tmp_path, entry)
        entries = load_lab_notebook(tmp_path)
        assert len(entries) == 1
        assert entries[0].cycle == 1
        assert entries[0].verdict == "iterate"
        assert entries[0].timestamp != ""

    def test_append_multiple(self, tmp_path):
        for i in range(3):
            append_lab_notebook(tmp_path, LabNotebookEntry(
                cycle=i, phase="test", verdict="pass",
            ))
        entries = load_lab_notebook(tmp_path)
        assert len(entries) == 3

    def test_load_empty(self, tmp_path):
        assert load_lab_notebook(tmp_path) == []

    def test_load_corrupt(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "lab-notebook.json").write_text("{bad")
        assert load_lab_notebook(tmp_path) == []


# ---------------------------------------------------------------------------
# Data Integrity
# ---------------------------------------------------------------------------

class TestDataIntegrity:
    def test_verify_correct_hash(self, tmp_path):
        data_file = tmp_path / "data.csv"
        data_file.write_text("a,b,c\n1,2,3\n")
        import hashlib
        expected = "sha256:" + hashlib.sha256(data_file.read_bytes()).hexdigest()
        assert verify_data_hash(data_file, expected) is True

    def test_verify_wrong_hash(self, tmp_path):
        data_file = tmp_path / "data.csv"
        data_file.write_text("a,b,c\n1,2,3\n")
        assert verify_data_hash(data_file, "sha256:0000000000") is False

    def test_verify_missing_file(self, tmp_path):
        assert verify_data_hash(tmp_path / "missing.csv", "sha256:abc") is False


# ---------------------------------------------------------------------------
# Dispatch Gates
# ---------------------------------------------------------------------------

class TestDispatchGates:
    def test_no_gates(self, tmp_path):
        task = {"notes": "", "title": "Build something"}
        ok, blockers = check_dispatch_gates(task, tmp_path, "standard")
        assert ok is True
        assert blockers == []

    def test_requires_file_missing(self, tmp_path):
        task = {"notes": "REQUIRES:data/input.csv", "title": "Process data"}
        ok, blockers = check_dispatch_gates(task, tmp_path, "standard")
        assert ok is False
        assert any("REQUIRES missing" in b for b in blockers)

    def test_requires_file_present(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "input.csv").write_text("data")
        task = {"notes": "REQUIRES:data/input.csv", "title": "Process data"}
        ok, blockers = check_dispatch_gates(task, tmp_path, "standard")
        assert ok is True

    def test_gate_file_missing(self, tmp_path):
        task = {"notes": "GATE:.swarm/validation_report.json", "title": "Write paper"}
        ok, blockers = check_dispatch_gates(task, tmp_path, "standard")
        assert ok is False
        assert any("GATE file missing" in b for b in blockers)

    def test_gate_file_not_passing(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "validation_report.json").write_text(
            json.dumps({"status": "failed"}))
        task = {"notes": "GATE:.swarm/validation_report.json", "title": "Write paper"}
        ok, blockers = check_dispatch_gates(task, tmp_path, "standard")
        assert ok is False
        assert any("GATE not passing" in b for b in blockers)

    def test_gate_file_passing(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "validation_report.json").write_text(
            json.dumps({"status": "pass", "converged": True}))
        task = {"notes": "GATE:.swarm/validation_report.json", "title": "Write paper"}
        ok, blockers = check_dispatch_gates(task, tmp_path, "standard")
        assert ok is True

    def test_scientific_investigation_needs_methodologist(self, tmp_path):
        task = {"notes": "TASK_TYPE:investigation", "title": "Test H1"}
        ok, blockers = check_dispatch_gates(task, tmp_path, "scientific")
        assert ok is False
        assert any("Methodologist" in b for b in blockers)

    def test_scientific_investigation_approved(self, tmp_path):
        task = {
            "notes": (
                "TASK_TYPE:investigation\n"
                "METHODOLOGIST_REVIEW: APPROVED\n"
                "PRE_REG: HYPOTHESIS=[h] | METHOD=[m] | CONTROLS=[c] | "
                "EXPECTED_RESULT=[e] | CONFOUNDS=[cf] | STAT_TEST=[t] | SAMPLE_SIZE=[10]\n"
                "PRE_REG_POWER: EFFECT_SIZE=[0.5d] | POWER=[0.80] | MIN_N=[64]\n"
                "PRE_REG_SENSITIVITY: PARAM1=[noise, 0.5-1.5] | PARAM2=[N, 50-200]"
            ),
            "title": "Test H1",
        }
        ok, blockers = check_dispatch_gates(task, tmp_path, "scientific")
        assert ok is True


# ---------------------------------------------------------------------------
# Merge Gates
# ---------------------------------------------------------------------------

class TestMergeGates:
    def test_no_gates(self, tmp_path):
        task = {"notes": "", "title": "Build something"}
        ok, blockers = check_merge_gates(task, tmp_path, "standard")
        assert ok is True

    def test_produces_missing(self, tmp_path):
        task = {"notes": "PRODUCES:output/results.json", "title": "Run experiments"}
        ok, blockers = check_merge_gates(task, tmp_path, "standard")
        assert ok is False
        assert any("PRODUCES missing" in b for b in blockers)

    def test_produces_present(self, tmp_path):
        (tmp_path / "output").mkdir()
        (tmp_path / "output" / "results.json").write_text("{}")
        task = {"notes": "PRODUCES:output/results.json", "title": "Run experiments"}
        ok, blockers = check_merge_gates(task, tmp_path, "standard")
        assert ok is True

    def test_finding_needs_stat_review(self, tmp_path):
        task = {"notes": "TYPE:finding", "title": "FINDING: encoding helps"}
        ok, blockers = check_merge_gates(task, tmp_path, "analytical")
        assert ok is False
        assert any("Statistician" in b for b in blockers)

    def test_finding_with_stat_review(self, tmp_path):
        task = {
            "notes": "TYPE:finding\nSTAT_REVIEW: APPROVED | QUALITY:0.91",
            "title": "FINDING: encoding helps",
        }
        ok, blockers = check_merge_gates(task, tmp_path, "analytical")
        assert ok is True

    def test_finding_needs_critic_at_scientific(self, tmp_path):
        task = {
            "notes": "TYPE:finding\nSTAT_REVIEW: APPROVED",
            "title": "FINDING: encoding helps",
        }
        ok, blockers = check_merge_gates(task, tmp_path, "scientific")
        assert ok is False
        assert any("Critic" in b for b in blockers)

    def test_finding_fully_reviewed(self, tmp_path):
        task = {
            "notes": "TYPE:finding\nSTAT_REVIEW: APPROVED\nCRITIC_REVIEW: APPROVED",
            "title": "FINDING: encoding helps",
        }
        ok, blockers = check_merge_gates(task, tmp_path, "scientific")
        assert ok is True


# ---------------------------------------------------------------------------
# Claim-Evidence Registry
# ---------------------------------------------------------------------------

class TestClaimEvidenceRegistry:
    def test_create_and_audit(self):
        from voronoi.science import ClaimEvidence, ClaimEvidenceRegistry
        reg = ClaimEvidenceRegistry()
        reg.add_claim(ClaimEvidence(
            claim_id="C1", claim_text="Encoding helps",
            finding_ids=["bd-5"], strength="robust",
        ))
        reg.add_claim(ClaimEvidence(
            claim_id="C2", claim_text="Pipeline scales",
            finding_ids=[], strength="unsupported",
        ))
        reg.audit(["bd-5", "bd-6"])
        assert reg.coverage_score == 0.5
        assert "C2" in reg.unsupported_claims
        assert "bd-6" in reg.orphan_findings

    def test_save_and_load(self, tmp_path):
        from voronoi.science import (
            ClaimEvidence, ClaimEvidenceRegistry,
            save_claim_evidence, load_claim_evidence,
        )
        reg = ClaimEvidenceRegistry()
        reg.add_claim(ClaimEvidence(
            claim_id="C1", claim_text="Test claim",
            finding_ids=["bd-1"], strength="provisional",
            interpretation="Medium practical effect",
        ))
        reg.audit(["bd-1"])
        save_claim_evidence(tmp_path, reg)
        loaded = load_claim_evidence(tmp_path)
        assert len(loaded.claims) == 1
        assert loaded.claims[0].claim_text == "Test claim"
        assert loaded.claims[0].interpretation == "Medium practical effect"
        assert loaded.coverage_score == 1.0

    def test_load_missing(self, tmp_path):
        from voronoi.science import load_claim_evidence
        reg = load_claim_evidence(tmp_path)
        assert reg.claims == []

    def test_load_corrupt(self, tmp_path):
        from voronoi.science import load_claim_evidence
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "claim-evidence.json").write_text("{not json")
        reg = load_claim_evidence(tmp_path)
        assert reg.claims == []

    def test_all_claims_supported(self):
        from voronoi.science import ClaimEvidence, ClaimEvidenceRegistry
        reg = ClaimEvidenceRegistry()
        reg.add_claim(ClaimEvidence(
            claim_id="C1", claim_text="Claim 1",
            finding_ids=["bd-1"], strength="robust",
        ))
        reg.add_claim(ClaimEvidence(
            claim_id="C2", claim_text="Claim 2",
            finding_ids=["bd-2"], strength="provisional",
        ))
        reg.audit(["bd-1", "bd-2"])
        assert reg.coverage_score == 1.0
        assert reg.unsupported_claims == []
        assert reg.orphan_findings == []


# ---------------------------------------------------------------------------
# Pre-registration Compliance
# ---------------------------------------------------------------------------

class TestPreRegCompliance:
    def test_compliant(self):
        from voronoi.science import audit_pre_registration_compliance
        notes = (
            "PRE_REG: HYPOTHESIS=[encoding helps] | METHOD=[ablation] | "
            "CONTROLS=[same data] | EXPECTED_RESULT=[encoding > raw by d=0.5] | "
            "CONFOUNDS=[prompt] | STAT_TEST=[t-test] | SAMPLE_SIZE=[100]\n"
            "VALENCE:positive\nN:100"
        )
        result = audit_pre_registration_compliance(notes)
        assert result.compliant is True

    def test_unexpected_negative_no_deviation(self):
        from voronoi.science import audit_pre_registration_compliance
        notes = (
            "PRE_REG: HYPOTHESIS=[encoding helps] | METHOD=[ablation] | "
            "CONTROLS=[same data] | EXPECTED_RESULT=[encoding outperforms raw] | "
            "CONFOUNDS=[prompt] | STAT_TEST=[t-test] | SAMPLE_SIZE=[100]\n"
            "VALENCE:negative"
        )
        result = audit_pre_registration_compliance(notes)
        assert result.compliant is False
        assert len(result.undocumented_deviations) > 0

    def test_n_deviation_undocumented(self):
        from voronoi.science import audit_pre_registration_compliance
        notes = (
            "PRE_REG: HYPOTHESIS=[h] | METHOD=[m] | CONTROLS=[c] | "
            "EXPECTED_RESULT=[positive] | CONFOUNDS=[cf] | STAT_TEST=[t] | "
            "SAMPLE_SIZE=[100]\n"
            "VALENCE:positive\nN:50"
        )
        result = audit_pre_registration_compliance(notes)
        assert result.compliant is False
        assert any("Sample size" in d for d in result.undocumented_deviations)

    def test_n_deviation_documented(self):
        from voronoi.science import audit_pre_registration_compliance
        notes = (
            "PRE_REG: HYPOTHESIS=[h] | METHOD=[m] | CONTROLS=[c] | "
            "EXPECTED_RESULT=[positive] | CONFOUNDS=[cf] | STAT_TEST=[t] | "
            "SAMPLE_SIZE=[100]\n"
            "PRE_REG_DEVIATION: WHAT=[changed sample size from 100 to 50] | WHY=[insufficient data]\n"
            "VALENCE:positive\nN:50"
        )
        result = audit_pre_registration_compliance(notes)
        assert result.compliant is True


# ---------------------------------------------------------------------------
# Enhanced Consistency Check
# ---------------------------------------------------------------------------

class TestEnhancedConsistency:
    def test_direction_conflict_with_stemming(self):
        from voronoi.science import check_consistency_enhanced
        findings = [
            {"id": "bd-1", "title": "FINDING: price elasticity estimation improves revenue prediction",
             "notes": "STAT_REVIEW: APPROVED\nVALENCE:positive"},
            {"id": "bd-2", "title": "FINDING: pricing elasticity estimates hurt revenue forecasting",
             "notes": "STAT_REVIEW: APPROVED\nVALENCE:negative"},
        ]
        conflicts = check_consistency_enhanced(findings)
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == "direction"

    def test_no_conflict_different_topics(self):
        from voronoi.science import check_consistency_enhanced
        findings = [
            {"id": "bd-1", "title": "FINDING: cache improves throughput",
             "notes": "STAT_REVIEW: APPROVED\nVALENCE:positive"},
            {"id": "bd-2", "title": "FINDING: auth module works correctly",
             "notes": "STAT_REVIEW: APPROVED\nVALENCE:positive"},
        ]
        conflicts = check_consistency_enhanced(findings)
        assert len(conflicts) == 0

    def test_magnitude_conflict(self):
        from voronoi.science import check_consistency_enhanced
        findings = [
            {"id": "bd-1",
             "title": "FINDING: encoding helps cross lever discovery via structured input",
             "notes": "STAT_REVIEW: APPROVED\nVALENCE:positive\nEFFECT_SIZE:2.5"},
            {"id": "bd-2",
             "title": "FINDING: encoding boost cross lever detection through structured data",
             "notes": "STAT_REVIEW: APPROVED\nVALENCE:positive\nEFFECT_SIZE:0.1"},
        ]
        conflicts = check_consistency_enhanced(findings)
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == "magnitude"

    def test_tokenize_removes_stopwords(self):
        from voronoi.science import _tokenize_title
        tokens = _tokenize_title("FINDING: this is a test with some very basic words")
        assert "this" not in tokens
        assert "with" not in tokens
        assert "some" not in tokens
        assert "test" in tokens or "basic" in tokens


# ---------------------------------------------------------------------------
# Finding Interpretation
# ---------------------------------------------------------------------------

class TestFindingInterpretation:
    def test_classify_effect_size(self):
        from voronoi.science import classify_effect_size
        assert classify_effect_size(0.1) == "negligible"
        assert classify_effect_size(0.3) == "small"
        assert classify_effect_size(0.6) == "medium"
        assert classify_effect_size(0.9) == "large"
        assert classify_effect_size(1.5) == "very large"

    def test_assess_ci_quality(self):
        from voronoi.science import assess_ci_quality
        assert assess_ci_quality("0.8", "[0.6, 1.0]") == "adequate"
        assert assess_ci_quality("0.8", "[0.75, 0.85]") == "precise"
        assert assess_ci_quality("0.5", "[-0.5, 1.5]") in ("very wide", "wide")

    def test_interpret_finding_robust(self):
        from voronoi.science import interpret_finding
        finding = {
            "title": "FINDING: encoding helps",
            "notes": (
                "EFFECT_SIZE:0.82\nCI_95:[0.61, 1.03]\n"
                "VALENCE:positive\nROBUST:yes\n"
                "STAT_REVIEW: APPROVED"
            ),
        }
        result = interpret_finding(finding)
        assert result["practical_significance"] == "large"
        assert result["strength_label"] == "robust"
        assert "robust" in result["interpretation_text"]

    def test_interpret_finding_fragile(self):
        from voronoi.science import interpret_finding
        finding = {
            "title": "FINDING: weak signal",
            "notes": (
                "EFFECT_SIZE:0.2\nCI_95:[-0.5, 0.9]\n"
                "VALENCE:inconclusive\nROBUST:no\n"
                "STAT_REVIEW: APPROVED"
            ),
        }
        result = interpret_finding(finding)
        assert result["practical_significance"] == "small"
        assert result["strength_label"] == "fragile"
        assert "fragile" in result["interpretation_text"]

    def test_interpret_finding_unreviewed(self):
        from voronoi.science import interpret_finding
        finding = {
            "title": "FINDING: preliminary",
            "notes": "EFFECT_SIZE:0.5\nVALENCE:positive",
        }
        result = interpret_finding(finding)
        assert result["strength_label"] == "unreviewed"
