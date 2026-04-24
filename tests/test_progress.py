"""Tests for voronoi.gateway.progress — formatting helpers.

The actual progress *polling* logic lives in the dispatcher and is tested
in test_dispatcher.py.  These tests cover the formatting functions only.
"""

from pathlib import Path

from voronoi.gateway.progress import (
    format_launch, format_complete, format_failure, format_alert,
    format_negative_result, format_restart, format_wake, format_pause,
    format_duration, progress_bar, estimate_remaining,
    build_digest, build_digest_whatsup, assess_track_status,
    phase_description, phase_position, _synthesize_narrative,
    VOICE_PHASE_VARIANTS, MSG_TYPE_MILESTONE, MSG_TYPE_STATUS,
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
        assert "didn't make it" in msg
        assert "error here" in msg

    def test_format_alert(self):
        msg = format_alert("Synapse", "something went wrong")
        assert "Synapse" in msg
        assert "something went wrong" in msg

    def test_format_restart(self):
        msg = format_restart("Synapse", 1, 2, log_tail="last line")
        assert "Synapse" in msg
        assert "1/2" in msg
        assert "hit a bump" in msg

    def test_format_restart_clean_exit(self):
        msg = format_restart("Synapse", 1, 2, clean_exit=True)
        assert "exited early" in msg
        assert "hit a bump" not in msg

    def test_format_restart_crash(self):
        msg = format_restart("Synapse", 1, 2, clean_exit=False)
        assert "hit a bump" in msg

    def test_format_wake_with_events(self):
        msg = format_wake("Synapse", n_events=5)
        assert "Synapse" in msg
        assert "workers finished" in msg
        assert "5 events" in msg
        assert "restarting" not in msg  # must NOT look like a crash

    def test_format_wake_no_events(self):
        msg = format_wake("Synapse", n_events=0)
        assert "Synapse" in msg
        assert "workers finished" in msg
        assert "events" not in msg

    def test_format_pause(self):
        msg = format_pause("Synapse", "auth expired", 7200, 5, 20)
        assert "Synapse" in msg
        assert "paused" in msg.lower()
        assert "auth expired" in msg
        assert "5/20" in msg
        assert "/voronoi resume" in msg

    def test_format_pause_no_tasks(self):
        msg = format_pause("Synapse", "auth expired", 300, 0, 0)
        assert "Synapse" in msg
        assert "paused" in msg.lower()
        assert "0/0" not in msg  # should skip progress when total=0

    def test_format_duration(self):
        assert format_duration(300) == "5min"
        assert format_duration(3600) == "1h"
        assert format_duration(5400) == "1h 30min"

    def test_format_negative_result(self):
        msg = format_negative_result("Synapse", 7200, 12, 15, eval_score=0.78,
                                     reason="Hypothesis falsified with d=0.02")
        assert "Synapse" in msg
        assert "negative result" in msg.lower()
        assert "rigorously" in msg.lower()
        assert "0.78" in msg
        assert "falsified" in msg

    def test_format_negative_result_no_score(self):
        msg = format_negative_result("Synapse", 3600, 8, 10)
        assert "Synapse" in msg
        assert "negative result" in msg.lower()
        assert "0." not in msg  # no score line when score=0


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
        msg, msg_type = build_digest(
            codename="Synapse",
            mode="discover",
            phase="investigating",
            elapsed_sec=3600,
            task_snapshot=snapshot,
            workspace=tmp_path,
            events_since_last=[
                {"type": "task_done", "msg": "✅ Wrapped up: *Build encoder*"},
            ],
        )
        assert "Synapse" in msg
        assert "1h" in msg
        assert "✓" in msg or "Completed" in msg
        assert "33%" in msg or "1/3" in msg
        assert msg_type == MSG_TYPE_STATUS

    def test_digest_with_findings(self, tmp_path):
        msg, msg_type = build_digest(
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
        assert "Simpson" in msg
        assert "★" in msg
        assert msg_type == MSG_TYPE_MILESTONE

    def test_digest_with_experiments_tsv(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "experiments.tsv").write_text(
            "timestamp\ttask_id\tbranch\tmetric_name\tmetric_value\tstatus\tdescription\n"
            "2026-01-01\tbd-1\tagent-1\tmbrs\t0.5\tkeep\tscenario 1\n"
            "2026-01-01\tbd-2\tagent-1\tmbrs\t0.3\tdiscard\tscenario 2\n"
        )
        msg, _ = build_digest(
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

        msg, _ = build_digest(
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


    def test_digest_with_serendipity(self, tmp_path):
        msg, msg_type = build_digest(
            codename="Synapse",
            mode="discover",
            phase="investigating",
            elapsed_sec=5400,
            task_snapshot={"t1": {"status": "in_progress", "notes": ""}},
            workspace=tmp_path,
            events_since_last=[
                {"type": "serendipity",
                 "msg": "🔮 *Unexpected observation*\nMemory leak correlates with GC pauses\n_Agent investigator noticed something outside the plan._"},
            ],
        )
        assert "🔮" in msg
        assert "Memory leak" in msg
        assert msg_type == MSG_TYPE_MILESTONE

    def test_digest_with_rigor_escalation(self, tmp_path):
        msg, msg_type = build_digest(
            codename="Synapse",
            mode="discover",
            phase="investigating",
            elapsed_sec=7200,
            task_snapshot={"t1": {"status": "in_progress", "notes": ""}},
            workspace=tmp_path,
            events_since_last=[
                {"type": "rigor_escalation",
                 "msg": "📐 *Rigor escalated* → scientific\n_pre-registration · hypothesis testing_"},
            ],
        )
        assert "📐" in msg
        assert msg_type == MSG_TYPE_MILESTONE

    def test_digest_with_claim_delta_new(self, tmp_path):
        msg, msg_type = build_digest(
            codename="Synapse",
            mode="discover",
            phase="investigating",
            elapsed_sec=3600,
            task_snapshot={"t1": {"status": "closed", "notes": ""}},
            workspace=tmp_path,
            events_since_last=[
                {"type": "claim_delta", "kind": "new", "claim_id": "C7",
                 "from_status": None, "to_status": "provisional",
                 "statement": "EWC beats replay on CIFAR"},
            ],
        )
        assert "C7" in msg
        assert "New claim" in msg
        # Provisional new claim is not a milestone
        assert msg_type == MSG_TYPE_STATUS

    def test_digest_with_claim_locked_is_milestone(self, tmp_path):
        msg, msg_type = build_digest(
            codename="Synapse",
            mode="prove",
            phase="reviewing",
            elapsed_sec=7200,
            task_snapshot={"t1": {"status": "closed", "notes": ""}},
            workspace=tmp_path,
            events_since_last=[
                {"type": "claim_delta", "kind": "transition", "claim_id": "C3",
                 "from_status": "asserted", "to_status": "locked",
                 "statement": "EWC beats replay"},
            ],
        )
        assert "C3" in msg
        assert "🔒" in msg
        assert "locked" in msg
        assert msg_type == MSG_TYPE_MILESTONE

    def test_digest_with_claim_retired(self, tmp_path):
        msg, msg_type = build_digest(
            codename="Synapse",
            mode="prove",
            phase="reviewing",
            elapsed_sec=7200,
            task_snapshot={"t1": {"status": "closed", "notes": ""}},
            workspace=tmp_path,
            events_since_last=[
                {"type": "claim_delta", "kind": "transition", "claim_id": "C9",
                 "from_status": "challenged", "to_status": "retired",
                 "statement": "Dropout 0.5 hurts"},
            ],
        )
        assert "C9" in msg
        assert "✗" in msg
        assert msg_type == MSG_TYPE_MILESTONE

    def test_digest_suppresses_reassurance_when_stall_signal_present(
        self, tmp_path,
    ):
        """Stall signal must override 'nothing to worry about' reassurance.

        Regression test: previously the digest told the PI "Still setting up
        — nothing to worry about yet." minutes before the stall escalator
        auto-parked the run. Digest and escalator must now agree.
        """
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "stall-signal.json").write_text(
            '{"level": 2, "directive": "experiments_only", '
            '"instruction": "Planning forbidden", '
            '"elapsed_minutes": 65.0, "timestamp": "2026-04-24T00:00:00Z"}'
        )
        msg, _ = build_digest(
            codename="Serotonin",
            mode="discover",
            phase="planning",  # is_early → would normally say "nothing to worry about"
            elapsed_sec=65 * 60,
            task_snapshot={"t1": {"status": "open", "notes": ""}},
            workspace=tmp_path,
            events_since_last=[],
        )
        assert "nothing to worry about" not in msg.lower()
        assert "strike 2" in msg.lower() or "🪫🪫" in msg
        assert "/voronoi extend" in msg


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
        assert "8/20" in msg or "investigating" in msg
        assert "accuracy" in msg.lower()


class TestVoiceRotation:
    def test_voice_variants_exist_for_all_phases(self):
        from voronoi.gateway.progress import PHASE_ORDER
        for phase in PHASE_ORDER:
            assert phase in VOICE_PHASE_VARIANTS
            assert len(VOICE_PHASE_VARIANTS[phase]) >= 2

    def test_phase_description_rotates_by_codename(self):
        desc_a = phase_description("discover", "investigating", codename="Synapse")
        desc_b = phase_description("discover", "investigating", codename="Dopamine")
        # Both should be valid variant strings (not fallback)
        assert desc_a in VOICE_PHASE_VARIANTS["investigating"]
        assert desc_b in VOICE_PHASE_VARIANTS["investigating"]

    def test_phase_description_deterministic(self):
        d1 = phase_description("discover", "investigating", codename="Synapse")
        d2 = phase_description("discover", "investigating", codename="Synapse")
        assert d1 == d2

    def test_phase_description_fallback_without_codename(self):
        desc = phase_description("discover", "investigating")
        assert "experiment" in desc.lower() or "parallel" in desc.lower()

    def test_phase_position(self):
        step, total = phase_position("investigating")
        assert step == 4
        assert total == 8

    def test_phase_position_unknown(self):
        step, total = phase_position("unknown")
        assert step == 0
        assert total == 8


class TestNarrativeSynthesis:
    def test_empty_workspace_returns_empty(self, tmp_path):
        result = _synthesize_narrative(tmp_path, "investigating", {}, 3600)
        assert result == ""

    def test_with_experiments(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "experiments.tsv").write_text(
            "timestamp\ttask_id\tbranch\tmetric_name\tmetric_value\tstatus\tdescription\n"
            "2026-01-01\tbd-1\tagent-1\tmbrs\t0.5\tkeep\tscenario 1\n"
            "2026-01-01\tbd-2\tagent-1\tmbrs\t0.3\tdiscard\tscenario 2\n"
        )
        result = _synthesize_narrative(tmp_path, "investigating", {}, 3600)
        assert "1/2" in result
        assert "passed" in result
        assert "discarded" in result

    def test_with_criteria(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "experiments.tsv").write_text(
            "timestamp\ttask_id\tbranch\tmetric_name\tmetric_value\tstatus\tdescription\n"
            "2026-01-01\tbd-1\tagent-1\tmbrs\t0.5\tkeep\tscenario 1\n"
        )
        (tmp_path / ".swarm" / "success-criteria.json").write_text(
            '[{"id": "SC1", "met": true}, {"id": "SC2", "met": false}]'
        )
        result = _synthesize_narrative(tmp_path, "investigating", {}, 3600)
        assert "1/2 criteria met" in result

    def test_with_belief_map(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "experiments.tsv").write_text(
            "timestamp\ttask_id\tbranch\tmetric_name\tmetric_value\tstatus\tdescription\n"
            "2026-01-01\tbd-1\tagent-1\tmbrs\t0.5\tkeep\tscenario 1\n"
        )
        (tmp_path / ".swarm" / "belief-map.json").write_text(
            '{"hypotheses": [{"name": "GABA encoding", "posterior": 0.85}]}'
        )
        result = _synthesize_narrative(tmp_path, "investigating", {}, 3600)
        assert "GABA encoding" in result
        assert "P=0.85" in result

    def test_planning_phase_shows_task_count(self, tmp_path):
        snapshot = {"t1": {"status": "open"}, "t2": {"status": "open"}}
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "success-criteria.json").write_text(
            '[{"id": "SC1", "met": false}]'
        )
        result = _synthesize_narrative(tmp_path, "planning", snapshot, 300)
        assert "2 experiments" in result
        assert "1 success criteria" in result


class TestMessageTypes:
    def test_finding_returns_milestone_type(self, tmp_path):
        _, msg_type = build_digest(
            codename="Synapse",
            mode="discover",
            phase="investigating",
            elapsed_sec=3600,
            task_snapshot={"t1": {"status": "closed", "notes": ""}},
            workspace=tmp_path,
            events_since_last=[
                {"type": "finding", "msg": "🔬 *NEW FINDING*\neffect found"},
            ],
        )
        assert msg_type == MSG_TYPE_MILESTONE

    def test_design_invalid_returns_milestone_type(self, tmp_path):
        _, msg_type = build_digest(
            codename="Synapse",
            mode="discover",
            phase="investigating",
            elapsed_sec=3600,
            task_snapshot={"t1": {"status": "open", "notes": ""}},
            workspace=tmp_path,
            events_since_last=[
                {"type": "design_invalid", "msg": "🚨 bad design"},
            ],
        )
        assert msg_type == MSG_TYPE_MILESTONE

    def test_status_update_returns_status_type(self, tmp_path):
        _, msg_type = build_digest(
            codename="Synapse",
            mode="discover",
            phase="investigating",
            elapsed_sec=3600,
            task_snapshot={"t1": {"status": "in_progress", "notes": ""}},
            workspace=tmp_path,
            events_since_last=[
                {"type": "task_new", "msg": "📋 Queued: *task 1*"},
            ],
        )
        assert msg_type == MSG_TYPE_STATUS


class TestReadTsvRows:
    """Tests for _read_tsv_rows — TSV parsing edge cases."""

    def test_short_row_padded_not_dropped(self, tmp_path):
        """Rows with fewer fields than the header must be padded, not dropped (BUG-006)."""
        from voronoi.gateway.progress import _read_tsv_rows

        tsv = tmp_path / "data.tsv"
        tsv.write_text(
            "a\tb\tc\n"
            "1\t2\t3\n"
            "4\t5\n"      # short row - 2 fields instead of 3
        )
        rows = _read_tsv_rows(tsv)
        assert len(rows) == 2
        assert rows[0] == {"a": "1", "b": "2", "c": "3"}
        assert rows[1] == {"a": "4", "b": "5", "c": ""}

    def test_single_field_row_padded(self, tmp_path):
        """A row with only one field gets remaining fields padded."""
        from voronoi.gateway.progress import _read_tsv_rows

        tsv = tmp_path / "data.tsv"
        tsv.write_text("x\ty\tz\nonly_one\n")
        rows = _read_tsv_rows(tsv)
        assert len(rows) == 1
        assert rows[0] == {"x": "only_one", "y": "", "z": ""}
