"""Tests for WorkspaceSnapshot."""

import json

import pytest

from voronoi.server.snapshot import (
    WorkspaceSnapshot,
    build_investigation_status,
    write_investigation_status,
    _detect_phase,
)


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

    def test_checkpoint_counts_used_when_task_snapshot_unavailable(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        cp = {
            "phase": "investigating",
            "total_tasks": 6,
            "closed_tasks": 2,
            "active_workers": ["agent-study-1"],
        }
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps(cp))

        snap = WorkspaceSnapshot.from_workspace(tmp_path)

        assert snap.total_tasks == 6
        assert snap.closed_tasks == 2
        assert snap.in_progress_tasks == 1
        assert snap.ready_tasks == 3

    def test_explicit_empty_task_list_does_not_use_checkpoint_counts(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        cp = {"total_tasks": 6, "closed_tasks": 2}
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps(cp))

        snap = WorkspaceSnapshot.from_workspace(tmp_path, tasks=[])

        assert snap.total_tasks == 0
        assert snap.closed_tasks == 0

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


class TestInvestigationStatus:
    """Unit tests for the PI-facing investigation status projection."""

    def test_build_status_projects_tasks_checkpoint_and_gates(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "belief-map.json").write_text('{"hypotheses": []}')
        (swarm / "success-criteria.json").write_text(json.dumps([
            {"id": "C1", "met": True},
            {"id": "C2", "met": False},
        ]))
        (swarm / "sentinel-audit.json").write_text(json.dumps({"passed": True}))
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "phase": "phase1_study2",
            "active_workers": [{"branch": "agent-phase1-study2"}],
            "next_actions": ["finish Study 2"],
            "recent_events": ["Study 1 merged"],
        }))
        tasks = [
            {"id": "inv17-xl7", "status": "in_progress", "title": "Phase 1 pilot", "notes": ""},
            {"id": "inv17-gko", "status": "open", "title": "Missing artifact", "notes": ""},
            {"id": "inv17-done", "status": "closed", "title": "Study 1", "notes": ""},
        ]

        snapshot = WorkspaceSnapshot.from_workspace(tmp_path, tasks=tasks)
        status = build_investigation_status(
            tmp_path,
            snapshot,
            investigation_id=17,
            codename="computational-triage",
            mode="prove",
            rigor="scientific",
            question="test encoding",
            session_alive=True,
        )

        assert status["phase"] == "phase1_study2"
        assert status["tasks"]["closed"] == 1
        assert status["tasks"]["in_progress_items"][0]["id"] == "inv17-xl7"
        assert status["tasks"]["ready_items"][0]["id"] == "inv17-gko"
        assert status["science"]["criteria_met"] == 1
        assert status["science"]["active_workers"] == ["agent-phase1-study2"]
        assert status["gates"]["sentinel"] == "passed"
        assert status["gates"]["eval_score"] == "pending"
        assert status["gates"]["success_criteria"] == "1/2"
        assert status["recommended_action"] == "resolve_ready_work"

    def test_failed_sentinel_gate_drives_operator_action(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "sentinel-audit.json").write_text(json.dumps({"passed": False}))
        snapshot = WorkspaceSnapshot.from_workspace(tmp_path)

        status = build_investigation_status(
            tmp_path,
            snapshot,
            investigation_id=3,
            session_alive=False,
        )

        assert status["gates"]["sentinel"] == "failed"
        assert status["recommended_action"] == "fix_failed_gate"
        assert "failed sentinel" in status["operator_summary"]

    def test_write_status_writes_json_and_health_markdown(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        snapshot = WorkspaceSnapshot.from_workspace(tmp_path)
        status = build_investigation_status(
            tmp_path,
            snapshot,
            investigation_id=9,
            codename="Monday",
        )

        write_investigation_status(tmp_path, status)

        saved = json.loads((swarm / "run-status.json").read_text())
        health = (swarm / "health.md").read_text()
        assert saved["investigation_id"] == 9
        assert saved["codename"] == "Monday"
        assert "Investigation Health: Monday" in health
        assert "Recommended action:" in health
