"""Tests for the Claim Ledger — cross-run scientific state."""

from __future__ import annotations

import json

import pytest

from voronoi.science.claims import (
    PROVENANCE_MODEL_PRIOR,
    PROVENANCE_RETRIEVED_PRIOR,
    PROVENANCE_RUN_EVIDENCE,
    STATUS_ASSERTED,
    STATUS_CHALLENGED,
    STATUS_LOCKED,
    STATUS_PROVISIONAL,
    STATUS_REPLICATED,
    STATUS_RETIRED,
    Claim,
    ClaimArtifact,
    ClaimLedger,
    Objection,
    diff_ledger_states,
    generate_self_critique,
    iter_all_ledgers,
    ledger_state_map,
    load_ledger,
    resolve_lineage_id,
    save_ledger,
)


# ---------------------------------------------------------------------------
# ClaimArtifact
# ---------------------------------------------------------------------------

class TestClaimArtifact:
    def test_valid_artifact(self):
        a = ClaimArtifact(path="data/raw/x.csv", artifact_type="data")
        assert a.path == "data/raw/x.csv"
        assert a.artifact_type == "data"

    def test_invalid_artifact_type(self):
        with pytest.raises(ValueError, match="Invalid artifact_type"):
            ClaimArtifact(path="x.py", artifact_type="banana")


# ---------------------------------------------------------------------------
# Objection
# ---------------------------------------------------------------------------

class TestObjection:
    def test_valid(self):
        o = Objection(id="O1", target_claim="C1", concern="N too small")
        assert o.status == "pending"
        assert o.raised_by == "PI"

    def test_invalid_type(self):
        with pytest.raises(ValueError, match="Invalid objection_type"):
            Objection(id="O1", target_claim="C1", concern="x",
                      objection_type="nonsense")

    def test_invalid_status(self):
        with pytest.raises(ValueError, match="Invalid objection status"):
            Objection(id="O1", target_claim="C1", concern="x", status="fake")


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

class TestClaim:
    def test_valid(self):
        c = Claim(id="C1", statement="L4 > L1", provenance=PROVENANCE_RUN_EVIDENCE)
        assert c.status == STATUS_PROVISIONAL
        assert c.provenance == PROVENANCE_RUN_EVIDENCE

    def test_invalid_provenance(self):
        with pytest.raises(ValueError, match="Invalid provenance"):
            Claim(id="C1", statement="x", provenance="magic")

    def test_invalid_status(self):
        with pytest.raises(ValueError, match="Invalid status"):
            Claim(id="C1", statement="x", provenance=PROVENANCE_RUN_EVIDENCE,
                  status="fake")


# ---------------------------------------------------------------------------
# ClaimLedger — CRUD
# ---------------------------------------------------------------------------

class TestClaimLedger:
    def test_add_claim(self):
        ledger = ClaimLedger()
        c = ledger.add_claim("L4 outperforms L1", PROVENANCE_RUN_EVIDENCE)
        assert c.id == "C1"
        assert c.status == STATUS_PROVISIONAL
        assert len(ledger.claims) == 1

    def test_add_multiple_claims(self):
        ledger = ClaimLedger()
        c1 = ledger.add_claim("A", PROVENANCE_RUN_EVIDENCE)
        c2 = ledger.add_claim("B", PROVENANCE_MODEL_PRIOR)
        assert c1.id == "C1"
        assert c2.id == "C2"
        assert len(ledger.claims) == 2

    def test_get_claim(self):
        ledger = ClaimLedger()
        ledger.add_claim("x", PROVENANCE_RUN_EVIDENCE)
        assert ledger.get_claim("C1") is not None
        assert ledger.get_claim("C99") is None

    def test_lock_claim(self):
        ledger = ClaimLedger()
        ledger.add_claim("x", PROVENANCE_RUN_EVIDENCE)
        # Must go through asserted first
        ledger.assert_claim("C1")
        c = ledger.lock_claim("C1")
        assert c.status == STATUS_LOCKED

    def test_lock_from_provisional_fails(self):
        ledger = ClaimLedger()
        ledger.add_claim("x", PROVENANCE_RUN_EVIDENCE)
        with pytest.raises(ValueError, match="Cannot transition"):
            ledger.lock_claim("C1")

    def test_challenge_claim(self):
        ledger = ClaimLedger()
        ledger.add_claim("x", PROVENANCE_RUN_EVIDENCE)
        c, obj = ledger.challenge_claim("C1", "N too small", "power")
        assert c.status == STATUS_CHALLENGED
        assert obj.target_claim == "C1"
        assert obj.concern == "N too small"
        assert len(ledger.objections) == 1
        assert len(c.challenges) == 1

    def test_retire_claim(self):
        ledger = ClaimLedger()
        ledger.add_claim("x", PROVENANCE_RUN_EVIDENCE)
        c = ledger.retire_claim("C1")
        assert c.status == STATUS_RETIRED

    def test_replicate_locked_claim(self):
        ledger = ClaimLedger()
        ledger.add_claim("x", PROVENANCE_RUN_EVIDENCE)
        ledger.assert_claim("C1")
        ledger.lock_claim("C1")
        c = ledger.replicate_claim("C1")
        assert c.status == STATUS_REPLICATED

    def test_invalid_transition_retired(self):
        ledger = ClaimLedger()
        ledger.add_claim("x", PROVENANCE_RUN_EVIDENCE)
        ledger.retire_claim("C1")
        with pytest.raises(ValueError, match="Cannot transition"):
            ledger.assert_claim("C1")

    def test_get_claim_not_found_raises(self):
        ledger = ClaimLedger()
        with pytest.raises(KeyError, match="C99"):
            ledger.lock_claim("C99")


