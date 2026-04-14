"""Tests for voronoi.server.events — structured event log."""

import json
import time
from pathlib import Path

from voronoi.server.events import (
    SwarmEvent,
    append_event,
    log_context_snapshot,
    log_finding,
    log_serendipity,
    log_test_result,
    log_tool_call,
    log_verify_step,
    read_events,
    summarize_events,
)


class TestSwarmEvent:
    def test_to_json_basic(self):
        ev = SwarmEvent(ts=1000.0, agent="worker", task_id="bd-1", event="test_run",
                        status="pass")
        raw = ev.to_json()
        parsed = json.loads(raw)
        assert parsed["agent"] == "worker"
        assert parsed["event"] == "test_run"
        assert parsed["status"] == "pass"

    def test_to_json_truncates_long_detail(self):
        long_detail = "x" * 1000
        ev = SwarmEvent(detail=long_detail)
        parsed = json.loads(ev.to_json())
        assert len(parsed["detail"]) <= 500
        assert parsed["detail"].endswith("...")


class TestAppendEvent:
    def test_creates_file(self, tmp_path):
        ev = SwarmEvent(agent="orchestrator", event="cycle_start")
        append_event(tmp_path, ev)
        log_path = tmp_path / ".swarm" / "events.jsonl"
        assert log_path.exists()
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["agent"] == "orchestrator"

    def test_appends_multiple(self, tmp_path):
        for i in range(3):
            append_event(tmp_path, SwarmEvent(agent=f"agent-{i}", event="work"))
        log_path = tmp_path / ".swarm" / "events.jsonl"
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 3


class TestConvenienceLoggers:
    def test_log_tool_call(self, tmp_path):
        log_tool_call(tmp_path, agent="investigator", task_id="bd-42",
                      tool="pytest", status="pass", detail="3 tests passed")
        events = read_events(tmp_path)
        assert len(events) == 1
        assert events[0].event == "tool_call"
        assert "pytest" in events[0].detail

    def test_log_finding(self, tmp_path):
        log_finding(tmp_path, agent="investigator", task_id="bd-42",
                    finding_id="bd-43", detail="effect d=0.82")
        events = read_events(tmp_path)
        assert events[0].event == "finding_committed"
        assert "bd-43" in events[0].detail

    def test_log_test_result_pass(self, tmp_path):
        log_test_result(tmp_path, agent="worker", task_id="bd-10",
                        passed=True, attempt=1)
        events = read_events(tmp_path)
        assert events[0].status == "pass"
        assert "attempt 1" in events[0].detail

    def test_log_test_result_fail(self, tmp_path):
        log_test_result(tmp_path, agent="worker", task_id="bd-10",
                        passed=False, attempt=2, detail="AssertionError in test_foo")
        events = read_events(tmp_path)
        assert events[0].status == "fail"

    def test_log_verify_step(self, tmp_path):
        log_verify_step(tmp_path, agent="worker", task_id="bd-10",
                        step="produces_check", passed=True)
        events = read_events(tmp_path)
        assert events[0].event == "verify_step"
        assert "produces_check" in events[0].detail

    def test_log_context_snapshot(self, tmp_path):
        log_context_snapshot(
            tmp_path, agent="orchestrator", cycle=5,
            model="claude-opus-4.6", model_limit=200000,
            total_used=50000, system_tokens=22600,
            message_tokens=27300, free_tokens=109600,
            buffer_tokens=40400,
        )
        events = read_events(tmp_path)
        assert len(events) == 1
        assert events[0].event == "context_snapshot"
        assert events[0].tokens_used == 50000
        assert "cycle=5" in events[0].detail
        assert "claude-opus-4.6" in events[0].detail
        assert "sys=22600" in events[0].detail
        assert "free=109600" in events[0].detail

    def test_log_serendipity(self, tmp_path):
        log_serendipity(tmp_path, agent="investigator", task_id="bd-7",
                        description="Cache hit rate correlates with memory pressure")
        events = read_events(tmp_path)
        assert len(events) == 1
        assert events[0].event == "serendipity"
        assert "Cache hit rate" in events[0].detail


class TestReadEvents:
    def test_empty_workspace(self, tmp_path):
        events = read_events(tmp_path)
        assert events == []

    def test_filters_by_since(self, tmp_path):
        now = time.time()
        append_event(tmp_path, SwarmEvent(ts=now - 100, event="old"))
        append_event(tmp_path, SwarmEvent(ts=now - 50, event="mid"))
        append_event(tmp_path, SwarmEvent(ts=now, event="new"))
        events = read_events(tmp_path, since=now - 60)
        assert len(events) == 2
        assert events[0].event == "mid"
        assert events[1].event == "new"

    def test_respects_max_events(self, tmp_path):
        for i in range(20):
            append_event(tmp_path, SwarmEvent(ts=float(i), event=f"ev-{i}"))
        events = read_events(tmp_path, max_events=5)
        assert len(events) == 5
        # Should return the last 5
        assert events[0].event == "ev-15"
        assert events[-1].event == "ev-19"

    def test_handles_malformed_lines(self, tmp_path):
        log_path = tmp_path / ".swarm" / "events.jsonl"
        log_path.parent.mkdir(parents=True)
        log_path.write_text(
            '{"ts":1.0,"event":"good","agent":"a","task_id":"","status":"","detail":"","tokens_used":0}\n'
            'not-json\n'
            '{"ts":2.0,"event":"also_good","agent":"b","task_id":"","status":"","detail":"","tokens_used":0}\n'
        )
        events = read_events(tmp_path)
        assert len(events) == 2
        assert events[0].event == "good"
        assert events[1].event == "also_good"


class TestSummarizeEvents:
    def test_empty(self, tmp_path):
        summary = summarize_events(tmp_path)
        assert summary["count"] == 0

    def test_counts_by_event_and_agent(self, tmp_path):
        append_event(tmp_path, SwarmEvent(agent="a", event="tool_call", status="ok", tokens_used=100))
        append_event(tmp_path, SwarmEvent(agent="a", event="tool_call", status="fail", tokens_used=50))
        append_event(tmp_path, SwarmEvent(agent="b", event="test_run", status="pass", tokens_used=200))
        summary = summarize_events(tmp_path)
        assert summary["count"] == 3
        assert summary["by_event"]["tool_call"] == 2
        assert summary["by_event"]["test_run"] == 1
        assert summary["by_agent"]["a"] == 2
        assert summary["by_agent"]["b"] == 1
        assert summary["total_tokens"] == 350
        assert summary["failures"] == 1

    def test_since_filter(self, tmp_path):
        now = time.time()
        append_event(tmp_path, SwarmEvent(ts=now - 100, event="old"))
        append_event(tmp_path, SwarmEvent(ts=now, event="new", tokens_used=99))
        summary = summarize_events(tmp_path, since=now - 50)
        assert summary["count"] == 1
        assert summary["total_tokens"] == 99
