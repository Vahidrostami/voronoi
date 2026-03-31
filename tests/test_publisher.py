"""Tests for voronoi.server.publisher — GitHub Publisher."""

from unittest.mock import patch

import pytest

from voronoi.server.publisher import GitHubPublisher


class TestGitHubPublisher:
    @patch("voronoi.server.publisher._run_cmd")
    def test_is_gh_available(self, mock_cmd):
        mock_cmd.return_value = (0, "logged in")
        pub = GitHubPublisher()
        assert pub.is_gh_available() is True

    @patch("voronoi.server.publisher._run_cmd")
    def test_is_gh_not_available(self, mock_cmd):
        mock_cmd.return_value = (1, "not logged in")
        pub = GitHubPublisher()
        assert pub.is_gh_available() is False

    @patch("voronoi.server.publisher._run_cmd")
    def test_publish_success(self, mock_cmd, tmp_path):
        mock_cmd.return_value = (0, "ok")
        pub = GitHubPublisher(lab_org="test-lab")
        success, url = pub.publish(str(tmp_path), "test-repo")
        assert success is True
        assert "test-lab/test-repo" in url

    @patch("voronoi.server.publisher._run_cmd")
    def test_publish_failure(self, mock_cmd, tmp_path):
        mock_cmd.return_value = (1, "authentication required")
        pub = GitHubPublisher()
        success, msg = pub.publish(str(tmp_path), "test-repo")
        # First call fails, then fallback also fails
        assert success is False

    @patch("voronoi.server.publisher._run_cmd")
    def test_publish_fallback_updates_remote_url(self, mock_cmd, tmp_path):
        """Bug fix: if git remote add fails, set-url should be tried."""
        mock_cmd.side_effect = [
            (1, "repo exists"),          # gh repo create fails
            (1, "remote already exists"), # git remote add fails
            (0, ""),                      # git remote set-url succeeds
            (0, ""),                      # git push succeeds
        ]
        pub = GitHubPublisher(lab_org="lab")
        success, url = pub.publish(str(tmp_path), "test-repo")
        assert success is True
        assert "lab/test-repo" in url
        # Verify set-url was called
        set_url_call = mock_cmd.call_args_list[2]
        assert "set-url" in set_url_call[0][0]

    @patch("voronoi.server.publisher._run_cmd")
    def test_create_finding_issues(self, mock_cmd):
        mock_cmd.return_value = (0, "https://github.com/lab/repo/issues/1")
        pub = GitHubPublisher(lab_org="lab")
        findings = [
            {"title": "FINDING: Cache works", "effect_size": "d=2.3", "valence": "positive"},
            {"title": "FINDING: No effect", "valence": "negative"},
        ]
        urls = pub.create_finding_issues("repo", findings)
        assert len(urls) == 2

    @patch("voronoi.server.publisher._run_cmd")
    def test_create_finding_issues_partial_failure(self, mock_cmd):
        mock_cmd.side_effect = [
            (0, "https://github.com/lab/repo/issues/1"),
            (1, "rate limit"),
        ]
        pub = GitHubPublisher()
        findings = [
            {"title": "F1"},
            {"title": "F2"},
        ]
        urls = pub.create_finding_issues("repo", findings)
        assert len(urls) == 1
