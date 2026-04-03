---
name: 'Data Integrity Rules'
description: 'Rules for handling raw and processed data files: hashing, preservation, provenance'
applyTo: 'data/**'
---
# Data File Rules — MANDATORY

## Raw Data Preservation
- Files in `data/raw/` are **immutable** after creation. NEVER modify or overwrite raw data.
- Processed data goes in `data/processed/`. Figures go in `data/figures/`.
- Every raw data file MUST have its SHA-256 hash computed immediately after creation.

## Hash Integrity
```bash
shasum -a 256 data/raw/<file>.csv
```
Record the hash in the corresponding Beads finding:
```bash
bd update <finding-id> --notes "DATA_HASH:sha256:<hash>"
```

## Provenance
- Every data file MUST be traceable to the script that produced it.
- The producing script MUST be committed alongside the data.
- If data comes from an external source, document the URL, access date, and retrieval method.

## Deletion Protection
- NEVER run `rm -rf data/raw/` or `rm data/raw/*`.
- To discard a dataset, move it to `data/archived/` with a note explaining why.
