"""Tests for voronoi.gateway.knowledge — knowledge recall system."""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from voronoi.gateway.knowledge import (
    Finding,
    FederatedKnowledge,
    KnowledgeStore,
    _escape_md,
)
from voronoi.utils import parse_finding_notes as _parse_finding_notes


# ---------------------------------------------------------------------------
# Finding formatting
# ---------------------------------------------------------------------------

class TestFinding:
    def test_format_telegram_basic(self):
        f = Finding(id="bd-42", title="Cache improves throughput", status="closed", priority=1)
        text = f.format_telegram()
        assert "bd-42" in text
        assert "Cache improves throughput" in text

    def test_format_telegram_with_metrics(self):
        f = Finding(
            id="bd-42",
            title="Redis outperforms Memcached",
            status="closed",
            priority=1,
            effect_size="d=2.3",
            confidence_interval="[1.9, 2.8]",
            sample_size="10000",
            valence="positive",
            robust="yes",
            stat_test="Welch t-test",
        )
        text = f.format_telegram()
        assert "d=2.3" in text
        assert "[1.9, 2.8]" in text
        assert "N=10000" in text
        assert "POSITIVE" in text
        assert "yes" in text
        assert "Welch t\\-test" in text

    def test_format_telegram_negative_finding(self):
        f = Finding(
            id="bd-10",
            title="L1 cache adds no benefit",
            status="closed",
            priority=2,
            valence="negative",
        )
        text = f.format_telegram()
        assert "❌" in text
        assert "NEGATIVE" in text

    def test_format_telegram_inconclusive(self):
        f = Finding(id="bd-5", title="Unclear result", status="closed", priority=2,
                    valence="inconclusive")
        text = f.format_telegram()
        assert "❓" in text


# ---------------------------------------------------------------------------
# Note parsing
# ---------------------------------------------------------------------------

class TestParseNotes:
    def test_parse_effect_size(self):
        notes = "TYPE:finding | VALENCE:positive | CONFIDENCE:0.8\nEFFECT_SIZE:d=2.3 | CI_95:[1.9, 2.8] | N:10000"
        parsed = _parse_finding_notes(notes)
        assert parsed["effect_size"] == "d=2.3"
        assert parsed["ci_95"] == "[1.9, 2.8]"
        assert parsed["n"] == "10000"
        assert parsed["valence"] == "positive"
        assert parsed["confidence"] == "0.8"

    def test_parse_robust(self):
        notes = "ROBUST:yes | STAT_TEST:Welch t-test"
        parsed = _parse_finding_notes(notes)
        assert parsed["robust"] == "yes"
        assert parsed["stat_test"] == "Welch t-test"

    def test_parse_empty(self):
        parsed = _parse_finding_notes("")
        assert parsed == {}

    def test_parse_data_file(self):
        notes = "DATA_FILE:data/raw/experiment_1.csv"
        parsed = _parse_finding_notes(notes)
        assert parsed["data_file"] == "data/raw/experiment_1.csv"


# ---------------------------------------------------------------------------
# Markdown escaping
# ---------------------------------------------------------------------------

class TestEscapeMd:
    def test_escapes_underscores(self):
        assert _escape_md("hello_world") == "hello\\_world"

    def test_escapes_asterisks(self):
        assert _escape_md("*bold*") == "\\*bold\\*"

    def test_escapes_backticks(self):
        assert _escape_md("`code`") == "\\`code\\`"

    def test_no_escaping_needed(self):
        assert _escape_md("hello world") == "hello world"


# ---------------------------------------------------------------------------
# KnowledgeStore — search_findings (mocked bd)
# ---------------------------------------------------------------------------

