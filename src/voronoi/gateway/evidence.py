"""Evidence extraction and rendering for investigation reports.

Static/pure functions extracted from ReportGenerator.
"""

from __future__ import annotations

import json
from pathlib import Path

from voronoi.beads import run_bd as _run_bd
from voronoi.utils import clean_finding_title as _clean_finding_title
from voronoi.utils import extract_field as _parse_note_value


def get_findings(workspace: Path, *, _cache: dict | None = None) -> list[dict]:
    """Extract FINDING tasks from Beads with interpretation metadata."""
    code, stdout = _run_bd("list", "--json", cwd=str(workspace))
    if code != 0:
        return []
    try:
        tasks = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return []

    findings: list[dict] = []
    for t in tasks:
        title = t.get("title", "")
        if "FINDING" not in title.upper():
            continue
        notes = t.get("notes", "")
        f: dict = {"title": title, "id": t.get("id", "?"), "notes": notes}
        for key in ("EFFECT_SIZE", "CI_95", "N", "STAT_TEST",
                     "VALENCE", "P", "ROBUST", "STAT_REVIEW",
                     "INTERPRETATION", "PRACTICAL_SIGNIFICANCE",
                     "SUPPORTS_HYPOTHESIS", "CONDITIONS"):
            val = _parse_note_value(notes, key)
            if val:
                f[key.lower()] = val
        if "interpretation" not in f or "practical_significance" not in f:
            from voronoi.science import interpret_finding
            interp = interpret_finding(t)
            if "practical_significance" not in f:
                f["practical_significance"] = interp["practical_significance"]
            if "ci_quality" not in f:
                f["ci_quality"] = interp["ci_quality"]
            if "strength_label" not in f:
                f["strength_label"] = interp["strength_label"]
            if "interpretation" not in f and interp["interpretation_text"]:
                f["interpretation"] = interp["interpretation_text"]
        findings.append(f)
    return findings


def render_findings_table(findings: list[dict], placeholder: str = "\u2014") -> list[str]:
    """Render a markdown findings table with strength indicators."""
    rows = ["| # | Finding | Effect | CI | N | Test | Verdict | Strength |",
            "|---|---------|--------|----|---|------|---------|----------|"]
    for i, f in enumerate(findings, 1):
        title = _clean_finding_title(f["title"])
        effect = f.get("effect_size", placeholder)
        ci = f.get("ci_95", placeholder)
        n = f.get("n", placeholder)
        test = f.get("stat_test", placeholder)
        valence = f.get("valence", placeholder)
        strength = f.get("strength_label", f.get("practical_significance", placeholder))
        rows.append(f"| {i} | {title} | {effect} | {ci} | {n} | {test} | {valence} | {strength} |")
    return rows


def render_findings_interpreted(findings: list[dict]) -> list[str]:
    """Render findings with interpretation and practical significance."""
    lines: list[str] = []
    for i, f in enumerate(findings, 1):
        title = _clean_finding_title(f["title"])
        valence = f.get("valence", "unknown")
        effect = f.get("effect_size", "")
        ci = f.get("ci_95", "")
        p_val = f.get("p", "")
        n = f.get("n", "")
        practical = f.get("practical_significance", "")
        strength = f.get("strength_label", "")
        interp = f.get("interpretation", "")
        supports = f.get("supports_hypothesis", "")

        lines.append(f"### Finding {i}: {title}\n")

        stat_parts = []
        if effect:
            stat_parts.append(f"**Effect size:** d={effect}")
            if practical and practical != "unknown":
                stat_parts.append(f"({practical} practical effect)")
        if ci:
            stat_parts.append(f"**CI 95%:** {ci}")
        if p_val:
            stat_parts.append(f"**p:** {p_val}")
        if n:
            stat_parts.append(f"**N:** {n}")
        if stat_parts:
            lines.append(" | ".join(stat_parts) + "\n")

        lines.append(f"**Verdict:** {valence}")
        if strength and strength not in ("unknown", "unreviewed"):
            lines.append(f" | **Evidence strength:** {strength}")
        lines.append("\n")

        if interp:
            lines.append(f"**Interpretation:** {interp}\n")
        if supports:
            lines.append(f"**Supports hypothesis:** {supports}\n")

        lines.append("")
    return lines


