---
name: 'Shell Script & LLM Call Rules'
description: 'Rules for shell scripts and programmatic LLM calls via Copilot CLI'
applyTo: '**/*.sh,scripts/**'
---
# Shell Script Rules

## LLM Calls via Copilot CLI
When scripts need programmatic LLM calls (e.g., discovery, judge), use:
```bash
LLM_MODEL=$(jq -r '.worker_model // ""' .swarm-config.json 2>/dev/null)
MODEL_FLAG=""
if [[ -n "$LLM_MODEL" ]]; then MODEL_FLAG="--model $LLM_MODEL"; fi

copilot $MODEL_FLAG -p "<prompt>" -s --no-color --allow-all
```

### Mandatory Rules
- Pass the prompt as a **direct argument** to `-p`, NOT via stdin.
- **NEVER** use `echo "..." | copilot -p -` or pipe/stdin patterns — they produce empty/generic responses.
- **ALWAYS** include the `--model` flag from `.swarm-config.json` — without it, copilot uses its default model.
- Cache responses by SHA-256 hash of the prompt text.
- The prompt MUST be a single shell-quoted string argument to `-p`.

## Script Conventions
- Always `set -euo pipefail` at the top of scripts.
- Read configuration from `.swarm-config.json` using `jq`.
- Scripts must be idempotent — safe to run multiple times.
- Use `#!/usr/bin/env bash` for portability.
