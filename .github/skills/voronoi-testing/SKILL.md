---
name: voronoi-testing
description: "Use when writing, updating, or running tests for voronoi. Use when any source code in src/voronoi/ is modified to ensure tests are updated. Covers test discovery, naming conventions, and verification workflow."
---
# Voronoi Testing Workflow

## When to Use

Every time you modify code in `src/voronoi/`, you MUST follow this workflow.

## Test File Discovery

Tests follow a naming convention — find the test file by module name:

```
src/voronoi/<module>.py        → tests/test_<module>.py
src/voronoi/gateway/<module>.py → tests/test_<module>.py
src/voronoi/server/<module>.py  → tests/test_<module>.py
src/voronoi/science/<module>.py → tests/test_science.py  (all science in one file)
src/voronoi/mcp/<module>.py     → tests/test_mcp.py      (all MCP in one file)
```

**Exceptions** (check these if the convention doesn't match):
- `server/prompt.py` → `test_unified_prompt.py` + `test_worker_prompt.py`
- `gateway/router.py` → `test_bridge.py` + integration tests
- `mcp/validators.py`, `mcp/tools_beads.py`, `mcp/tools_swarm.py` → all in `test_mcp.py`

**When in doubt**: run `ls tests/test_*<module>*.py` or `grep -rl '<function_name>' tests/` to find the right file.

## Workflow

### After ANY code change:

1. **Run the specific test file** for the module you changed:
   ```bash
   python -m pytest tests/test_<module>.py -x -q
   ```

2. **Run the full suite** to catch cross-module regressions:
   ```bash
   python -m pytest tests/ -x -q
   ```

3. **If tests fail**: fix the code or update the test — do NOT commit with failing tests.

### If you changed behavior:

4. **Update existing tests** to match new behavior
5. **Add new tests** for new functionality — in the same commit as the code change

### Test conventions:

- Use `pytest` with `tmp_path` fixture for filesystem tests
- Use `unittest.mock.patch` for isolating dependencies
- Use `subprocess.run` tests for CLI integration tests
- No runtime dependencies in tests — mock external tools (bd, copilot, docker)
- Test classes group related tests: `class TestFeatureX:`

## Verification Checklist

Before committing, confirm:
- [ ] Specific module tests pass
- [ ] Full test suite passes (829+ tests, all green)
- [ ] New behavior has corresponding test coverage
- [ ] No test depends on external services or network
