"""Tests for voronoi.gateway.handoff — Anton handoff protocol."""

import json
from unittest.mock import patch, call

import pytest

from voronoi.gateway.handoff import AntonHandoff, FixSpec


# ---------------------------------------------------------------------------
# FixSpec formatting
# ---------------------------------------------------------------------------

class TestFixSpec:
    def test_github_body_format(self):
        spec = FixSpec(
            title="Fix session token expiry",
            finding_id="bd-42",
            root_cause="Tokens expire at TZ boundary for UTC+5 to UTC+8",
            fix_description="Use UTC-normalized expiry timestamps",
            expected_improvement="3.2% session failure reduction, CI [2.8%, 3.6%]",
            files_to_change=["src/auth/token.py", "src/auth/middleware.py"],
            repo="acme/api",
            validation_criteria="Re-run session failure analysis, verify <1% rate",
        )
        body = spec.to_github_body()
        assert "Root Cause" in body
        assert "bd-42" in body
        assert "Fix Specification" in body
        assert "src/auth/token.py" in body
        assert "Expected Improvement" in body
        assert "voronoi-spec" in body

    def test_beads_description_format(self):
        spec = FixSpec(
            title="Fix token expiry",
            finding_id="bd-42",
            root_cause="TZ boundary issue",
            fix_description="Use UTC timestamps",
            expected_improvement="3.2% improvement",
            files_to_change=["src/auth.py"],
        )
        desc = spec.to_beads_description()
        assert "Root cause:" in desc
        assert "Fix:" in desc
        assert "Expected:" in desc
        assert "src/auth.py" in desc
        assert "bd-42" in desc

    def test_beads_description_no_files(self):
        spec = FixSpec(
            title="Fix bug",
            finding_id="bd-1",
            root_cause="X",
            fix_description="Y",
            expected_improvement="Z",
        )
        desc = spec.to_beads_description()
        assert "Files:" not in desc

    def test_github_body_default_validation(self):
        spec = FixSpec(
            title="Fix bug",
            finding_id="bd-1",
            root_cause="X",
            fix_description="Y",
            expected_improvement="Z",
        )
        body = spec.to_github_body()
        assert "Re-run the original experiment" in body


# ---------------------------------------------------------------------------
# AntonHandoff — Beads task creation (mocked)
# ---------------------------------------------------------------------------

class TestHandoffBeadsTask:
    @patch("voronoi.gateway.handoff._run_cmd")
    def test_create_beads_task_success(self, mock_cmd, tmp_path):
        mock_cmd.side_effect = [
            (0, json.dumps({"id": "bd-99"})),  # create
            (0, "ok"),                           # update notes
        ]
        spec = FixSpec(
            title="Fix auth", finding_id="bd-42",
            root_cause="TZ issue", fix_description="Use UTC",
            expected_improvement="3% improvement",
        )
        handoff = AntonHandoff(tmp_path)
        success, msg = handoff.create_beads_task(spec)

        assert success is True
        assert "bd-99" in msg
        # Verify bd create was called with [ANTON] prefix
        create_call = mock_cmd.call_args_list[0]
        assert "[ANTON]" in create_call[0][0][2]

    @patch("voronoi.gateway.handoff._run_cmd")
    def test_create_beads_task_failure(self, mock_cmd, tmp_path):
        mock_cmd.return_value = (1, "bd error")
        spec = FixSpec(
            title="Fix auth", finding_id="bd-42",
            root_cause="X", fix_description="Y",
            expected_improvement="Z",
        )
        handoff = AntonHandoff(tmp_path)
        success, msg = handoff.create_beads_task(spec)
        assert success is False
        assert "Failed" in msg

    @patch("voronoi.gateway.handoff._run_cmd")
    def test_create_beads_task_invalid_json_skips_metadata(self, mock_cmd, tmp_path):
        """Bug fix: if bd create returns invalid JSON, don't call bd update with bad ID."""
        mock_cmd.side_effect = [
            (0, "not-json"),  # create succeeds but output is not JSON
        ]
        spec = FixSpec(
            title="Fix auth", finding_id="bd-42",
            root_cause="X", fix_description="Y",
            expected_improvement="Z",
        )
        handoff = AntonHandoff(tmp_path)
        success, msg = handoff.create_beads_task(spec)
        assert success is True
        assert "unknown id" in msg
        # bd update should NOT have been called
        assert mock_cmd.call_count == 1

    @patch("voronoi.gateway.handoff._run_cmd")
    def test_create_beads_task_missing_id_skips_metadata(self, mock_cmd, tmp_path):
        """Bug fix: if bd create returns JSON without id, skip metadata update."""
        mock_cmd.side_effect = [
            (0, json.dumps({"status": "created"})),  # no "id" field
        ]
        spec = FixSpec(
            title="Fix auth", finding_id="bd-42",
            root_cause="X", fix_description="Y",
            expected_improvement="Z",
        )
        handoff = AntonHandoff(tmp_path)
        success, msg = handoff.create_beads_task(spec)
        assert success is True
        assert "unknown id" in msg
        assert mock_cmd.call_count == 1


