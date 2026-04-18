---
name: deep-research
description: >
  Skill for deep research grounding using Copilot CLI /research for multi-source
  literature review, prior-art search, and SOTA anchoring. Use before forming
  hypotheses to anchor claims in real, citation-backed evidence.
---

# Deep Research Skill

Grounding investigations in real evidence before forming hypotheses.

## When to Use

Use this skill when tasked with:
- Literature review or prior-art search
- SOTA anchoring (what's the current best approach?)
- Grounding hypotheses in existing evidence
- Verifying claims before committing them as findings

## The Problem This Solves

LLM agents can "recall" information from training data without citations,
leading to fabricated or outdated claims in knowledge briefs. The `/research`
command provides citation-backed evidence from live sources, eliminating
training-data-only recall as a knowledge source.

## How to Use

```
/research <specific, focused question>
```

The command searches GitHub repositories + live web sources and returns
citation-backed results with source URLs.

## Protocol

1. **Formulate specific queries** — not "machine learning" but
   "continual learning methods that prevent catastrophic forgetting
   in transformer models"
2. **Run /research** for each major topic area
3. **Extract citations** — record source URLs in strategic-context.md
4. **Cross-reference** with Semantic Scholar for academic depth (if available)
5. **Record all sources** in the knowledge brief with inline citations

## Problem Positioning Queries

When doing positioning research for the Scout, craft queries that find
the **FRONTIER**, not the textbook:

**BAD:** "transformer attention mechanisms"
**GOOD:** "2025 2026 advances in structured context encoding for LLMs"

**BAD:** "multi-agent systems"
**GOOD:** "multi-agent coordination for scientific discovery latest results"

**BAD:** "optimization"
**GOOD:** "high-dimensional coupled decision optimization with heterogeneous constraints recent papers"

**Query design rules:**
- Include year markers (2025, 2026) to bias toward recent work
- Include "state of the art" or "latest results" to avoid survey papers
- For the closest-work query, include the specific technique or contribution
- For methodology comparison, include "methodology" or "approach" plus the specific technique
- Do NOT search for textbook-level concepts — search for what CHANGED recently

**Three mandatory positioning queries (Scout Phase 0):**
1. **Frontier:** "[field] latest results 2025 2026 state of the art"
2. **Sub-problem:** "[specific technique/approach] recent advances methodology comparison"
3. **Closest work:** "[one-sentence investigation description] published results"

## Rules

- NEVER rely on training data recall for factual claims — always verify via /research
- If /research returns no relevant results, state "no prior art found" explicitly
- Each claim in the knowledge brief must trace to a /research citation or a
  Semantic Scholar paper
- Run as many /research queries as needed to ground claims properly

## When NOT to Use

- Simple codebase search (use grep/search tools instead)
- Questions answerable from the current repository
- Tasks with tight time budgets where premium request cost matters
- Build/implementation tasks (these don't need literature grounding)
