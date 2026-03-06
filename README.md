<div align="center">

# 🔬 Voronoi

### Science-first multi-agent orchestration

**Ask a question on Telegram. Get a research paper.**

<br/>

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Copilot](https://img.shields.io/badge/GitHub_Copilot-Powered-000?style=flat-square&logo=github&logoColor=white)](https://github.com/features/copilot)
[![Telegram](https://img.shields.io/badge/Telegram-26A5E4?style=flat-square&logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![Beads](https://img.shields.io/badge/Beads-Task_Tracking-orange?style=flat-square)](https://github.com/steveyegge/beads)
[![MIT](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](./LICENSE)

<br/>

<a href="#quickstart"><strong>Quickstart</strong></a>&nbsp;&nbsp;&middot;&nbsp;&nbsp;<a href="#how-it-works"><strong>How It Works</strong></a>&nbsp;&nbsp;&middot;&nbsp;&nbsp;<a href="#commands"><strong>Commands</strong></a>&nbsp;&nbsp;&middot;&nbsp;&nbsp;<a href="#telegram"><strong>Telegram</strong></a>&nbsp;&nbsp;&middot;&nbsp;&nbsp;<a href="#demos"><strong>Demos</strong></a>&nbsp;&nbsp;&middot;&nbsp;&nbsp;<a href="DESIGN.md"><strong>Design</strong></a>

</div>

<br/>

> **Voronoi** orchestrates multiple AI agents in parallel — with hypothesis management, statistical rigor, convergence feedback loops, and evidence preservation. Engineering is science with the rigor gates turned off.

---

<br/>

## What Makes This Different

<table>
<tr>
<td width="33%">

**Science, Not Just Code**

Other agent frameworks build software. Voronoi runs **investigations** — with pre-registration, competing hypotheses, belief maps, and statistical validation. Findings come with effect sizes and confidence intervals, not just "it works."

</td>
<td width="33%">

**One Prompt, Zero Config**

Type `/swarm "Why is our model accuracy dropping?"` and walk away. The system auto-detects whether to **build**, **investigate**, **explore**, or **hybridize** — and selects the rigor level to match.

</td>
<td width="33%">

**Telegram-Native Science**

Text a question in your Telegram group. Voronoi classifies intent, dispatches agents, streams progress updates, and delivers findings — all from your pocket. Or use the CLI. Same engine either way.

</td>
</tr>
</table>

---

<h2 id="quickstart">Quickstart</h2>

```bash
pip install voronoi
```

```bash
cd my-project
voronoi init

# Start your AI coding agent
copilot                    # or: claude
> /swarm Build a full-stack SaaS app with auth, billing, dashboard, and API
```

That's it. The swarm plans the work, spawns isolated agents, and merges results back.

For science:

```bash
> /swarm Why is our recommendation model's CTR dropping 15% after each retrain?
```

Voronoi classifies this as **Investigate** (Scientific rigor), spawns a Scout, generates hypotheses, dispatches parallel Investigators, validates findings with a Statistician, and delivers a research report with evidence.

---

<h2 id="how-it-works">How It Works</h2>

```
You ─► "Why is latency 3x higher?"
         │
         ▼
    ┌─────────────┐
    │  Classifier  │──► Investigate · Scientific rigor
    └──────┬──────┘
           │
    ┌──────▼──────┐     ┌─────────────────────────────────────────┐
    │    Scout     │────►│  Knowledge brief: known results,        │
    │   (Phase 0)  │     │  failed approaches, suggested hypotheses│
    └──────┬──────┘     └─────────────────────────────────────────┘
           │
    ┌──────▼──────────────────────────────┐
    │  Orchestrator generates hypotheses   │
    │  H1: Feature drift       (P=0.40)   │
    │  H2: Data contamination  (P=0.35)   │
    │  H3: Serving timeout     (P=0.25)   │
    └──────┬──────────────────────────────┘
           │
    ┌──────┼──────────────┐
    ▼      ▼              ▼
 ┌──────┐ ┌──────┐    ┌──────┐
 │Inv-1 │ │Inv-2 │    │Inv-3 │     ◄── parallel agents
 │(H1)  │ │(H2)  │    │(H3)  │         in git worktrees
 └──┬───┘ └──┬───┘    └──┬───┘
    │        │            │
    ▼        ▼            ▼
 FINDING  FINDING      FINDING       ◄── effect size, CI, N, p-value
    │        │            │
    └────────┼────────────┘
             ▼
    ┌────────────────┐
    │  Statistician   │──► Reviews CI, tests, data integrity
    │  Critic         │──► Adversarial review (partially blinded)
    │  Synthesizer    │──► Integrates findings, updates belief map
    └────────┬───────┘
             │
             ▼
    ┌────────────────┐
    │  Evaluator      │──► Completeness · Coherence · Strength · Actionability
    └────────┬───────┘
             │
             ▼
      📄 deliverable.md        ◄── research paper with full evidence trail
```

For **engineering tasks**, the system simplifies automatically:

```
You ─► "Build a REST API with auth"
         │
         ▼
    Classifier ──► Build · Standard rigor
         │
    ┌────┼────────────┐
    ▼    ▼            ▼
 agent-auth  agent-api  agent-dash     ◄── parallel builders
 (worktree)  (worktree)  (worktree)
    │         │           │
    └────────┬────────────┘
             ▼
       Critic review ──► Merge to main
```

Same framework. Same commands. Rigor gates activate only when warranted.

---

<h2 id="commands">Commands</h2>

### From your AI agent (CLI)

| Command | What it does |
|---------|-------------|
| `/swarm <task>` | Classify intent → plan tasks → spawn parallel agents |
| `/standup` | Status report across all agents |
| `/progress` | Quick metric overview |
| `/spawn <id>` | Launch a single agent on a specific task |
| `/merge` | Merge completed agent branches |
| `/teardown` | Kill all agents, clean up worktrees |

<h3 id="telegram">From Telegram</h3>

| Command | What Happens |
|---------|-------------|
| `/voronoi investigate <question>` | Classify → hypothesize → parallel investigation → findings with evidence |
| `/voronoi explore <question>` | Generate options → benchmark → comparison matrix |
| `/voronoi build <description>` | Decompose → parallel build → critic review → merge |
| `/voronoi experiment <hypothesis>` | Pre-register → experiment → replicate → report (max rigor) |
| `/voronoi recall <query>` | Search past findings in knowledge store |
| `/voronoi belief` | Show current belief map with hypothesis probabilities |
| `/voronoi journal` | Recent investigation journal entries |
| `/voronoi finding <id>` | Detailed view of a specific finding |
| `/voronoi status` | Swarm status — open tasks, ready tasks |
| `/voronoi guide <msg>` | Send guidance to agents mid-flight |
| `/voronoi pivot <msg>` | Strategic direction change |
| Free-text in groups | Auto-detect scientific intent and dispatch |

Natural language works too — _"Why is our model accuracy dropping after each retrain?"_ — Voronoi detects the intent, classifies rigor level, and dispatches agents automatically.

---

## The Science Stack

What makes Voronoi unique — no other agent framework has this:

<table>
<tr>
<td width="50%">

### 🧪 11 Specialized Roles

| Role | When Active |
|------|------------|
| **Builder** 🔨 | Build tasks |
| **Scout** 🔍 | Before any investigation |
| **Investigator** 🔬 | Tests hypotheses |
| **Critic** ⚖️ | Before any merge |
| **Synthesizer** 🧩 | Integrates findings |
| **Evaluator** 🎯 | Scores deliverables |
| **Explorer** 🧭 | Compares options |
| **Theorist** 🧬 | Builds causal models |
| **Methodologist** 📐 | Reviews experiment design |
| **Statistician** 📊 | Reviews quantitative claims |
| **Worker** ⚙️ | General-purpose tasks |

Auto-selected by task type. Build mode uses 2 roles. Full investigation uses all 11.

</td>
<td width="50%">

### 🔒 Rigor Gates

| Gate | Standard | Analytical | Scientific | Experimental |
|------|:--------:|:----------:|:----------:|:------------:|
| Critic review | ✅ | ✅ | ✅ | ✅ |
| Statistician | — | ✅ | ✅ | ✅ |
| Final evaluation | — | ✅ | ✅ | ✅ |
| Methodologist | — | — | ✅ | ✅ |
| Pre-registration | — | — | ✅ | ✅ |
| Power analysis | — | — | ✅ | ✅ |
| Partial blinding | — | — | ✅ | ✅ |
| Adversarial review | — | — | ✅ | ✅ |
| Replication | — | — | — | ✅ |

Auto-classified. _"Build X"_ → Standard. _"Why X?"_ → Scientific. When in doubt, classify higher — gates can be skipped but not added retroactively.

</td>
</tr>
</table>

### Evidence System

Every finding is a first-class artifact with a complete evidence trail:

```
📊 FINDING bd-42: Redis outperforms Memcached for our workload
   Effect: d=2.3, CI [1.9, 2.8], N=10,000 requests
   Test: Welch t-test, p<0.001
   Robust: YES (3 parameter variations tested)
   Data: data/raw/cache_benchmark.csv (SHA-256: a3f2...)
   Replicated: 2/2 agree (overlapping 95% CIs)
```

| Layer | Location | Purpose |
|-------|----------|---------|
| **Findings** | Beads entries | Effect size, CI, N, stat test, data hash |
| **Raw Data** | `data/raw/` | CSV/JSON committed per experiment |
| **Journal** | `.swarm/journal.md` | Narrative continuity across cycles |
| **Belief Map** | `.swarm/belief-map.json` | Hypothesis probabilities, updated per cycle |
| **Strategic Context** | `.swarm/strategic-context.md` | Dead ends, gaps, decision rationale |
| **Deliverable** | `.swarm/deliverable.md` | Final output scored by Evaluator |

---

## Architecture

```
voronoi/
├── src/voronoi/
│   ├── cli.py                  # CLI entry point (init, upgrade, demo)
│   └── gateway/                # Telegram science interface
│       ├── intent.py           # Free-text → workflow mode + rigor classifier
│       ├── memory.py           # Per-chat conversation memory (SQLite)
│       ├── knowledge.py        # Knowledge store queries (findings, beliefs)
│       ├── progress.py         # Real-time OODA progress relay
│       └── handoff.py          # Voronoi → Anton/MVCHA handoff protocol
│
├── scripts/                    # Infrastructure plumbing
│   ├── swarm-init.sh           # One-time setup: git, Beads, tmux
│   ├── spawn-agent.sh          # Git worktree + tmux, launch agent
│   ├── merge-agent.sh          # Merge branch → main, clean up
│   ├── teardown.sh             # Kill sessions, prune worktrees
│   ├── notify-telegram.sh      # Outbound Telegram notifications
│   ├── telegram-bridge.py      # Inbound Telegram command bridge
│   └── dashboard.py            # Live terminal monitoring (Rich)
│
├── .github/
│   ├── agents/                 # Specialized agent personas
│   ├── prompts/                # Slash command definitions
│   └── skills/                 # Reusable domain knowledge
│
├── demos/                      # 3 proof-of-concept scenarios
└── DESIGN.md                   # Full design philosophy
```

**Everything is local files.** No daemon, no server, no account. Agents are coordinated through git branches, [Beads](https://github.com/steveyegge/beads) for task tracking, and tmux sessions. Orchestration is Copilot's native reasoning — shell scripts are pure plumbing.

---

<h2 id="demos">Demos</h2>

```bash
voronoi demo list                          # see available demos
voronoi demo run coupled-decisions         # launch a demo
voronoi demo run forgetting-cure --safe    # restrict agent tools
voronoi demo run emergent-ecosystem --dry-run  # copy files only
```

<table>
<tr>
<td width="33%">

**[Coupled Decisions](demos/coupled-decisions/)**

Multi-agent reasoning over 5 coupled commercial levers. Planted ground truth across 100K+ synthetic transactions. Can the swarm discover what humans can't see in raw data?

</td>
<td width="33%">

**[Emergent Ecosystem](demos/emergent-ecosystem/)**

100×100 grid, 4 species, 4 communication strategies. Each agent builds one species module in isolation. Watch highways, flocks, and extinction cascades emerge.

</td>
<td width="33%">

**[Forgetting Cure](demos/forgetting-cure/)**

4 brain-inspired anti-forgetting strategies implemented from scratch (no PyTorch). Head-to-head MNIST benchmark, then discover the optimal hybrid. Pure numpy-free backprop.

</td>
</tr>
</table>

---

## Telegram Setup

```bash
# 1. Get a bot token from @BotFather on Telegram
# 2. Set credentials:
export VORONOI_TG_BOT_TOKEN="your-bot-token"
export VORONOI_TG_CHAT_ID="your-chat-id"      # optional: restrict to one chat

# 3. Start the bridge:
python scripts/telegram-bridge.py
```

Or add to `.env` and let `swarm-init.sh` start it automatically.

**New in v0.3:** Free-text intent detection in group chats. Just ask a question — no `/voronoi` prefix needed. The classifier detects scientific intent and dispatches automatically.

---

## Voronoi + Anton (MVCHA)

Voronoi is the **science brain**. [Anton (MVCHA)](https://github.com/shyamsridhar123/MVCHA) is the **engineering hands**.

```
Voronoi investigates:  "Why is our API slow?"
         │
         ▼
    Root cause found: N+1 query in /users endpoint
    Expected fix: 3x latency reduction, CI [2.1x, 4.2x]
         │
         ▼
    Creates structured spec → GitHub issue labeled voronoi-spec
         │
         ▼
Anton picks it up:  Clone → implement fix → run tests → open PR
         │
         ▼
Voronoi validates:  Re-runs experiment → "✅ 2.8x improvement, within CI"
```

They can coexist in the same Telegram group — Voronoi handles _"why"_ questions, Anton handles _"fix"_ commands.

---

## Prerequisites

- **Python 3.10+**
- **[Beads (bd)](https://github.com/steveyegge/beads)** — dependency-aware task tracking
- **[tmux](https://github.com/tmux/tmux)** — terminal multiplexer for agent sessions
- **[GitHub CLI (gh)](https://cli.github.com/)** — optional, for GitHub integration
- **[Copilot CLI](https://githubnext.com/projects/copilot-cli/)** — AI coding agent (or Claude CLI)

```bash
# macOS
brew install beads tmux gh
```

## Configuration

After `voronoi init`, `.swarm-config.json` is generated:

```json
{
  "max_agents": 4,
  "agent_command": "copilot",
  "agent_flags": "--allow-all",
  "notifications": {
    "telegram": {
      "bot_token": "...",
      "chat_id": "...",
      "bridge_enabled": true,
      "free_text_in_groups": true
    }
  }
}
```

## Upgrade

```bash
pip install --upgrade voronoi
cd my-project
voronoi upgrade    # Replaces scripts/ and .github/ — your CLAUDE.md is preserved
```

---

## Contributing

```bash
git clone https://github.com/Vahidrostami/voronoi
cd voronoi
pip install -e .
pytest              # 135 tests
```

Voronoi uses [Beads](https://github.com/steveyegge/beads) for issue tracking:

```bash
bd onboard          # Get started
bd ready            # Find available work
```

## Design

See [DESIGN.md](DESIGN.md) for architecture, workflow modes, rigor levels, evidence layers, and convergence criteria.

---

<div align="center">
  <sub>MIT License</sub>
  <br/>
  <sub><em>Voronoi — ask a question, get evidence.</em></sub>
</div>
