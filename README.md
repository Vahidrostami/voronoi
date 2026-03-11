<div align="center">

# Voronoi

**Ask a question. Get evidence.**

<br/>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/voronoi-banner.svg" />
  <source media="(prefers-color-scheme: light)" srcset="assets/voronoi-banner-light.svg" />
  <img alt="Voronoi — Scientific Discovery Engine" src="assets/voronoi-banner-light.svg" width="900" />
</picture>

<br/>

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Copilot](https://img.shields.io/badge/GitHub_Copilot-Powered-000?style=flat-square&logo=github&logoColor=white)](https://github.com/features/copilot)
[![Telegram](https://img.shields.io/badge/Telegram-26A5E4?style=flat-square&logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![MIT](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](./LICENSE)

<br/>

<img src="assets/voronoi-manuscript.svg" alt="Voronoi — scientific discovery with feedback loops" width="800"/>

<sub>Question → hypotheses → parallel agents → failure → OODA loop → new hypothesis → convergence → manuscript</sub>

<br/>

<details>
<summary>Quick investigation (simpler flow)</summary>
<br/>
<img src="assets/voronoi-demo.svg" alt="Voronoi — quick investigation to findings" width="800"/>
</details>

<br/>
<br/>

<a href="#install"><strong>Install</strong></a>&nbsp;&nbsp;&middot;&nbsp;&nbsp;<a href="#how-it-works"><strong>How It Works</strong></a>&nbsp;&nbsp;&middot;&nbsp;&nbsp;<a href="#commands"><strong>Commands</strong></a>&nbsp;&nbsp;&middot;&nbsp;&nbsp;<a href="#demos"><strong>Demos</strong></a>&nbsp;&nbsp;&middot;&nbsp;&nbsp;<a href="DESIGN.md"><strong>Design Doc</strong></a>

</div>

<br/>

> Multi-agent orchestration with **hypothesis management**, **statistical rigor gates**, and **evidence preservation**. Other frameworks build software — Voronoi runs **investigations**.

---

<h2 id="install">Install</h2>

```bash
pip install voronoi
```

**Telegram** (recommended) — set up once, text questions from your phone:

```bash
voronoi server init
# Edit ~/.voronoi/.env with your VORONOI_TG_BOT_TOKEN
voronoi server start
```

**CLI** — work inside a project:

```bash
cd my-project && voronoi init
copilot   # or: claude
> /swarm Why is our model accuracy dropping 15% after each retrain?
```

---

<h2 id="how-it-works">How It Works</h2>

```mermaid
graph LR
    Q["🧑 Question"] --> C["🏷️ Classify"]
    C --> S["🔍 Scout"]
    S --> O["🧠 Orchestrator"]
    O --> I1["🔬 Agent 1"]
    O --> I2["🔬 Agent 2"]
    O --> I3["🔬 Agent 3"]
    I1 --> R["⚖️ Review Gate"]
    I2 --> R
    I3 --> R
    R --> D["📄 Report or Paper"]
```

1. **You ask** — Telegram or CLI, natural language
2. **Classifier** picks the workflow (build / investigate / explore) and rigor level
3. **Scout** researches existing knowledge, generates hypotheses
4. **Agents run in parallel** — each in its own git worktree + tmux session
5. **Self-healing verify loop** — each agent iterates against its own errors (test failures, lint, crashes) before escalating. Builders retry up to 5 times; investigators retry each experiment variant up to 3 times.
6. **Metric contracts** — orchestrator declares what success looks like (metric shape + baseline). Workers fill in the concrete metric at pre-registration. Results are directly comparable across agents.
7. **Review gates** — Statistician, Critic, Evaluator score the output
8. **You get** a teaser with key findings + a PDF — **report** for investigations, **scientific manuscript** if the scope warrants it

Every finding ships with **effect size, confidence interval, sample size, p-value, and data hash**.

> _"Investigate catastrophic forgetting mitigation"_ → the system runs experiments, gathers evidence, then assembles a structured manuscript (Abstract, Methods, Results, Discussion) with real statistical findings. Auto-detected — no special flag needed.

### Two loops, not one

Voronoi runs a **fast inner loop** per agent (try → verify → retry) and a **deliberate outer loop** at the orchestrator level (OODA: observe → orient → decide → act). The inner loop handles execution errors autonomously. The outer loop handles strategic decisions — which hypotheses to pursue, when to change direction, when to converge.

```mermaid
graph LR
    subgraph Inner["Inner Loop (per agent)"]
        A1["Execute"] --> A2["Verify"]
        A2 -->|fail| A3["Retry with error context"]
        A3 --> A1
        A2 -->|pass| A4["Done"]
    end

    subgraph Outer["Outer Loop (orchestrator)"]
        B1["Observe"] --> B2["Orient"]
        B2 --> B3["Decide"]
        B3 --> B4["Act"]
        B4 --> B1
    end

    A4 --> B1
```

### Tasks form a dependency graph, not a flat queue

In real investigations, work has structure — you need baselines before hybrids, data before analysis, controls before treatments. Voronoi enforces **baseline-first**: every investigation epic's first subtask is always a baseline measurement. All experimental tasks are blocked until the baseline completes. This gives every agent a concrete number to beat.

```mermaid
graph TD
    O["🧠 Orchestrator"] --> B["🔬 Baseline\n(sequential training)"]
    O --> E["🔬 EWC\n(elastic weights)"]
    O --> R["🔬 Replay\n(experience replay)"]

    B --> H["🔬 Hybrid\n(EWC + Replay)"]
    E --> H
    R --> H

    H --> Rev["⚖️ Review Gate"]
    Rev --> D["📄 Report"]

    style B fill:#161b22,stroke:#3fb950
    style E fill:#161b22,stroke:#3fb950
    style R fill:#161b22,stroke:#3fb950
    style H fill:#161b22,stroke:#d29922
```

<sup>**Baseline**, **EWC**, and **Replay** run in parallel. **Hybrid** is automatically blocked until all three finish — its experiment depends on their results. The orchestrator tracks this via [Beads](https://github.com/steveyegge/beads) dependency graph.</sup>

---

<h2 id="commands">Commands</h2>

**From Telegram** — just text a question, or use explicit commands:

| Command | What happens |
|---------|-------------|
| `/voronoi investigate <question>` | Parallel investigation with findings |
| `/voronoi explore <question>` | Options, benchmark, comparison matrix |
| `/voronoi build <description>` | Decompose, parallel build, merge |
| `/voronoi results [id]` | View past investigation results |
| `/voronoi status` | Open tasks, ready tasks |
| `/voronoi recall <query>` | Search past findings |
| Free text in groups | Auto-detect intent and dispatch |

**From CLI**: `/swarm <task>` · `/standup` · `/progress` · `/merge` · `/teardown`

---

<h2 id="demos">Demos</h2>

```bash
voronoi demo list
voronoi demo run forgetting-cure
voronoi demo run emergent-ecosystem --safe
```

| Demo | What it does |
|------|-------------|
| **coupled-decisions** | 5 coupled levers, planted ground truth in 100K transactions |
| **emergent-ecosystem** | 4 species on a 100×100 grid, each agent builds one in isolation |
| **forgetting-cure** | 4 anti-forgetting strategies, head-to-head MNIST benchmark |

---

<details>
<summary><strong>🧪 The Science Stack</strong></summary>

<br/>

**11 Specialized Roles** — auto-selected by task type:

Builder 🔨 · Scout 🔍 · Investigator 🔬 · Critic ⚖️ · Synthesizer 🧩 · Evaluator 🎯 · Explorer 🧭 · Theorist 🧬 · Methodologist 📐 · Statistician 📊 · Worker ⚙️

**4 Rigor Levels** — auto-classified from your question:

| Gate | Standard | Analytical | Scientific | Experimental |
|------|:--------:|:----------:|:----------:|:------------:|
| Critic review | ✅ | ✅ | ✅ | ✅ |
| Statistician | — | ✅ | ✅ | ✅ |
| Methodologist | — | — | ✅ | ✅ |
| Pre-registration | — | — | ✅ | ✅ |
| Replication | — | — | — | ✅ |

**Evidence System** — every finding includes:

```
FINDING bd-42: Sleep Replay + EWC hybrid outperforms all
  Effect: d=1.47, CI [1.12, 1.83], N=15 (5 tasks × 3 seeds)
  Test: Welch t-test, p<0.001
  Data: data/raw/forgetting_benchmark.csv (SHA-256: e7b3f...)
  Reviewed: Statistician + Critic + Methodologist
```

**Self-Healing Agents** — each agent runs a verify loop:
- Builders: test + lint + artifact check, up to 5 retries
- Investigators: experiment + metric extraction, up to 3 retries per variant
- Only escalates to orchestrator after exhausting self-repair attempts
- Every verify iteration is logged to `.swarm/verify-log-<id>.jsonl`

**Metric Contracts** — structured agreements between orchestrator and worker:
- Orchestrator declares metric *shape* at dispatch (direction, constraint, baseline)
- Worker fills concrete metric at pre-registration
- Statistician validates the metric *choice*, not just the number
- Results are directly comparable across agents

**Experiment Ledger** — append-only `.swarm/experiments.tsv`:
- Every experiment attempt (success, failure, crash) gets one row
- Greppable chronological audit trail
- Orchestrator reads at each OODA observe step

</details>

<details>
<summary><strong>🏗️ Architecture</strong></summary>

<br/>

```
src/voronoi/
  cli.py                  # init, upgrade, demo, server
  gateway/                # Telegram interface
    config.py  router.py  report.py  intent.py
    memory.py  knowledge.py  handoff.py
  server/
    dispatcher.py  queue.py  workspace.py
    sandbox.py  publisher.py
```

Each agent is a **full Copilot CLI session** in its own **tmux window** with its own **git worktree**. No custom IPC — agents communicate through git + [Beads](https://github.com/steveyegge/beads).

```
~/.voronoi/              # server mode
  config.json  queue.db
  objects/               # shared bare git repos
  active/                # one workspace per investigation
    inv-1-slug/
      .swarm/            # journal, beliefs, deliverable
      data/raw/          # experimental data
```

</details>

<details>
<summary><strong>📊 Comparison</strong></summary>

<br/>

| Capability | **Voronoi** | CrewAI | AutoGen | MetaGPT |
|:-----------|:----------:|:------:|:-------:|:-------:|
| Parallel agents in git worktrees | ✅ | — | — | — |
| Hypothesis management | ✅ | — | — | — |
| Statistical rigor gates | ✅ | — | — | — |
| Pre-registration & replication | ✅ | — | — | — |
| Evidence system (SHA-256) | ✅ | — | — | — |
| Telegram-native interface | ✅ | — | — | — |
| Docker-sandboxed execution | ✅ | — | ✅ | — |
| Role-based specialization | ✅ (11) | ✅ | ✅ | ✅ (6) |
| Works with any LLM agent | ✅ | ✅ | ✅ | — |

</details>

<details>
<summary><strong>⚙️ Setup & Configuration</strong></summary>

<br/>

**Prerequisites**: Python 3.10+ · [Beads](https://github.com/steveyegge/beads) · [tmux](https://github.com/tmux/tmux) · [Copilot CLI](https://githubnext.com/projects/copilot-cli/) (or Claude)

```bash
brew install beads tmux gh   # macOS
pip install voronoi[report]  # optional: PDF generation
```

**Telegram**: Get bot token from @BotFather → set `VORONOI_TG_BOT_TOKEN` in `~/.voronoi/.env` → `voronoi server start`

**Docker**: `docker build -t voronoi-python:latest -f docker/voronoi-python.Dockerfile .`

**Upgrade**: `pip install --upgrade voronoi && voronoi upgrade`

</details>

---

## Contributing

```bash
git clone https://github.com/Vahidrostami/voronoi && cd voronoi
pip install -e . && pytest   # 223 tests
```

See [DESIGN.md](DESIGN.md) for the full design philosophy.

---

<div align="center">
  <sub>MIT License · <em>Voronoi — ask a question, get evidence.</em></sub>
</div>