# ---------------------------------------------------------------------------
# ClaimLedger — Objections
# ---------------------------------------------------------------------------

class TestLedgerObjections:
    def test_add_objection(self):
        ledger = ClaimLedger()
        ledger.add_claim("x", PROVENANCE_RUN_EVIDENCE)
        obj = ledger.add_objection("C1", "confound!", "confound")
        assert obj.id == "O1"
        assert obj.status == "pending"

    def test_resolve_objection(self):
        ledger = ClaimLedger()
        ledger.add_claim("x", PROVENANCE_RUN_EVIDENCE)
        ledger.add_objection("C1", "confound!", "confound")
        obj = ledger.resolve_objection("O1", "Controlled for it", resolution_cycle=2)
        assert obj.status == "resolved"
        assert obj.resolution == "Controlled for it"
        assert obj.resolution_cycle == 2

    def test_dismiss_objection(self):
        ledger = ClaimLedger()
        ledger.add_objection("C1", "not relevant")
        obj = ledger.dismiss_objection("O1", "Out of scope")
        assert obj.status == "dismissed"

    def test_resolve_nonexistent(self):
        ledger = ClaimLedger()
        with pytest.raises(KeyError, match="O99"):
            ledger.resolve_objection("O99", "x")

    def test_dismiss_nonexistent(self):
        ledger = ClaimLedger()
        with pytest.raises(KeyError, match="O99"):
            ledger.dismiss_objection("O99", "x")


# ---------------------------------------------------------------------------
# ClaimLedger — Queries
# ---------------------------------------------------------------------------

class TestLedgerQueries:
    def _build_ledger(self) -> ClaimLedger:
        ledger = ClaimLedger()
        # C1: locked
        ledger.add_claim("A", PROVENANCE_RUN_EVIDENCE,
                         artifacts=[ClaimArtifact("data/a.csv", "data")])
        ledger.assert_claim("C1")
        ledger.lock_claim("C1")
        # C2: challenged
        ledger.add_claim("B", PROVENANCE_RUN_EVIDENCE)
        ledger.challenge_claim("C2", "N too small", "power")
        # C3: model prior
        ledger.add_claim("C", PROVENANCE_MODEL_PRIOR)
        # C4: retired
        ledger.add_claim("D", PROVENANCE_RUN_EVIDENCE)
        ledger.retire_claim("C4")
        return ledger

    def test_get_locked(self):
        ledger = self._build_ledger()
        locked = ledger.get_locked()
        assert len(locked) == 1
        assert locked[0].id == "C1"

    def test_get_challenged(self):
        ledger = self._build_ledger()
        challenged = ledger.get_challenged()
        assert len(challenged) == 1
        assert challenged[0].id == "C2"

    def test_get_pending_objections(self):
        ledger = self._build_ledger()
        pending = ledger.get_pending_objections()
        assert len(pending) == 1
        assert pending[0].target_claim == "C2"

    def test_get_by_provenance(self):
        ledger = self._build_ledger()
        priors = ledger.get_by_provenance(PROVENANCE_MODEL_PRIOR)
        assert len(priors) == 1
        assert priors[0].id == "C3"

    def test_get_immutable_paths(self):
        ledger = self._build_ledger()
        paths = ledger.get_immutable_paths()
        assert "data/a.csv" in paths

    def test_summary(self):
        ledger = self._build_ledger()
        s = ledger.summary()
        assert "Claims:" in s
        assert "4 total" in s

    def test_empty_summary(self):
        ledger = ClaimLedger()
        assert ledger.summary() == "No claims yet."


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

