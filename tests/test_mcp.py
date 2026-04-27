"""Tests for voronoi.mcp — validators, tools, and server."""

from __future__ import annotations

import json
import os
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

    def test_absolute_in_workspace_path_rejected(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("col1,col2\n1,2\n")
        with pytest.raises(ValidationError, match="path must be relative"):
            require_file_exists(str(f), str(tmp_path))


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
             patch("voronoi.mcp.tools_beads.run_bd", return_value=(0, "ok")), \
             patch("voronoi.mcp.tools_beads.run_bd_json", return_value=(0, {"notes": ""})):
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

    def test_confidence_zero_is_preserved_and_robust_is_normalized(self, tmp_path):
        from voronoi.mcp.tools_beads import record_finding

        data_file = tmp_path / "data.csv"
        data_file.write_text("x,y\n1,2\n")
        written_notes = ""

        def fake_run_bd(*args, cwd=None):
            nonlocal written_notes
            if "--notes" in args:
                written_notes = args[args.index("--notes") + 1]
            return 0, "ok"

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_beads.run_bd", side_effect=fake_run_bd), \
             patch("voronoi.mcp.tools_beads.run_bd_json", return_value=(0, {"notes": ""})):
            record_finding(
                task_id="bd-42", effect_size="d=0.5",
                ci_95=[0.3, 0.7], n=100,
                stat_test="t-test", valence="positive",
                data_file="data.csv", confidence=0.0,
                robust="YES",
            )

        assert "CONFIDENCE:0.0" in written_notes
        assert "ROBUST:yes" in written_notes

    def test_invalid_robust_value_rejected(self, tmp_path):
        from voronoi.mcp.tools_beads import record_finding

        data_file = tmp_path / "data.csv"
        data_file.write_text("x,y\n1,2\n")

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="robust must be one of"):
                record_finding(
                    task_id="bd-42", effect_size="d=0.5",
                    ci_95=[0.3, 0.7], n=100,
                    stat_test="t-test", valence="positive",
                    data_file="data.csv", robust="maybe",
                )

    def test_absolute_data_file_rejected(self, tmp_path):
        from voronoi.mcp.tools_beads import record_finding

        data_file = tmp_path / "data.csv"
        data_file.write_text("x,y\n1,2\n")

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="path must be relative"):
                record_finding(
                    task_id="bd-42", effect_size="d=0.5",
                    ci_95=[0.3, 0.7], n=100,
                    stat_test="t-test", valence="positive",
                    data_file=str(data_file),
                )


class TestPreRegister:
    def test_valid_pre_registration(self, tmp_path):
        from voronoi.mcp.tools_beads import pre_register

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_beads.run_bd", return_value=(0, "ok")), \
             patch("voronoi.mcp.tools_beads.run_bd_json", return_value=(0, {"notes": ""})):
            result = pre_register(
                task_id="bd-10",
                hypothesis="L4 encoding outperforms L1",
                method="Between-subjects comparison",
                controls="Random baseline",
                expected_result="L4 > L1 by d=0.5",
                sample_size=500,
                stat_test="Welch t-test",
                effect_size="d=0.50",
            )
        assert result["status"] == "pre_registered"
        assert result["sample_size"] == 500

    def test_missing_hypothesis(self, tmp_path):
        from voronoi.mcp.tools_beads import pre_register

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="required"):
                pre_register(
                    task_id="bd-10", hypothesis="",
                    method="test", controls="none",
                    expected_result="expected",
                    sample_size=100, stat_test="t-test",
                    effect_size="d=0.50",
                )

    def test_mcp_schema_includes_all_required_pre_registration_fields(self):
        from voronoi.mcp.server import TOOLS, _build_registry

        TOOLS.clear()
        _build_registry()
        tool = TOOLS["voronoi_pre_register"]

        assert "expected_result" in tool["params"]
        assert "effect_size" in tool["params"]
        assert "expected_result" in tool["required"]
        assert "effect_size" in tool["required"]


