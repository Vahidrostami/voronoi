# Evidence System Skill

Managing findings, belief maps, investigation journal, and raw data across the knowledge store.

## When to Use

Use this skill when creating, reviewing, or querying evidence artifacts in investigation workflows.

## Layer 1: Findings (Structured Knowledge)

Findings are the unit of scientific knowledge. They live in Beads with a strict schema.

### Positive Finding
```bash
bd create "FINDING: [result with effect size and CI]" -t task --parent <epic>
bd update <id> --notes "TYPE:finding | VALENCE:positive | CONFIDENCE:0.X"
bd update <id> --notes "SOURCE_TASK:<investigation-task-id>"
bd update <id> --notes "EFFECT_SIZE:[d] | CI_95:[lo, hi] | N:[n] | STAT_TEST:[test] | P:[p]"
bd update <id> --notes "DATA_FILE:<path>"
bd update <id> --notes "DATA_HASH:sha256:<hash>"
bd update <id> --notes "SENSITIVITY: [param variations and results] | ROBUST:yes|no"
bd update <id> --notes "REPLICATED:no | STAT_QUALITY:[score] | REVIEWED_BY:[reviewer]"
bd update <id> --notes "CONTRADICTS:[finding-ids] | SUPPORTS:[hypothesis-ids]"
```

### Negative Finding
```bash
bd create "FINDING: [variable] has no measurable effect on [outcome]" -t task --parent <epic>
bd update <id> --notes "TYPE:finding | VALENCE:negative | CONFIDENCE:0.X"
bd update <id> --notes "EFFECT_SIZE:[d] | CI_95:[lo, hi] | N:[n] | P:[p]"
bd update <id> --notes "IMPLICATION: [what this rules out]"
```

### Finding States
| State | Meaning |
|-------|---------|
| `pending_review` | Awaiting Statistician + Critic review |
| `validated` | Passed all review gates |
| `contested` | Failed adversarial loop or replication disagreement |
| `quarantined` | Data integrity check failed |
| `replicated` | Independently confirmed |

## Layer 2: Raw Data

### Storage Convention
Raw data files live in the agent's worktree:
```
<worktree>/data/raw/      # Untouched experimental output
<worktree>/data/processed/ # Cleaned/transformed data
<worktree>/data/figures/   # Generated visualizations
```

### Data Integrity Chain
1. Compute SHA-256 immediately after collection:
   ```bash
   shasum -a 256 data/raw/<file>.csv
   ```
2. Record hash in finding:
   ```bash
   bd update <finding-id> --notes "DATA_HASH:sha256:<hash>"
   ```
3. Reviewers independently verify the hash before analysis
4. Hash mismatch → finding quarantined immediately

## Layer 3: Investigation Journal

Location: `.swarm/journal.md`

The Synthesizer maintains this running document for narrative continuity across OODA cycles and sessions.

### Journal Entry Format
```markdown
## Cycle N — YYYY-MM-DD HH:MM UTC
**State**: X hypotheses tested, Y confirmed, Z refuted, W inconclusive
**Key finding**: [most important discovery this cycle]
**Working theory**: [current best explanation]
**Next actions**: [planned next steps]
**Belief map**: [compact hypothesis status summary]
```

### Who Reads/Writes
| Role | Access |
|------|--------|
| Orchestrator | Reads at session start for state recovery |
| Synthesizer | Appends after each cycle |
| Theorist | Reads when building causal models |

## Layer 4: Belief Map

A structured representation of all hypotheses and their current status.

### Belief Map Entry
```bash
bd create "BELIEF_MAP: [investigation name]" -t task --parent <epic>
bd update <id> --notes "UPDATED:cycle-N | HYPOTHESES_TOTAL:X | TESTED:Y | REMAINING:Z"
bd update <id> --notes "H1:[name] | STATUS:confirmed|refuted|untested|contested|abandoned | P:0.X | EVIDENCE:[finding-ids]"
bd update <id> --notes "H2:[name] | STATUS:[status] | PRIOR:0.X | BASIS:[evidence source]"
```

### Information-Gain Formula
The orchestrator selects the next hypothesis to test using:
```
priority(H) = uncertainty(H) × impact(H) × testability(H)
```
Where:
- `uncertainty(H)` = 1 - |prior - 0.5| × 2 (highest at 0.5 prior)
- `impact(H)` = number of downstream tasks/hypotheses depending on H
- `testability(H)` = Methodologist's assessment of how cleanly H can be tested

## Querying Evidence

### Find all validated findings
```bash
bd list --json | python3 -c "
import sys, json
for t in json.load(sys.stdin):
    notes = t.get('notes','')
    if 'TYPE:finding' in notes and 'STAT_REVIEW: APPROVED' in notes:
        print(f\"{t['id']}: {t['title']}\")
"
```

### Find belief map
```bash
bd list --json | python3 -c "
import sys, json
for t in json.load(sys.stdin):
    if 'BELIEF_MAP' in t.get('title',''):
        print(f\"{t['id']}: {t['title']}\")
"
```

### Find contested findings
```bash
bd list --json | python3 -c "
import sys, json
for t in json.load(sys.stdin):
    notes = t.get('notes','')
    if 'ADVERSARIAL_STATUS:CONTESTED' in notes or 'DATA_INTEGRITY:FAILED' in notes:
        print(f\"{t['id']}: {t['title']}\")
"
```

## Consistency Gate

When the Synthesizer integrates a new finding:
1. Pairwise comparison against ALL existing validated findings
2. Check: Do conclusions contradict? Do effect directions conflict?
3. If contradiction detected:
   ```bash
   bd update <finding-id> --notes "CONSISTENCY_CONFLICT:<finding-A> vs <finding-B> | TYPE:[type] | SEVERITY:[level]"
   ```
4. CONSISTENCY_CONFLICT blocks convergence — must be resolved before investigation closes
5. Resolution: re-run experiments, identify moderating variable, or update causal model

## Convergence Requirements by Rigor

| Rigor | Requirements |
|-------|-------------|
| Standard | All build tasks closed, tests passing |
| Analytical | All questions answered with data, Statistician reviewed all findings |
| Scientific | All hypotheses resolved, causal model complete, 1+ prediction confirmed, 1+ competing theory ruled out, all findings ROBUST or FRAGILE-with-conditions, zero CONSISTENCY_CONFLICTs |
| Experimental | Scientific + all high-impact findings replicated, pre-registration verified, meta-analysis complete, all adversarial loops resolved |
