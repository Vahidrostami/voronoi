# Agent Instructions

## Task Tracking — MANDATORY
This project uses Beads (bd) for ALL planning and task tracking.
- Run `bd prime` at session start to get context
- Check `bd ready` for available work
- Claim work: `bd update <id> --claim`
- Log progress: `bd update <id> --notes "what you did"`
- Close work: `bd close <id> --reason "summary of what was built"`
- NEVER create markdown plan files. Beads is the plan.
- NEVER use `bd edit` (opens interactive editor). Use `bd update` with flags.

## Git Discipline — MANDATORY
- ALWAYS push before ending a session. Unpushed work = lost work.
- NEVER say "ready to push when you are." YOU push. NOW.
- Commit early and often with clear messages.
- If push fails, rebase and retry until it succeeds.

## Multi-Agent Awareness
- You are one of multiple agents working in parallel.
- Work ONLY in your assigned worktree directory.
- Do NOT touch files outside your scope.
- If you discover work that belongs to another agent, file a Beads issue:
  `bd create "Discovered: [description]" -t task -p 2 --notes "Found while working on [your task]"`
- Check `bd list --blocked` to understand the dependency graph.

## Quality Standards
- Write tests for everything you build.
- Run the test suite before closing a task.
- Leave the codebase cleaner than you found it.