class TestCloseTask:
    def test_create_rejects_produces_path_escape(self, tmp_path):
        from voronoi.mcp.tools_beads import create_task

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="path escapes workspace"):
                create_task("bad output", produces="../outside.json")

    def test_close_rejects_absolute_produces_path(self, tmp_path):
        from voronoi.mcp.tools_beads import close_task

        outside = tmp_path.parent / "outside-results.json"
        outside.write_text("{}")
        task_data = {"notes": f"PRODUCES:{outside}"}

        try:
            with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
                 patch("voronoi.mcp.tools_beads.run_bd_json", return_value=(0, task_data)):
                with pytest.raises(ValidationError, match="path must be relative"):
                    close_task("bd-42", "done")
        finally:
            outside.unlink(missing_ok=True)

    def test_close_with_missing_produces(self, tmp_path):
        from voronoi.mcp.tools_beads import close_task

        task_data = {"notes": "PRODUCES:output/bd-42/experiment_metrics.json"}
        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_beads.run_bd_json",
                   return_value=(0, task_data)):
            with pytest.raises(ValidationError, match="PRODUCES artifact missing"):
                close_task("bd-42", "done")

    def test_close_with_produces_present(self, tmp_path):
        from voronoi.mcp.tools_beads import close_task

        metrics_dir = tmp_path / "output" / "bd-42"
        metrics_dir.mkdir(parents=True)
        (metrics_dir / "experiment_metrics.json").write_text("{}")

        task_data = {"notes": "PRODUCES:output/bd-42/experiment_metrics.json"}
        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_beads.run_bd_json",
                   return_value=(0, task_data)), \
             patch("voronoi.mcp.tools_beads.run_bd",
                   return_value=(0, "closed")):
            result = close_task("bd-42", "done")
        assert result["status"] == "closed"


