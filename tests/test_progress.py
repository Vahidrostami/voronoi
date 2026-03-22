"""Tests for voronoi.gateway.progress — formatting helpers.

The actual progress *polling* logic lives in the dispatcher and is tested
in test_dispatcher.py.  These tests cover the formatting functions only.
"""

from pathlib import Path

from voronoi.gateway.progress import (
    format_launch, format_complete, format_failure, format_alert,
    format_restart, format_duration, progress_bar, estimate_remaining,
    build_digest, build_digest_whatsup, assess_track_status,
    phase_description,
)


class TestBuddyFormatters:
    def test_format_launch(self):
        msg = format_launch("Synapse", "discover", "adaptive", "Why is latency high?")
        assert "Synapse" in msg
        assert "is live" in msg
        assert "latency" in msg

    def test_format_complete(self):
        msg = format_complete("Synapse", "discover", 20, 18, 3600)
        assert "Synapse" in msg
        assert "done" in msg.lower()
        assert "18" in msg

    def test_format_failure(self):
        msg = format_failure("Synapse", "crashed", 7200, 5, 20, log_tail="error here")
        assert "Synapse" in msg
        assert "failed" in msg.lower()
        assert "error here" in msg

    def test_format_alert(self):
        msg = format_alert("Synapse", "something went wrong")
        assert "Synapse" in msg
        assert "something went wrong" in msg

    def test_format_restart(self):
        msg = format_restart("Synapse", 1, 2, log_tail="last line")
        assert "Synapse" in msg
        assert "1/2" in msg

    def test_format_duration(self):
        assert format_duration(300) == "5min"
        assert format_duration(3600) == "1h"
        assert format_duration(5400) == "1h 30min"


class TestProgressBar:
    def test_empty(self):
        bar = progress_bar(0, 10)
        assert "0%" in bar

    def test_full(self):
        bar = progress_bar(10, 10)
        assert "100%" in bar

    def test_half(self):
        bar = progress_bar(5, 10)
        assert "50%" in bar

    def test_zero_total(self):
        bar = progress_bar(0, 0)
        assert "0%" in bar


class TestEstimateRemaining:
    def test_no_done(self):
        assert estimate_remaining(100, 0, 10) == ""

    def test_all_done(self):
        assert estimate_remaining(100, 10, 10) == ""

    def test_partial(self):
        result = estimate_remaining(600, 5, 10)
        assert "left" in result or "almost" in result


class TestPhaseDescription:
    def test_known_phase(self):
        desc = phase_description("investigate", "investigating")
        assert "experiment" in desc.lower() or "parallel" in desc.lower()

    def test_unknown_phase(self):
        desc = phase_description("investigate", "unknown_phase")
        assert "unknown_phase" in desc


class TestTrackAssessment:
    def test_on_track_with_progress(self, tmp_path):
        snapshot = {"t1": {"status": "closed", "notes": ""}, "t2": {"status": "in_progress", "notes": ""}}
        status, reason = assess_track_status(tmp_path, snapshot)
        assert status == "on_track"

    def test_off_track_design_invalid(self, tmp_path):
        snapshot = {"t1": {"status": "open", "notes": "DESIGN_INVALID: bad"}}
        status, reason = assess_track_status(tmp_path, snapshot)
        assert status == "off_track"

    def test_watch_no_tasks(self, tmp_path):
        status, reason = assess_track_status(tmp_path, {})
        assert status == "watch"


class TestBuildDigest:
    def test_basic_digest(self, tmp_path):
        snapshot = {
            "t1": {"status": "closed", "notes": ""},
            "t2": {"status": "in_progress", "notes": ""},
            "t3": {"status": "open", "notes": ""},
        }
        msg = build_digest(
            codename="Synapse",
            mode="discover",
            phase="investigating",
            elapsed_sec=3600,
            task_snapshot=snapshot,
            workspace=tmp_path,
            events_since_last=[
                {"type": "task_done", "msg": "✅ Done: *Build encoder*"},
            ],
        )
        assert "Synapse" in msg
        assert "1h" in msg
        assert "Finished" in msg
        assert "33%" in msg or "1/3" in msg

    def test_digest_with_findings(self, tmp_path):
        msg = build_digest(
            codename="Synapse",
            mode="discover",
            phase="reviewing",
            elapsed_sec=7200,
            task_snapshot={"t1": {"status": "closed", "notes": ""}},
            workspace=tmp_path,
            events_since_last=[
                {"type": "finding", "msg": "🔬 *NEW FINDING*\nSimpson's paradox detected"},
            ],
        )
        assert "finding" in msg.lower()
        assert "Simpson" in msg

    def test_digest_with_experiments_tsv(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "experiments.tsv").write_text(
            "timestamp\ttask_id\tbranch\tmetric_name\tmetric_value\tstatus\tdescription\n"
            "2026-01-01\tbd-1\tagent-1\tmbrs\t0.5\tkeep\tscenario 1\n"
            "2026-01-01\tbd-2\tagent-1\tmbrs\t0.3\tdiscard\tscenario 2\n"
        )
        msg = build_digest(
            codename="Synapse",
            mode="discover",
            phase="investigating",
            elapsed_sec=3600,
            task_snapshot={"t1": {"status": "in_progress", "notes": ""}},
            workspace=tmp_path,
            events_since_last=[],
        )
        assert "Experiment" in msg
        assert "1 good" in msg
        assert "1 discard" in msg

    def test_digest_merges_worker_ledgers_and_artifacts(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        swarm_dir = tmp_path.parent / f"{tmp_path.name}-swarm"
        agent_dir = swarm_dir / "agent-phase2"
        (agent_dir / ".swarm").mkdir(parents=True)
        (agent_dir / "demos" / "demo-a" / "output").mkdir(parents=True)
        (tmp_path / ".swarm-config.json").write_text(
            '{"swarm_dir": "%s"}' % str(swarm_dir)
        )
        (agent_dir / ".swarm" / "experiments.tsv").write_text(
            "timestamp\ttask_id\tbranch\tmetric_name\tmetric_value\tstatus\tdescription\n"
            "2026-01-01\tbd-9\tagent-phase2\tmbrs\t0.7\tkeep\tscenario 9\n"
        )
        (agent_dir / "demos" / "demo-a" / "output" / "pilot_results.json").write_text("{}")

        msg = build_digest(
            codename="Synapse",
            mode="discover",
            phase="investigating",
            elapsed_sec=3600,
            task_snapshot={"t1": {"status": "in_progress", "notes": ""}},
            workspace=tmp_path,
            events_since_last=[],
        )

        assert "Experiment" in msg
        assert "1 good" in msg
        assert "Observed artifacts" in msg


class TestBuildDigestWhatsup:
    def test_nothing_running(self):
        msg = build_digest_whatsup(running_investigations=[], queued=0)
        assert "Nothing running" in msg

    def test_with_investigation(self):
        msg = build_digest_whatsup(
            running_investigations=[{
                "label": "Synapse",
                "mode": "investigate",
                "elapsed_sec": 3600,
                "total_tasks": 20,
                "closed_tasks": 8,
                "in_progress_tasks": 3,
                "ready_tasks": 2,
                "agents_healthy": 3,
                "agents_stuck": 0,
                "phase": "investigating",
                "question": "Why is accuracy dropping?",
            }],
            queued=0,
        )
        assert "Synapse" in msg
        assert "1h" in msg
        assert "8/20" in msg
        assert "accuracy" in msg.lower()
