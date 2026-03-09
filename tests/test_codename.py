"""Tests for voronoi.gateway.codename — investigation codename generator."""

from voronoi.gateway.codename import (
    CODENAME_NAMES,
    codename_for_id,
    codename_pool_prompt,
    theme_for_codename,
)


class TestCodenameForId:
    def test_deterministic(self):
        assert codename_for_id(1) == codename_for_id(1)

    def test_wraps_around(self):
        n = len(CODENAME_NAMES)
        assert codename_for_id(0) == codename_for_id(n)
        assert codename_for_id(1) == codename_for_id(n + 1)

    def test_returns_valid_name(self):
        for i in range(20):
            assert codename_for_id(i) in CODENAME_NAMES


class TestTheme:
    def test_known_codename(self):
        theme = theme_for_codename("Dopamine")
        assert "reward" in theme

    def test_case_insensitive(self):
        assert theme_for_codename("dopamine") == theme_for_codename("Dopamine")

    def test_unknown_codename(self):
        assert theme_for_codename("NotANeurotransmitter") == ""


class TestPoolPrompt:
    def test_contains_all_names(self):
        prompt = codename_pool_prompt()
        for name in CODENAME_NAMES:
            assert name in prompt

    def test_contains_themes(self):
        prompt = codename_pool_prompt()
        assert "reward" in prompt
        assert "creativity" in prompt
