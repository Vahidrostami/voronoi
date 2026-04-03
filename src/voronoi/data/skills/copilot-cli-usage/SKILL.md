---
name: copilot-cli-usage
description: >
  Skill for making programmatic LLM calls via Copilot CLI.
  Covers correct invocation patterns, model configuration, caching,
  and common error recovery. Use when any agent or script needs
  to call an LLM programmatically.
---

# Copilot CLI Usage

Use this skill when scripts or agents need to make programmatic LLM calls.

## Correct Invocation Pattern

```bash
# 1. Read configured model from workspace config
LLM_MODEL=$(jq -r '.worker_model // ""' .swarm-config.json 2>/dev/null)
MODEL_FLAG=""
if [[ -n "$LLM_MODEL" ]]; then MODEL_FLAG="--model $LLM_MODEL"; fi

# 2. Call Copilot with the prompt as a direct argument
copilot $MODEL_FLAG -p "<your prompt here>" -s --no-color --allow-all
```

## Mandatory Rules

| Rule | Why |
|------|-----|
| Prompt is a **direct argument** to `-p` | Stdin/pipe patterns produce empty responses |
| **NEVER** `echo "..." \| copilot -p -` | Pipe/stdin = broken |
| **ALWAYS** include `--model` from config | Without it, copilot uses its default model |
| Cache by SHA-256 of prompt text | Avoid redundant API calls |
| Prompt is a **single shell-quoted string** | Prevents shell expansion issues |

## Common Anti-Patterns

```bash
# WRONG — pipe to stdin
echo "Analyze this data" | copilot -p -

# WRONG — missing model flag
copilot -p "Analyze this data" -s --no-color

# WRONG — unquoted prompt
copilot -p Analyze this data -s --no-color

# RIGHT
copilot $MODEL_FLAG -p "Analyze this data" -s --no-color --allow-all
```

## Response Caching

Cache LLM responses to avoid redundant API calls:

```bash
PROMPT="Your prompt text here"
CACHE_KEY=$(echo -n "$PROMPT" | shasum -a 256 | cut -d' ' -f1)
CACHE_FILE=".cache/llm/${CACHE_KEY}.txt"

if [[ -f "$CACHE_FILE" ]]; then
  RESPONSE=$(cat "$CACHE_FILE")
else
  mkdir -p .cache/llm
  RESPONSE=$(copilot $MODEL_FLAG -p "$PROMPT" -s --no-color --allow-all)
  echo "$RESPONSE" > "$CACHE_FILE"
fi
```

## Error Recovery

| Error | Fix |
|-------|-----|
| Empty response | Check `--model` flag is set; verify prompt is passed as arg, not pipe |
| Auth failure | Check `COPILOT_HOME` and `GH_HOST` env vars; run `copilot /login` |
| Rate limit | Wait and retry with exponential backoff; check cache first |
| Timeout | Reduce prompt size; split into sub-prompts |

## Batch Calls

For experiments requiring multiple LLM calls:
1. Estimate total calls **before starting**.
2. If > 50 calls, consider reducing sample size.
3. Cache aggressively — same prompt = same cache key.
4. Log every call to `.swarm/events.jsonl` for audit trail.
