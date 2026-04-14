"""Tests for voronoi.beads — Beads subprocess helpers."""

import os
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from voronoi.beads import (
    BeadsError,
    _LOCK_ERROR_FRAGMENT,
    _LOCK_RETRIES,
    add_dependency,
    has_beads_dir,
    run_bd,
    run_bd_json,
    run_cmd,
)


class TestRunBd:
    @patch("voronoi.beads.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="output", stderr=""
        )
        code, out = run_bd("list", "--json", cwd="/tmp")
        assert code == 0
        assert out == "output"

    @patch("voronoi.beads.subprocess.run")
    def test_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error"
        )
        code, out = run_bd("list", cwd="/tmp")
        assert code == 1

    @patch("voronoi.beads.subprocess.run")
    def test_strict_raises(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="bd error"
        )
        with pytest.raises(BeadsError, match="failed"):
            run_bd("list", cwd="/tmp", strict=True)

    @patch("voronoi.beads.subprocess.run", side_effect=FileNotFoundError)
    def test_bd_not_found(self, mock_run):
        code, out = run_bd("list")
        assert code == 1
        assert out == ""

    @patch("voronoi.beads.subprocess.run", side_effect=FileNotFoundError)
    def test_bd_not_found_strict(self, mock_run):
        with pytest.raises(BeadsError, match="not found"):
            run_bd("list", strict=True)

    @patch("voronoi.beads.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="bd", timeout=30))
    def test_timeout(self, mock_run):
        code, out = run_bd("list")
        assert code == 1

    @patch("voronoi.beads.subprocess.run")
    def test_sets_beads_dir(self, mock_run, tmp_path):
        beads_dir = tmp_path / ".beads"
        beads_dir.mkdir()
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        run_bd("list", cwd=str(tmp_path))
        call_env = mock_run.call_args.kwargs.get("env", {})
        assert call_env.get("BEADS_DIR") == str(beads_dir)

    @patch("voronoi.beads.time.sleep")
    @patch("voronoi.beads.subprocess.run")
    def test_retries_on_lock_contention(self, mock_run, mock_sleep):
        """Retry when embedded Dolt exclusive lock error is detected."""
        lock_err = MagicMock(
            returncode=1, stdout="",
            stderr=f'{{"error": "{_LOCK_ERROR_FRAGMENT}..."}}'
        )
        success = MagicMock(returncode=0, stdout="ok", stderr="")
        mock_run.side_effect = [lock_err, lock_err, success]
        code, out = run_bd("list", "--json", cwd="/tmp")
        assert code == 0
        assert out == "ok"
        assert mock_run.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("voronoi.beads.time.sleep")
    @patch("voronoi.beads.subprocess.run")
    def test_lock_retries_exhausted(self, mock_run, mock_sleep):
        """After max retries, return the failing exit code."""
        lock_err = MagicMock(
            returncode=1, stdout="",
            stderr=f'{{"error": "{_LOCK_ERROR_FRAGMENT}..."}}'
        )
        mock_run.return_value = lock_err
        code, out = run_bd("list", cwd="/tmp")
        assert code == 1
        assert mock_run.call_count == _LOCK_RETRIES + 1

    @patch("voronoi.beads.time.sleep")
    @patch("voronoi.beads.subprocess.run")
    def test_no_retry_on_other_errors(self, mock_run, mock_sleep):
        """Non-lock errors should not trigger retries."""
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="some other error"
        )
        code, out = run_bd("list", cwd="/tmp")
        assert code == 1
        assert mock_run.call_count == 1
        mock_sleep.assert_not_called()


class TestRunBdJson:
    @patch("voronoi.beads.run_bd")
    def test_valid_json(self, mock_bd):
        mock_bd.return_value = (0, '[{"id": 1}]')
        code, data = run_bd_json("list", "--json")
        assert code == 0
        assert data == [{"id": 1}]

    @patch("voronoi.beads.run_bd")
    def test_invalid_json(self, mock_bd):
        mock_bd.return_value = (0, "not json")
        code, data = run_bd_json("list", "--json")
        assert code == 0
        assert data is None

    @patch("voronoi.beads.run_bd")
    def test_failure(self, mock_bd):
        mock_bd.return_value = (1, "")
        code, data = run_bd_json("list", "--json")
        assert code == 1
        assert data is None

    @patch("voronoi.beads.run_bd")
    def test_empty_output(self, mock_bd):
        mock_bd.return_value = (0, "")
        code, data = run_bd_json("list", "--json")
        assert code == 0
        assert data is None


class TestHasBeadsDir:
    def test_with_beads_dir(self, tmp_path):
        (tmp_path / ".beads").mkdir()
        assert has_beads_dir(str(tmp_path)) is True

    def test_without_beads_dir(self, tmp_path):
        assert has_beads_dir(str(tmp_path)) is False

    def test_none_cwd(self):
        assert has_beads_dir(None) is False

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("BEADS_DIR", "/tmp/.beads")
        assert has_beads_dir(None) is True


class TestRunCmd:
    @patch("voronoi.beads.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="out", stderr="err"
        )
        code, out = run_cmd(["echo", "hi"])
        assert code == 0
        assert "out" in out

    @patch("voronoi.beads.subprocess.run", side_effect=FileNotFoundError)
    def test_command_not_found(self, mock_run):
        code, out = run_cmd(["nonexistent"])
        assert code == 1
        assert "not found" in out.lower()

    @patch("voronoi.beads.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="test", timeout=30))
    def test_timeout(self, mock_run):
        code, out = run_cmd(["sleep", "100"], timeout=1)
        assert code == 1


class TestAddDependency:
    @patch("voronoi.beads.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="ok", stderr=""
        )
        code, out = add_dependency("bd-2", "bd-1", cwd="/tmp")
        assert code == 0
        # Verify the correct command was called
        args = mock_run.call_args[0][0]
        assert args == ["bd", "dep", "add", "bd-2", "bd-1"]

    @patch("voronoi.beads.subprocess.run")
    def test_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="not found"
        )
        code, out = add_dependency("bd-2", "bd-1")
        assert code == 1
