"""Tests for voronoi.science — science gate enforcement layer."""

import json
from pathlib import Path

import pytest

from voronoi.science import (
    AntiFabricationResult,
    BeliefMap,
    CalibrationResult,
    ConsistencyConflict,
    ConvergenceResult,
    FabricationFlag,
    Hypothesis,
    Invariant,
    InvariantCheckResult,
    PreRegistration,
    ReplicationNeed,
    SimulationBypassResult,
    audit_all_findings,
    check_calibration,
    check_consistency,
    check_convergence,
    check_dispatch_gates,
    check_heartbeat_stall,
    check_invariants,
    check_merge_gates,
    check_paradigm_stress,
    compute_data_hash,
    detect_simulation_bypass,
    format_fabrication_report,
    format_invariants_for_prompt,
    load_belief_map,
    load_invariants,
    load_success_criteria,
    parse_pre_registration,
    parse_revise_context,
    save_belief_map,
    save_invariants,
    save_success_criteria,
    validate_pre_registration,
    validate_data_invariants,
    verify_data_hash,
    verify_finding_against_data,
    write_convergence,
    OrchestratorCheckpoint,
    load_checkpoint,
    save_checkpoint,
    format_checkpoint_for_prompt,
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
        valid, missing = validate_pre_registration(notes, "adaptive")
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
        valid, missing = validate_pre_registration("", "adaptive")
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
        result = check_convergence(tmp_path, "adaptive")
        assert result.converged is True
        assert result.status == "converged"

    def test_standard_no_deliverable(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        result = check_convergence(tmp_path, "adaptive")
        assert result.converged is False

    def test_adaptive_high_score(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "deliverable.md").write_text("# Done")
        result = check_convergence(tmp_path, "adaptive", eval_score=0.80)
        assert result.converged is True

    def test_adaptive_low_score_needs_improvement(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "deliverable.md").write_text("# Done")
        result = check_convergence(tmp_path, "adaptive", eval_score=0.60,
                                    improvement_rounds=0)
        assert result.converged is False
        assert result.status == "not_ready"

    def test_adaptive_max_improvement_rounds(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "deliverable.md").write_text("# Done")
        result = check_convergence(tmp_path, "adaptive", eval_score=0.60,
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
        ok, blockers = check_dispatch_gates(task, tmp_path, "adaptive")
        assert ok is True
        assert blockers == []

    def test_requires_file_missing(self, tmp_path):
        task = {"notes": "REQUIRES:data/input.csv", "title": "Process data"}
        ok, blockers = check_dispatch_gates(task, tmp_path, "adaptive")
        assert ok is False
        assert any("REQUIRES missing" in b for b in blockers)

    def test_requires_file_present(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "input.csv").write_text("data")
        task = {"notes": "REQUIRES:data/input.csv", "title": "Process data"}
        ok, blockers = check_dispatch_gates(task, tmp_path, "adaptive")
        assert ok is True

    def test_gate_file_missing(self, tmp_path):
        task = {"notes": "GATE:.swarm/validation_report.json", "title": "Write paper"}
        ok, blockers = check_dispatch_gates(task, tmp_path, "adaptive")
        assert ok is False
        assert any("GATE file missing" in b for b in blockers)

    def test_gate_file_not_passing(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "validation_report.json").write_text(
            json.dumps({"status": "failed"}))
        task = {"notes": "GATE:.swarm/validation_report.json", "title": "Write paper"}
        ok, blockers = check_dispatch_gates(task, tmp_path, "adaptive")
        assert ok is False
        assert any("GATE not passing" in b for b in blockers)

    def test_gate_file_passing(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "validation_report.json").write_text(
            json.dumps({"status": "pass", "converged": True}))
        task = {"notes": "GATE:.swarm/validation_report.json", "title": "Write paper"}
        ok, blockers = check_dispatch_gates(task, tmp_path, "adaptive")
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
        ok, blockers = check_merge_gates(task, tmp_path, "adaptive")
        assert ok is True

    def test_produces_missing(self, tmp_path):
        task = {"notes": "PRODUCES:output/results.json", "title": "Run experiments"}
        ok, blockers = check_merge_gates(task, tmp_path, "adaptive")
        assert ok is False
        assert any("PRODUCES missing" in b for b in blockers)

    def test_produces_present(self, tmp_path):
        (tmp_path / "output").mkdir()
        (tmp_path / "output" / "results.json").write_text("{}")
        task = {"notes": "PRODUCES:output/results.json", "title": "Run experiments"}
        ok, blockers = check_merge_gates(task, tmp_path, "adaptive")
        assert ok is True

    def test_finding_needs_stat_review(self, tmp_path):
        task = {"notes": "TYPE:finding", "title": "FINDING: encoding helps"}
        ok, blockers = check_merge_gates(task, tmp_path, "adaptive")
        assert ok is False
        assert any("Statistician" in b for b in blockers)

    def test_finding_with_stat_review(self, tmp_path):
        # Set up valid data file so anti-fabrication check passes
        data_dir = tmp_path / "data" / "raw"
        data_dir.mkdir(parents=True)
        csv_file = data_dir / "results.csv"
        csv_file.write_text("score\n1\n2\n3\n")
        from voronoi.science import compute_data_hash
        h = compute_data_hash(csv_file)
        exp_dir = tmp_path / "experiments"
        exp_dir.mkdir()
        (exp_dir / "run.py").write_text("# experiment\n")
        task = {
            "notes": (
                "TYPE:finding\nSTAT_REVIEW: APPROVED | QUALITY:0.91\n"
                f"DATA_FILE:data/raw/results.csv\nDATA_HASH:{h}\nN:3\n"
            ),
            "title": "FINDING: encoding helps",
        }
        ok, blockers = check_merge_gates(task, tmp_path, "adaptive")
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
        # Set up valid data so anti-fabrication check passes at scientific rigor
        data_dir = tmp_path / "data" / "raw"
        data_dir.mkdir(parents=True)
        csv_file = data_dir / "results.csv"
        csv_file.write_text("score\n1\n2\n3\n")
        from voronoi.science import compute_data_hash
        h = compute_data_hash(csv_file)
        exp_dir = tmp_path / "experiments"
        exp_dir.mkdir()
        (exp_dir / "run.py").write_text("# experiment\n")
        task = {
            "notes": (
                "TYPE:finding\nSTAT_REVIEW: APPROVED\nCRITIC_REVIEW: APPROVED\n"
                f"DATA_FILE:data/raw/results.csv\nDATA_HASH:{h}\nN:3\n"
            ),
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

    def test_load_list_with_non_dict_claims(self, tmp_path):
        """Regression: LLM may emit a list-of-lists instead of list-of-dicts."""
        import json
        from voronoi.science import load_claim_evidence
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "claim-evidence.json").write_text(json.dumps([
            ["C1", "some claim", ["bd-1"]],
            {"claim_id": "C2", "claim_text": "valid claim", "finding_ids": ["bd-2"]},
        ]))
        reg = load_claim_evidence(tmp_path)
        assert len(reg.claims) == 1
        assert reg.claims[0].claim_id == "C2"

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
        from voronoi.science._helpers import _tokenize_title
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


# ---------------------------------------------------------------------------
# Anti-Fabrication Verification
# ---------------------------------------------------------------------------

class TestComputeDataHash:
    def test_hash_matches(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n3,4\n")
        h = compute_data_hash(f)
        assert h.startswith("sha256:")
        assert verify_data_hash(f, h)

    def test_hash_mismatch(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n")
        assert not verify_data_hash(f, "sha256:0000")


class TestVerifyFindingAgainstData:
    def test_no_data_file_referenced(self, tmp_path):
        notes = "TYPE:finding\nEFFECT_SIZE:0.5\n"
        result = verify_finding_against_data(tmp_path, notes, "bd-1")
        assert not result.passed
        assert any(f.category == "data_missing" for f in result.flags)

    def test_data_file_missing_on_disk(self, tmp_path):
        notes = "DATA_FILE:data/raw/results.csv\nEFFECT_SIZE:0.5\n"
        result = verify_finding_against_data(tmp_path, notes, "bd-1")
        assert not result.passed
        assert any(f.category == "data_missing" for f in result.flags)

    def test_hash_mismatch_critical(self, tmp_path):
        data_dir = tmp_path / "data" / "raw"
        data_dir.mkdir(parents=True)
        csv_file = data_dir / "results.csv"
        csv_file.write_text("group,score\nA,10\nA,12\nB,15\nB,18\n")
        notes = (
            "DATA_FILE:data/raw/results.csv\n"
            "DATA_HASH:sha256:0000badhash\n"
            "EFFECT_SIZE:1.2\nN:4\n"
        )
        result = verify_finding_against_data(tmp_path, notes, "bd-2")
        assert not result.passed
        assert any(f.category == "hash_mismatch" for f in result.flags)

    def test_n_mismatch_critical(self, tmp_path):
        data_dir = tmp_path / "data" / "raw"
        data_dir.mkdir(parents=True)
        csv_file = data_dir / "results.csv"
        csv_file.write_text("group,score\nA,10\nA,12\nB,15\n")
        actual_hash = compute_data_hash(csv_file)
        notes = (
            f"DATA_FILE:data/raw/results.csv\n"
            f"DATA_HASH:{actual_hash}\n"
            "EFFECT_SIZE:0.5\nN:100\n"  # reported N=100, actual rows=3
        )
        result = verify_finding_against_data(tmp_path, notes, "bd-3")
        assert not result.passed
        assert any(f.category == "n_mismatch" for f in result.flags)

    def test_valid_finding_passes(self, tmp_path):
        data_dir = tmp_path / "data" / "raw"
        data_dir.mkdir(parents=True)
        exp_dir = tmp_path / "experiments"
        exp_dir.mkdir()
        (exp_dir / "run_experiment.py").write_text("# experiment code\n")

        csv_file = data_dir / "results.csv"
        rows = ["group,score"] + [f"A,{10 + i * 0.3}" for i in range(50)]
        rows += [f"B,{12 + i * 0.4}" for i in range(50)]
        csv_file.write_text("\n".join(rows) + "\n")
        actual_hash = compute_data_hash(csv_file)

        notes = (
            f"DATA_FILE:data/raw/results.csv\n"
            f"DATA_HASH:{actual_hash}\n"
            "EFFECT_SIZE:0.7\nN:100\nP:0.003\n"
        )
        result = verify_finding_against_data(tmp_path, notes, "bd-4")
        assert result.passed
        assert result.data_file_exists
        assert result.hash_verified
        assert result.experiment_script_exists

    def test_suspiciously_clean_data(self, tmp_path):
        data_dir = tmp_path / "data" / "raw"
        data_dir.mkdir(parents=True)
        csv_file = data_dir / "results.csv"
        # All identical values = zero variance
        rows = ["score"] + ["42.0"] * 20
        csv_file.write_text("\n".join(rows) + "\n")
        actual_hash = compute_data_hash(csv_file)

        notes = (
            f"DATA_FILE:data/raw/results.csv\n"
            f"DATA_HASH:{actual_hash}\n"
            "N:20\nEFFECT_SIZE:0.5\n"
        )
        result = verify_finding_against_data(tmp_path, notes, "bd-5")
        assert any(f.category == "too_clean" for f in result.flags)

    def test_implausible_effect_size(self, tmp_path):
        data_dir = tmp_path / "data" / "raw"
        data_dir.mkdir(parents=True)
        csv_file = data_dir / "results.csv"
        csv_file.write_text("score\n1\n2\n3\n4\n5\n")
        actual_hash = compute_data_hash(csv_file)

        notes = (
            f"DATA_FILE:data/raw/results.csv\n"
            f"DATA_HASH:{actual_hash}\n"
            "N:5\nEFFECT_SIZE:4.5\n"
        )
        result = verify_finding_against_data(tmp_path, notes, "bd-6")
        assert any(f.category == "implausible_effect" for f in result.flags)

    def test_no_experiment_script(self, tmp_path):
        data_dir = tmp_path / "data" / "raw"
        data_dir.mkdir(parents=True)
        csv_file = data_dir / "results.csv"
        csv_file.write_text("score\n1\n2\n3\n")
        actual_hash = compute_data_hash(csv_file)

        notes = (
            f"DATA_FILE:data/raw/results.csv\n"
            f"DATA_HASH:{actual_hash}\n"
            "N:3\nEFFECT_SIZE:0.5\n"
        )
        result = verify_finding_against_data(tmp_path, notes, "bd-7")
        assert any(f.category == "no_experiment_script" for f in result.flags)

    def test_json_data_file(self, tmp_path):
        data_dir = tmp_path / "data" / "raw"
        data_dir.mkdir(parents=True)
        json_file = data_dir / "results.json"
        json_file.write_text(json.dumps({"results": [1, 2, 3]}))
        actual_hash = compute_data_hash(json_file)

        notes = (
            f"DATA_FILE:data/raw/results.json\n"
            f"DATA_HASH:{actual_hash}\n"
            "N:3\nEFFECT_SIZE:0.5\n"
        )
        result = verify_finding_against_data(tmp_path, notes, "bd-8")
        assert result.data_file_exists
        assert result.hash_verified

    def test_corrupt_json_data_file(self, tmp_path):
        data_dir = tmp_path / "data" / "raw"
        data_dir.mkdir(parents=True)
        json_file = data_dir / "results.json"
        json_file.write_text("{bad json")
        actual_hash = compute_data_hash(json_file)

        notes = (
            f"DATA_FILE:data/raw/results.json\n"
            f"DATA_HASH:{actual_hash}\n"
        )
        result = verify_finding_against_data(tmp_path, notes, "bd-9")
        assert not result.passed
        assert any(f.category == "corrupt_data" for f in result.flags)


class TestAuditAllFindings:
    def test_no_findings(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "voronoi.science._helpers._fetch_tasks",
            lambda ws: [{"id": 1, "title": "Build feature X", "notes": ""}],
        )
        results = audit_all_findings(tmp_path)
        assert results == []

    def test_audit_with_findings(self, tmp_path):
        data_dir = tmp_path / "data" / "raw"
        data_dir.mkdir(parents=True)
        csv_file = data_dir / "results.csv"
        csv_file.write_text("score\n1\n2\n3\n")
        actual_hash = compute_data_hash(csv_file)

        tasks = [
            {
                "id": 10,
                "title": "FINDING: effect found",
                "notes": (
                    f"DATA_FILE:data/raw/results.csv\n"
                    f"DATA_HASH:{actual_hash}\n"
                    "N:3\nEFFECT_SIZE:0.5\n"
                ),
            }
        ]
        results = audit_all_findings(tmp_path, tasks=tasks)
        assert len(results) == 1
        assert results[0].finding_id == "10"


class TestFormatFabricationReport:
    def test_empty(self):
        report = format_fabrication_report([])
        assert "No findings" in report

    def test_with_flags(self):
        result = AntiFabricationResult(
            finding_id="bd-1",
            passed=False,
            data_file_exists=False,
            flags=[FabricationFlag(
                severity="critical",
                category="data_missing",
                message="No DATA_FILE",
                finding_id="bd-1",
            )],
        )
        report = format_fabrication_report([result])
        assert "FAIL" in report
        assert "CRITICAL" in report
        assert "bd-1" in report


class TestMergeGateAntiFabrication:
    """Verify that check_merge_gates integrates anti-fabrication checks."""

    def test_finding_without_data_blocked(self, tmp_path, monkeypatch):
        task = {
            "id": 42,
            "title": "FINDING: something discovered",
            "notes": "TYPE:finding\nEFFECT_SIZE:0.5\nSTAT_REVIEW: APPROVED\nCRITIC_REVIEW: APPROVED\n",
        }
        can_merge, blockers = check_merge_gates(task, tmp_path, "adaptive")
        assert not can_merge
        assert any("FABRICATION_CHECK" in b for b in blockers)


# ---------------------------------------------------------------------------
# Investigation-Level Invariants
# ---------------------------------------------------------------------------

class TestInvariants:
    def test_save_and_load(self, tmp_path):
        invariants = [
            Invariant(id="NO_TRUNCATION", description="Never truncate context",
                      check_type="custom"),
            Invariant(id="NO_LEADING", description="Don't list expected effects",
                      check_type="output_excludes",
                      params={"text": "Simpson's paradox"}),
        ]
        save_invariants(tmp_path, invariants)
        loaded = load_invariants(tmp_path)
        assert len(loaded) == 2
        assert loaded[0].id == "NO_TRUNCATION"
        assert loaded[1].params["text"] == "Simpson's paradox"

    def test_load_missing(self, tmp_path):
        assert load_invariants(tmp_path) == []

    def test_load_corrupt(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "invariants.json").write_text("{bad")
        assert load_invariants(tmp_path) == []

    def test_load_skips_invalid_entries(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "invariants.json").write_text(
            json.dumps([{"id": "GOOD", "description": "ok"}, {"no_id": True}, "not a dict"])
        )
        loaded = load_invariants(tmp_path)
        assert len(loaded) == 1
        assert loaded[0].id == "GOOD"

    def test_format_for_prompt(self):
        invariants = [
            Invariant(id="NO_TRUNC", description="Never truncate", check_type="custom"),
        ]
        text = format_invariants_for_prompt(invariants)
        assert "NO_TRUNC" in text
        assert "Never truncate" in text
        assert "MANDATORY" in text

    def test_format_empty(self):
        assert format_invariants_for_prompt([]) == ""

    def test_check_prompt_contains_pass(self):
        inv = [Invariant(id="HAS_WARNING", description="must warn",
                         check_type="prompt_contains", params={"text": "WARNING"})]
        result = check_invariants(inv, "This prompt has a WARNING embedded")
        assert result.passed is True

    def test_check_prompt_contains_fail(self):
        inv = [Invariant(id="HAS_WARNING", description="must warn",
                         check_type="prompt_contains", params={"text": "WARNING"})]
        result = check_invariants(inv, "This prompt has no alerts")
        assert result.passed is False
        assert "HAS_WARNING" in result.violations[0]

    def test_check_output_excludes_pass(self):
        inv = [Invariant(id="NO_LEAK", description="no leaks",
                         check_type="output_excludes", params={"text": "SECRET"})]
        result = check_invariants(inv, "This output is clean")
        assert result.passed is True

    def test_check_output_excludes_fail(self):
        inv = [Invariant(id="NO_LEAK", description="no leaks",
                         check_type="output_excludes", params={"text": "SECRET"})]
        result = check_invariants(inv, "This output contains SECRET data")
        assert result.passed is False

    def test_check_custom_type_passes(self):
        inv = [Invariant(id="CUSTOM", description="custom check",
                         check_type="custom")]
        result = check_invariants(inv, "anything")
        assert result.passed is True


# ---------------------------------------------------------------------------
# Data Invariants (min_csv_rows)
# ---------------------------------------------------------------------------

class TestValidateDataInvariants:
    def test_min_rows_passes(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # Write a CSV with header + 500 data rows
        lines = ["col_a,col_b\n"] + [f"{i},{i*2}\n" for i in range(500)]
        (data_dir / "scenario.csv").write_text("".join(lines))

        inv = [Invariant(id="MIN_ROWS", description="500 rows min",
                         check_type="min_csv_rows",
                         params={"min_rows": 500, "glob": "data/*.csv"})]
        result = validate_data_invariants(tmp_path, inv)
        assert result.passed is True

    def test_min_rows_fails(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # Write a CSV with header + only 150 data rows
        lines = ["col_a,col_b\n"] + [f"{i},{i*2}\n" for i in range(150)]
        (data_dir / "scenario.csv").write_text("".join(lines))

        inv = [Invariant(id="MIN_ROWS", description="500 rows min",
                         check_type="min_csv_rows",
                         params={"min_rows": 500, "glob": "data/*.csv"})]
        result = validate_data_invariants(tmp_path, inv)
        assert result.passed is False
        assert "150" in result.violations[0]
        assert "500" in result.violations[0]

    def test_min_rows_empty_csv(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "empty.csv").write_text("col_a,col_b\n")

        inv = [Invariant(id="MIN_ROWS", description="500 rows min",
                         check_type="min_csv_rows",
                         params={"min_rows": 500, "glob": "data/*.csv"})]
        result = validate_data_invariants(tmp_path, inv)
        assert result.passed is False
        assert "0" in result.violations[0]

    def test_min_rows_no_matching_files(self, tmp_path):
        """No CSV files matching the glob — nothing to check, passes."""
        inv = [Invariant(id="MIN_ROWS", description="500 rows min",
                         check_type="min_csv_rows",
                         params={"min_rows": 500, "glob": "data/*.csv"})]
        result = validate_data_invariants(tmp_path, inv)
        assert result.passed is True

    def test_min_rows_skips_non_csv_invariants(self, tmp_path):
        """Non-min_csv_rows invariants are ignored."""
        inv = [Invariant(id="OTHER", description="text check",
                         check_type="prompt_contains",
                         params={"text": "hello"})]
        result = validate_data_invariants(tmp_path, inv)
        assert result.passed is True

    def test_min_rows_multiple_files(self, tmp_path):
        """One good CSV, one bad — should fail."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        good = ["col_a\n"] + [f"{i}\n" for i in range(500)]
        bad = ["col_a\n"] + [f"{i}\n" for i in range(100)]
        (data_dir / "good.csv").write_text("".join(good))
        (data_dir / "bad.csv").write_text("".join(bad))

        inv = [Invariant(id="MIN_ROWS", description="500 rows min",
                         check_type="min_csv_rows",
                         params={"min_rows": 500, "glob": "data/*.csv"})]
        result = validate_data_invariants(tmp_path, inv)
        assert result.passed is False
        assert len(result.violations) == 1
        assert "bad.csv" in result.violations[0]


# ---------------------------------------------------------------------------
# REVISE Task & Calibration Check
# ---------------------------------------------------------------------------

class TestCalibration:
    def test_calibration_passes(self):
        notes = (
            "CALIBRATION_TARGET:recall_l4=[0.50, 0.70]\n"
            "CALIBRATION_ACTUAL:recall_l4=0.62\n"
        )
        results = check_calibration(notes)
        assert len(results) == 1
        assert results[0].passed is True
        assert results[0].metric_name == "recall_l4"

    def test_calibration_fails_too_high(self):
        notes = (
            "CALIBRATION_TARGET:recall_l4=[0.50, 0.70]\n"
            "CALIBRATION_ACTUAL:recall_l4=0.85\n"
        )
        results = check_calibration(notes)
        assert len(results) == 1
        assert results[0].passed is False

    def test_calibration_fails_too_low(self):
        notes = (
            "CALIBRATION_TARGET:recall_l1=[0.20, 0.40]\n"
            "CALIBRATION_ACTUAL:recall_l1=0.05\n"
        )
        results = check_calibration(notes)
        assert results[0].passed is False

    def test_calibration_missing_actual(self):
        notes = "CALIBRATION_TARGET:recall_l4=[0.50, 0.70]\n"
        results = check_calibration(notes)
        assert len(results) == 1
        assert results[0].passed is False
        assert "no actual" in results[0].message

    def test_calibration_multiple_metrics(self):
        notes = (
            "CALIBRATION_TARGET:recall_l4=[0.50, 0.70]\n"
            "CALIBRATION_TARGET:recall_l1=[0.20, 0.40]\n"
            "CALIBRATION_ACTUAL:recall_l4=0.60\n"
            "CALIBRATION_ACTUAL:recall_l1=0.30\n"
        )
        results = check_calibration(notes)
        assert len(results) == 2
        assert all(r.passed for r in results)

    def test_calibration_no_targets(self):
        results = check_calibration("just some notes")
        assert results == []


class TestReviseContext:
    def test_parse_revise(self):
        notes = (
            "REVISE_OF:bd-42\n"
            "PRIOR_RESULT:L4 recall was 0.95 (too easy)\n"
            "FAILURE_DIAGNOSIS:planted effects not encoding-sensitive\n"
            "REVISED_PARAMS:increase noise, add confounders\n"
        )
        ctx = parse_revise_context(notes)
        assert ctx["revise_of"] == "bd-42"
        assert "too easy" in ctx["prior_result"]
        assert "encoding-sensitive" in ctx["failure_diagnosis"]
        assert "confounders" in ctx["revised_params"]

    def test_parse_revise_empty(self):
        ctx = parse_revise_context("some normal notes")
        assert ctx == {}

    def test_parse_revise_partial(self):
        notes = "REVISE_OF:bd-10\nPRIOR_RESULT:failed calibration\n"
        ctx = parse_revise_context(notes)
        assert "revise_of" in ctx
        assert "prior_result" in ctx
        assert "failure_diagnosis" not in ctx


# ---------------------------------------------------------------------------
# Heartbeat Stall Detection
# ---------------------------------------------------------------------------

class TestHeartbeatStall:
    def test_stall_detected(self, tmp_path):
        from datetime import datetime, timezone, timedelta
        base = datetime.now(timezone.utc) - timedelta(minutes=15)
        path = tmp_path / ".swarm" / "heartbeat-stuck.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for i in range(5):
            ts = (base + timedelta(minutes=i * 3)).isoformat()
            lines.append(json.dumps({
                "branch": "stuck", "phase": "building", "iteration": 1,
                "last_action": "waiting", "status": "idle", "timestamp": ts,
            }))
        path.write_text("\n".join(lines) + "\n")
        assert check_heartbeat_stall(tmp_path, "stuck") is True

    def test_no_stall_when_changing(self, tmp_path):
        from datetime import datetime, timezone, timedelta
        base = datetime.now(timezone.utc) - timedelta(minutes=15)
        path = tmp_path / ".swarm" / "heartbeat-active.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for i in range(5):
            ts = (base + timedelta(minutes=i * 3)).isoformat()
            lines.append(json.dumps({
                "branch": "active", "phase": f"phase-{i}", "iteration": i,
                "last_action": "working", "status": "active", "timestamp": ts,
            }))
        path.write_text("\n".join(lines) + "\n")
        assert check_heartbeat_stall(tmp_path, "active") is False

    def test_no_stall_missing_file(self, tmp_path):
        assert check_heartbeat_stall(tmp_path, "nonexistent") is False

    def test_no_stall_too_few_beats(self, tmp_path):
        path = tmp_path / ".swarm" / "heartbeat-new.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "branch": "new", "phase": "start", "iteration": 0,
            "last_action": "init", "status": "active",
            "timestamp": "2025-01-01T00:00:00+00:00",
        }) + "\n")
        assert check_heartbeat_stall(tmp_path, "new") is False


# ---------------------------------------------------------------------------
# Success Criteria
# ---------------------------------------------------------------------------

class TestSuccessCriteria:
    def test_save_and_load(self, tmp_path):
        criteria = [
            {"id": "SC1", "description": "L4 > L1 on F1", "met": False},
            {"id": "SC2", "description": "Pipeline compresses 10x", "met": True},
        ]
        save_success_criteria(tmp_path, criteria)
        loaded = load_success_criteria(tmp_path)
        assert len(loaded) == 2
        assert loaded[0]["id"] == "SC1"
        assert loaded[1]["met"] is True

    def test_load_missing(self, tmp_path):
        assert load_success_criteria(tmp_path) == []

    def test_load_corrupt(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "success-criteria.json").write_text("{bad")
        assert load_success_criteria(tmp_path) == []


# ---------------------------------------------------------------------------
# Convergence — DESIGN_INVALID blocking
# ---------------------------------------------------------------------------

class TestConvergenceDesignInvalid:
    def test_design_invalid_blocks_convergence(self, tmp_path, monkeypatch):
        (tmp_path / ".swarm").mkdir()
        monkeypatch.setattr(
            "voronoi.science._helpers._fetch_tasks",
            lambda ws: [
                {"id": "bd-1", "title": "Test H1", "status": "open",
                 "notes": "DESIGN_INVALID: L1 beats L4, encoding broken"},
            ],
        )
        result = check_convergence(tmp_path, "scientific", eval_score=0.80)
        assert result.converged is False
        assert any("DESIGN_INVALID" in b for b in result.blockers)

    def test_closed_design_invalid_does_not_block(self, tmp_path, monkeypatch):
        (tmp_path / ".swarm").mkdir()
        monkeypatch.setattr(
            "voronoi.science._helpers._fetch_tasks",
            lambda ws: [
                {"id": "bd-1", "title": "Test H1", "status": "closed",
                 "notes": "DESIGN_INVALID: was broken, now fixed"},
            ],
        )
        result = check_convergence(tmp_path, "scientific", eval_score=0.80)
        assert not any("DESIGN_INVALID" in b for b in result.blockers)


# ---------------------------------------------------------------------------
# Convergence — Success criteria blocking
# ---------------------------------------------------------------------------

class TestConvergenceSuccessCriteria:
    def test_unmet_criterion_blocks(self, tmp_path, monkeypatch):
        (tmp_path / ".swarm").mkdir()
        save_success_criteria(tmp_path, [
            {"id": "SC1", "description": "L4 > L1", "met": False},
        ])
        monkeypatch.setattr("voronoi.science._helpers._fetch_tasks", lambda ws: [])
        result = check_convergence(tmp_path, "scientific", eval_score=0.80)
        assert result.converged is False
        assert any("SC1" in b for b in result.blockers)

    def test_all_met_does_not_block(self, tmp_path, monkeypatch):
        (tmp_path / ".swarm").mkdir()
        save_success_criteria(tmp_path, [
            {"id": "SC1", "description": "L4 > L1", "met": True},
            {"id": "SC2", "description": "Pipeline 10x", "met": True},
        ])
        monkeypatch.setattr("voronoi.science._helpers._fetch_tasks", lambda ws: [])
        result = check_convergence(tmp_path, "scientific", eval_score=0.80)
        assert not any("Success criterion" in b for b in result.blockers)

    def test_no_criteria_file_does_not_block(self, tmp_path, monkeypatch):
        (tmp_path / ".swarm").mkdir()
        monkeypatch.setattr("voronoi.science._helpers._fetch_tasks", lambda ws: [])
        result = check_convergence(tmp_path, "scientific", eval_score=0.80)
        assert not any("Success criterion" in b for b in result.blockers)


# ---------------------------------------------------------------------------
# Convergence — Hypothesis alignment blocking
# ---------------------------------------------------------------------------

class TestConvergenceHypothesisAlignment:
    def test_contradicting_hypothesis_blocks(self, tmp_path, monkeypatch):
        (tmp_path / ".swarm").mkdir()
        monkeypatch.setattr(
            "voronoi.science._helpers._fetch_tasks",
            lambda ws: [
                {"id": "bd-5", "title": "Primary experiment", "status": "open",
                 "notes": "RESULT_CONTRADICTS_HYPOTHESIS:Expected L4>L1 but observed L1>L4"},
            ],
        )
        result = check_convergence(tmp_path, "scientific", eval_score=0.80)
        assert result.converged is False
        assert any("contradicts hypothesis" in b.lower() for b in result.blockers)

    def test_closed_contradiction_does_not_block(self, tmp_path, monkeypatch):
        (tmp_path / ".swarm").mkdir()
        monkeypatch.setattr(
            "voronoi.science._helpers._fetch_tasks",
            lambda ws: [
                {"id": "bd-5", "title": "Primary experiment", "status": "closed",
                 "notes": "RESULT_CONTRADICTS_HYPOTHESIS:Was broken, redesigned"},
            ],
        )
        result = check_convergence(tmp_path, "scientific", eval_score=0.80)
        assert not any("contradicts hypothesis" in b.lower() for b in result.blockers)


# ---------------------------------------------------------------------------
# Merge Gates — EVA enforcement
# ---------------------------------------------------------------------------

class TestMergeGateEVA:
    def test_investigation_without_eva_blocked(self, tmp_path):
        task = {
            "title": "FINDING: encoding helps",
            "notes": "TASK_TYPE:investigation\nSTAT_REVIEW: APPROVED",
        }
        ok, blockers = check_merge_gates(task, tmp_path, "adaptive")
        assert ok is False
        assert any("EVA" in b for b in blockers)

    def test_investigation_with_eva_pass(self, tmp_path):
        data_dir = tmp_path / "data" / "raw"
        data_dir.mkdir(parents=True)
        csv_file = data_dir / "r.csv"
        csv_file.write_text("s\n1\n2\n3\n")
        h = compute_data_hash(csv_file)
        exp_dir = tmp_path / "experiments"
        exp_dir.mkdir()
        (exp_dir / "run.py").write_text("#")
        task = {
            "title": "FINDING: encoding helps",
            "notes": (
                "TASK_TYPE:investigation\n"
                "STAT_REVIEW: APPROVED\n"
                "EVA: PASS | MANIPULATION_VARIED:yes\n"
                f"DATA_FILE:data/raw/r.csv\nDATA_HASH:{h}\nN:3\n"
            ),
        }
        ok, blockers = check_merge_gates(task, tmp_path, "adaptive")
        assert ok is True

    def test_investigation_with_eva_fail_blocked(self, tmp_path):
        task = {
            "title": "FINDING: encoding helps",
            "notes": "TASK_TYPE:investigation\nSTAT_REVIEW: APPROVED\nEVA: FAIL | CHECK:manipulation",
        }
        ok, blockers = check_merge_gates(task, tmp_path, "adaptive")
        assert ok is False
        assert any("EVA FAILED" in b for b in blockers)

    def test_non_investigation_no_eva_required(self, tmp_path):
        task = {"title": "Build encoder", "notes": "TASK_TYPE:build"}
        ok, blockers = check_merge_gates(task, tmp_path, "adaptive")
        assert ok is True


# ---------------------------------------------------------------------------
# Simulation / LLM-Bypass Detection
# ---------------------------------------------------------------------------

class TestSimulationBypassDetection:
    def test_clean_workspace_passes(self, tmp_path):
        """Workspace with no simulation markers should pass."""
        result = detect_simulation_bypass(tmp_path)
        assert result.passed is True
        assert len(result.critical_flags) == 0

    def test_simulated_model_in_results_json(self, tmp_path):
        """results.json with 'simulated' in model field should fail."""
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        (out_dir / "results.json").write_text(
            json.dumps({"model": "copilot-cli-simulated", "data": []})
        )
        result = detect_simulation_bypass(tmp_path)
        assert result.passed is False
        assert any(f.category == "simulated_model" for f in result.flags)

    def test_mock_model_in_results_json(self, tmp_path):
        """results.json with 'mock' in model field should fail."""
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        (out_dir / "results.json").write_text(
            json.dumps({"model": "mock-gpt-4"})
        )
        result = detect_simulation_bypass(tmp_path)
        assert result.passed is False
        assert any("mock" in f.message for f in result.critical_flags)

    def test_real_model_passes(self, tmp_path):
        """results.json with real model name should pass."""
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        (out_dir / "results.json").write_text(
            json.dumps({"model": "copilot-cli"})
        )
        result = detect_simulation_bypass(tmp_path)
        assert result.passed is True

    def test_simulation_file_detected(self, tmp_path):
        """Source files named *sim* with np.random patterns should be flagged."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "experiment_sim.py").write_text(
            "import numpy as np\n"
            "np.random.seed(42)\n"
            "# This avoids the infeasibility of running 1000+ copilot CLI calls\n"
        )
        result = detect_simulation_bypass(tmp_path)
        assert result.passed is False
        assert any(f.category == "simulation_bypass" for f in result.flags)
        assert "experiment_sim.py" in str(result.bypass_files)

    def test_legitimate_random_in_non_sim_file(self, tmp_path):
        """np.random.seed in a legitimately-named file should not trigger critical."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "data_generator.py").write_text(
            "import numpy as np\n"
            "np.random.seed(42)\n"
            "# Generate synthetic scenarios\n"
        )
        result = detect_simulation_bypass(tmp_path)
        # The file is not named *sim*/*mock*/*fake*, so no critical flag
        assert result.passed is True

    def test_alternative_runner_detected(self, tmp_path):
        """run_sim.py alongside run_experiments.py should be flagged as critical."""
        (tmp_path / "run_experiments.py").write_text("# real runner\n")
        (tmp_path / "run_sim.py").write_text("# simulation bypass\n")
        result = detect_simulation_bypass(tmp_path)
        assert any(f.category == "simulation_runner" for f in result.flags)
        assert any(f.severity == "critical" for f in result.flags)
        assert result.passed is False
        assert "run_sim.py" in str(result.bypass_files)

    def test_insufficient_cache_critical(self, tmp_path):
        """Too-few cache entries vs expected should fail."""
        cache_dir = tmp_path / ".llm_cache"
        cache_dir.mkdir()
        # Only 3 cache entries when 100 are expected
        for i in range(3):
            (cache_dir / f"hash_{i}.json").write_text("{}")
        result = detect_simulation_bypass(tmp_path, expected_min_llm_calls=100)
        assert result.passed is False
        assert result.cache_entries == 3
        assert any(f.category == "insufficient_cache" for f in result.flags)

    def test_sufficient_cache_passes(self, tmp_path):
        """Enough cache entries should pass."""
        cache_dir = tmp_path / ".llm_cache"
        cache_dir.mkdir()
        for i in range(120):
            (cache_dir / f"hash_{i}.json").write_text("{}")
        result = detect_simulation_bypass(tmp_path, expected_min_llm_calls=100)
        assert result.passed is True
        assert result.cache_entries == 120


# ---------------------------------------------------------------------------
# Orchestrator Checkpoint
# ---------------------------------------------------------------------------

class TestOrchestratorCheckpoint:
    def test_save_and_load(self, tmp_path):
        cp = OrchestratorCheckpoint(
            cycle=5,
            phase="investigating",
            mode="discover",
            rigor="experimental",
            hypotheses_summary="H1:confirmed, H2:testing",
            total_tasks=30,
            closed_tasks=12,
            active_workers=["agent-pilot", "agent-scenario-3"],
            recent_events=["Pilot passed", "Scenario 3 complete"],
            recent_decisions=["Moved to full experiment"],
            dead_ends=["L2 encoding redundant"],
            next_actions=["Wait for scenarios 4-6"],
            criteria_status={"SC1": False, "SC2": False},
            eval_score=0.0,
        )
        save_checkpoint(tmp_path, cp)
        assert (tmp_path / ".swarm" / "orchestrator-checkpoint.json").exists()

        loaded = load_checkpoint(tmp_path)
        assert loaded.cycle == 5
        assert loaded.phase == "investigating"
        assert loaded.hypotheses_summary == "H1:confirmed, H2:testing"
        assert loaded.total_tasks == 30
        assert loaded.closed_tasks == 12
        assert len(loaded.active_workers) == 2
        assert loaded.dead_ends == ["L2 encoding redundant"]
        assert loaded.criteria_status == {"SC1": False, "SC2": False}

    def test_load_missing_file(self, tmp_path):
        cp = load_checkpoint(tmp_path)
        assert cp.cycle == 0
        assert cp.phase == "starting"

    def test_load_corrupt_file(self, tmp_path):
        (tmp_path / ".swarm").mkdir(parents=True)
        (tmp_path / ".swarm" / "orchestrator-checkpoint.json").write_text("not json")
        cp = load_checkpoint(tmp_path)
        assert cp.cycle == 0

    def test_rolling_window_bounded(self, tmp_path):
        cp = OrchestratorCheckpoint(
            recent_events=[f"event-{i}" for i in range(20)],
            recent_decisions=[f"decision-{i}" for i in range(20)],
        )
        save_checkpoint(tmp_path, cp)
        loaded = load_checkpoint(tmp_path)
        assert len(loaded.recent_events) == 5
        assert len(loaded.recent_decisions) == 5

    def test_format_for_prompt(self):
        cp = OrchestratorCheckpoint(
            cycle=10, phase="reviewing", mode="discover", rigor="scientific",
            hypotheses_summary="H1:confirmed, H2:refuted",
            total_tasks=40, closed_tasks=30,
            active_workers=["agent-stats"],
            recent_events=["ANOVA complete"],
            next_actions=["Dispatch critic review"],
            dead_ends=["L2 gradient approach"],
            criteria_status={"SC1": True, "SC2": False},
            eval_score=0.68,
            improvement_rounds=1,
        )
        text = format_checkpoint_for_prompt(cp)
        assert "cycle 10" in text
        assert "reviewing" in text
        assert "30/40" in text
        assert "H1:confirmed" in text
        assert "SC1:met" in text
        assert "0.68" in text
        assert "ANOVA complete" in text
        assert "L2 gradient" in text
        assert "Dispatch critic" in text
