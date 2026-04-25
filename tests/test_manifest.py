"""Tests for the Run Manifest (``src/voronoi/science/manifest.py``).

The manifest is a DERIVED artifact assembled from existing ``.swarm/`` state
at completion time.  Tests cover:
  1. Schema roundtrip (save → load → equality on core fields).
  2. Rigor-tiered validation.
  3. ``build_manifest_from_workspace`` with realistic fixtures.
  4. Graceful behaviour on empty / malformed workspaces.
  5. Artifact discovery and SHA-256 hashing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from voronoi.science.manifest import (
    MANIFEST_FILENAME,
    SCHEMA_VERSION,
    ExperimentRecord,
    HypothesisOutcome,
    ManifestArtifact,
    PrimaryClaim,
    ProvenanceInfo,
    RunManifest,
    build_manifest_from_workspace,
    load_manifest,
    save_manifest,
    validate,
)


# ---------------------------------------------------------------------------
# Schema roundtrip
# ---------------------------------------------------------------------------

class TestSchemaRoundtrip:

    def test_save_creates_file_at_canonical_path(self, swarm_workspace):
        m = RunManifest(question="Q?", status="converged", converged=True)
        path = save_manifest(swarm_workspace, m)
        assert path.exists()
        assert path.name == MANIFEST_FILENAME
        assert path.parent.name == ".swarm"

    def test_save_sets_generated_at_timestamp(self, swarm_workspace):
        m = RunManifest(question="Q?")
        assert m.generated_at == ""
        save_manifest(swarm_workspace, m)
        assert m.generated_at != ""

    def test_load_returns_none_for_missing_file(self, tmp_path):
        assert load_manifest(tmp_path) is None

    def test_load_returns_none_for_malformed_json(self, swarm_workspace):
        (swarm_workspace / ".swarm" / MANIFEST_FILENAME).write_text("{not json")
        assert load_manifest(swarm_workspace) is None

    def test_roundtrip_preserves_core_fields(self, swarm_workspace):
        original = RunManifest(
            question="Why does X affect Y?",
            answer="X increases Y by 12% (d=0.4)",
            mode="discover",
            rigor="analytical",
            status="converged",
            converged=True,
            reason="All hypotheses resolved",
            primary_claims=[PrimaryClaim(
                id="C1", statement="X increases Y", effect_size="d=0.4",
                confidence_interval="[0.2, 0.6]", status="asserted",
                supporting_findings=["bd-5"],
            )],
            hypotheses=[HypothesisOutcome(
                id="H1", statement="X affects Y",
                observed_direction="confirmed", confidence="strong",
            )],
            experiments=[ExperimentRecord(
                id="bd-5", method="baseline vs treatment",
                effect_size="0.4", n="150", stat_test="t-test",
            )],
            caveats=["Single-site study"],
            provenance=ProvenanceInfo(
                investigation_id=42, lineage_id=42, cycle_number=2,
                mode="discover", rigor="analytical",
            ),
        )
        save_manifest(swarm_workspace, original)
        loaded = load_manifest(swarm_workspace)

        assert loaded is not None
        assert loaded.question == original.question
        assert loaded.answer == original.answer
        assert loaded.status == original.status
        assert loaded.converged is True
        assert len(loaded.primary_claims) == 1
        assert loaded.primary_claims[0].id == "C1"
        assert loaded.primary_claims[0].effect_size == "d=0.4"
        assert len(loaded.hypotheses) == 1
        assert loaded.hypotheses[0].observed_direction == "confirmed"
        assert len(loaded.experiments) == 1
        assert loaded.experiments[0].stat_test == "t-test"
        assert loaded.caveats == ["Single-site study"]
        assert loaded.provenance.investigation_id == 42
        assert loaded.provenance.lineage_id == 42
        assert loaded.provenance.cycle_number == 2

    def test_save_writes_valid_json(self, swarm_workspace):
        m = RunManifest(question="Q?", primary_claims=[
            PrimaryClaim(id="C1", statement="X"),
        ])
        save_manifest(swarm_workspace, m)
        data = json.loads(
            (swarm_workspace / ".swarm" / MANIFEST_FILENAME).read_text(),
        )
        assert data["schema_version"] == SCHEMA_VERSION
        assert data["question"] == "Q?"
        assert isinstance(data["primary_claims"], list)
        assert data["primary_claims"][0]["id"] == "C1"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:

    def test_empty_manifest_invalid_even_at_standard(self):
        m = RunManifest()
        r = validate(m, rigor="standard")
        assert not r.valid
        assert "question" in r.missing or any("question" in x for x in r.missing)

    def test_standard_tier_only_needs_question_and_status(self):
        m = RunManifest(question="Q?", status="converged")
        r = validate(m, rigor="standard")
        assert r.valid, f"expected valid, missing={r.missing}"

    def test_adaptive_tier_requires_answer_and_claims(self):
        m = RunManifest(question="Q?", status="converged")
        r = validate(m, rigor="adaptive")
        assert not r.valid
        assert any("answer" in x for x in r.missing)
        assert any("primary_claims" in x for x in r.missing)

    def test_adaptive_passes_with_answer_and_one_claim(self):
        m = RunManifest(
            question="Q?", status="converged", answer="Yes.",
            primary_claims=[PrimaryClaim(id="C1", statement="x")],
        )
        assert validate(m, rigor="adaptive").valid

    def test_analytical_tier_requires_experiments(self):
        m = RunManifest(
            question="Q?", status="converged", answer="Yes.",
            primary_claims=[PrimaryClaim(id="C1", statement="x")],
        )
        r = validate(m, rigor="analytical")
        assert not r.valid
        assert any("experiments" in x for x in r.missing)

    def test_scientific_tier_requires_hypotheses(self):
        m = RunManifest(
            question="Q?", status="converged", answer="Yes.",
            primary_claims=[PrimaryClaim(id="C1", statement="x")],
            experiments=[ExperimentRecord(id="bd-1", method="m")],
        )
        r = validate(m, rigor="scientific")
        assert not r.valid
        assert any("hypotheses" in x for x in r.missing)

    def test_unknown_rigor_treated_as_adaptive(self):
        m = RunManifest(question="Q?", status="converged")
        r_unknown = validate(m, rigor="bogus")
        r_adaptive = validate(m, rigor="adaptive")
        assert r_unknown.missing == r_adaptive.missing

    def test_experimental_warns_on_missing_ci(self):
        m = RunManifest(
            question="Q?", status="converged", answer="Yes.",
            primary_claims=[PrimaryClaim(id="C1", statement="x",
                                         effect_size="d=0.4")],
            experiments=[ExperimentRecord(id="bd-1", method="m")],
            hypotheses=[HypothesisOutcome(id="H1", statement="h")],
        )
        r = validate(m, rigor="experimental")
        assert any("missing effect_size or CI" in w for w in r.warnings)


# ---------------------------------------------------------------------------
# Factory: build_manifest_from_workspace
# ---------------------------------------------------------------------------

class TestBuildFromWorkspace:

    def test_empty_workspace_produces_minimal_manifest(self, swarm_workspace):
        m = build_manifest_from_workspace(swarm_workspace, question="Q?")
        assert m.question == "Q?"
        assert m.status == "unknown"
        assert not m.converged
        assert m.primary_claims == []
        assert m.hypotheses == []
        assert m.experiments == []

    def test_reads_convergence_json(self, swarm_workspace):
        (swarm_workspace / ".swarm" / "convergence.json").write_text(json.dumps({
            "converged": True,
            "status": "converged",
            "reason": "All hypotheses resolved",
            "score": 0.85,
        }))
        m = build_manifest_from_workspace(swarm_workspace, question="Q?")
        assert m.converged is True
        assert m.status == "converged"
        assert m.reason == "All hypotheses resolved"

    def test_reads_eval_score(self, swarm_workspace):
        (swarm_workspace / ".swarm" / "eval-score.json").write_text(json.dumps({
            "score": 0.82,
            "rounds": 2,
            "dimensions": {"completeness": {"score": 0.9, "note": "ok"}},
            "remediations": ["add more replicates"],
        }))
        m = build_manifest_from_workspace(swarm_workspace, question="Q?")
        assert m.evaluator.score == pytest.approx(0.82)
        assert m.evaluator.rounds == 2
        assert "completeness" in m.evaluator.dimensions
        assert m.evaluator.remediations == ["add more replicates"]

    def test_reads_belief_map_into_hypotheses(self, swarm_workspace):
        (swarm_workspace / ".swarm" / "belief-map.json").write_text(json.dumps({
            "cycle": 3,
            "hypotheses": [
                {
                    "id": "H1", "name": "X affects Y",
                    "prior": 0.5, "posterior": 0.9,
                    "status": "confirmed", "evidence": ["bd-3", "bd-5"],
                    "confidence": "strong",
                },
                {
                    "id": "H2", "name": "Z is a moderator",
                    "prior": 0.5, "posterior": 0.2,
                    "status": "refuted_reversed", "evidence": ["bd-7"],
                    "confidence": "supported",
                },
            ],
        }))
        m = build_manifest_from_workspace(swarm_workspace, question="Q?")
        assert len(m.hypotheses) == 2
        h1 = next(h for h in m.hypotheses if h.id == "H1")
        assert h1.observed_direction == "confirmed"
        assert h1.confidence == "strong"
        assert h1.supporting_findings == ["bd-3", "bd-5"]
        h2 = next(h for h in m.hypotheses if h.id == "H2")
        assert h2.observed_direction == "refuted_reversed"

    def test_fallback_claims_from_claim_evidence(self, swarm_workspace, monkeypatch):
        # No ledger provided — must fall back to claim-evidence.json.
        (swarm_workspace / ".swarm" / "claim-evidence.json").write_text(json.dumps([
            {
                "claim_id": "C1",
                "claim_text": "Treatment reduces Y by 12%",
                "finding_ids": ["bd-5"],
                "hypothesis_ids": ["H1"],
                "strength": "robust",
                "interpretation": "Large effect, narrow CI",
            },
        ]))
        # Stub findings to avoid beads dependency
        monkeypatch.setattr(
            "voronoi.science.manifest._safe_get_findings",
            lambda ws: [],
        )
        m = build_manifest_from_workspace(swarm_workspace, question="Q?")
        assert len(m.primary_claims) == 1
        c = m.primary_claims[0]
        assert c.id == "C1"
        assert c.statement == "Treatment reduces Y by 12%"
        assert c.supporting_findings == ["bd-5"]

    def test_claims_prefer_ledger_over_registry(self, swarm_workspace, monkeypatch):
        from voronoi.science.claims import (
            PROVENANCE_RUN_EVIDENCE,
            ClaimLedger,
        )
        # Registry has a claim the ledger does NOT mirror — ledger wins.
        (swarm_workspace / ".swarm" / "claim-evidence.json").write_text(json.dumps([
            {"claim_id": "CX", "claim_text": "Registry-only", "finding_ids": []},
        ]))
        ledger = ClaimLedger()
        ledger.add_claim(
            statement="Ledger claim",
            provenance=PROVENANCE_RUN_EVIDENCE,
            source_cycle=1,
            supporting_findings=["bd-1"],
        )
        monkeypatch.setattr(
            "voronoi.science.manifest._safe_get_findings",
            lambda ws: [],
        )

        class _Inv:
            id = 1
            lineage_id = 1
            cycle_number = 1
            parent_id = None
            codename = "Dopamine"
            mode = "discover"
            rigor = "analytical"
            question = "Q?"
            started_at = None
            completed_at = None

        m = build_manifest_from_workspace(
            swarm_workspace, ledger=ledger, investigation=_Inv(),
        )
        assert len(m.primary_claims) == 1
        assert m.primary_claims[0].statement == "Ledger claim"

    def test_findings_flow_into_experiments(self, swarm_workspace, monkeypatch):
        monkeypatch.setattr(
            "voronoi.science.manifest._safe_get_findings",
            lambda ws: [
                {
                    "id": "bd-5", "title": "FINDING: baseline vs treatment",
                    "notes": "",
                    "effect_size": "0.4", "ci_95": "[0.2, 0.6]",
                    "p": "0.031", "n": "150", "stat_test": "t-test",
                    "valence": "positive",
                },
            ],
        )
        m = build_manifest_from_workspace(swarm_workspace, question="Q?")
        assert len(m.experiments) == 1
        e = m.experiments[0]
        assert e.id == "bd-5"
        assert "baseline" in e.method.lower()
        assert e.effect_size == "0.4"
        assert e.stat_test == "t-test"
        assert e.valence == "positive"

    def test_caveats_include_non_convergence(self, swarm_workspace):
        (swarm_workspace / ".swarm" / "convergence.json").write_text(json.dumps({
            "converged": False,
            "status": "exhausted",
            "reason": "Time budget exceeded",
            "blockers": ["missing_replication"],
        }))
        m = build_manifest_from_workspace(swarm_workspace, question="Q?")
        assert m.converged is False
        assert any("exhausted" in c for c in m.caveats)
        assert any("missing_replication" in c for c in m.caveats)

    def test_answer_picks_highest_priority_claim_status(
        self, swarm_workspace, monkeypatch,
    ):
        from voronoi.science.claims import (
            PROVENANCE_RUN_EVIDENCE,
            ClaimLedger,
        )
        ledger = ClaimLedger()
        ledger.add_claim(
            statement="Provisional claim",
            provenance=PROVENANCE_RUN_EVIDENCE,
            source_cycle=1,
        )
        c2 = ledger.add_claim(
            statement="Asserted claim",
            provenance=PROVENANCE_RUN_EVIDENCE,
            source_cycle=1,
        )
        ledger.assert_claim(c2.id)
        monkeypatch.setattr(
            "voronoi.science.manifest._safe_get_findings", lambda ws: [],
        )

        class _Inv:
            id = 1
            lineage_id = 1
            cycle_number = 1
            parent_id = None
            codename = ""
            mode = "discover"
            rigor = "analytical"
            question = "Q?"
            started_at = None
            completed_at = None

        m = build_manifest_from_workspace(
            swarm_workspace, ledger=ledger, investigation=_Inv(),
        )
        assert m.answer == "Asserted claim"


# ---------------------------------------------------------------------------
# Artifact discovery
# ---------------------------------------------------------------------------

class TestArtifactDiscovery:

    def test_discovers_known_artifacts(self, swarm_workspace, monkeypatch):
        # Create some canonical artifacts
        (swarm_workspace / ".swarm" / "deliverable.md").write_text("# Deliverable")
        (swarm_workspace / ".swarm" / "paper.tex").write_text(r"\documentclass{article}")
        (swarm_workspace / "submission.csv").write_text("id,label\n1,0\n")
        figures = swarm_workspace / "output" / "figures"
        figures.mkdir(parents=True)
        (figures / "fig1.png").write_bytes(b"\x89PNG\r\n\x1a\n")

        monkeypatch.setattr(
            "voronoi.science.manifest._safe_get_findings", lambda ws: [],
        )
        m = build_manifest_from_workspace(swarm_workspace, question="Q?")
        paths = {a.path for a in m.artifacts}
        assert ".swarm/deliverable.md" in paths
        assert ".swarm/paper.tex" in paths
        assert "submission.csv" in paths
        assert any(p.endswith("fig1.png") for p in paths)

    def test_artifacts_include_sha256_and_size(self, swarm_workspace, monkeypatch):
        (swarm_workspace / "submission.csv").write_text("id,label\n1,0\n")
        monkeypatch.setattr(
            "voronoi.science.manifest._safe_get_findings", lambda ws: [],
        )
        m = build_manifest_from_workspace(swarm_workspace, question="Q?")
        sub = next(a for a in m.artifacts if a.path == "submission.csv")
        assert sub.kind == "submission"
        assert sub.sha256 is not None
        assert len(sub.sha256) == 64  # sha256 hex digest length
        assert sub.bytes is not None
        assert sub.bytes > 0


# ---------------------------------------------------------------------------
# Integration: end-to-end smoke test
# ---------------------------------------------------------------------------

class TestEndToEnd:

    def test_realistic_workspace_produces_valid_analytical_manifest(
        self, swarm_workspace, monkeypatch,
    ):
        # Populate a realistic `.swarm/` state
        (swarm_workspace / ".swarm" / "convergence.json").write_text(json.dumps({
            "converged": True, "status": "converged",
            "reason": "All hypotheses resolved", "score": 0.84,
        }))
        (swarm_workspace / ".swarm" / "eval-score.json").write_text(json.dumps({
            "score": 0.84, "rounds": 1,
            "dimensions": {
                "completeness": {"score": 0.85, "note": "all parts answered"},
                "coherence":    {"score": 0.90, "note": "unified answer"},
                "strength":     {"score": 0.78, "note": "robust CI"},
                "actionability": {"score": 0.82, "note": "actionable next steps"},
                "non_triviality": {"score": 0.80, "note": "novel"},
            },
            "remediations": [],
        }))
        (swarm_workspace / ".swarm" / "belief-map.json").write_text(json.dumps({
            "cycle": 1,
            "hypotheses": [{
                "id": "H1", "name": "Encoding enables discovery",
                "prior": 0.5, "posterior": 0.82,
                "status": "confirmed", "evidence": ["bd-5"],
                "confidence": "strong",
            }],
        }))
        (swarm_workspace / ".swarm" / "claim-evidence.json").write_text(json.dumps([{
            "claim_id": "C1",
            "claim_text": "Encoding enables discovery of cross-lever effects",
            "finding_ids": ["bd-5"],
            "hypothesis_ids": ["H1"],
            "strength": "robust",
            "interpretation": "d=1.47, narrow CI",
        }]))

        monkeypatch.setattr(
            "voronoi.science.manifest._safe_get_findings",
            lambda ws: [{
                "id": "bd-5", "title": "FINDING: encoding experiment",
                "notes": "",
                "effect_size": "1.47", "ci_95": "[1.10, 1.84]",
                "p": "0.001", "n": "120", "stat_test": "t-test",
                "valence": "positive", "stat_review": "APPROVED",
                "robust": "yes",
            }],
        )

        m = build_manifest_from_workspace(
            swarm_workspace, question="Can encoding enable discovery?",
            rigor="analytical",
        )
        assert m.converged is True
        assert m.evaluator.score == pytest.approx(0.84)
        assert len(m.hypotheses) == 1
        assert len(m.primary_claims) == 1
        assert len(m.experiments) == 1
        assert m.answer  # should have picked something
        # Should validate at analytical rigor
        r = validate(m, rigor="analytical")
        # Allow warnings but no hard-missing fields
        assert r.valid, f"unexpectedly invalid: missing={r.missing}"

    def test_save_then_load_full_manifest(self, swarm_workspace, monkeypatch):
        monkeypatch.setattr(
            "voronoi.science.manifest._safe_get_findings", lambda ws: [],
        )
        m = build_manifest_from_workspace(
            swarm_workspace, question="Q?", rigor="standard",
        )
        m.answer = "Placeholder answer"
        save_manifest(swarm_workspace, m)
        loaded = load_manifest(swarm_workspace)
        assert loaded is not None
        assert loaded.question == "Q?"
        assert loaded.answer == "Placeholder answer"
        assert loaded.schema_version == SCHEMA_VERSION