class TestLedgerFormatting:
    def test_format_for_prompt(self):
        ledger = ClaimLedger()
        ledger.add_claim("L4 > L1", PROVENANCE_RUN_EVIDENCE,
                         effect_summary="d=0.8")
        ledger.assert_claim("C1")
        ledger.lock_claim("C1")
        ledger.add_claim("No effect for conv", PROVENANCE_RUN_EVIDENCE)
        ledger.challenge_claim("C2", "N too small", "power")
        text = ledger.format_for_prompt()
        assert "Established" in text
        assert "do NOT re-test" in text
        assert "Under Challenge" in text
        assert "MUST address" in text
        assert "C1" in text
        assert "C2" in text

    def test_format_empty(self):
        ledger = ClaimLedger()
        assert ledger.format_for_prompt() == ""

    def test_format_for_review(self):
        ledger = ClaimLedger()
        ledger.add_claim("x", PROVENANCE_RUN_EVIDENCE)
        text = ledger.format_for_review()
        assert "C1" in text

    def test_format_review_empty(self):
        ledger = ClaimLedger()
        assert "No claims" in ledger.format_for_review()


# ---------------------------------------------------------------------------
# Self-critique
# ---------------------------------------------------------------------------

class TestSelfCritique:
    def test_single_finding_warning(self):
        ledger = ClaimLedger()
        ledger.add_claim("x", PROVENANCE_RUN_EVIDENCE,
                         supporting_findings=["bd-17"])
        critiques = generate_self_critique(ledger)
        types = [o.concern for o in critiques]
        assert any("single experiment" in c for c in types)

    def test_model_prior_warning(self):
        ledger = ClaimLedger()
        ledger.add_claim("x", PROVENANCE_MODEL_PRIOR)
        critiques = generate_self_critique(ledger)
        assert any("model training data" in o.concern for o in critiques)

    def test_low_sample_warning(self):
        ledger = ClaimLedger()
        ledger.add_claim("x", PROVENANCE_RUN_EVIDENCE,
                         sample_summary="N=50 across 2 experiments")
        critiques = generate_self_critique(ledger)
        assert any("underpowered" in o.concern for o in critiques)

    def test_no_critique_for_retired(self):
        ledger = ClaimLedger()
        ledger.add_claim("x", PROVENANCE_MODEL_PRIOR)
        ledger.retire_claim("C1")
        critiques = generate_self_critique(ledger)
        assert len(critiques) == 0

    def test_no_critique_if_already_challenged(self):
        ledger = ClaimLedger()
        ledger.add_claim("x", PROVENANCE_RUN_EVIDENCE,
                         supporting_findings=["bd-1"])
        ledger.challenge_claim("C1", "already doubted")
        critiques = generate_self_critique(ledger)
        assert len(critiques) == 0

    def test_self_critique_raised_by(self):
        ledger = ClaimLedger()
        ledger.add_claim("x", PROVENANCE_MODEL_PRIOR)
        critiques = generate_self_critique(ledger)
        assert all(o.raised_by == "self_critique" for o in critiques)
        assert all(o.status == "surfaced" for o in critiques)