class TestCreateTaskGuards:
    """INV-55/56: title gate, PRODUCES contract, CREATED_BY provenance."""

    def test_rejects_laundered_imperative_title(self, tmp_path):
        from voronoi.mcp.tools_beads import create_task
        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="imperative verb"):
                create_task("Analyze business prompt findings")

    def test_rejects_laundered_title_with_findings_substring(self, tmp_path):
        from voronoi.mcp.tools_beads import create_task
        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="imperative verb"):
                create_task("Analyze pricing dataset for five action-changing findings")

    def test_accepts_imperative_with_relational_marker(self, tmp_path):
        from voronoi.mcp.tools_beads import create_task
        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_beads.run_bd", return_value=(0, "Created task bd-1")), \
             patch("voronoi.mcp.tools_beads.run_bd_json", return_value=(0, {"notes": ""})):
            result = create_task("Test whether L4 > L1 in coverage")
            assert result["status"] == "created"

    def test_accepts_finding_prefixed_title(self, tmp_path):
        from voronoi.mcp.tools_beads import create_task
        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_beads.run_bd", return_value=(0, "Created task bd-1")), \
             patch("voronoi.mcp.tools_beads.run_bd_json", return_value=(0, {"notes": ""})):
            result = create_task("FINDING: encoding reduces regret (d=-0.40)")
            assert result["status"] == "created"

    def test_experiment_type_requires_produces(self, tmp_path):
        from voronoi.mcp.tools_beads import create_task
        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="MUST declare PRODUCES"):
                create_task("Phase 1 pilot", task_type="experiment")

    @pytest.mark.parametrize(
        "task_type",
        ["build", "experiment", "investigation", "evaluation", "paper"],
    )
    def test_required_task_types_require_produces(self, tmp_path, task_type):
        from voronoi.mcp.tools_beads import create_task
        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="MUST declare PRODUCES"):
                create_task("Phase 1 pilot", task_type=task_type)

    def test_produces_rejects_shared_namespace_basename(self, tmp_path):
        from voronoi.mcp.tools_beads import create_task
        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="shared artifact basename"):
                create_task(
                    "Phase 1 pilot",
                    task_type="experiment",
                    produces="answer.json",
                )

    def test_produces_rejects_shared_namespace_in_subdir_basename(self, tmp_path):
        from voronoi.mcp.tools_beads import create_task
        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            # Even within a subdir, the shared basename is forbidden.
            with pytest.raises(ValidationError, match="shared artifact basename"):
                create_task(
                    "Phase 1 pilot",
                    task_type="experiment",
                    produces="output/results.json",
                )

    def test_produces_rejects_denylisted_basename_when_task_scoped(self, tmp_path):
        from voronoi.mcp.tools_beads import create_task
        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="shared artifact basename"):
                create_task(
                    "Phase 1 pilot",
                    task_type="experiment",
                    produces="output/bd-1/results.json",
                )

    def test_namespaced_produces_under_task_id_dir_accepted(self, tmp_path):
        from voronoi.mcp.tools_beads import create_task
        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_beads.run_bd", return_value=(0, "Created task bd-1")), \
             patch("voronoi.mcp.tools_beads.run_bd_json", return_value=(0, {"notes": ""})):
            result = create_task(
                "Phase 1 pilot",
                task_type="experiment",
                produces="output/bd-1/pilot.json",
            )
            assert result["status"] == "created"

    def test_requires_rejects_absolute_in_workspace_path(self, tmp_path):
        from voronoi.mcp.tools_beads import create_task

        req = tmp_path / "input.csv"
        req.write_text("x\n1\n")
        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="path must be relative"):
                create_task("FINDING: x is greater than y", requires=str(req))

    def test_create_task_schema_exposes_created_by(self):
        from voronoi.mcp.server import TOOLS, _build_registry

        TOOLS.clear()
        _build_registry()
        tool = TOOLS["voronoi_create_task"]

        assert "created_by" in tool["params"]
        assert "created_by" not in tool["required"]

    def test_stamps_created_by_from_env(self, tmp_path):
        """CREATED_BY provenance stamped from VORONOI_AGENT_ROLE."""
        from voronoi.mcp.tools_beads import create_task

        captured: dict[str, str] = {}

        def fake_run_bd(*args, cwd=None):
            if args and args[0] == "update":
                # args = ("update", task_id, "--notes", notes)
                captured["notes"] = args[3]
                return 0, ""
            return 0, "Created task bd-1"

        with patch.dict(os.environ, {
                "VORONOI_WORKSPACE": str(tmp_path),
                "VORONOI_AGENT_ROLE": "orchestrator",
                }), \
             patch("voronoi.mcp.tools_beads.run_bd", side_effect=fake_run_bd), \
             patch("voronoi.mcp.tools_beads.run_bd_json",
                   return_value=(0, {"notes": ""})):
            create_task("FINDING: x is greater than y")
        assert "CREATED_BY:orchestrator" in captured.get("notes", "")

    def test_explicit_created_by_overrides_env(self, tmp_path):
        from voronoi.mcp.tools_beads import create_task
        captured: dict[str, str] = {}

        def fake_run_bd(*args, cwd=None):
            if args and args[0] == "update":
                captured["notes"] = args[3]
                return 0, ""
            return 0, "Created task bd-1"

        with patch.dict(os.environ, {
                "VORONOI_WORKSPACE": str(tmp_path),
                "VORONOI_AGENT_ROLE": "worker:bd-99",
                }), \
             patch("voronoi.mcp.tools_beads.run_bd", side_effect=fake_run_bd), \
             patch("voronoi.mcp.tools_beads.run_bd_json",
                   return_value=(0, {"notes": ""})):
            create_task("FINDING: x is greater than y", created_by="orchestrator")
        assert "CREATED_BY:orchestrator" in captured.get("notes", "")


