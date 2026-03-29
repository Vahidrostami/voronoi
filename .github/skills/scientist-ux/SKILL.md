---
name: scientist-ux
description: "Use when brainstorming Voronoi UX from a real scientist's perspective. Contains domain knowledge about how researchers actually work, common pain points in scientific tooling, and UX patterns that respect the scientific workflow. Loaded by the Catalyst agent."
---

# Scientist UX — Domain Knowledge for Voronoi Design

## The Real Scientific Workflow

What textbooks say vs what actually happens:

### The Textbook Version
Question → Literature Review → Hypothesis → Experiment → Analysis → Publication

### What Actually Happens

```
Vague curiosity
    → Read 3 papers, get confused by contradictions
    → Talk to colleague at coffee, get a hunch
    → Quick-and-dirty exploratory analysis at midnight
    → "Huh, that's weird" moment
    → 2 weeks chasing an artifact (caching bug, off-by-one, wrong column)
    → Finally real signal, but small and fragile
    → Design proper experiment, realize you need 10x more data
    → Collect data (weeks/months)
    → Analyze, discover 3 confounds you didn't anticipate
    → Partial result: not what you expected, but interesting
    → Pivot hypothesis
    → Re-analyze with corrected methodology
    → Result holds! Write paper.
    → Reviewer #2 says "why didn't you control for X?" (X is valid)
    → 3 months of additional experiments for revision
    → Published. 4 citations in 2 years.
    → New postdoc joins, can't reproduce it from your notes.
```

### Key Implications for Voronoi

1. **"Huh, that's weird" is the most valuable moment** — systems that force pre-registration too early kill serendipity
2. **Most time is spent on debugging, not discovery** — tools should help distinguish signal from artifact
3. **Pivoting is normal, not failure** — the system must handle hypothesis evolution gracefully
4. **Reproducibility fails at the edges** — not the main experiment, but the data cleaning, normalization choices, exclusion criteria
5. **Reviewer #2 is inevitable** — output must be defensive, pre-answering obvious challenges

---

## Scientist Personas

### Dr. Chen — The Computational Biologist (Primary User)
- PhD + 3 years postdoc, first faculty position
- Proficient in Python, R, basic stats
- Runs genomics analyses that take hours to days
- Pain: "I have 50 scripts, half-documented. I can't remember why I excluded sample 17."
- Need: Provenance tracking, decision logging, reproducible pipelines
- Trust threshold: Will stop using the tool the first time it gives a wrong p-value

### Dr. Okafor — The Experimental Physicist
- 15 years experience, large team (8 postdocs, 12 students)
- Delegates most computational work, reads results
- Pain: "My students show me results I can't verify. I need to trust but verify."
- Need: Clear evidence chains, at-a-glance quality indicators, delegation that maintains rigor
- Trust threshold: Wants to see raw data and the exact statistical test — not just the conclusion

### Dr. Johansson — The Social Scientist
- Runs behavioral experiments with human subjects
- Deeply aware of replication crisis, p-hacking, garden-of-forking-paths
- Pain: "Every analysis choice I make is defensible but arbitrary. There are 200 valid pipelines."
- Need: Multiverse analysis support, pre-registration that's practical not performative
- Trust threshold: Will reject any system that doesn't show specification curves

### Alex — The PhD Student
- 2nd year, impostor syndrome, first real investigation
- Knows Python, doesn't know stats deeply
- Pain: "I don't know what I don't know. My advisor says 'just run a t-test' but I'm not sure that's right."
- Need: Gentle guidance ("a t-test assumes normality — here's why that matters for your data"), not just execution
- Trust threshold: Will blindly trust anything that looks authoritative — which is dangerous

### Dr. Petrova — The Department Chair (Skeptic)
- Evaluates tools for the department
- Pain: "We've adopted 5 'revolutionary' tools in 3 years. None stuck."
- Need: Proof that it integrates with existing workflows, not replaces them
- Trust threshold: Wants a pilot with measurable outcomes before committing

---

## Pain Points in Current Scientific Tooling

### 1. The Reproducibility Gap
- **Problem**: Tools capture the final analysis but not the decision tree that led there
- **What scientists want**: A complete provenance graph — "I tried X, Y, Z. Z worked because..."
- **Voronoi opportunity**: The OODA loop + Beads task history + `.swarm/` state IS this provenance graph. But is it readable by a human 6 months later?

### 2. The Trust Calibration Problem
- **Problem**: Tools either show everything (overwhelming) or hide everything (trust me bro)
- **What scientists want**: Progressive disclosure — summary by default, drill down on demand, full audit trail available
- **Voronoi opportunity**: The evaluator score + claim-evidence registry could be this. But what's the actual UI affordance?

### 3. The Methodology Mismatch
- **Problem**: Statistical tests are often chosen by convention, not appropriateness
- **What scientists want**: "Given my data structure and hypothesis, which test is appropriate and why?"
- **Voronoi opportunity**: The Methodologist + Statistician agents could provide this. But they currently activate only at Scientific+ rigor — what about helping novice researchers at Analytical level?