# ---------------------------------------------------------------------------
# Persistence (save / load roundtrip)
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_save_load_roundtrip(self, tmp_path):
        ledger = ClaimLedger()
        ledger.add_claim("L4 > L1", PROVENANCE_RUN_EVIDENCE,
                         supporting_findings=["bd-17"],
                         effect_summary="d=0.8",
                         artifacts=[ClaimArtifact("data/x.csv", "data", sha256="abc")])
        ledger.assert_claim("C1")
        ledger.lock_claim("C1")
        ledger.add_claim("No effect", PROVENANCE_RUN_EVIDENCE)
        ledger.challenge_claim("C2", "N too small", "power")

        save_ledger(1, ledger, base_dir=tmp_path)
        loaded = load_ledger(1, base_dir=tmp_path)

        assert len(loaded.claims) == 2
        assert loaded.claims[0].id == "C1"
        assert loaded.claims[0].status == STATUS_LOCKED
        assert len(loaded.claims[0].artifacts) == 1
        assert loaded.claims[0].artifacts[0].sha256 == "abc"
        assert loaded.claims[1].status == STATUS_CHALLENGED
        assert len(loaded.objections) == 1
        assert loaded.objections[0].concern == "N too small"

    def test_load_nonexistent(self, tmp_path):
        ledger = load_ledger(999, base_dir=tmp_path)
        assert len(ledger.claims) == 0

    def test_load_corrupt_json(self, tmp_path):
        path = tmp_path / "ledgers" / "1" / "claim-ledger.json"
        path.parent.mkdir(parents=True)
        path.write_text("{invalid json")
        ledger = load_ledger(1, base_dir=tmp_path)
        assert len(ledger.claims) == 0

    def test_save_creates_directory(self, tmp_path):
        ledger = ClaimLedger()
        ledger.add_claim("x", PROVENANCE_RUN_EVIDENCE)
        path = save_ledger(42, ledger, base_dir=tmp_path)
        assert path.exists()
        assert "42" in str(path)

    def test_id_counters_preserved(self, tmp_path):
        ledger = ClaimLedger()
        ledger.add_claim("A", PROVENANCE_RUN_EVIDENCE)
        ledger.add_claim("B", PROVENANCE_RUN_EVIDENCE)
        ledger.add_objection("C1", "doubt")
        save_ledger(1, ledger, base_dir=tmp_path)
        loaded = load_ledger(1, base_dir=tmp_path)
        # Next claim should be C3
        c = loaded.add_claim("C", PROVENANCE_RUN_EVIDENCE)
        assert c.id == "C3"
        # Next objection should be O2
        o = loaded.add_objection("C3", "q")
        assert o.id == "O2"


# ---------------------------------------------------------------------------
# Lineage resolution
# ---------------------------------------------------------------------------

class TestLineageResolution:
    def test_root_investigation(self):
        class FakeInv:
            def __init__(self, id, parent_id=None):
                self.id = id
                self.parent_id = parent_id

        store = {1: FakeInv(1)}
        assert resolve_lineage_id(1, store.get) == 1

    def test_chain(self):
        class FakeInv:
            def __init__(self, id, parent_id=None):
                self.id = id
                self.parent_id = parent_id

        store = {
            1: FakeInv(1),
            2: FakeInv(2, parent_id=1),
            3: FakeInv(3, parent_id=2),
        }
        assert resolve_lineage_id(3, store.get) == 1
        assert resolve_lineage_id(2, store.get) == 1
        assert resolve_lineage_id(1, store.get) == 1

    def test_missing_parent(self):
        class FakeInv:
            def __init__(self, id, parent_id=None):
                self.id = id
                self.parent_id = parent_id

        store = {3: FakeInv(3, parent_id=99)}
        # parent 99 not found → stop at 99
        assert resolve_lineage_id(3, store.get) == 99


# ---------------------------------------------------------------------------
# Forward-compatibility: extra keys in serialized data
# ---------------------------------------------------------------------------

class TestForwardCompatibility:
    def test_load_ledger_with_extra_claim_keys(self, tmp_path):
        """A ledger saved by a newer version may have extra fields on claims."""
        data = {
            "claims": [{
                "id": "C1",
                "statement": "test",
                "provenance": "run_evidence",
                "status": "provisional",
                "supporting_findings": [],
                "source_cycle": 1,
                "artifacts": [],
                "challenges": [],
                "first_asserted": "2025-01-01T00:00:00+00:00",
                "last_updated": "2025-01-01T00:00:00+00:00",
                "future_field": "from_newer_version",
            }],
            "objections": [],
            "_next_claim_id": 2,
            "_next_objection_id": 1,
        }
        path = tmp_path / "ledgers" / "1" / "claim-ledger.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(data))
        ledger = load_ledger(1, base_dir=tmp_path)
        assert len(ledger.claims) == 1
        assert ledger.claims[0].id == "C1"

    def test_load_ledger_with_extra_objection_keys(self, tmp_path):
        """Extra fields on objections are silently dropped."""
        data = {
            "claims": [],
            "objections": [{
                "id": "O1",
                "target_claim": "C1",
                "concern": "N too small",
                "objection_type": "power",
                "raised_by": "PI",
                "status": "pending",
                "timestamp": "2025-01-01T00:00:00+00:00",
                "new_field": 42,
            }],
            "_next_claim_id": 1,
            "_next_objection_id": 2,
        }
        path = tmp_path / "ledgers" / "1" / "claim-ledger.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(data))
        ledger = load_ledger(1, base_dir=tmp_path)
        assert len(ledger.objections) == 1
        assert ledger.objections[0].id == "O1"

    def test_load_ledger_with_extra_artifact_keys(self, tmp_path):
        """Extra fields on artifacts are silently dropped."""
        data = {
            "claims": [{
                "id": "C1",
                "statement": "test",
                "provenance": "run_evidence",
                "status": "provisional",
                "supporting_findings": [],
                "source_cycle": 1,
                "artifacts": [{"path": "x.csv", "artifact_type": "data",
                               "future_tag": "v2"}],
                "challenges": [],
                "first_asserted": "2025-01-01T00:00:00+00:00",
                "last_updated": "2025-01-01T00:00:00+00:00",
            }],
            "objections": [],
            "_next_claim_id": 2,
            "_next_objection_id": 1,
        }
        path = tmp_path / "ledgers" / "1" / "claim-ledger.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(data))
        ledger = load_ledger(1, base_dir=tmp_path)
        assert len(ledger.claims[0].artifacts) == 1
        assert ledger.claims[0].artifacts[0].path == "x.csv"


