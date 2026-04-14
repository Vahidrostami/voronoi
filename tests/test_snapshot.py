"""Tests for WorkspaceSnapshot."""

import json

import pytest

from voronoi.server.snapshot import WorkspaceSnapshot, _detect_phase


class TestWorkspaceSnapshot:
    """Unit tests for WorkspaceSnapshot.from_workspace()."""

    def test_empty_workspace(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        snap = WorkspaceSnapshot.from_workspace(tmp_path)
        assert snap.phase == "starting"
        assert snap.total_tasks == 0
        assert not snap.has_deliverable
        assert not snap.has_convergence

    def test_with_deliverable(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "deliverable.md").write_text("# Report")
        snap = WorkspaceSnapshot.from_workspace(tmp_path)
        assert snap.phase == "complete"
        assert snap.has_deliverable is True

    def test_with_convergence(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "convergence.json").write_text('{"converged": true}')
        snap = WorkspaceSnapshot.from_workspace(tmp_path)
        assert snap.phase == "converging"
        assert snap.has_convergence is True

    def test_with_belief_map_and_tasks(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "belief-map.json").write_text('{"hypotheses": []}')
        tasks = [{"id": "1", "status": "open", "title": "Exp 1", "notes": ""}]
        snap = WorkspaceSnapshot.from_workspace(tmp_path, tasks=tasks)
        assert snap.phase == "synthesizing"
        assert snap.has_belief_map is True

    def test_scout_to_planning(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "scout-brief.md").write_text("# Brief")
        snap = WorkspaceSnapshot.from_workspace(tmp_path, old_phase="scouting")
        assert snap.phase == "planning"

    def test_tasks_counted(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        tasks = [
            {"id": "1", "status": "closed", "title": "T1", "notes": ""},
            {"id": "2", "status": "in_progress", "title": "T2", "notes": ""},
            {"id": "3", "status": "open", "title": "T3", "notes": ""},
        ]
        snap = WorkspaceSnapshot.from_workspace(tmp_path, tasks=tasks)
        assert snap.total_tasks == 3
        assert snap.closed_tasks == 1
        assert snap.in_progress_tasks == 1
        assert snap.ready_tasks == 1

    def test_eval_score(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "eval-score.json").write_text('{"score": 0.85}')
        snap = WorkspaceSnapshot.from_workspace(tmp_path)
        assert snap.eval_score == 0.85

    def test_eval_score_out_of_range_ignored(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "eval-score.json").write_text('{"score": 1.5}')
        snap = WorkspaceSnapshot.from_workspace(tmp_path)
        assert snap.eval_score == 0.0

    def test_criteria(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        criteria = [
            {"id": "C1", "met": True, "description": "done"},
            {"id": "C2", "met": False, "description": "pending"},
        ]
        (swarm / "success-criteria.json").write_text(json.dumps(criteria))
        snap = WorkspaceSnapshot.from_workspace(tmp_path)
        assert snap.criteria_met == 1
        assert snap.criteria_total == 2

    def test_checkpoint_phase_overrides(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        cp = {"phase": "reviewing", "cycle": 3}
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps(cp))
        tasks = [{"id": "1", "status": "in_progress", "title": "T1", "notes": ""}]
        snap = WorkspaceSnapshot.from_workspace(tmp_path, tasks=tasks)
        assert snap.phase == "reviewing"
        assert snap.checkpoint is not None

    def test_scouting_phase(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        tasks = [
            {"id": "1", "status": "in_progress", "title": "Scout prior work", "notes": ""},
        ]
        snap = WorkspaceSnapshot.from_workspace(tmp_path, tasks=tasks)
        assert snap.phase == "scouting"

    def test_investigating_phase(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        tasks = [
            {"id": "1", "status": "in_progress", "title": "Run experiment", "notes": ""},
            {"id": "2", "status": "closed", "title": "Setup baseline", "notes": ""},
        ]
        snap = WorkspaceSnapshot.from_workspace(tmp_path, tasks=tasks)
        assert snap.phase == "investigating"


class TestDetectPhase:
    """Unit tests for the _detect_phase helper."""

    def test_no_artifacts(self):
        phase = _detect_phase(
            has_deliverable=False, has_convergence=False,
            has_belief_map=False, has_scout_brief=False,
            task_snapshot={}, total_tasks=0, closed_tasks=0,
            in_progress_tasks=0, checkpoint=None, old_phase="",
        )
        assert phase == "starting"

    def test_deliverable_wins(self):
        phase = _detect_phase(
            has_deliverable=True, has_convergence=True,
            has_belief_map=True, has_scout_brief=True,
            task_snapshot={}, total_tasks=5, closed_tasks=5,
            in_progress_tasks=0, checkpoint=None, old_phase="",
        )
        assert phase == "complete"

    def test_checkpoint_phase_authoritative(self):
        phase = _detect_phase(
            has_deliverable=False, has_convergence=False,
            has_belief_map=False, has_scout_brief=False,
            task_snapshot={}, total_tasks=0, closed_tasks=0,
            in_progress_tasks=0, checkpoint={"phase": "converging"},
            old_phase="",
        )
        assert phase == "converging"