# ---------------------------------------------------------------------------
# AntonHandoff — GitHub issue creation (mocked)
# ---------------------------------------------------------------------------

class TestHandoffGitHub:
    @patch("voronoi.gateway.handoff._run_cmd")
    def test_create_github_issue_success(self, mock_cmd, tmp_path):
        mock_cmd.return_value = (0, "https://github.com/acme/api/issues/123")
        spec = FixSpec(
            title="Fix auth", finding_id="bd-42",
            root_cause="X", fix_description="Y",
            expected_improvement="Z",
            repo="acme/api",
        )
        handoff = AntonHandoff(tmp_path)
        success, msg = handoff.create_github_issue(spec)
        assert success is True
        assert "https://github.com" in msg

    @patch("voronoi.gateway.handoff._run_cmd")
    def test_create_github_issue_no_repo(self, mock_cmd, tmp_path):
        spec = FixSpec(
            title="Fix auth", finding_id="bd-42",
            root_cause="X", fix_description="Y",
            expected_improvement="Z",
        )
        handoff = AntonHandoff(tmp_path)
        success, msg = handoff.create_github_issue(spec)
        assert success is False
        assert "No repo" in msg

    @patch("voronoi.gateway.handoff._run_cmd")
    def test_create_github_issue_failure(self, mock_cmd, tmp_path):
        mock_cmd.return_value = (1, "gh: not authenticated")
        spec = FixSpec(
            title="Fix auth", finding_id="bd-42",
            root_cause="X", fix_description="Y",
            expected_improvement="Z",
            repo="acme/api",
        )
        handoff = AntonHandoff(tmp_path)
        success, msg = handoff.create_github_issue(spec)
        assert success is False


# ---------------------------------------------------------------------------
# AntonHandoff — validation task creation (mocked)
# ---------------------------------------------------------------------------

class TestHandoffValidation:
    @patch("voronoi.gateway.handoff._run_cmd")
    def test_create_validation_task(self, mock_cmd, tmp_path):
        mock_cmd.side_effect = [
            (0, json.dumps({"id": "bd-100"})),  # create
            (0, "ok"),                            # dep add
            (0, "ok"),                            # update notes
        ]
        spec = FixSpec(
            title="Fix auth", finding_id="bd-42",
            root_cause="X", fix_description="Y",
            expected_improvement="Z",
            validation_criteria="Check session failure rate",
        )
        handoff = AntonHandoff(tmp_path)
        success, msg = handoff.create_validation_task(spec, "bd-99")

        assert success is True
        assert "bd-100" in msg
        assert "bd-99" in msg  # blocked by fix task
        # Verify dep add was called
        dep_call = mock_cmd.call_args_list[1]
        assert "dep" in dep_call[0][0]


# ---------------------------------------------------------------------------
# Notification formatting
# ---------------------------------------------------------------------------

class TestHandoffNotification:
    def test_format_handoff_notification(self, tmp_path):
        spec = FixSpec(
            title="Fix auth", finding_id="bd-42",
            root_cause="TZ boundary causes token expiry",
            fix_description="Normalize to UTC",
            expected_improvement="3.2% improvement",
        )
        handoff = AntonHandoff(tmp_path)
        msg = handoff.format_handoff_notification(spec, "bd-99")
        assert "Handoff to Anton" in msg
        assert "bd-42" in msg
        assert "bd-99" in msg
        assert "TZ boundary" in msg
