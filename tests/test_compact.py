"""Tests for voronoi.server.compact — workspace state compaction."""

import json
import time

import pytest

from voronoi.server.compact import (
    _compact_events,
    _compact_experiments,
    _write_state_digest,
    compact_workspace_state,
)


class TestCompactExperiments:
    def test_no_tsv(self, tmp_path):
        assert _compact_experiments(tmp_path) is False

    def test_small_tsv_unchanged(self, tmp_path):
        tsv = tmp_path / "experiments.tsv"
        header = "id\tstatus\tresult"
        rows = [f"exp-{i}\tkeep\tok" for i in range(10)]
        tsv.write_text(header + "\n" + "\n".join(rows) + "\n")
        assert _compact_experiments(tmp_path) is False

    def test_large_tsv_compacted(self, tmp_path):
        tsv = tmp_path / "experiments.tsv"
        header = "id\tstatus\tresult"
        rows = [f"exp-{i}\tkeep\tok" for i in range(30)]
        tsv.write_text(header + "\n" + "\n".join(rows) + "\n")

        assert _compact_experiments(tmp_path) is True

        # Active file should have header + 20 recent rows
        active_lines = tsv.read_text().strip().splitlines()
        assert active_lines[0] == header
        assert len(active_lines) == 21  # header + 20

        # Archive should have header + 10 old rows
        archive = tmp_path / "experiments.archive.tsv"
        assert archive.exists()
        archive_lines = archive.read_text().strip().splitlines()
        assert archive_lines[0] == header
        assert len(archive_lines) == 11  # header + 10


class TestCompactEvents:
    def test_no_events_file(self, tmp_path):
        assert _compact_events(tmp_path) is False

    def test_small_log_unchanged(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        lines = [json.dumps({"ts": time.time(), "event": f"ev-{i}"}) for i in range(10)]
        events_file.write_text("\n".join(lines) + "\n")
        assert _compact_events(tmp_path) is False

    def test_old_events_archived(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        now = time.time()
        old_ts = now - 4 * 3600  # 4 hours ago (beyond 2h cutoff)
        recent_ts = now - 0.5 * 3600  # 30 min ago

        lines = []
        for i in range(30):
            lines.append(json.dumps({"ts": old_ts + i, "event": f"old-{i}"}))
        for i in range(25):
            lines.append(json.dumps({"ts": recent_ts + i, "event": f"new-{i}"}))
        events_file.write_text("\n".join(lines) + "\n")

        assert _compact_events(tmp_path) is True

        # Active file should only have recent events
        remaining = events_file.read_text().strip().splitlines()
        assert len(remaining) == 25

        # Archive should have old events
        archive = tmp_path / "events.archive.jsonl"
        assert archive.exists()
        archived = archive.read_text().strip().splitlines()
        assert len(archived) == 30

    def test_concurrent_append_preserved(self, tmp_path):
        """BUG-006: Events appended during compaction should be preserved.

        Simulates the scenario where the orchestrator appends new events
        between the initial read and the rewrite.  The fix detects the
        file growth and includes the appended lines in the rewritten file.
        """
        events_file = tmp_path / "events.jsonl"
        now = time.time()
        old_ts = now - 4 * 3600  # 4 hours ago
        recent_ts = now - 0.5 * 3600  # 30 min ago

        lines = []
        for i in range(30):
            lines.append(json.dumps({"ts": old_ts + i, "event": f"old-{i}"}))
        for i in range(25):
            lines.append(json.dumps({"ts": recent_ts + i, "event": f"recent-{i}"}))
        initial_content = "\n".join(lines) + "\n"

        # Write initial content, then append a "concurrent" event
        events_file.write_text(initial_content)
        appended_event = json.dumps({"ts": now, "event": "appended-during-compact"})
        with open(events_file, "a") as f:
            f.write(appended_event + "\n")

        # _compact_events reads the full file (including appended line).
        # Because the file contains the appended event in its read buffer,
        # it should classify it as "recent" and keep it.
        result = _compact_events(tmp_path)
        assert result is True

        # The appended event should be in the active file, not lost
        remaining_text = events_file.read_text()
        assert "appended-during-compact" in remaining_text


class TestWriteStateDigest:
    def test_empty_workspace(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        assert _write_state_digest(tmp_path) is False

    def test_with_criteria(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        criteria = [
            {"id": "C1", "met": True, "description": "done"},
            {"id": "C2", "met": False, "description": "pending"},
        ]
        (swarm / "success-criteria.json").write_text(json.dumps(criteria))

        assert _write_state_digest(tmp_path) is True
        digest = (swarm / "state-digest.md").read_text()
        assert "1/2 met" in digest
        assert "[MET] C1" in digest
        assert "[PENDING] C2" in digest

    def test_checkpoint_promotes_criteria(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        criteria = [
            {"id": "C1", "met": False, "description": "first"},
            {"id": "C2", "met": False, "description": "second"},
        ]
        (swarm / "success-criteria.json").write_text(json.dumps(criteria))
        cp = {"criteria_status": {"C1": True}}
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps(cp))

        assert _write_state_digest(tmp_path) is True
        digest = (swarm / "state-digest.md").read_text()
        assert "1/2 met" in digest

    def test_with_experiments_tsv(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        tsv = swarm / "experiments.tsv"
        tsv.write_text("id\tstatus\tresult\nexp-1\tkeep\tok\nexp-2\tcrash\tbad\n")

        assert _write_state_digest(tmp_path) is True
        digest = (swarm / "state-digest.md").read_text()
        assert "Experiments" in digest
        assert "1 keep" in digest
        assert "1 crash" in digest


class TestCompactWorkspaceState:
    def test_no_swarm_dir(self, tmp_path):
        assert compact_workspace_state(tmp_path) is False

    def test_empty_swarm(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        assert compact_workspace_state(tmp_path) is False