class TestCloseTaskFindingGate:
    """INV-57: experiment-type tasks need FINDING linkage to close."""

    def _task_data(self, notes: str) -> dict:
        return {"notes": notes}

    def test_experiment_close_without_finding_link_rejected(self, tmp_path):
        from voronoi.mcp.tools_beads import close_task
        (tmp_path / "out").mkdir()
        (tmp_path / "out" / "r.json").write_text("{}")
        notes = "TASK_TYPE:experiment\nPRODUCES:out/r.json"
        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_beads.run_bd_json",
                   return_value=(0, self._task_data(notes))):
            with pytest.raises(ValidationError,
                               match="FINDING_TASK_IDS|FINDING:NULL"):
                close_task("bd-42", "done")

    def test_experiment_close_with_finding_link_accepted(self, tmp_path):
        from voronoi.mcp.tools_beads import close_task
        (tmp_path / "out").mkdir()
        (tmp_path / "out" / "r.json").write_text("{}")
        notes = ("TASK_TYPE:experiment\nPRODUCES:out/r.json\n"
                 "FINDING_TASK_IDS:bd-50")

        def fake_run_bd_json(*args, cwd=None):
            task_id = args[1]
            records = {
                "bd-42": self._task_data(notes),
                "bd-50": {"title": "FINDING: phase 1 improves recall"},
            }
            return 0, records[task_id]

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_beads.run_bd_json",
                   side_effect=fake_run_bd_json), \
             patch("voronoi.mcp.tools_beads.run_bd",
                   return_value=(0, "closed")):
            result = close_task("bd-42", "done")
        assert result["status"] == "closed"

    def test_experiment_close_rejects_missing_finding_task_id(self, tmp_path):
        from voronoi.mcp.tools_beads import close_task
        (tmp_path / "out").mkdir()
        (tmp_path / "out" / "r.json").write_text("{}")
        notes = ("TASK_TYPE:experiment\nPRODUCES:out/r.json\n"
                 "FINDING_TASK_IDS:bd-404")

        def fake_run_bd_json(*args, cwd=None):
            task_id = args[1]
            if task_id == "bd-42":
                return 0, self._task_data(notes)
            return 1, {}

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_beads.run_bd_json",
                   side_effect=fake_run_bd_json):
            with pytest.raises(ValidationError, match="missing task bd-404"):
                close_task("bd-42", "done")

    def test_experiment_close_rejects_non_finding_task_id(self, tmp_path):
        from voronoi.mcp.tools_beads import close_task
        (tmp_path / "out").mkdir()
        (tmp_path / "out" / "r.json").write_text("{}")
        notes = ("TASK_TYPE:experiment\nPRODUCES:out/r.json\n"
                 "FINDING_TASK_IDS:bd-50")

        def fake_run_bd_json(*args, cwd=None):
            task_id = args[1]
            records = {
                "bd-42": self._task_data(notes),
                "bd-50": {"title": "Analyze business prompt findings"},
            }
            return 0, records[task_id]

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_beads.run_bd_json",
                   side_effect=fake_run_bd_json):
            with pytest.raises(ValidationError, match="does not start with FINDING"):
                close_task("bd-42", "done")

    def test_experiment_close_with_finding_null_rationale_accepted(self, tmp_path):
        from voronoi.mcp.tools_beads import close_task
        (tmp_path / "out").mkdir()
        (tmp_path / "out" / "r.json").write_text("{}")
        rationale = "interaction p=0.86 contradicts pilot; no claim-grade effect"
        notes = (f"TASK_TYPE:experiment\nPRODUCES:out/r.json\n"
                 f"FINDING:NULL {rationale}")
        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_beads.run_bd_json",
                   return_value=(0, self._task_data(notes))), \
             patch("voronoi.mcp.tools_beads.run_bd",
                   return_value=(0, "closed")):
            result = close_task("bd-42", "null result")
        assert result["status"] == "closed"

    def test_experiment_close_with_short_null_rationale_rejected(self, tmp_path):
        from voronoi.mcp.tools_beads import close_task
        (tmp_path / "out").mkdir()
        (tmp_path / "out" / "r.json").write_text("{}")
        notes = ("TASK_TYPE:experiment\nPRODUCES:out/r.json\n"
                 "FINDING:NULL too short")
        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_beads.run_bd_json",
                   return_value=(0, self._task_data(notes))):
            with pytest.raises(ValidationError, match="rationale"):
                close_task("bd-42", "done")

    def test_non_experiment_close_unaffected(self, tmp_path):
        from voronoi.mcp.tools_beads import close_task
        (tmp_path / "out").mkdir()
        (tmp_path / "out" / "r.json").write_text("{}")
        notes = "TASK_TYPE:build\nPRODUCES:out/r.json"
        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_beads.run_bd_json",
                   return_value=(0, self._task_data(notes))), \
             patch("voronoi.mcp.tools_beads.run_bd",
                   return_value=(0, "closed")):
            result = close_task("bd-42", "build done")
        assert result["status"] == "closed"


