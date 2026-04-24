"""Tests for voronoi.science.lab_kg — per-PI institutional memory."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from voronoi.science.claims import (
    ClaimArtifact,
    ClaimLedger,
    PROVENANCE_MODEL_PRIOR,
    PROVENANCE_RUN_EVIDENCE,
)
from voronoi.science.lab_kg import (
    DEFAULT_HALF_LIFE_DAYS,
    DURABLE_STATUSES,
    DeadEnd,
    LabEntry,
    LabKG,
)


def _path(tmp_path: Path) -> Path:
    return tmp_path / "kg.json"


def _ledger_with_locked_claim(statement: str = "L4 compiled beats L1 raw at K4-depth") -> ClaimLedger:
    ledger = ClaimLedger()
    claim = ledger.add_claim(
        statement=statement,
        provenance=PROVENANCE_RUN_EVIDENCE,
        supporting_findings=["bd-finding-42"],
        effect_summary="accuracy gap +14.2pp (95% CI [11.0, 17.5])",
        artifacts=[ClaimArtifact(path="output/k4_depth.csv", artifact_type="data", sha256="abc")],
    )
    ledger.assert_claim(claim.id)
    ledger.lock_claim(claim.id)
    return ledger


class TestLoadSaveRoundTrip:
    def test_fresh_kg_is_empty(self, tmp_path):
        kg = LabKG.load(_path(tmp_path))
        assert kg.entries == []
        assert kg.dead_ends == []

    def test_save_then_load_preserves_entries(self, tmp_path):
        kg = LabKG(_path(tmp_path))
        kg.upsert_from_ledger("lineage-alpha", _ledger_with_locked_claim())
        kg.save()

        reloaded = LabKG.load(_path(tmp_path))
        assert len(reloaded.entries) == 1
        assert reloaded.entries[0].source_lineage == "lineage-alpha"
        assert reloaded.entries[0].status == "locked"

    def test_save_is_atomic_via_temp_file(self, tmp_path):
        kg = LabKG(_path(tmp_path))
        kg.upsert_from_ledger("lineage-beta", _ledger_with_locked_claim())
        kg.save()
        assert _path(tmp_path).exists()
        # No leftover temp file
        assert not _path(tmp_path).with_suffix(".json.tmp").exists()


class TestUpsertFromLedger:
    def test_first_upsert_creates_entry(self, tmp_path):
        kg = LabKG(_path(tmp_path))
        touched = kg.upsert_from_ledger("lineage-1", _ledger_with_locked_claim())
        assert len(touched) == 1
        assert len(kg.entries) == 1
        assert kg.entries[0].supporting_lineages == ["lineage-1"]

    def test_same_claim_different_lineage_triggers_replication(self, tmp_path):
        kg = LabKG(_path(tmp_path))
        kg.upsert_from_ledger("lineage-1", _ledger_with_locked_claim())
        # Second lineage confirms the same locked claim
        kg.upsert_from_ledger("lineage-2", _ledger_with_locked_claim())
        assert len(kg.entries) == 1
        entry = kg.entries[0]
        assert entry.status == "replicated"
        assert "lineage-2" in entry.replicated_in

    def test_provisional_claim_without_support_is_skipped(self, tmp_path):
        kg = LabKG(_path(tmp_path))
        ledger = ClaimLedger()
        ledger.add_claim(
            statement="Hunch: X > Y", provenance=PROVENANCE_MODEL_PRIOR
        )
        kg.upsert_from_ledger("lineage-x", ledger)
        assert kg.entries == []

    def test_challenge_in_another_lineage_records_dissent(self, tmp_path):
        kg = LabKG(_path(tmp_path))
        kg.upsert_from_ledger("lineage-1", _ledger_with_locked_claim())
        # Same statement, now challenged elsewhere
        ledger2 = ClaimLedger()
        c = ledger2.add_claim(
            statement="L4 compiled beats L1 raw at K4-depth",
            provenance=PROVENANCE_RUN_EVIDENCE,
            supporting_findings=["bd-finding-99"],
        )
        ledger2.assert_claim(c.id)
        ledger2.challenge_claim(c.id, concern="Our dataset disagrees at K4-width")
        kg.upsert_from_ledger("lineage-2", ledger2)
        assert "lineage-2" in kg.entries[0].dissent

    def test_retired_claim_propagates_to_kg(self, tmp_path):
        kg = LabKG(_path(tmp_path))
        kg.upsert_from_ledger("lineage-1", _ledger_with_locked_claim())
        # Same statement retired in another lineage
        ledger2 = ClaimLedger()
        c = ledger2.add_claim(
            statement="L4 compiled beats L1 raw at K4-depth",
            provenance=PROVENANCE_RUN_EVIDENCE,
            supporting_findings=["bd-finding-77"],
        )
        ledger2.assert_claim(c.id)
        ledger2.retire_claim(c.id)
        kg.upsert_from_ledger("lineage-2", ledger2)
        assert kg.entries[0].status == "retired"

    def test_empty_lineage_id_rejected(self, tmp_path):
        kg = LabKG(_path(tmp_path))
        with pytest.raises(ValueError):
            kg.upsert_from_ledger("", _ledger_with_locked_claim())


class TestQuery:
    def test_query_returns_only_durable_by_default(self, tmp_path):
        kg = LabKG(_path(tmp_path))
        # Durable: locked
        kg.upsert_from_ledger("lineage-1", _ledger_with_locked_claim("knowledge compilation helps reasoning"))
        # Asserted-only: appears in durable=False only
        l2 = ClaimLedger()
        c = l2.add_claim(
            statement="token budget is compressed 2x by compilation",
            provenance=PROVENANCE_RUN_EVIDENCE,
            supporting_findings=["bd-finding-1"],
        )
        l2.assert_claim(c.id)
        kg.upsert_from_ledger("lineage-2", l2)

        durable_only = kg.query("knowledge compilation reasoning")
        assert len(durable_only) == 1
        assert durable_only[0].status == "locked"

        with_non_durable = kg.query("compression compilation token", include_non_durable=True)
        assert any(e.status == "asserted" for e in with_non_durable)

    def test_query_empty_topic_returns_empty(self, tmp_path):
        kg = LabKG(_path(tmp_path))
        kg.upsert_from_ledger("lineage-1", _ledger_with_locked_claim())
        assert kg.query("") == []
        assert kg.query("   ") == []

    def test_query_ranking_by_overlap(self, tmp_path):
        kg = LabKG(_path(tmp_path))
        kg.upsert_from_ledger("lineage-a", _ledger_with_locked_claim("compilation helps reasoning"))
        kg.upsert_from_ledger("lineage-b", _ledger_with_locked_claim("different topic about caching"))
        hits = kg.query("compilation reasoning")
        assert hits[0].source_lineage == "lineage-a"

    def test_stale_flag_set_when_half_life_expired(self, tmp_path):
        kg = LabKG(_path(tmp_path))
        kg.upsert_from_ledger("lineage-1", _ledger_with_locked_claim("stale topic here"))
        # Backdate half_life_due to the past
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        kg.entries[0].half_life_due = past
        hits = kg.query("stale topic")
        assert hits[0].stale_as_of_query is True

    def test_half_life_set_for_durable_entries(self, tmp_path):
        kg = LabKG(_path(tmp_path))
        kg.upsert_from_ledger("lineage-1", _ledger_with_locked_claim())
        assert kg.entries[0].half_life_due is not None


class TestDeadEnds:
    def test_record_and_query(self, tmp_path):
        kg = LabKG(_path(tmp_path))
        kg.record_dead_end(
            "lineage-7",
            description="StandardScaler applied per-batch instead of fit on train",
            reason="Caused 14pp spurious improvement; artifact of data leakage",
            category="artifact",
        )
        hits = kg.query_dead_ends("StandardScaler leakage")
        assert len(hits) == 1
        assert hits[0].category == "artifact"

    def test_dead_end_requires_description_and_reason(self, tmp_path):
        kg = LabKG(_path(tmp_path))
        with pytest.raises(ValueError):
            kg.record_dead_end("lineage-1", "", "reason", "artifact")
        with pytest.raises(ValueError):
            kg.record_dead_end("lineage-1", "desc", "", "artifact")

    def test_invalid_category_rejected(self, tmp_path):
        kg = LabKG(_path(tmp_path))
        with pytest.raises(ValueError):
            kg.record_dead_end("lineage-1", "desc", "reason", "nonsense")


class TestFormatBrief:
    def test_empty_kg_returns_empty_string(self, tmp_path):
        kg = LabKG(_path(tmp_path))
        assert kg.format_brief("any topic") == ""

    def test_brief_mentions_adversarial_framing(self, tmp_path):
        kg = LabKG(_path(tmp_path))
        kg.upsert_from_ledger("lineage-1", _ledger_with_locked_claim("adversarial framing matters"))
        brief = kg.format_brief("adversarial framing")
        assert "hypothesis to challenge" in brief
        assert "fresh external" in brief
        assert "L1" in brief  # entry id

    def test_brief_includes_dead_ends(self, tmp_path):
        kg = LabKG(_path(tmp_path))
        kg.record_dead_end(
            "lineage-1",
            description="Used single-seed baseline",
            reason="Baseline variance dominated the reported gap",
            category="method",
        )
        brief = kg.format_brief("single-seed baseline variance")
        assert "Recorded dead ends" in brief
        assert "single-seed" in brief


class TestPersistence:
    def test_forward_compat_unknown_keys_ignored(self, tmp_path):
        path = _path(tmp_path)
        # Manually write a KG with a future-schema unknown field
        payload = {
            "schema_version": 99,
            "entries": [
                {
                    "id": "L1",
                    "statement": "future claim",
                    "provenance": "run_evidence",
                    "status": "locked",
                    "source_lineage": "lin-1",
                    "source_claim_id": "C1",
                    "supporting_lineages": ["lin-1"],
                    "replicated_in": [],
                    "dissent": [],
                    "effect_summary": None,
                    "artifact_paths": [],
                    "first_recorded": "2026-01-01T00:00:00+00:00",
                    "last_updated": "2026-01-01T00:00:00+00:00",
                    "half_life_due": "2027-01-01T00:00:00+00:00",
                    "NEW_UNKNOWN_FIELD": "ignored",
                }
            ],
            "dead_ends": [],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        kg = LabKG.load(path)
        assert len(kg.entries) == 1
        assert kg.entries[0].statement == "future claim"

    def test_malformed_entries_are_dropped_on_load(self, tmp_path):
        path = _path(tmp_path)
        payload = {
            "schema_version": 1,
            "entries": [
                {"id": "L1", "statement": "", "provenance": "run_evidence", "status": "locked"},  # empty statement
                {"id": "L2", "statement": "good", "provenance": "bogus", "status": "locked"},     # bad provenance
            ],
            "dead_ends": [],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        kg = LabKG.load(path)
        assert kg.entries == []


class TestEnvOverride:
    def test_env_var_redirects_default_path(self, tmp_path, monkeypatch):
        from voronoi.science.lab_kg import default_store_path
        custom = tmp_path / "custom" / "kg.json"
        monkeypatch.setenv("VORONOI_LAB_KG_PATH", str(custom))
        assert default_store_path() == custom
