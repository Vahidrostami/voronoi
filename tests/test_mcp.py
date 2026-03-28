"""Tests for voronoi.mcp — validators, tools, and server."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from voronoi.mcp.validators import (
    ValidationError,
    compute_sha256,
    require_ci,
    require_effect_size,
    require_enum,
    require_file_exists,
    require_non_empty,
    require_positive_int,
    require_probability,
    sanitize_tsv_field,
    verify_data_hash,
    VALID_VALENCES,
)


# ====================================================================
# Validators
# ====================================================================

class TestRequireEnum:
    def test_valid_value(self):
        assert require_enum("positive", VALID_VALENCES, "v") == "positive"

    def test_invalid_value(self):
        with pytest.raises(ValidationError, match="must be one of"):
            require_enum("maybe", VALID_VALENCES, "v")


class TestRequirePositiveInt:
    def test_valid(self):
        assert require_positive_int(42, "n") == 42
        assert require_positive_int("100", "n") == 100

    def test_zero(self):
        with pytest.raises(ValidationError, match="must be positive"):
            require_positive_int(0, "n")

    def test_negative(self):
        with pytest.raises(ValidationError, match="must be positive"):
            require_positive_int(-5, "n")

    def test_non_numeric(self):
        with pytest.raises(ValidationError, match="must be a positive integer"):
            require_positive_int("abc", "n")


class TestRequireProbability:
    def test_valid(self):
        assert require_probability(0.5, "p") == 0.5
        assert require_probability(0.0, "p") == 0.0
        assert require_probability(1.0, "p") == 1.0

    def test_out_of_range(self):
        with pytest.raises(ValidationError, match="must be 0.0"):
            require_probability(1.5, "p")
        with pytest.raises(ValidationError, match="must be 0.0"):
            require_probability(-0.1, "p")


class TestRequireEffectSize:
    def test_valid_d(self):
        assert require_effect_size("d=0.82") == "d=0.82"

    def test_valid_r(self):
        assert require_effect_size("r=0.45") == "r=0.45"

    def test_invalid_format(self):
        with pytest.raises(ValidationError, match="must be in format"):
            require_effect_size("large")

    def test_invalid_prefix(self):
        with pytest.raises(ValidationError, match="must be in format"):
            require_effect_size("g=0.5")

    def test_negative_effect_size(self):
        assert require_effect_size("d=-0.50") == "d=-0.50"

    def test_multi_dot_rejected(self):
        with pytest.raises(ValidationError, match="must be in format"):
            require_effect_size("d=1.2.3")

    def test_no_decimal_rejected(self):
        with pytest.raises(ValidationError, match="must be in format"):
            require_effect_size("d=5")


class TestRequireCI:
    def test_valid_list(self):
        assert require_ci([0.61, 1.03]) == [0.61, 1.03]

    def test_valid_string(self):
        assert require_ci("[0.61, 1.03]") == [0.61, 1.03]

    def test_wrong_length(self):
        with pytest.raises(ValidationError, match="exactly 2"):
            require_ci([1.0])

    def test_inverted_bounds(self):
        with pytest.raises(ValidationError, match="lower bound"):
            require_ci([1.5, 0.5])


class TestFileValidation:
    def test_file_exists(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("col1,col2\n1,2\n")
        assert require_file_exists("data.csv", str(tmp_path)) == f

    def test_file_missing(self, tmp_path):
        with pytest.raises(ValidationError, match="file not found"):
            require_file_exists("missing.csv", str(tmp_path))

    def test_hash_computation(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("hello world\n")
        h = compute_sha256(f)
        assert h.startswith("sha256:")
        assert len(h) > 10

    def test_hash_verification_pass(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("test data\n")
        h = compute_sha256(f)
        verify_data_hash(f, h)  # should not raise

    def test_hash_verification_fail(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("test data\n")
        with pytest.raises(ValidationError, match="hash mismatch"):
            verify_data_hash(f, "sha256:0000")

    def test_path_traversal_rejected(self, tmp_path):
        # Create a file outside workspace
        outside = tmp_path / "outside.txt"
        outside.write_text("secret")
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        with pytest.raises(ValidationError, match="path escapes workspace"):
            require_file_exists("../outside.txt", str(workspace))


class TestRequireNonEmpty:
    def test_valid(self):
        assert require_non_empty("hello", "f") == "hello"

    def test_empty(self):
        with pytest.raises(ValidationError, match="required"):
            require_non_empty("", "f")

    def test_none(self):
        with pytest.raises(ValidationError, match="required"):
            require_non_empty(None, "f")


class TestSanitizeTsvField:
    def test_removes_tabs(self):
        assert sanitize_tsv_field("a\tb") == "a b"

    def test_removes_newlines(self):
        assert sanitize_tsv_field("a\nb") == "a b"

    def test_removes_carriage_return(self):
        assert sanitize_tsv_field("a\r\nb") == "a b"

    def test_clean_string_unchanged(self):
        assert sanitize_tsv_field("hello world") == "hello world"


# ====================================================================
# Beads Tools (mocked bd)
# ====================================================================

class TestRecordFinding:
    def test_valid_finding(self, tmp_path):
        from voronoi.mcp.tools_beads import record_finding

        # Create a data file
        data_file = tmp_path / "data" / "raw" / "results.csv"
        data_file.parent.mkdir(parents=True)
        data_file.write_text("x,y\n1,2\n3,4\n")

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch(
                 "voronoi.mcp.tools_beads.run_bd_json",
                 return_value=(0, {"notes": "TASK_TYPE:analysis\nCUSTOM:keep"}),
             ), \
             patch("voronoi.mcp.tools_beads.run_bd", return_value=(0, "ok")) as mock_run_bd:
            result = record_finding(
                task_id="bd-42",
                effect_size="d=0.82",
                ci_95=[0.61, 1.03],
                n=500,
                stat_test="Welch t-test",
                valence="positive",
                data_file="data/raw/results.csv",
            )
        assert result["status"] == "recorded"
        assert result["data_hash"].startswith("sha256:")
        assert result["effect_size"] == "d=0.82"
        notes = mock_run_bd.call_args.args[3]
        assert "TASK_TYPE:analysis" in notes
        assert "CUSTOM:keep" in notes
        assert "TYPE:finding" in notes
        assert "EFFECT_SIZE:d=0.82" in notes
        assert "DATA_FILE:data/raw/results.csv" in notes

    def test_missing_effect_size(self, tmp_path):
        from voronoi.mcp.tools_beads import record_finding

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="must be in format"):
                record_finding(
                    task_id="bd-42", effect_size="big",
                    ci_95=[0.5, 1.0], n=100,
                    stat_test="t-test", valence="positive",
                    data_file="data.csv",
                )

    def test_invalid_valence(self, tmp_path):
        from voronoi.mcp.tools_beads import record_finding

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="must be one of"):
                record_finding(
                    task_id="bd-42", effect_size="d=0.5",
                    ci_95=[0.3, 0.7], n=100,
                    stat_test="t-test", valence="maybe",
                    data_file="data.csv",
                )

    def test_data_file_missing(self, tmp_path):
        from voronoi.mcp.tools_beads import record_finding

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="file not found"):
                record_finding(
                    task_id="bd-42", effect_size="d=0.5",
                    ci_95=[0.3, 0.7], n=100,
                    stat_test="t-test", valence="positive",
                    data_file="missing.csv",
                )

    def test_hash_mismatch(self, tmp_path):
        from voronoi.mcp.tools_beads import record_finding

        f = tmp_path / "data.csv"
        f.write_text("x,y\n1,2\n")

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="hash mismatch"):
                record_finding(
                    task_id="bd-42", effect_size="d=0.5",
                    ci_95=[0.3, 0.7], n=100,
                    stat_test="t-test", valence="positive",
                    data_file="data.csv",
                    data_hash="sha256:0000",
                )


class TestPreRegister:
    def test_valid_pre_registration(self, tmp_path):
        from voronoi.mcp.tools_beads import pre_register
        from voronoi.science.gates import parse_pre_registration

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch(
                 "voronoi.mcp.tools_beads.run_bd_json",
                 return_value=(0, {"notes": "TASK_TYPE:investigation\nCUSTOM:keep"}),
             ), \
             patch("voronoi.mcp.tools_beads.run_bd", return_value=(0, "ok")) as mock_run_bd:
            result = pre_register(
                task_id="bd-10",
                hypothesis="L4 encoding outperforms L1",
                method="Between-subjects comparison",
                controls="Random baseline",
                expected_result="L4 F1 is higher than L1",
                sample_size=500,
                stat_test="Welch t-test",
                effect_size="d=0.50",
                confounds="dataset shift",
                sensitivity_plan="vary seeds and thresholds",
            )
        assert result["status"] == "pre_registered"
        assert result["sample_size"] == 500
        notes = mock_run_bd.call_args.args[3]
        parsed = parse_pre_registration(notes)
        assert "CUSTOM:keep" in notes
        assert parsed.hypothesis == "L4 encoding outperforms L1"
        assert parsed.method == "Between-subjects comparison"
        assert parsed.controls == "Random baseline"
        assert parsed.expected_result == "L4 F1 is higher than L1"
        assert parsed.confounds == "dataset shift"
        assert parsed.stat_test == "Welch t-test"
        assert parsed.sample_size == "500"
        assert parsed.power_analysis == "d=0.50"
        assert parsed.sensitivity_plan == "vary seeds and thresholds"

    def test_missing_hypothesis(self, tmp_path):
        from voronoi.mcp.tools_beads import pre_register

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="required"):
                pre_register(
                    task_id="bd-10", hypothesis="",
                    method="test", controls="none",
                    expected_result="wins",
                    sample_size=100, stat_test="t-test",
                    effect_size="d=0.50",
                )


class TestCloseTask:
    def test_close_with_missing_produces(self, tmp_path):
        from voronoi.mcp.tools_beads import close_task

        task_data = {"notes": "PRODUCES:output/results.json"}
        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_beads.run_bd_json",
                   return_value=(0, task_data)):
            with pytest.raises(ValidationError, match="PRODUCES artifact missing"):
                close_task("bd-42", "done")

    def test_close_with_produces_present(self, tmp_path):
        from voronoi.mcp.tools_beads import close_task

        (tmp_path / "output").mkdir()
        (tmp_path / "output" / "results.json").write_text("{}")

        task_data = {"notes": "PRODUCES:output/results.json"}
        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_beads.run_bd_json",
                   return_value=(0, task_data)), \
             patch("voronoi.mcp.tools_beads.run_bd",
                   return_value=(0, "closed")):
            result = close_task("bd-42", "done")
        assert result["status"] == "closed"


class TestStatReview:
    def test_valid_review(self, tmp_path):
        from voronoi.mcp.tools_beads import stat_review

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch(
                 "voronoi.mcp.tools_beads.run_bd_json",
                 return_value=(0, {"notes": "TYPE:finding\nEFFECT_SIZE:d=0.82\nCUSTOM:keep"}),
             ), \
             patch("voronoi.mcp.tools_beads.run_bd", return_value=(0, "ok")) as mock_run_bd:
            result = stat_review(
                finding_id="bd-50",
                verdict="APPROVED",
                interpretation="Encoding helps detection",
                practical_significance="large",
            )
        assert result["verdict"] == "APPROVED"
        notes = mock_run_bd.call_args.args[3]
        assert "CUSTOM:keep" in notes
        assert "EFFECT_SIZE:d=0.82" in notes
        assert "STAT_REVIEW:APPROVED" in notes
        assert "PRACTICAL_SIGNIFICANCE:large" in notes

    def test_invalid_verdict(self, tmp_path):
        from voronoi.mcp.tools_beads import stat_review

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="must be one of"):
                stat_review(finding_id="bd-50", verdict="MAYBE")


# ====================================================================
# .swarm/ Tools
# ====================================================================

class TestWriteCheckpoint:
    def test_valid_checkpoint(self, tmp_path):
        from voronoi.mcp.tools_swarm import write_checkpoint

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            result = write_checkpoint(
                cycle=5, phase="investigating",
                total_tasks=12, closed_tasks=3,
                context_window_remaining_pct=0.65,
            )
        assert result["status"] == "written"
        assert result["cycle"] == 5

        cp = json.loads((tmp_path / ".swarm" / "orchestrator-checkpoint.json").read_text())
        assert cp["cycle"] == 5
        assert cp["phase"] == "investigating"
        assert cp["context_window_remaining_pct"] == 0.65

    def test_preserves_existing_checkpoint_fields(self, tmp_path):
        from voronoi.mcp.tools_swarm import write_checkpoint

        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "orchestrator-checkpoint.json").write_text(json.dumps({
            "cycle": 2,
            "phase": "starting",
            "mode": "experiment",
            "rigor": "scientific",
            "hypotheses_summary": "H1:testing",
            "total_tasks": 4,
            "closed_tasks": 1,
            "criteria_status": {"SC1": True},
            "tokens_this_cycle": 123,
            "tokens_cumulative": 456,
            "context_window_remaining_pct": 0.4,
        }))

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            write_checkpoint(cycle=6, phase="investigating", total_tasks=7)

        cp = json.loads((swarm / "orchestrator-checkpoint.json").read_text())
        assert cp["cycle"] == 6
        assert cp["phase"] == "investigating"
        assert cp["total_tasks"] == 7
        assert cp["mode"] == "experiment"
        assert cp["rigor"] == "scientific"
        assert cp["criteria_status"] == {"SC1": True}
        assert cp["tokens_this_cycle"] == 123
        assert cp["tokens_cumulative"] == 456
        assert cp["context_window_remaining_pct"] == 0.4

    def test_invalid_phase(self, tmp_path):
        from voronoi.mcp.tools_swarm import write_checkpoint

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="must be one of"):
                write_checkpoint(cycle=1, phase="dancing")

    def test_invalid_context_pct(self, tmp_path):
        from voronoi.mcp.tools_swarm import write_checkpoint

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="must be 0.0"):
                write_checkpoint(cycle=1, phase="starting",
                                 context_window_remaining_pct=1.5)


class TestUpdateBeliefMap:
    def test_create_hypothesis(self, tmp_path):
        from voronoi.mcp.tools_swarm import update_belief_map

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_swarm.run_bd_json", return_value=(0, {"id": "bd-15"})):
            result = update_belief_map(
                hypothesis_id="H1",
                name="Encoding helps detection",
                posterior=0.7,
                evidence_ids=["bd-15"],
            )
        assert result["posterior"] == 0.7

        bm = json.loads((tmp_path / ".swarm" / "belief-map.json").read_text())
        hyps = bm["hypotheses"]
        assert isinstance(hyps, list)
        h1 = next(h for h in hyps if h["id"] == "H1")
        assert h1["posterior"] == 0.7
        assert h1["evidence"] == ["bd-15"]
        assert h1["prior"] == 0.7

    def test_update_existing(self, tmp_path):
        from voronoi.mcp.tools_swarm import update_belief_map

        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "belief-map.json").write_text(json.dumps({
            "hypotheses": [{"id": "H1", "name": "test", "posterior": 0.5}]
        }))

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            update_belief_map(hypothesis_id="H1", posterior=0.9)

        bm = json.loads((swarm / "belief-map.json").read_text())
        hyps = bm["hypotheses"]
        h1 = next(h for h in hyps if h["id"] == "H1")
        assert h1["posterior"] == 0.9
        assert h1["name"] == "test"  # preserved

    def test_invalid_posterior(self, tmp_path):
        from voronoi.mcp.tools_swarm import update_belief_map

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="must be 0.0"):
                update_belief_map(hypothesis_id="H1", posterior=1.5)

    def test_unknown_evidence_rejected(self, tmp_path):
        from voronoi.mcp.tools_swarm import update_belief_map

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_swarm.run_bd_json", return_value=(1, None)):
            with pytest.raises(ValidationError, match="Unknown evidence task"):
                update_belief_map(hypothesis_id="H1", evidence_ids=["bd-404"])


class TestUpdateSuccessCriteria:
    def test_create_criterion(self, tmp_path):
        from voronoi.mcp.tools_swarm import update_success_criteria

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            result = update_success_criteria(
                criteria_id="SC1",
                description="L4 outperforms L1 on F1",
                met=False,
            )
        assert result["met"] is False

        sc = json.loads((tmp_path / ".swarm" / "success-criteria.json").read_text())
        assert len(sc) == 1
        assert sc[0]["id"] == "SC1"

    def test_update_criterion(self, tmp_path):
        from voronoi.mcp.tools_swarm import update_success_criteria

        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "success-criteria.json").write_text(json.dumps([
            {"id": "SC1", "description": "test", "met": False}
        ]))

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            update_success_criteria(criteria_id="SC1", met=True, evidence="bd-42")

        sc = json.loads((swarm / "success-criteria.json").read_text())
        assert sc[0]["met"] is True
        assert sc[0]["evidence"] == "bd-42"


class TestLogExperiment:
    def test_valid_log(self, tmp_path):
        from voronoi.mcp.tools_swarm import log_experiment

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            result = log_experiment(
                task_id="bd-42", branch="agent-pilot",
                metric="MBRS", value="0.71",
                experiment_status="keep",
                description="Pilot run",
            )
        assert result["status"] == "logged"

        tsv = (tmp_path / ".swarm" / "experiments.tsv").read_text()
        assert "bd-42" in tsv
        assert "agent-pilot" in tsv
        lines = tsv.strip().split("\n")
        assert len(lines) == 2  # header + 1 row

    def test_invalid_status(self, tmp_path):
        from voronoi.mcp.tools_swarm import log_experiment

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="must be one of"):
                log_experiment(
                    task_id="bd-42", branch="x",
                    metric="M", value="1",
                    experiment_status="awesome",
                )

    def test_append_multiple(self, tmp_path):
        from voronoi.mcp.tools_swarm import log_experiment

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            log_experiment("bd-1", "b1", "M", "1", "keep")
            log_experiment("bd-2", "b2", "M", "2", "discard")

        lines = (tmp_path / ".swarm" / "experiments.tsv").read_text().strip().split("\n")
        assert len(lines) == 3  # header + 2 rows

    def test_tsv_injection_sanitized(self, tmp_path):
        from voronoi.mcp.tools_swarm import log_experiment

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            log_experiment(
                task_id="bd-1", branch="b1", metric="M", value="1",
                experiment_status="keep",
                description="has\ttabs\nand\nnewlines",
            )

        tsv = (tmp_path / ".swarm" / "experiments.tsv").read_text()
        lines = tsv.strip().split("\n")
        assert len(lines) == 2  # header + 1 row (no injection)
        assert "\t\t" not in lines[1].replace("\t", "", 6)  # only 6 tab separators


# ====================================================================
# MCP Server Protocol
# ====================================================================

class TestMCPServer:
    def test_initialize(self):
        from voronoi.mcp.server import _build_registry, _process_message
        _build_registry()

        response = _process_message({
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
        })
        assert response["id"] == 1
        assert "voronoi-mcp" in response["result"]["serverInfo"]["name"]

    def test_tools_list(self):
        from voronoi.mcp.server import _build_registry, _process_message
        _build_registry()

        response = _process_message({
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
        })
        tools = response["result"]["tools"]
        names = {t["name"] for t in tools}
        assert "voronoi_record_finding" in names
        assert "voronoi_pre_register" in names
        assert "voronoi_write_checkpoint" in names
        assert "voronoi_update_belief_map" in names
        assert len(tools) >= 10

    def test_tools_list_includes_required(self):
        from voronoi.mcp.server import _build_registry, _process_message
        _build_registry()

        response = _process_message({
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
        })
        tools = {t["name"]: t for t in response["result"]["tools"]}
        finding = tools["voronoi_record_finding"]
        assert "required" in finding["inputSchema"]
        assert "task_id" in finding["inputSchema"]["required"]
        assert "effect_size" in finding["inputSchema"]["required"]
        # Optional fields should not be in required
        assert "data_hash" not in finding["inputSchema"]["required"]
        pre_register = tools["voronoi_pre_register"]
        assert "expected_result" in pre_register["inputSchema"]["required"]
        assert "effect_size" in pre_register["inputSchema"]["required"]
        checkpoint = tools["voronoi_write_checkpoint"]
        assert "mode" in checkpoint["inputSchema"]["properties"]
        assert "criteria_status" in checkpoint["inputSchema"]["properties"]

    def test_tools_call_validation_error(self, tmp_path):
        from voronoi.mcp.server import _build_registry, _process_message
        _build_registry()

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            response = _process_message({
                "jsonrpc": "2.0", "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "voronoi_record_finding",
                    "arguments": {
                        "task_id": "bd-1",
                        "effect_size": "big",  # invalid
                        "ci_95": "[0.5, 1.0]",
                        "n": 100,
                        "stat_test": "t-test",
                        "valence": "positive",
                        "data_file": "data.csv",
                    }
                }
            })
        assert response["result"]["isError"] is True
        assert "Validation error" in response["result"]["content"][0]["text"]

    def test_unknown_tool(self):
        from voronoi.mcp.server import _build_registry, _process_message
        _build_registry()

        response = _process_message({
            "jsonrpc": "2.0", "id": 4,
            "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}}
        })
        assert response["result"]["isError"] is True

    def test_notification_no_response(self):
        from voronoi.mcp.server import _build_registry, _process_message
        _build_registry()

        response = _process_message({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {}
        })
        assert response is None

    def test_unknown_method(self):
        from voronoi.mcp.server import _build_registry, _process_message
        _build_registry()

        response = _process_message({
            "jsonrpc": "2.0", "id": 5,
            "method": "unknown/method",
            "params": {}
        })
        assert "error" in response
        assert response["error"]["code"] == -32601


# ====================================================================
# MCP Config Integration
# ====================================================================

class TestMCPConfigIntegration:
    def test_patch_swarm_config_writes_mcp(self, tmp_path):
        """Dispatcher's _patch_swarm_config writes .github/mcp-config.json."""
        from voronoi.server.dispatcher import DispatcherConfig, InvestigationDispatcher

        config = DispatcherConfig(base_dir=tmp_path)
        d = InvestigationDispatcher(config, send_message=lambda m: None)

        (tmp_path / ".swarm-config.json").write_text("{}")
        (tmp_path / ".github").mkdir()

        d._patch_swarm_config(tmp_path, "scientific")

        mcp_path = tmp_path / ".github" / "mcp-config.json"
        assert mcp_path.exists()
        mcp = json.loads(mcp_path.read_text())
        assert "voronoi" in mcp["mcpServers"]
        assert mcp["mcpServers"]["voronoi"]["command"] == sys.executable
        assert mcp["mcpServers"]["voronoi"]["args"] == ["-m", "voronoi.mcp"]

    def test_init_writes_mcp_config(self, tmp_path):
        """voronoi init should write .github/mcp-config.json."""
        from voronoi.cli import _current_python_command, _write_mcp_config

        mcp_config_path = tmp_path / ".github" / "mcp-config.json"
        mcp_config_path.parent.mkdir(parents=True)

        _write_mcp_config(mcp_config_path.parent)

        data = json.loads(mcp_config_path.read_text())
        assert "voronoi" in data["mcpServers"]
        assert data["mcpServers"]["voronoi"]["command"] == _current_python_command()
        assert data["mcpServers"]["voronoi"]["args"] == ["-m", "voronoi.mcp"]
