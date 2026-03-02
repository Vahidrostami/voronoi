# Platform Unification: GitHub Copilot ↔ Claude Code

> How to maintain a single `.github/` configuration that works for both platforms
> via symlinks and the shared Agent Skills open standard.

---

## 1. Architecture Quick-View

```
repo-root/
├── .github/                    ← Canonical source of truth
│   ├── agents/                 ← Custom agents (.agent.md)
│   ├── prompts/                ← Slash-command prompts (.prompt.md)
│   ├── skills/                 ← Agent Skills (SKILL.md per dir)
│   ├── hooks/                  ← Hook configs (.json)
│   ├── instructions/           ← Path-scoped instructions (.instructions.md)
│   ├── copilot-instructions.md ← Repo-wide Copilot instructions
│   └── workflows/              ← GitHub Actions
│
├── .claude/                    ← Symlinks + Claude-only overrides
│   ├── agents   → ../.github/agents       (symlink)
│   ├── skills   → ../.github/skills       (symlink)
│   ├── settings.json           ← Claude-specific (hooks, permissions)
│   └── settings.local.json     ← Local overrides (gitignored)
│
├── CLAUDE.md                   ← Project memory (Claude Code reads this)
├── AGENTS.md                   ← Agent context (both platforms read this)
└── .mcp.json                   ← MCP server config (Claude Code)
```

---

## 2. Feature Comparison Matrix

| Capability | GitHub Copilot / VS Code | Claude Code | Shared? |
|---|---|---|---|
| **Custom Agents** | `.github/agents/*.agent.md` | `.claude/agents/*.md` | ✅ Yes — VS Code reads `.claude/agents/*.md` too |
| **Skills** | `.github/skills/*/SKILL.md` | `.claude/skills/*/SKILL.md` | ✅ Identical — Agent Skills open standard |
| **Prompts / Commands** | `.github/prompts/*.prompt.md` | `.claude/commands/*.md` (legacy → skills) | ⚠️ Similar concept, different format |
| **Instructions** | `.github/copilot-instructions.md` + `.github/instructions/*.instructions.md` | `CLAUDE.md` + `.claude/rules/*.md` | ❌ Different — requires dual files |
| **Hooks** | `.github/hooks/*.json` | `.claude/settings.json` `hooks:` key | ✅ Same JSON format, different locations |
| **MCP Servers** | VS Code settings or `.github/` | `.mcp.json` (project) / `~/.claude.json` (user) | ⚠️ Partial overlap |
| **Root Context File** | `AGENTS.md` (nearest in tree wins) | `CLAUDE.md` (project root) | ❌ Both read their own, but VS Code also reads `CLAUDE.md` |

---

## 3. Deep Dive: Each Config Type

### 3.1 Custom Agents

**VS Code format** (`.github/agents/planner.agent.md`):
```yaml
---
name: planner
description: Creates implementation plans from feature requests
tools: ["search", "read", "fetch"]
model: Claude Sonnet 4.5 (copilot)
user-invokable: true
disable-model-invocation: false
agents: ["*"]
handoffs:
  - label: Start Implementation
    agent: implementer
    prompt: Implement the plan above.
    send: false
---

# Planner Agent
Your instructions here...
```

**Claude Code format** (`.claude/agents/planner.md`):
```yaml
---
name: planner
description: Creates implementation plans from feature requests
tools: Read, Grep, Glob, LS, Bash
model: claude-sonnet-4-5-20250514
permissionMode: plan
maxTurns: 50
skills:
  - task-planning
mcpServers:
  - github
hooks:
  PreToolUse:
    - type: command
      command: ./scripts/validate.sh
memory:
  - CLAUDE.md
---

# Planner Agent
Your instructions here...
```

**Key differences:**

| Field | VS Code | Claude Code | Notes |
|---|---|---|---|
| File extension | `.agent.md` | `.md` | VS Code detects any `.md` in `.claude/agents/` |
| `tools` | YAML array of VS Code tool IDs | Comma-separated string of Claude tool names | VS Code auto-maps Claude tool names |
| `model` | `"Model Name (vendor)"` | Model API identifier | Platform-specific |
| `handoffs` | Supported | Not supported | VS Code only |
| `permissionMode` | Not supported | `plan`, `bypassPermissions`, etc. | Claude only |
| `maxTurns` | Not supported | Integer | Claude only |
| `skills` | Not in agent frontmatter | Supported | Claude can scope skills per agent |
| `mcpServers` | `mcp-servers` (for `target: github-copilot`) | Supported | Different key name |
| `hooks` | Not in agent frontmatter | Supported | Claude allows per-agent hooks |
| `memory` | Not supported | Files to include as context | Claude only |
| `agents` | List of sub-agent names | Not supported | VS Code sub-agent allowlist |