### 4. The Artifact Hell
- **Problem**: 90% of "discoveries" are artifacts of the experimental setup (caching, truncation, resource limits, data leakage)
- **What scientists want**: Automatic artifact detection before they waste weeks
- **Voronoi opportunity**: EVA (Experiment Validity Audit) is exactly right. World-class feature. Make it louder.

### 5. The Communication Gap
- **Problem**: Scientists can't explain their findings to non-specialists (or even to themselves clearly)
- **What scientists want**: Help translating statistical results into plain language ("this means the drug reduces symptom duration by ~2 days, with 95% confidence it's between 1-3 days")
- **Voronoi opportunity**: The Statistician already produces interpretation metadata. The Scribe produces papers. What about the in-between — a 1-page executive summary for a PI meeting?

### 6. The Iteration Tax
- **Problem**: Each iteration of an experiment requires re-explaining context to collaborators/tools
- **What scientists want**: A system that remembers context across sessions, across days, across team members
- **Voronoi opportunity**: `.swarm/strategic-context.md` + belief maps do this. But is this context accessible in a natural way?

### 7. The Negative Result Problem
- **Problem**: Negative results are valuable but unpublished, lost, and repeated by others
- **What scientists want**: A way to record "we tried X, it didn't work, here's why" that's searchable
- **Voronoi opportunity**: Dead ends in strategic context. But are they surfaced when someone starts a similar investigation?

---

## UX Patterns That Respect Scientific Workflow

### Pattern 1: Confidence-Aware Output
Every result should communicate confidence:
```
Finding: Treatment A outperforms Treatment B
Confidence: MODERATE (effect size d=0.4, N=120, single study)
Would strengthen: Larger sample, independent replication, active control
Weakness: No blinding, convenience sample
```

### Pattern 2: The Evidence Chain
Every claim links to evidence, every evidence links to raw data:
```
Claim → Finding → Experiment → Raw Data → Script
                                   ↓
                             SHA-256 verified ✓
```
The scientist should be able to click through this chain in under 10 seconds.

### Pattern 3: Progressive Rigor
Don't front-load rigor. Let the scientist explore freely, then tighten:
```
Phase 1: "Just show me the data" (no gates)
Phase 2: "This looks promising, let's be more careful" (basic validation)
Phase 3: "This could be real, full rigor please" (pre-registration, controls, replication)
```
This is what DISCOVER mode already does. Make it feel effortless.

### Pattern 4: The Honest Failure
When things don't work, say so clearly:
```
❌ Hypothesis H1 NOT supported
   Effect size: d=0.02 (negligible), p=0.78 (not significant)
   This is a valid negative result. Recorded for future reference.
   Possible reasons: [1] Effect doesn't exist [2] Underpowered (would need N=2000) [3] Wrong measure
```

### Pattern 5: The Reviewer Defense Brief
Anticipate reviewer objections and pre-answer them:
```
Potential objection: "Sample size too small"
Defense: Power analysis showed N=80 sufficient for d>0.5 (α=0.05, power=0.80).
         Observed d=0.62 with 95% CI [0.35, 0.89].
         Sensitivity analysis: conclusion stable across N=60-120.
```

### Pattern 6: The Living Document
Results are not final — they evolve as new data arrives:
```
v1 (Jan): Preliminary, N=30, d=0.8 (likely inflated, small sample)
v2 (Mar): Confirmed, N=120, d=0.45 (regression to mean as expected)
v3 (Jun): Replicated, N=200 independent sample, d=0.42
→ Robust finding
```

---

## Breakthrough Design Questions

These questions can drive brainstorming sessions:

### On Trust
- What would make a scientist trust Voronoi more than their own manual analysis?
- At what point does automation become a liability for scientific credibility?
- How do we handle the case where the system's statistical analysis disagrees with the scientist's intuition?

### On Workflow
- Can Voronoi handle the "Monday morning" scenario: scientist returns after a weekend, needs to resume with full context?
- What happens when two investigations (by different scientists) are studying the same question? Does the system know?
- Can a PI use Voronoi to review a student's work without re-running everything?

### On Output
- Is a PDF paper the right deliverable? What about a Jupyter notebook? A dashboard? A pre-print draft?
- What does the output look like for a negative result? (Most investigations produce negative results.)
- Can the output adapt to audience: journal paper vs conference talk vs departmental seminar vs grant application?

### On Scale
- What happens when an investigation runs for weeks, not hours?
- What if the dataset is 100GB? 1TB? Does the architecture assume everything fits in a git repo?
- How does the system handle investigations that require access to paid APIs, compute clusters, or institutional resources?

### On Collaboration
- Can two scientists co-investigate? What does that look like?
- How does a lab group use Voronoi? Is it one instance per PI? Per project? Per person?
- What happens when a postdoc leaves? Is the investigation portable?

### On Ethics
- How does Voronoi handle human subjects data (IRB, GDPR)?
- What if the system discovers something that has safety implications? (e.g., a drug interaction)
- Can the system enforce data sharing policies (embargo periods, license restrictions)?
