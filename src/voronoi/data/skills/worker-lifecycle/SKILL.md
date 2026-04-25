---
name: worker-lifecycle
description: >
  Complete recipe for dispatching, monitoring, merging, and cleaning up
  worker agents. Read this skill BEFORE dispatching any worker.
  Covers build_worker_prompt, spawn-agent.sh, merge-agent.sh, checkpoint
  updates, and common failure modes.
user-invocable: true
disable-model-invocation: false
---

# Worker Lifecycle — Dispatch · Monitor · Merge · Cleanup

Read this skill **every time** you need to dispatch a worker agent.

## CRITICAL — Do NOT Use Built-in Agent Tools

**NEVER** use Copilot's built-in "General-purpose agent" or "Read" tools to run
experiments or worker tasks. These run inline in YOUR session, consuming YOUR
context window with idle output.

**ALWAYS** use `./scripts/spawn-agent.sh` — it creates an isolated tmux window
with a fresh Copilot instance and its own context budget.

## Step 1: Create the Task in Beads

```bash
bd create "Task title" --priority 1
# Note the task ID (e.g., bd-42)
bd update bd-42 --notes "TASK_TYPE:investigation
PRODUCES: data/results.json, data/analysis.csv
REQUIRES: data/raw/input.csv
BRIEFING: <detailed instructions for the worker>"
```

## Step 2: Build the Worker Prompt

Use `build_worker_prompt()` to assemble the prompt — it injects the correct
role file, skills, and project context automatically.

```bash
python3 -c "
from voronoi.server.prompt import build_worker_prompt
prompt = build_worker_prompt(
    task_type='investigation',   # investigation|experiment|scout|scribe|paper
    task_id='bd-42',
    branch='agent-phase2',
    briefing='''
    Run the factorial experiment across 3 models x 3 positions.
    Write results to data/results.json with SHA-256 hashes.
    Expected runtime: ~30 minutes.
    ''',
    workspace_path='$(pwd)',
    produces='data/results.json, data/analysis.csv',
    requires='data/raw/input.csv',
)
open('/tmp/prompt-agent-phase2.txt', 'w').write(prompt)
"
```

### Task Types → Agent Roles

| task_type | Agent role loaded | When to use |
|-----------|-------------------|-------------|
| `investigation` | investigator | Pre-registered experiments, sensitivity analysis |
| `experiment` | investigator | Generic experiment execution |
| `scout` | scout | Prior knowledge research, SOTA anchoring |
| `exploration` | explorer | Option evaluation, comparison matrices |
| `scribe` | scribe | LaTeX paper writing, figure generation |
| `paper` | worker | Generic paper/doc tasks |
| `compilation` | worker | LaTeX compilation, build tasks |

## Step 3: Spawn the Worker

```bash
./scripts/spawn-agent.sh bd-42 agent-phase2 /tmp/prompt-agent-phase2.txt
```

This will:
1. Create a git worktree at `$SWARM_DIR/agent-phase2`
2. Open a new tmux window in the swarm session
3. Launch Copilot CLI with the prompt file
4. Claim the Beads task (`bd update bd-42 --claim`)

### Safe Mode (restricted tool access)

```bash
./scripts/spawn-agent.sh --safe bd-42 agent-phase2 /tmp/prompt-agent-phase2.txt
```

### What spawn-agent.sh Validates

- REQUIRES files must exist (rejects dispatch if missing)
- Paper/scribe tasks are blocked while DESIGN_INVALID tasks are open
- Agent CLI must be on PATH

## Step 4: Update Your Checkpoint

After dispatching, write the checkpoint so the dispatcher knows you have
active workers. **The file MUST be named `orchestrator-checkpoint.json`** —
the dispatcher looks for this exact name.

```bash
cat > .swarm/orchestrator-checkpoint.json << 'CHECKPOINT'
{
  "cycle": 1,
  "phase": "experiment_execution",
  "active_workers": ["agent-phase2", "agent-phase3"],
  "next_actions": ["Wait for experiments", "Then run ANOVA analysis"],
  "total_tasks": 10,
  "closed_tasks": 2
}
CHECKPOINT
```

**Then EXIT cleanly.** The dispatcher will restart you when all workers finish.
Do NOT idle-loop waiting — that wastes your entire context window.

## Step 5: Merge Completed Work

When a worker exits, merge its branch back to main:

```bash
./scripts/merge-agent.sh agent-phase2 bd-42
```

This will:
1. Push the worker's branch to remote (safety net)
2. Merge the branch into main
3. Remove the git worktree
4. Close the Beads task (`bd close bd-42`)

### Handling Merge Conflicts

If merge fails, the script will abort. You should:
1. Check the worker's branch: `git log agent-phase2 --oneline -5`
2. Try manual merge: `git merge agent-phase2 --no-ff`
3. If conflict is in data files, keep the worker's version
4. If conflict is structural, dispatch a new worker to resolve

## Step 6: Cleanup

After all workers are merged and the investigation is complete:

```bash
./scripts/teardown.sh
```

This kills tmux sessions and prunes orphaned worktrees/branches.

## Common Failure Modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Worker exits immediately | Missing REQUIRES files | Check file paths, dispatch prerequisite task first |
| Worker loops on same error | Bug in experiment code | Read worker's tmux output, dispatch fix worker |
| Merge rejected | PRODUCES files missing | Worker didn't complete — re-dispatch or fix manually |
| "Agent CLI not found" | Copilot not on PATH | Check `which copilot`, verify auth with `copilot --version` |
| Worker runs but no commits | Worker is stuck | Check health: `/voronoi health`, consider abort + re-dispatch |

## Anti-Patterns — NEVER Do These

| Anti-pattern | Why it's bad | Do this instead |
|-------------|-------------|-----------------|
| Run experiment inline in orchestrator | Burns orchestrator context with idle output | Dispatch a worker |
| `sleep 600 && check` loops | 30%+ context wasted on zero-information polling | Write checkpoint, exit, let dispatcher restart you |
| Use built-in "General-purpose agent" | Runs in YOUR session, not isolated | Use `spawn-agent.sh` |
| Copy role files into prompt manually | Stale, error-prone, context-bloating | Use `build_worker_prompt()` |
| Enter worker's worktree to fix code | Violates isolation, causes merge conflicts | Dispatch new fix worker |