**Unification strategy:** Write agents in the **VS Code `.agent.md` format** using the shared subset of frontmatter fields (`name`, `description`, `tools` as YAML array, `user-invokable`, `disable-model-invocation`). VS Code reads `.claude/agents/` natively, so symlink `.claude/agents/ → .github/agents/` and both platforms will discover the same agents. Platform-specific fields are silently ignored by the other platform.

---

### 3.2 Agent Skills (SKILL.md) — Fully Shared

Both platforms implement the **[Agent Skills open standard](https://agentskills.io/)**.

**Canonical format** (`.github/skills/beads-tracking/SKILL.md`):
```yaml
---
name: beads-tracking
description: >
  Skill for using Beads (bd) issue tracking system. Use when
  managing tasks, dependencies, epics, and work queues.
---

# Beads Tracking
Step-by-step instructions...
```

**Standard fields (agentskills.io spec):**

| Field | Required | Max Length | Notes |
|---|---|---|---|
| `name` | Yes | 64 chars | Lowercase + hyphens, must match directory name |
| `description` | Yes | 1024 chars | What it does + when to use it |
| `license` | No | — | License name or file reference |
| `compatibility` | No | 500 chars | Environment requirements |
| `metadata` | No | — | Arbitrary key-value pairs |
| `allowed-tools` | No | — | Space-delimited pre-approved tools (experimental) |

**Platform extensions** (non-standard, platform-specific):

| Field | Platform | Purpose |
|---|---|---|
| `argument-hint` | Both | Hint text for slash-command input |
| `user-invocable` | Both | Show in `/` menu (default: true) |
| `disable-model-invocation` | Both | Prevent auto-loading (default: false) |
| `model` | Claude Code | Override model for this skill |
| `context` | Claude Code | `fork` = run as subagent |
| `agent` | Claude Code | Run within a specific agent |
| `hooks` | Claude Code | Per-skill hook configuration |

**Discovery locations:**

| Platform | Paths Searched |
|---|---|
| VS Code | `.github/skills/`, `.claude/skills/`, `.agents/skills/`, `~/.copilot/skills/`, `~/.claude/skills/`, `~/.agents/skills/` + custom via `chat.agentSkillsLocations` |
| Claude Code | `.claude/skills/` |

**Unification strategy:** Keep skills in `.github/skills/`. Symlink `.claude/skills/ → .github/skills/`. Both platforms discover them. Use only standard + shared extension fields in frontmatter for maximum portability.

---

### 3.3 Prompts / Commands

**VS Code** uses `.prompt.md` files as reusable slash commands:
```yaml
---
name: swarm
description: Plan and dispatch a multi-agent workload
agent: agent
tools: [execute, read, search, edit, github/*]
argument-hint: Describe the feature or epic to plan
---

# Instructions here...
```

**Claude Code** historically used `.claude/commands/*.md` but these have been **merged into skills**. A skill with `user-invocable: true` and `argument-hint` behaves identically to a prompt/command.

**Unification strategy:** Use **skills** for anything that needs cross-platform portability. Use `.prompt.md` files only for VS Code-specific features (like `agent:` field to target a specific custom agent, or `${input:variable}` syntax).

---

### 3.4 Instructions / Memory

**VS Code:**
- `AGENTS.md` — Nearest-in-tree context file (VS Code also reads `CLAUDE.md` in root)
- `.github/copilot-instructions.md` — Repo-wide instructions (always applied)
- `.github/instructions/NAME.instructions.md` — Path-scoped with frontmatter:
  ```yaml
  ---
  applyTo: "src/**/*.ts"
  excludeAgent: ["planner"]
  ---
  Use strict TypeScript. No `any` types.
  ```

**Claude Code:**
- `CLAUDE.md` — Project root (or `.claude/CLAUDE.md`)
- `~/.claude/CLAUDE.md` — User-level
- `.claude/rules/*.md` — Path-scoped with frontmatter:
  ```yaml
  ---
  paths:
    - "src/**/*.ts"
  ---
  Use strict TypeScript. No `any` types.
  ```

**Unification strategy:** Maintain both:
1. `CLAUDE.md` at repo root — Claude Code reads it natively; VS Code reads it too
2. `.github/copilot-instructions.md` — Copilot-only instructions (can `@import` CLAUDE.md content or keep minimal)
3. `AGENTS.md` at repo root — Keep as thin pointer to `CLAUDE.md`
4. Path-scoped rules: Keep in `.github/instructions/` for Copilot and symlink/duplicate to `.claude/rules/` for Claude Code (frontmatter differs: `applyTo` vs `paths`)

---

### 3.5 Hooks — Same Format, Different Locations

Both platforms use the **same JSON hook schema** (VS Code explicitly documents Claude Code compatibility).

**Hook JSON format (shared):**
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "type": "command",
        "command": "./scripts/validate-tool.sh",
        "timeout": 15
      }
    ],
    "PostToolUse": [
      {
        "type": "command",
        "command": "npx prettier --write \"$TOOL_INPUT_FILE_PATH\""
      }
    ]
  }
}
```

**Hook events comparison:**

| Event | VS Code | Claude Code |
|---|---|---|
| `SessionStart` | ✅ | ✅ |
| `UserPromptSubmit` | ✅ | ✅ |
| `PreToolUse` | ✅ | ✅ (with matchers) |
| `PostToolUse` | ✅ | ✅ (with matchers) |
| `PostToolUseFailure` | ❌ | ✅ |
| `PreCompact` | ✅ | ✅ |
| `SubagentStart` | ✅ | ✅ |
| `SubagentStop` | ✅ | ✅ |
| `Stop` | ✅ | ✅ |
| `Notification` | ❌ | ✅ |
| `PermissionRequest` | ❌ | ✅ |
| `TeammateIdle` | ❌ | ✅ |
| `TaskCompleted` | ❌ | ✅ |
| `ConfigChange` | ❌ | ✅ |
| `WorktreeCreate` | ❌ | ✅ |
| `WorktreeRemove` | ❌ | ✅ |
| `SessionEnd` | ❌ | ✅ |

**Where hooks live:**

| Platform | Location | Notes |
|---|---|---|
| VS Code | `.github/hooks/*.json` | Project-shared hooks |
| VS Code | `.claude/settings.json` | VS Code reads Claude's hook config too! |
| VS Code | `.claude/settings.local.json` | Local overrides |
| Claude Code | `.claude/settings.json` | Primary hook config |
| Claude Code | `.claude/settings.local.json` | Local overrides (gitignored) |

**Unification strategy:** Put shared hooks in `.claude/settings.json` — both VS Code and Claude Code read this location. VS Code auto-parses Claude Code's hook format including matcher syntax (though it currently ignores matcher values). For VS Code-only hooks, use `.github/hooks/*.json`.

---

### 3.6 MCP Servers

**VS Code:** Configured in VS Code settings (`settings.json`) or `.github/` directory.

**Claude Code:** `.mcp.json` at project root (project-scoped) or `~/.claude.json` (user-scoped).

**Unification strategy:** Use `.mcp.json` at project root for shared MCP servers. Both platforms can read this.

---

## 4. Symlink Setup Script

```bash
#!/usr/bin/env bash
# setup-symlinks.sh — Create .claude/ symlinks pointing to .github/ configs

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

mkdir -p .claude

# Skills — identical format (Agent Skills open standard)
if [[ ! -L .claude/skills ]] && [[ ! -d .claude/skills ]]; then
  ln -s ../.github/skills .claude/skills
  echo "✓ Symlinked .claude/skills → .github/skills"
fi

# Agents — VS Code reads .claude/agents/*.md natively
if [[ ! -L .claude/agents ]] && [[ ! -d .claude/agents ]]; then
  ln -s ../.github/agents .claude/agents
  echo "✓ Symlinked .claude/agents → .github/agents"
fi

# Hooks — VS Code reads .claude/settings.json hook format
# (Keep .claude/settings.json as a real file, not symlink — it has Claude-specific fields)

echo ""
echo "Symlinks created. Both platforms now share:"
echo "  - Agents:  .github/agents/ (canonical)"
echo "  - Skills:  .github/skills/ (canonical)"
echo ""
echo "Platform-specific files (no symlink):"
echo "  - .claude/settings.json       — Claude hooks, permissions"
echo "  - .github/hooks/*.json        — VS Code-only hooks"
echo "  - .github/copilot-instructions.md — Copilot instructions"
echo "  - CLAUDE.md                   — Claude Code memory"
```

---

## 5. What Can Be Shared vs What Cannot

### ✅ Fully Shared (symlink-safe)

| Asset | Why |
|---|---|
| **Skills** (`SKILL.md`) | Identical open standard; both platforms search both directories |
| **Agents** (with caveats) | VS Code reads `.claude/agents/*.md`; platform-specific frontmatter is silently ignored |
| **Hook JSON format** | Same schema; VS Code documents Claude Code format compatibility |

### ⚠️ Partially Shared (need adapter or dual files)

| Asset | Issue | Solution |
|---|---|---|
| **Prompts** | `.prompt.md` is VS Code-only; Claude uses skills | Convert shared prompts to skills; keep VS Code-specific ones as `.prompt.md` |
| **Path-scoped rules** | Different frontmatter (`applyTo` vs `paths`) | Maintain in both directories, or script a converter |
| **MCP config** | Different file locations | Use `.mcp.json` at root (Claude reads it; VS Code can be configured) |

### ❌ Cannot Be Shared (platform-specific)

| Asset | Platform | Why |
|---|---|---|
| `.github/copilot-instructions.md` | VS Code only | Copilot-specific repo-wide instructions |
| `CLAUDE.md` | Claude Code primary | Claude's memory system; VS Code reads but doesn't write |
| `.claude/settings.json` (non-hook fields) | Claude Code only | Permissions, sandbox, env, allowed tools |
| `handoffs` in agent frontmatter | VS Code only | Agent-to-agent workflow transitions |
| `permissionMode`, `maxTurns` in agents | Claude Code only | Execution control |
| VS Code `${input:variable}` in prompts | VS Code only | Interactive variable substitution |

---

## 6. Recommended Frontmatter: Portable Agent Template

Use this template for agents that work on both platforms:

```yaml
---
name: my-agent
description: What this agent does and when to invoke it
tools: ["read", "search", "edit", "execute"]
user-invokable: true
disable-model-invocation: false
---

# My Agent

Instructions that work on both platforms...
```

**Rules for portable agents:**
1. Use **YAML arrays** for `tools` (VS Code format) — Claude Code also accepts this
2. Use generic tool names: `read`, `search`, `edit`, `execute` — both platforms map these
3. Avoid platform-specific fields (`handoffs`, `permissionMode`, `maxTurns`, `agents`)
4. Keep the file extension as `.agent.md` in `.github/agents/` (VS Code canonical) — symlink to `.claude/agents/`
5. If you need platform-specific behavior, add it in the body text with conditional notes

---

## 7. Recommended Frontmatter: Portable Skill Template

```yaml
---
name: my-skill
description: >
  What this skill does. When to use it. Keywords for discovery.
---

# My Skill

Step-by-step instructions here.
Reference files: [helper script](./scripts/helper.sh)
```

**Rules for portable skills:**
1. Only use fields from the **agentskills.io spec**: `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`
2. Extension fields (`argument-hint`, `user-invocable`, `disable-model-invocation`) are supported by both platforms
3. Avoid Claude-only extensions (`model`, `context`, `agent`, `hooks`) unless you only need Claude Code
4. Keep `SKILL.md` under 500 lines; put details in `references/` subdirectory

---

## 8. This Repo's Current State

Our `.github/` directory already follows the portable pattern:

```
.github/
├── agents/
│   ├── swarm-orchestrator.agent.md   ← Tools as YAML array ✅
│   └── worker-agent.agent.md         ← disable-model-invocation ✅
├── prompts/
│   ├── swarm.prompt.md               ← VS Code-specific (has agent: field)
│   ├── spawn.prompt.md
│   ├── merge.prompt.md
│   ├── standup.prompt.md
│   ├── progress.prompt.md
│   └── teardown.prompt.md
├── skills/
│   ├── beads-tracking/SKILL.md       ← Standard format ✅
│   ├── task-planning/SKILL.md        ← Standard format ✅
│   ├── branch-merging/SKILL.md       ← Standard format ✅
│   ├── agent-standup/SKILL.md        ← Standard format ✅
│   └── git-worktree-management/SKILL.md ← Standard format ✅
└── workflows/
    ├── agent-ci.yml
    └── daily-standup.yml
```

**Action items to complete unification:**
1. Run `setup-symlinks.sh` to create `.claude/agents` and `.claude/skills` symlinks
2. Create `.claude/settings.json` with shared hook definitions
3. Ensure `CLAUDE.md` imports or mirrors key content from `.github/copilot-instructions.md`
4. Convert any prompts that need Claude Code portability into skills
5. Add symlink setup to `scripts/swarm-init.sh`

---

## 9. References

- [VS Code Custom Agents](https://code.visualstudio.com/docs/copilot/customization/custom-agents)
- [VS Code Agent Skills](https://code.visualstudio.com/docs/copilot/customization/agent-skills)
- [VS Code Prompt Files](https://code.visualstudio.com/docs/copilot/customization/prompt-files)
- [VS Code Hooks](https://code.visualstudio.com/docs/copilot/customization/hooks)
- [VS Code Custom Instructions](https://code.visualstudio.com/docs/copilot/customization/custom-instructions)
- [Claude Code Sub-Agents](https://code.claude.com/docs/en/sub-agents)
- [Claude Code Skills](https://code.claude.com/docs/en/skills)
- [Claude Code Hooks](https://code.claude.com/docs/en/hooks)
- [Claude Code Settings](https://code.claude.com/docs/en/settings)
- [Claude Code Memory (CLAUDE.md)](https://code.claude.com/docs/en/memory)
- [Agent Skills Specification](https://agentskills.io/specification)
