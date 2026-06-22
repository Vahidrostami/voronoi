"""Tests for the Locked Claim schema and fidelity comparator (SCIENCE.md §23)."""

from __future__ import annotations

from pathlib import Path

import pytest

from voronoi.science.locked_claim import (
    EXECUTED_CLAIM_FILENAME,
    LOCKED_CLAIM_FILENAME,
    SLOT_NAMES,
    FidelityResult,
    LockedClaim,
    compare_claims,
    load_locked_claim,
    normalized_equivalence,
    save_locked_claim,
)


def _full_claim(**overrides) -> LockedClaim:
    base = LockedClaim(
        claim="E∪M features predict T-type with ΔBalAcc ≥ 0.05 vs M-only",
        scope="mouse cortical neurons with paired E+M+T data, donor-grouped CV",
        decision_rule="ΔBalAcc ≥ 0.05 AND p < 0.0033 AND both models agree in sign",
        falsifier="ΔBalAcc < 0 OR models disagree post-residualization",
        preconditions="T-type labels available for ≥20 cells per type after join",
        locked_by="gateway-extractor",
        source_prompt="prove that E adds to M for T-type prediction",
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_slot_names_are_the_five_documented_slots():
    assert SLOT_NAMES == (
        "claim",
        "scope",
        "decision_rule",
        "falsifier",
        "preconditions",
    )


def test_is_complete_requires_all_five_slots():
    full = _full_claim()
    assert full.is_complete
    assert full.missing_slots() == []

    partial = _full_claim(falsifier="")
    assert not partial.is_complete
    assert partial.missing_slots() == ["falsifier"]


def test_save_and_load_round_trip(tmp_path: Path):
    claim = _full_claim()
    path = save_locked_claim(claim, tmp_path)
    assert path == tmp_path / ".swarm" / LOCKED_CLAIM_FILENAME
    assert path.exists()
    loaded = load_locked_claim(tmp_path)
    assert loaded is not None
    for slot in SLOT_NAMES:
        assert getattr(loaded, slot) == getattr(claim, slot)
    # Metadata round-trips too.
    assert loaded.locked_by == "gateway-extractor"
    assert loaded.locked_at  # auto-stamped on save


def test_load_returns_none_when_absent(tmp_path: Path):
    assert load_locked_claim(tmp_path) is None


def test_executed_filename_distinct_from_locked(tmp_path: Path):
    locked = _full_claim()
    save_locked_claim(locked, tmp_path)
    save_locked_claim(locked, tmp_path, filename=EXECUTED_CLAIM_FILENAME)
    assert (tmp_path / ".swarm" / LOCKED_CLAIM_FILENAME).exists()
    assert (tmp_path / ".swarm" / EXECUTED_CLAIM_FILENAME).exists()


def test_compare_identical_claims_passes():
    locked = _full_claim()
    executed = _full_claim()
    result = compare_claims(locked, executed)
    assert isinstance(result, FidelityResult)
    assert result.passed
    assert result.divergent_slots == []


def test_compare_trivially_different_whitespace_still_passes():
    locked = _full_claim()
    executed = _full_claim(claim="  " + locked.claim + ".  ")
    result = compare_claims(locked, executed)
    assert result.passed, "whitespace/trailing punctuation should normalize"


def test_compare_detects_target_substitution():
    """The trimodal-demo failure mode: same shape, different MEASURE."""
    locked = _full_claim()
    executed = _full_claim(
        claim="E∪M features predict dendrite-type with ΔBalAcc ≥ 0.05 vs M-only",
    )
    result = compare_claims(locked, executed)
    assert not result.passed
    assert result.divergent_slots == ["claim"]


def test_compare_detects_decision_rule_drift():
    """The 'both models must agree' violation re-narrated as 'weakly positive'."""
    locked = _full_claim()
    executed = _full_claim(
        decision_rule="ΔBalAcc ≥ 0.05 AND p < 0.0033 (LightGBM only)",
    )
    result = compare_claims(locked, executed)
    assert not result.passed
    assert "decision_rule" in result.divergent_slots


def test_compare_detects_missing_executed_slot():
    locked = _full_claim()
    executed = _full_claim(falsifier="")
    result = compare_claims(locked, executed)
    assert not result.passed
    assert "falsifier" in result.divergent_slots


def test_compare_metadata_does_not_affect_fidelity():
    locked = _full_claim(locked_by="user")
    executed = _full_claim(locked_by="agent-9")
    assert compare_claims(locked, executed).passed


def test_normalized_equivalence_examples():
    assert normalized_equivalence("Foo bar.", "foo  bar")
    assert not normalized_equivalence("foo", "bar")
    assert normalized_equivalence("", "")
    # One-sided-empty must NOT be equivalent: this is the contract that makes
    # missing declared-executed slots fail the fidelity gate.
    assert not normalized_equivalence("foo", "")
    assert not normalized_equivalence("", "foo")


def test_injectable_equivalence_fn_overrides_default():
    locked = _full_claim()
    executed = _full_claim(claim="completely different wording")

    def always_equivalent(a: str, b: str) -> bool:  # noqa: ARG001
        return True

    result = compare_claims(locked, executed, equivalence_fn=always_equivalent)
    assert result.passed, "equivalence_fn must be honored for LLM-based future work"


def test_result_summary_strings():
    locked = _full_claim()
    pass_result = compare_claims(locked, _full_claim())
    assert "PASS" in pass_result.summary()
    fail_result = compare_claims(locked, _full_claim(scope="different"))
    summary = fail_result.summary()
    assert "FAIL" in summary
    assert "scope" in summary


def test_public_api_surface():
    """Re-exported from voronoi.science."""
    from voronoi import science

    for name in (
        "LockedClaim",
        "FidelityDiff",
        "FidelityResult",
        "compare_claims",
        "save_locked_claim",
        "load_locked_claim",
        "normalized_equivalence",
    ):
        assert hasattr(science, name), f"voronoi.science is missing {name}"
