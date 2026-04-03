---
name: 'Test File Rules'
description: 'Quality standards for test files in investigation workspaces'
applyTo: 'tests/**'
---
# Test File Rules

## Quality Standards
- Write tests for everything you build.
- Run the test suite before closing a task.
- Leave the codebase cleaner than you found it.

## No Simulation in Tests
- Tests MUST exercise real code paths. No mock data that replaces real computation.
- Use `unittest.mock` only to stub external services (network, LLM APIs) — never to skip computation.
- Test assertions MUST verify actual computed values, not hardcoded expected outputs.

## Test-Before-Close Protocol
Before closing any Beads task:
```bash
python -m pytest tests/ -x -q   # or the project's test command
```
If tests fail, fix them before marking the task as closed.