def pick_headline(findings: list[dict]) -> dict:
    """Pick the finding with the largest numeric effect size."""
    best, best_val = None, -1.0
    for f in findings:
        es = f.get("effect_size", "")
        try:
            val = abs(float(es))
            if val > best_val:
                best, best_val = f, val
        except (ValueError, TypeError):
            continue
    if not findings:
        return {}
    return best if best is not None else findings[0]


def valence_emoji(valence: str) -> str:
    return {"positive": "\u2705", "negative": "\u274c"}.get(valence.lower(), "\u2753")


def render_evidence_chain(workspace: Path) -> str | None:
    """Render claim-evidence traceability from .swarm/claim-evidence.json."""
    from voronoi.science import load_claim_evidence
    reg = load_claim_evidence(workspace)
    if not reg.claims:
        return None

    lines = []
    for c in reg.claims:
        strength_badge = {"robust": "\u2705", "provisional": "\u26a0\ufe0f",
                          "weak": "\u274c", "unsupported": "\u2b55"}.get(
            c.strength, "\u2753")
        lines.append(f"### {strength_badge} {c.claim_text}\n")
        lines.append(f"**Evidence strength:** {c.strength}")
        if c.finding_ids:
            lines.append(f" | **Supported by:** {', '.join(c.finding_ids)}")
        if c.hypothesis_ids:
            lines.append(f" | **Tests:** {', '.join(c.hypothesis_ids)}")
        lines.append("\n")
        if c.interpretation:
            lines.append(f"{c.interpretation}\n")
        lines.append("")

    if reg.unsupported_claims:
        lines.append("\n**\u26a0\ufe0f Unsupported claims:** "
                     f"{', '.join(reg.unsupported_claims)}\n")
    if reg.orphan_findings:
        lines.append("**\u2139\ufe0f Findings not cited in claims:** "
                     f"{', '.join(reg.orphan_findings)}\n")

    lines.append(f"\n**Evidence coverage:** {reg.coverage_score:.0%} of claims "
                 f"have supporting evidence\n")
    return "\n".join(lines)


def render_limitations(findings: list[dict], workspace: Path) -> str | None:
    """Auto-generate limitations from fragile, contested, wide-CI findings."""
    limitations: list[str] = []

    fragile = [f for f in findings if f.get("robust", "").lower() == "no"]
    for f in fragile:
        title = _clean_finding_title(f["title"])
        conditions = f.get("conditions", "conditions not documented")
        limitations.append(
            f"- **Fragile result:** {title} "
            f"(not robust under sensitivity analysis; {conditions})"
        )

    for f in findings:
        ci_q = f.get("ci_quality", "")
        if ci_q in ("wide", "very wide"):
            title = _clean_finding_title(f["title"])
            limitations.append(
                f"- **Imprecise estimate:** {title} "
                f"(CI quality: {ci_q} — interpret with caution)"
            )

    unreviewed = [f for f in findings
                  if f.get("strength_label") in ("unreviewed", None)
                  and not f.get("stat_review")]
    if unreviewed:
        titles = [_clean_finding_title(f["title"]) for f in unreviewed[:3]]
        limitations.append(
            f"- **Unreviewed evidence:** {len(unreviewed)} finding(s) "
            f"not yet reviewed by Statistician ({', '.join(titles)})"
        )

    rejected = [f for f in findings if f.get("strength_label") == "rejected"]
    for f in rejected:
        title = _clean_finding_title(f["title"])
        limitations.append(
            f"- **Rejected by review:** {title} (failed statistical review)"
        )

    # Read belief map for inconclusive hypotheses
    try:
        from voronoi.science.convergence import load_belief_map
        bm = load_belief_map(workspace)
        for h in bm.hypotheses:
            if h.status == "inconclusive":
                limitations.append(
                    f"- **Inconclusive hypothesis:** {h.display_name} "
                    f"(insufficient evidence to confirm or refute)"
                )
    except Exception:
        pass

    return "\n".join(limitations) if limitations else None