class TestKnowledgeStoreSearch:
    @patch("voronoi.gateway.knowledge._run_bd")
    def test_search_findings_empty(self, mock_bd, tmp_path):
        mock_bd.return_value = (0, json.dumps([]))
        ks = KnowledgeStore(tmp_path)
        results = ks.search_findings("caching")
        assert results == []

    @patch("voronoi.gateway.knowledge._run_bd")
    def test_search_findings_matches(self, mock_bd, tmp_path):
        tasks = [
            {"id": "bd-1", "title": "FINDING: Cache improves throughput", "status": "closed",
             "priority": 1, "notes": "EFFECT_SIZE:d=2.3 | VALENCE:positive", "type": "investigation"},
            {"id": "bd-2", "title": "Build login page", "status": "closed",
             "priority": 2, "notes": "", "type": "build"},
        ]
        mock_bd.return_value = (0, json.dumps(tasks))
        ks = KnowledgeStore(tmp_path)
        results = ks.search_findings("cache")
        # "cache" appears in bd-1 title but not in bd-2 at all
        assert len(results) == 1
        assert results[0].id == "bd-1"
        assert results[0].effect_size == "d=2.3"

    @patch("voronoi.gateway.knowledge._run_bd")
    def test_search_findings_bd_failure(self, mock_bd, tmp_path):
        mock_bd.return_value = (1, "bd not found")
        ks = KnowledgeStore(tmp_path)
        results = ks.search_findings("anything")
        assert results == []

    @patch("voronoi.gateway.knowledge._run_bd")
    def test_search_respects_max_results(self, mock_bd, tmp_path):
        tasks = [
            {"id": f"bd-{i}", "title": f"FINDING: result {i}", "status": "closed",
             "priority": 1, "notes": "finding", "type": "investigation"}
            for i in range(20)
        ]
        mock_bd.return_value = (0, json.dumps(tasks))
        ks = KnowledgeStore(tmp_path)
        results = ks.search_findings("result", max_results=5)
        assert len(results) == 5

    @patch("voronoi.gateway.knowledge._run_bd")
    def test_format_recall_response_no_results(self, mock_bd, tmp_path):
        mock_bd.return_value = (0, json.dumps([]))
        ks = KnowledgeStore(tmp_path)
        resp = ks.format_recall_response("nonexistent topic")
        assert "No findings match" in resp

    @patch("voronoi.gateway.knowledge._run_bd")
    def test_format_recall_response_with_results(self, mock_bd, tmp_path):
        tasks = [
            {"id": "bd-1", "title": "FINDING: caching helps", "status": "closed",
             "priority": 1, "notes": "EFFECT_SIZE:d=1.5 | VALENCE:positive", "type": "investigation"},
        ]
        mock_bd.return_value = (0, json.dumps(tasks))
        ks = KnowledgeStore(tmp_path)
        resp = ks.format_recall_response("caching")
        assert "1 finding" in resp
        assert "bd-1" in resp


# ---------------------------------------------------------------------------
# KnowledgeStore — files (journal, belief map, strategic context)
# ---------------------------------------------------------------------------

