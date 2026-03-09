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