def render_cross_finding_comparison(findings: list[dict]) -> str | None:
    """Rank findings by effect size and narrate relative magnitudes."""
    scored: list[tuple[float, dict]] = []
    for f in findings:
        es = f.get("effect_size", "")
        try:
            val = abs(float(es))
            scored.append((val, f))
        except (ValueError, TypeError):
            continue

    if len(scored) < 2:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    lines = []
    top = scored[0]
    top_title = _clean_finding_title(top[1]["title"])
    lines.append(f"The strongest effect observed was **{top_title}** "
                 f"(d={top[1].get('effect_size', '?')}"
                 f"{', ' + top[1].get('practical_significance', '') if top[1].get('practical_significance') else ''}).")

    if len(scored) >= 2:
        bot = scored[-1]
        bot_title = _clean_finding_title(bot[1]["title"])
        if top[0] > 0 and bot[0] > 0:
            ratio = top[0] / bot[0]
            lines.append(
                f"This is {ratio:.1f}x larger than the weakest effect, "
                f"**{bot_title}** (d={bot[1].get('effect_size', '?')}).")

    positive = [f for _, f in scored if f.get("valence", "").lower() == "positive"]
    negative = [f for _, f in scored if f.get("valence", "").lower() == "negative"]
    if positive and negative:
        pos_titles = [_clean_finding_title(f["title"]) for f in positive[:2]]
        neg_titles = [_clean_finding_title(f["title"]) for f in negative[:2]]
        lines.append(
            f"\nNotably, results were mixed: {', '.join(pos_titles)} showed "
            f"positive effects while {', '.join(neg_titles)} showed negative effects."
        )

    return "\n".join(lines)


def render_negative_results(findings: list[dict]) -> str | None:
    """Render a dedicated section for negative/inconclusive findings."""
    negative = [f for f in findings
                if f.get("valence", "").lower() in ("negative", "inconclusive")]
    if not negative:
        return None

    lines = ["The following hypotheses were tested and did not produce "
             "the expected positive result. These negative results are "
             "scientifically valuable as they narrow the solution space "
             "and prevent future wasted effort.\n"]
    for f in negative:
        title = _clean_finding_title(f["title"])
        effect = f.get("effect_size", "")
        p_val = f.get("p", "")
        valence = f.get("valence", "")
        stat_parts = []
        if effect:
            stat_parts.append(f"d={effect}")
        if p_val:
            stat_parts.append(f"p={p_val}")
        stat_str = f" ({', '.join(stat_parts)})" if stat_parts else ""
        lines.append(f"- **{title}**{stat_str} \u2014 {valence}")
    return "\n".join(lines)


def humanize_stats(finding: dict) -> str:
    """Translate raw stats into a human-friendly description."""
    parts: list[str] = []
    p_val = finding.get("p", "")
    effect = finding.get("effect_size", "")
    try:
        p_float = float(p_val)
        if p_float < 0.001:
            parts.append("very strong evidence")
        elif p_float < 0.01:
            parts.append("strong evidence")
        elif p_float < 0.05:
            parts.append("significant")
        else:
            parts.append("weak evidence")
        parts.append(f"p={p_val}")
    except (ValueError, TypeError):
        pass
    if effect:
        try:
            d = abs(float(effect))
            if d >= 0.8:
                size = "large effect"
            elif d >= 0.5:
                size = "medium effect"
            elif d >= 0.2:
                size = "small effect"
            else:
                size = "negligible effect"
            parts.append(size)
        except (ValueError, TypeError):
            pass
    return ", ".join(parts)