class TestKnowledgeStoreFiles:
    def test_get_belief_map_md(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "belief-map.md").write_text("# Belief Map\nH1: P=0.7\nH2: P=0.3")
        ks = KnowledgeStore(tmp_path)
        belief = ks.get_belief_map()
        assert "H1" in belief
        assert "H2" in belief

    def test_get_belief_map_json(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        data = {"hypotheses": [
            {"name": "H1", "prior": 0.7, "status": "confirmed"},
            {"name": "H2", "prior": 0.3, "status": "refuted"},
        ]}
        (swarm / "belief-map.json").write_text(json.dumps(data))
        ks = KnowledgeStore(tmp_path)
        belief = ks.get_belief_map()
        assert "H1" in belief
        assert "0.7" in belief
        assert "confirmed" in belief

    def test_get_belief_map_missing(self, tmp_path):
        ks = KnowledgeStore(tmp_path)
        assert ks.get_belief_map() is None

    def test_get_strategic_context(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "strategic-context.md").write_text("## Goal\nFind root cause of latency")
        ks = KnowledgeStore(tmp_path)
        ctx = ks.get_strategic_context()
        assert "latency" in ctx

    def test_get_strategic_context_missing(self, tmp_path):
        ks = KnowledgeStore(tmp_path)
        assert ks.get_strategic_context() is None


# ---------------------------------------------------------------------------
# Federated knowledge index
# ---------------------------------------------------------------------------

class TestFederatedKnowledge:
    def test_init_creates_db(self, tmp_path):
        db_path = tmp_path / "knowledge.db"
        fk = FederatedKnowledge(db_path)
        assert db_path.exists()

    def test_init_rebuilds_stale_fts_index(self, tmp_path):
        db_path = tmp_path / "knowledge.db"
        FederatedKnowledge(db_path)

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "INSERT INTO findings "
                "(id, investigation, codename, title, notes, effect_size, valence, confidence, robust, synced_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "bd-1", "inv-1", "Alpha", "FINDING: Cache improves throughput",
                    "VALENCE:positive", "2.3", "positive", "0.9", "yes", 1.0,
                ),
            )
            conn.execute("DELETE FROM findings_fts")
            conn.commit()
        finally:
            conn.close()

        fk = FederatedKnowledge(db_path)
        results = fk.search("cache")

        assert len(results) == 1
        assert results[0].id == "Alpha:bd-1"

    @patch("voronoi.gateway.knowledge._run_bd")
    def test_sync_findings(self, mock_bd, tmp_path):
        db_path = tmp_path / "knowledge.db"
        findings_data = [
            {"id": "bd-5", "title": "FINDING: Cache hit rate improved",
             "notes": "VALENCE:positive\nEFFECT_SIZE:0.82"},
            {"id": "bd-6", "title": "Task: setup experiment", "notes": ""},
            {"id": "bd-7", "title": "FINDING: No effect on latency",
             "notes": "VALENCE:negative\nEFFECT_SIZE:0.05"},
        ]
        mock_bd.return_value = (0, json.dumps(findings_data))

        fk = FederatedKnowledge(db_path)
        count = fk.sync_findings("inv-1", "Synapse", tmp_path)
        assert count == 2  # Only FINDING tasks

    @patch("voronoi.gateway.knowledge._run_bd")
    def test_sync_findings_resync_counts_only_new_rows(self, mock_bd, tmp_path):
        db_path = tmp_path / "knowledge.db"
        findings_data = [
            {"id": "bd-5", "title": "FINDING: Cache hit rate improved",
             "notes": "VALENCE:positive\nEFFECT_SIZE:0.82"},
        ]
        mock_bd.return_value = (0, json.dumps(findings_data))

        fk = FederatedKnowledge(db_path)
        assert fk.sync_findings("inv-1", "Synapse", tmp_path) == 1
        assert fk.sync_findings("inv-1", "Synapse", tmp_path) == 0

    @patch("voronoi.gateway.knowledge._run_bd")
    def test_search_across_investigations(self, mock_bd, tmp_path):
        db_path = tmp_path / "knowledge.db"
        fk = FederatedKnowledge(db_path)

        # Sync findings from two investigations
        mock_bd.return_value = (0, json.dumps([
            {"id": "bd-1", "title": "FINDING: Cache improves throughput",
             "notes": "VALENCE:positive\nEFFECT_SIZE:2.3"},
        ]))
        fk.sync_findings("inv-1", "Alpha", tmp_path)

        mock_bd.return_value = (0, json.dumps([
            {"id": "bd-2", "title": "FINDING: Cache invalidation causes stalls",
             "notes": "VALENCE:negative\nEFFECT_SIZE:0.9"},
        ]))
        fk.sync_findings("inv-2", "Beta", tmp_path)

        results = fk.search("cache")
        assert len(results) == 2
        ids = {f.id for f in results}
        assert "Alpha:bd-1" in ids
        assert "Beta:bd-2" in ids

    def test_search_empty_db(self, tmp_path):
        db_path = tmp_path / "knowledge.db"
        fk = FederatedKnowledge(db_path)
        results = fk.search("anything")
        assert results == []

    def test_search_empty_query(self, tmp_path):
        db_path = tmp_path / "knowledge.db"
        fk = FederatedKnowledge(db_path)
        results = fk.search("")
        assert results == []

    @patch("voronoi.gateway.knowledge._run_bd")
    def test_format_search_response(self, mock_bd, tmp_path):
        db_path = tmp_path / "knowledge.db"
        fk = FederatedKnowledge(db_path)

        mock_bd.return_value = (0, json.dumps([
            {"id": "bd-1", "title": "FINDING: Protein X binds Y",
             "notes": "VALENCE:positive\nEFFECT_SIZE:1.5"},
        ]))
        fk.sync_findings("inv-1", "Dopamine", tmp_path)

        response = fk.format_search_response("protein")
        assert "🌐" in response
        assert "Protein X" in response

    @patch("voronoi.gateway.knowledge._run_bd")
    def test_format_search_no_results(self, mock_bd, tmp_path):
        db_path = tmp_path / "knowledge.db"
        fk = FederatedKnowledge(db_path)
        response = fk.format_search_response("nonexistent")
        assert "🌐" in response
        assert "No cross-investigation" in response
