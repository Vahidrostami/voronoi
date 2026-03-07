"""Tests for voronoi.gateway.progress — formatting helpers.

The actual progress *polling* logic lives in the dispatcher and is tested
in test_dispatcher.py.  These tests cover the formatting functions only.
"""

from voronoi.gateway.progress import format_workflow_start, format_workflow_complete


class TestFormatting:
    def test_format_workflow_start(self):
        msg = format_workflow_start("investigate", "scientific", "Why is latency high?")
        assert "INVESTIGATE" in msg
        assert "scientific" in msg
        assert "Why is latency high?" in msg

    def test_format_workflow_start_explore(self):
        msg = format_workflow_start("explore", "analytical", "Redis vs Memcached")
        assert "EXPLORE" in msg
        assert "🧭" in msg

    def test_format_workflow_start_build(self):
        msg = format_workflow_start("build", "standard", "Build REST API")
        assert "BUILD" in msg
        assert "🔨" in msg

    def test_format_workflow_complete(self):
        msg = format_workflow_complete("investigate", 12, 3, 15.5)
        assert "INVESTIGATE" in msg
        assert "12" in msg
        assert "3" in msg
        assert "15.5" in msg