# ---------------------------------------------------------------------------
# Cross-lineage iteration (F1 — dead-ends query plumbing)
# ---------------------------------------------------------------------------

class TestIterAllLedgers:
    def test_empty_base_dir(self, tmp_path):
        assert list(iter_all_ledgers(base_dir=tmp_path)) == []

    def test_skips_non_numeric_dirs(self, tmp_path):
        (tmp_path / "ledgers" / "not-a-number").mkdir(parents=True)
        assert list(iter_all_ledgers(base_dir=tmp_path)) == []

    def test_yields_populated_ledgers_only(self, tmp_path):
        # Lineage 1 has a claim, lineage 2 is empty (no file written)
        ledger1 = ClaimLedger()
        ledger1.add_claim("A holds", PROVENANCE_RUN_EVIDENCE)
        save_ledger(1, ledger1, base_dir=tmp_path)
        # Lineage 2: empty ledger saved to disk should be skipped
        save_ledger(2, ClaimLedger(), base_dir=tmp_path)

        results = list(iter_all_ledgers(base_dir=tmp_path))
        assert len(results) == 1
        assert results[0][0] == 1
        assert results[0][1].claims[0].statement == "A holds"


class TestGetRetired:
    def test_returns_only_retired(self):
        ledger = ClaimLedger()
        ledger.add_claim("keep", PROVENANCE_RUN_EVIDENCE)
        ledger.add_claim("drop", PROVENANCE_RUN_EVIDENCE)
        ledger.retire_claim("C2")
        retired = ledger.get_retired()
        assert len(retired) == 1
        assert retired[0].id == "C2"


# ---------------------------------------------------------------------------
# Claim-delta helpers (F5 — progress digest plumbing)
# ---------------------------------------------------------------------------

class TestLedgerDiff:
    def test_new_claim_delta(self):
        old: dict[str, str] = {}
        ledger = ClaimLedger()
        ledger.add_claim("X", PROVENANCE_RUN_EVIDENCE)
        new = ledger_state_map(ledger)
        deltas = diff_ledger_states(old, new, ledger=ledger)
        assert len(deltas) == 1
        assert deltas[0]["kind"] == "new"
        assert deltas[0]["claim_id"] == "C1"
        assert deltas[0]["to_status"] == STATUS_PROVISIONAL
        assert deltas[0]["from_status"] is None
        assert deltas[0]["statement"] == "X"

    def test_transition_delta(self):
        ledger = ClaimLedger()
        ledger.add_claim("Y", PROVENANCE_RUN_EVIDENCE)
        old = ledger_state_map(ledger)
        ledger.assert_claim("C1")
        ledger.lock_claim("C1")
        new = ledger_state_map(ledger)
        deltas = diff_ledger_states(old, new, ledger=ledger)
        assert len(deltas) == 1
        assert deltas[0]["kind"] == "transition"
        assert deltas[0]["from_status"] == STATUS_PROVISIONAL
        assert deltas[0]["to_status"] == STATUS_LOCKED

    def test_no_delta_when_identical(self):
        ledger = ClaimLedger()
        ledger.add_claim("same", PROVENANCE_RUN_EVIDENCE)
        snap = ledger_state_map(ledger)
        assert diff_ledger_states(snap, snap, ledger=ledger) == []

    def test_preview_truncates_long_statements(self):
        ledger = ClaimLedger()
        ledger.add_claim("Z" * 200, PROVENANCE_RUN_EVIDENCE)
        deltas = diff_ledger_states({}, ledger_state_map(ledger), ledger=ledger)
        assert len(deltas[0]["statement"]) <= 80
        assert deltas[0]["statement"].endswith("…")
