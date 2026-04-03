---
name: context-management
description: >
  Skill for context window management in long-running agent sessions. Prevents
  context exhaustion through proactive compression and delegation. Used by
  orchestrators and long-running worker agents.
---

# Context Management Skill

Preventing context exhaustion in long-running investigations.

## When to Use

Use this skill when:
- Running investigations expected to span many OODA cycles
- The dispatcher sends a `context_warning` or `context_critical` directive
- You notice degraded reasoning, forgotten findings, or repeated work

## The Problem This Solves

Long investigations accumulate 30+ OODA cycles of tool calls, reasoning, and
outputs. Without management, agents lose strategic reasoning ability after
exhausting their context window. Checkpoint files preserve state on disk, but
the agent's conversation memory — the accumulated reasoning chain — fills up
and cannot be recovered without intervention.

## /compact — Native Context Compression

When context pressure is detected (by dispatcher directive or self-monitoring):

```
/compact
```

This compresses your conversation history in-place, recovering 60-70% of
context budget without restarting. Checkpoint files and `.swarm/` state survive
because they're on disk, not in conversation context.

## Self-Monitoring Protocol

1. At the **start of every OODA cycle**, run `/context` to get ground-truth token usage
2. Parse the output and include the snapshot in your checkpoint:

```
/context
```

This outputs something like:

```
● Context Usage
  claude-opus-4.6 · 50k/200k tokens (25%)
  ○ System/Tools:  22.6k (11%)
  ◉ Messages:      27.3k (14%)
  · Free Space:   109.6k (55%)
  ◎ Buffer:        40.4k (20%)
```

3. Extract these values and pass them in your `voronoi_write_checkpoint` call:

```json
{
  "context_snapshot": {
    "model": "claude-opus-4.6",
    "model_limit": 200000,
    "total_used": 50000,
    "system_tokens": 22600,
    "message_tokens": 27300,
    "free_tokens": 109600,
    "buffer_tokens": 40400
  }
}
```

4. The dispatcher reads this snapshot and:
   - Logs it to `events.jsonl` for timeline analysis
   - Auto-derives `context_window_remaining_pct` from `free_tokens / model_limit`
   - Triggers pressure directives based on **actual usage** instead of time heuristics

5. If you notice forgetting earlier findings or repeating work:
   - Run `/context` to check token usage
   - If messages exceed 70% of the window, run `/compact` proactively
6. After running `/compact`, re-read your checkpoint to restore strategic context
7. If still above 90% after compacting, delegate remaining work to fresh agents

## Dispatcher Directive Response

When you read `.swarm/dispatcher-directive.json`:

| Directive | Required Action |
|-----------|----------------|
| `context_advisory` | Prioritize convergence, avoid opening new threads |
| `context_warning` | Run `/compact` NOW, then delegate remaining work to fresh agents |
| `context_critical` | Run `/compact` NOW, write checkpoint, dispatch Scribe immediately |

## Complementary Mechanisms

| Mechanism | What It Compresses | When |
|-----------|-------------------|------|
| `/compact` (you run this) | Your conversation history (context window) | On directive or self-detected pressure |
| Checkpoint files | Strategic state snapshot on disk | Every OODA cycle |
| Targeted `bd query` | Avoids loading full task list into context | Routine cycles (never `bd list --json`) |
| Belief map compression | Hypothesis space | When >10 hypotheses active |

## Key Principle

Checkpoint + file state survives `/compact` because they're on disk, not in
conversation context. The agent reads checkpoint at each OODA cycle start, so
compacted conversation history doesn't lose critical state — only the raw
reasoning chain is summarized.