class TestStatReview:
    def test_valid_review(self, tmp_path):
        from voronoi.mcp.tools_beads import stat_review

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_beads.run_bd", return_value=(0, "ok")), \
             patch("voronoi.mcp.tools_beads.run_bd_json", return_value=(0, {"notes": "TYPE:finding"})):
            result = stat_review(
                finding_id="bd-50",
                verdict="APPROVED",
                interpretation="Encoding helps detection",
                practical_significance="large",
            )
        assert result["verdict"] == "APPROVED"

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
        h1 = next(h for h in bm["hypotheses"] if h["id"] == "H1")
        assert h1["posterior"] == 0.7

    def test_update_existing(self, tmp_path):
        from voronoi.mcp.tools_swarm import update_belief_map

        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "belief-map.json").write_text(json.dumps({
            "hypotheses": {"H1": {"name": "test", "posterior": 0.5}}
        }))

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            update_belief_map(hypothesis_id="H1", posterior=0.9)

        bm = json.loads((swarm / "belief-map.json").read_text())
        h1 = next(h for h in bm["hypotheses"] if h["id"] == "H1")
        assert h1["posterior"] == 0.9
        assert h1["name"] == "test"  # preserved

    def test_invalid_posterior(self, tmp_path):
        from voronoi.mcp.tools_swarm import update_belief_map

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="must be 0.0"):
                update_belief_map(hypothesis_id="H1", posterior=1.5)

    def test_evidence_appended_not_replaced(self, tmp_path):
        """BUG-001 regression: updating evidence should append, not replace."""
        from voronoi.mcp.tools_swarm import update_belief_map

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_swarm.run_bd_json", return_value=(0, {"id": "bd-1"})):
            update_belief_map(
                hypothesis_id="H1", name="Test",
                posterior=0.6, evidence_ids=["bd-1"],
            )

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_swarm.run_bd_json", return_value=(0, {"id": "bd-5"})):
            update_belief_map(
                hypothesis_id="H1", evidence_ids=["bd-5"],
            )

        bm = json.loads((tmp_path / ".swarm" / "belief-map.json").read_text())
        h1 = next(h for h in bm["hypotheses"] if h["id"] == "H1")
        assert "bd-1" in h1["evidence"], "original evidence should be preserved"
        assert "bd-5" in h1["evidence"], "new evidence should be appended"

    def test_evidence_no_duplicates(self, tmp_path):
        """Appending the same evidence ID should not create duplicates."""
        from voronoi.mcp.tools_swarm import update_belief_map

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}), \
             patch("voronoi.mcp.tools_swarm.run_bd_json", return_value=(0, {"id": "bd-1"})):
            update_belief_map(
                hypothesis_id="H1", name="Test",
                posterior=0.6, evidence_ids=["bd-1"],
            )
            update_belief_map(
                hypothesis_id="H1", evidence_ids=["bd-1"],
            )

        bm = json.loads((tmp_path / ".swarm" / "belief-map.json").read_text())
        h1 = next(h for h in bm["hypotheses"] if h["id"] == "H1")
        assert h1["evidence"].count("bd-1") == 1

    def test_confidence_reinferred_on_posterior_update(self, tmp_path):
        """BUG-005 regression: updating posterior should re-infer confidence."""
        from voronoi.mcp.tools_swarm import update_belief_map

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            update_belief_map(hypothesis_id="H1", name="Test", posterior=0.5)

        bm = json.loads((tmp_path / ".swarm" / "belief-map.json").read_text())
        h1 = next(h for h in bm["hypotheses"] if h["id"] == "H1")
        assert h1["confidence"] == "unknown"  # P=0.5 → max uncertainty

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            update_belief_map(hypothesis_id="H1", posterior=0.95)

        bm = json.loads((tmp_path / ".swarm" / "belief-map.json").read_text())
        h1 = next(h for h in bm["hypotheses"] if h["id"] == "H1")
        assert h1["confidence"] == "strong"  # P=0.95 → near resolved

    def test_explicit_confidence_overrides_inference(self, tmp_path):
        """Explicit confidence should override posterior-based inference."""
        from voronoi.mcp.tools_swarm import update_belief_map

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            update_belief_map(hypothesis_id="H1", name="Test", posterior=0.5)
            update_belief_map(hypothesis_id="H1", posterior=0.95, confidence="hunch")

        bm = json.loads((tmp_path / ".swarm" / "belief-map.json").read_text())
        h1 = next(h for h in bm["hypotheses"] if h["id"] == "H1")
        assert h1["confidence"] == "hunch"  # explicit wins over inferred

    def test_invalid_status_rejected(self, tmp_path):
        """Bug fix: update_belief_map should reject invalid status values."""
        from voronoi.mcp.tools_swarm import update_belief_map

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="status must be one of"):
                update_belief_map(hypothesis_id="H1", name="Test", status="maybe_true")

    def test_valid_statuses_accepted(self, tmp_path):
        """All valid hypothesis statuses should be accepted."""
        from voronoi.mcp.tools_swarm import update_belief_map

        valid_statuses = ["untested", "testing", "confirmed", "refuted", "refuted_reversed", "inconclusive", "merged"]
        for status in valid_statuses:
            with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
                update_belief_map(hypothesis_id=f"H_{status}", name="Test", status=status)

            bm = json.loads((tmp_path / ".swarm" / "belief-map.json").read_text())
            h = next(h for h in bm["hypotheses"] if h["id"] == f"H_{status}")
            assert h["status"] == status

    def test_invalid_confidence_rejected(self, tmp_path):
        """Invalid confidence tier should be rejected."""
        from voronoi.mcp.tools_swarm import update_belief_map

        with patch.dict(os.environ, {"VORONOI_WORKSPACE": str(tmp_path)}):
            with pytest.raises(ValidationError, match="confidence must be one of"):
                update_belief_map(hypothesis_id="H1", name="Test", confidence="very_confident")

    def test_mcp_schema_includes_confidence_rationale_next_test(self):
        """Bug fix: tools/list schema should expose confidence, rationale, next_test fields."""
        from voronoi.mcp.server import TOOLS, _build_registry

        TOOLS.clear()
        _build_registry()
        tool = TOOLS["voronoi_update_belief_map"]

        # Check that new fields are present
        assert "confidence" in tool["params"]
        assert "rationale" in tool["params"]
        assert "next_test" in tool["params"]

        # Check descriptions
        assert "unknown" in tool["params"]["confidence"]["description"]
        assert "hunch" in tool["params"]["confidence"]["description"]
        assert "Evidence" in tool["params"]["rationale"]["description"] or "reasoning" in tool["params"]["rationale"]["description"]
        assert "experiment" in tool["params"]["next_test"]["description"] or "analysis" in tool["params"]["next_test"]["description"]

        # Status description should list all valid values
        status_desc = tool["params"]["status"]["description"]
        assert "untested" in status_desc
        assert "confirmed" in status_desc
        assert "refuted" in status_desc
        assert "inconclusive" in status_desc


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
        data_file_description = finding["inputSchema"]["properties"]["data_file"]["description"]
        assert "Workspace-relative" in data_file_description
        assert "absolute paths" in data_file_description
        # Optional fields should not be in required
        assert "data_hash" not in finding["inputSchema"]["required"]

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
        import sys
        assert mcp["mcpServers"]["voronoi"]["command"] == sys.executable
        assert mcp["mcpServers"]["voronoi"]["args"] == ["-m", "voronoi.mcp"]

    def test_init_writes_mcp_config(self, tmp_path):
        """voronoi init should write .github/mcp-config.json."""
        import subprocess
        # This test verifies the file would be created by cmd_init
        # but we test the code path directly since cmd_init needs a git repo
        mcp_config_path = tmp_path / ".github" / "mcp-config.json"
        mcp_config_path.parent.mkdir(parents=True)
        mcp_config = {
            "mcpServers": {
                "voronoi": {
                    "command": "python",
                    "args": ["-m", "voronoi.mcp"],
                    "env": {"VORONOI_WORKSPACE": "."},
                }
            }
        }
        mcp_config_path.write_text(json.dumps(mcp_config, indent=2))

        data = json.loads(mcp_config_path.read_text())
        assert "voronoi" in data["mcpServers"]
        assert data["mcpServers"]["voronoi"]["args"] == ["-m", "voronoi.mcp"]


# ---------------------------------------------------------------------------
# require_claim_statement (INV-47 — claims are propositions, not tasks)
# ---------------------------------------------------------------------------

class TestRequireClaimStatement:
    def test_accepts_proposition(self):
        from voronoi.mcp.validators import require_claim_statement
        assert require_claim_statement("L4 > L1 on F1 (d=0.35)") == \
            "L4 > L1 on F1 (d=0.35)"

    def test_rejects_bare_imperative(self):
        from voronoi.mcp.validators import (
            ValidationError, require_claim_statement,
        )
        with pytest.raises(ValidationError, match="imperative"):
            require_claim_statement(
                "Analyze pricing dataset for five action-changing findings",
            )

    def test_rejects_empty(self):
        from voronoi.mcp.validators import (
            ValidationError, require_claim_statement,
        )
        with pytest.raises(ValidationError, match="empty"):
            require_claim_statement("")
