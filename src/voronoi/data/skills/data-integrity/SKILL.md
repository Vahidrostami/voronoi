---
name: data-integrity
description: >
  Skill for ensuring data integrity across investigation workflows.
  Covers SHA-256 hashing protocol, raw data preservation, provenance
  tracking, and data-file validation. Use when creating, moving,
  or validating experimental data files.
---

# Data Integrity

Use this skill when working with experimental data files — creation, validation, archival, or provenance tracking.

## Hashing Protocol

Every raw data file MUST have its SHA-256 hash computed immediately after creation:

```bash
# Compute hash
HASH=$(shasum -a 256 data/raw/<file>.csv | cut -d' ' -f1)

# Record in Beads finding
bd update <finding-id> --notes "DATA_HASH:sha256:${HASH}"
bd update <finding-id> --notes "DATA_FILE:data/raw/<file>.csv"
```

## Directory Structure

```
<workspace>/
├── data/
│   ├── raw/           # Immutable after creation — NEVER modify
│   ├── processed/     # Cleaned/transformed outputs
│   ├── figures/       # Generated visualizations
│   └── archived/      # Discarded datasets (with notes)
```

## Raw Data Rules

1. **Immutable**: Once written, `data/raw/` files are NEVER modified or overwritten.
2. **Versioned**: If you need a corrected version, create a new file with a version suffix (e.g., `results_v2.csv`) and document why.
3. **Deletion forbidden**: NEVER `rm data/raw/*`. Move to `data/archived/` with a note.
4. **Script-traceable**: Every data file MUST link to the script that produced it via `"runner": "<script>"` in results metadata.

## Validation Checklist

Before a finding is considered reviewed:

- [ ] Raw data file exists at the declared `DATA_FILE` path
- [ ] SHA-256 hash matches the declared `DATA_HASH`
- [ ] Row count matches the declared `N` in the finding
- [ ] No suspiciously clean patterns (all identical values, perfect round numbers)
- [ ] Producing script is committed alongside data

## Verification Script Pattern

```bash
#!/usr/bin/env bash
set -euo pipefail

DATA_FILE="$1"
EXPECTED_HASH="$2"
EXPECTED_N="$3"

# Verify hash
ACTUAL_HASH=$(shasum -a 256 "$DATA_FILE" | cut -d' ' -f1)
if [[ "$ACTUAL_HASH" != "$EXPECTED_HASH" ]]; then
  echo "HASH_MISMATCH: expected $EXPECTED_HASH, got $ACTUAL_HASH"
  exit 1
fi

# Verify row count (excluding header)
ACTUAL_N=$(($(wc -l < "$DATA_FILE") - 1))
if [[ "$ACTUAL_N" -ne "$EXPECTED_N" ]]; then
  echo "ROW_COUNT_MISMATCH: expected $EXPECTED_N, got $ACTUAL_N"
  exit 1
fi

echo "VERIFIED: hash and row count match"
```

## Cross-Agent Data Sharing

When one agent's output is another agent's input:
1. Source agent commits data + hash to its worktree.
2. Orchestrator merges the source branch before dispatching the dependent agent.
3. Dependent agent verifies the hash before using the data.
4. Both agents record the same `DATA_HASH` — any mismatch flags a merge issue.
