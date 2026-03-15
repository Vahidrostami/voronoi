"""Unified orchestrator prompt builder — single source of truth.

Both the CLI (``voronoi demo run``) and the Telegram dispatcher use this
module to generate the orchestrator system prompt.  This guarantees that
every copilot instance — regardless of entry point — gets the same
workflow instructions, the same agent role references, and the same
science-gate definitions.

The key design principle: the prompt *references* ``.github/agents/*.agent.md``
files instead of duplicating their content.  This means the rich role
definitions (startup sequences, evidence standards, completion checklists)
are always used by copilot's native agent system.
"""

from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_orchestrator_prompt(
    *,
    question: str,
    mode: str,
    rigor: str,
    workspace_path: str = "",
    codename: str = "",
    prompt_path: str = "PROMPT.md",
    output_dir: str = "",
    max_agents: int = 4,
    safe: bool = False,
) -> str:
    """Build the unified orchestrator system prompt.

    Parameters
    ----------
    question : str
        The investigation/build question or the literal content of PROMPT.md.
    mode : str
        One of investigate, explore, build, hybrid.
    rigor : str
        One of standard, analytical, scientific, experimental.
    workspace_path : str
        Absolute path to the workspace (shown in prompt for context).
    codename : str
        Brain-themed codename for this investigation (e.g. "Dopamine").
    prompt_path : str
        Relative path to the project brief file (default "PROMPT.md").
    output_dir : str
        If set, scopes all work under this directory (used by demos).
    max_agents : int
        Maximum concurrent worker agents.
    safe : bool
        If True, spawns workers with restricted tool access.
    """
    _MODE_VERB = {
        "investigate": "Investigation",
        "explore": "Exploration",
        "build": "Build",
        "hybrid": "Investigation",
        "experiment": "Experiment",
    }
    verb = _MODE_VERB.get(mode, mode.title())
    label = codename or "Voronoi"
    safe_flag = "--safe " if safe else ""

    sections: list[str] = []

    # -- Identity ----------------------------------------------------------
    sections.append(
        "You are the Voronoi swarm orchestrator. Your job: read the project brief, "
        "plan tasks, spawn parallel worker agents, monitor their progress, merge "
        "completed work, and repeat until done.\n"
    )

    # -- Role protocol (the critical link to .github/agents) ---------------
    sections.append(
        "\n## Your Full Protocol\n\n"
        "Read `.github/agents/swarm-orchestrator.agent.md` NOW — it contains your "
        "complete role definition including OODA workflow, role selection tables, "
        "convergence criteria, paradigm checks, bias monitoring, and the macro "
        "retry loop.  Follow it precisely.\n"
    )

    # -- Mission -----------------------------------------------------------
    sections.append(f"\n## {verb}\n\n")
    if workspace_path:
        sections.append(f"**Workspace:** {workspace_path}\n")
    sections.append(
        f"**Mode:** {mode}\n"
        f"**Rigor:** {rigor}\n"
        f"**Max concurrent agents:** {max_agents}\n"
    )
    sections.append(f"\n**Project brief:** Read `{prompt_path}` completely — every line matters.\n")
    if output_dir:
        sections.append(
            f"**Output scope:** All work under `{output_dir}/` "
            f"(source in `{output_dir}/src/`, output in `{output_dir}/output/`).\n"
        )

    # -- Codename & personality --------------------------------------------
    if codename:
        sections.append(
            f"\n## Your Codename: {label}\n\n"
            f'Use "{label}" in EVERY Telegram notification. '
            "This is your identity.\n"
        )

    sections.append(
        "\n## Personality — IMPORTANT\n\n"
        "Your Telegram notifications should be EXCITED, high-energy, and fun — "
        "like a hype crew that genuinely loves watching agents crush it.  "
        "Use brain/neuroscience metaphors when they fit naturally.  "
        "Always stay INFORMATIVE — every message must include real numbers "
        "(task counts, progress, findings). Never fluff without facts.\n"
    )

    # -- Science sections (mode + rigor aware) -----------------------------
    sections.append(_build_science_sections(mode, rigor))

    # -- Investigation invariants (injected into every prompt) -------------
    sections.append(
        "\n## Investigation Invariants\n\n"
        "If `.swarm/invariants.json` exists, read it at startup and enforce "
        "every invariant listed.  Include ALL invariants verbatim in every "
        "worker prompt you write.  Violations are structural failures — "
        "not judgment calls.\n\n"
        "Workers: check invariants during your EVA self-audit.  If you detect "
        "a violation, flag `INVARIANT_VIOLATED:<id>` in Beads notes and stop.\n\n"
        "**Data invariants are enforced structurally** by the convergence gate. "
        "If the project brief specifies a minimum row count for data files, "
        "write a `min_csv_rows` invariant at session start:\n"
        "```json\n"
        '[{"id": "MIN_ROWS", "description": "Minimum 500 rows per scenario CSV", '
        '"check_type": "min_csv_rows", "params": {"min_rows": 500, "glob": "**/data/**/*.csv"}}]\n'
        "```\n"
        "The convergence gate will REJECT completion if any matching CSV has "
        "fewer rows than declared. This prevents workers from silently reducing "
        "data size.\n"
    )

    # -- REVISE task support -----------------------------------------------
    sections.append(
        "\n## REVISE Tasks (Iterative Experiment Design)\n\n"
        "When a pilot experiment fails calibration or results are unexpected, "
        "create a REVISE task instead of a fresh task.  REVISE tasks carry "
        "forward context from the previous attempt:\n\n"
        "```bash\n"
        "bd create \"REVISE: <description>\" -t task -p 1 --json\n"
        "bd update <id> --notes \"REVISE_OF:<previous-task-id>\"\n"
        "bd update <id> --notes \"PRIOR_RESULT:<what happened>\"\n"
        "bd update <id> --notes \"FAILURE_DIAGNOSIS:<why it failed>\"\n"
        "bd update <id> --notes \"REVISED_PARAMS:<what changed>\"\n"
        "```\n\n"
        "The worker receiving a REVISE task gets the full context of what was "
        "tried and why it failed.  Include ALL revise context in the worker prompt.\n\n"
        "**Calibration workflow:**\n"
        "1. Dispatch a PILOT task (small N, quick run)\n"
        "2. Read pilot results — check CALIBRATION_TARGET vs CALIBRATION_ACTUAL\n"
        "3. If calibration fails, create a REVISE task with diagnosis\n"
        "4. Only dispatch the full experiment after calibration passes\n"
    )

    # -- Verify loop guidance (compact — details are in worker role files) ---
    sections.append(
        "\n## Worker Self-Healing\n\n"
        "Workers retry against their own errors before escalating. "
        "When a worker reports `VERIFY_EXHAUSTED`, check their notes before retrying. "
        "When a worker reports `DESIGN_INVALID`, dispatch Methodologist for post-mortem.\n"
    )

    # -- Checkpoint-based OODA (the core context management protocol) ------
    sections.append(
        "\n## Context Management — CRITICAL FOR LONG RUNS\n\n"
        "You have a finite context window. In 10+ hour runs, you WILL lose early "
        "instructions if you're not disciplined. These rules prevent that:\n\n"
        "**1. Write a checkpoint after EVERY OODA cycle:**\n"
        "```bash\n"
        "python3 -c \"\n"
        "import json\n"
        "from voronoi.science import OrchestratorCheckpoint, save_checkpoint\n"
        "from pathlib import Path\n"
        "cp = OrchestratorCheckpoint(\n"
        "    cycle=N, phase='investigating', mode='investigate', rigor='experimental',\n"
        "    hypotheses_summary='H1:confirmed, H2:testing',\n"
        "    total_tasks=50, closed_tasks=20,\n"
        "    active_workers=['agent-pilot', 'agent-scenario-3'],\n"
        "    recent_events=['Pilot passed MBRS gap 0.32', 'Scenario 3 complete'],\n"
        "    recent_decisions=['Moved to full experiment after pilot passed'],\n"
        "    dead_ends=['L2/L3 encoding too similar, skipped'],\n"
        "    next_actions=['Wait for scenarios 4-6', 'Then dispatch ANOVA'],\n"
        "    criteria_status={'SC1': False, 'SC2': False, 'SC3': False},\n"
        "    eval_score=0.0, improvement_rounds=0,\n"
        ")\n"
        "save_checkpoint(Path('.'), cp)\n"
        "\"\n"
        "```\n\n"
        "**2. Read checkpoint at the START of each OODA cycle** (before reading anything else):\n"
        "```bash\n"
        "cat .swarm/orchestrator-checkpoint.json\n"
        "```\n"
        "This reminds you of your own state if context has degraded.\n\n"
        "**3. Use targeted Beads queries, NOT `bd list --json`:**\n"
        "```bash\n"
        '# Only tasks that changed recently\n'
        'bd query "status!=closed AND updated>30m" --json\n\n'
        '# Only findings\n'
        'bd query "title=FINDING" --json\n\n'
        '# Only open tasks with problems\n'
        'bd query "notes=DESIGN_INVALID AND status!=closed" --json\n\n'
        '# Ready work\n'
        'bd ready --json\n'
        "```\n"
        "NEVER run `bd list --json` in a routine OODA cycle — it returns ALL tasks "
        "and floods your context.\n\n"
        "**4. Worker prompts are code-assembled.** You write a ~200 word briefing; "
        "`build_worker_prompt()` adds the role file, git discipline, and skills. "
        "This saves ~15K tokens per dispatch from your context.\n\n"
        "**5. Read the project brief ONCE at startup.** After that, work from your "
        "checkpoint + belief map. If you need to re-check a specific detail, "
        "`grep` for it instead of re-reading the whole file.\n"
    )

    # -- Success criteria ---------------------------------------------------
    sections.append(
        "\n## Success Criteria Tracking\n\n"
        "At investigation start, write `.swarm/success-criteria.json` capturing "
        "the PROMPT's measurable success criteria.  Format:\n"
        "```json\n"
        "[{\"id\": \"SC1\", \"description\": \"L4 outperforms L1 on F1\", \"met\": false},\n"
        " {\"id\": \"SC2\", \"description\": \"Pipeline compresses >=10x\", \"met\": false}]\n"
        "```\n\n"
        "During each OODA Orient cycle, check whether results satisfy each criterion.\n"
        "Update `met: true` when evidence supports it.  **Convergence is blocked** "
        "while any criterion has `met: false`.\n\n"
        "If a criterion is unmet AND the experiment ran validly, document why in "
        "the limitations section.  If it's unmet because the experiment was broken "
        "(DESIGN_INVALID), fix and re-run — do NOT ship broken results.\n\n"
        "**Result-hypothesis alignment:**\n"
        "When the primary hypothesis predicts direction X (e.g., L4 > L1) but "
        "results show the opposite, flag:\n"
        "```bash\n"
        "bd update <id> --notes \"RESULT_CONTRADICTS_HYPOTHESIS:Expected L4>L1 but observed L1>L4\"\n"
        "```\n"
        "This blocks convergence until resolved (redesign experiment or revise hypothesis).\n"
    )

    # -- Phase gate enforcement --------------------------------------------
    sections.append(
        "\n## Phase Gate Enforcement — HARD GATES\n\n"
        "Before dispatching any paper/scribe/compilation task, you MUST verify:\n"
        "1. Read `.swarm/success-criteria.json` — ALL criteria must have `met: true`\n"
        "2. Run `bd list --json` and confirm NO open tasks have `DESIGN_INVALID` in notes\n"
        "3. If ANY check fails, create a REVISE task instead of a paper task\n\n"
        "**These gates are also enforced structurally:**\n"
        "- `spawn-agent.sh` will REJECT dispatch of paper/scribe/compile tasks "
        "while any DESIGN_INVALID experiment is unresolved\n"
        "- The dispatcher will BLOCK completion while DESIGN_INVALID tasks are open\n"
        "- You CANNOT bypass these gates by writing deliverable.md — the server checks\n\n"
        "**If an experiment fails its hard gate** (e.g., p ≥ 0.05 when p < 0.05 was required):\n"
        "1. Flag `DESIGN_INVALID` in the task notes with diagnosis\n"
        "2. Dispatch Methodologist for post-mortem review\n"
        "3. Create a REVISE task with the Methodologist's recommendations\n"
        "4. Only proceed to paper after the revised experiment passes its gate\n"
    )

    # -- Anti-simulation enforcement (compact) --------------------------------
    sections.append(
        "\n## Anti-Simulation — HARD GATE\n\n"
        "NEVER create simulation/mock/fake files that replace real LLM calls. "
        "The convergence gate will BLOCK completion if it detects simulated data. "
        "Reduce N if budget is tight — never simulate.\n"
    )

    # -- Workflow ----------------------------------------------------------
    sections.append("\n## Workflow\n\n")
    sections.append(_build_workflow_steps(mode, rigor, prompt_path))

    # -- Tools -------------------------------------------------------------
    sections.append(
        "\n## Tools\n\n"
        "Task tracking (Beads):\n"
        "  bd prime                       # Load context at start\n"
        '  bd create "title" -t task -p <1-3> --description "..." --json\n'
        '  bd create "title" -t epic -p 1 --json\n'
        "  bd dep add <child-id> <parent-id>\n"
        "  bd ready --json                # Unblocked tasks\n"
        '  bd update <id> --notes "PRODUCES:file1,file2"\n'
        '  bd update <id> --notes "REQUIRES:file1,file2"\n'
        '  bd close <id> --reason "summary"\n'
        "  bd list --json / bd show <id> --json\n\n"
        "Spawn a worker agent:\n"
        "  1. Write the worker's prompt to a temp file, e.g. /tmp/prompt-<branch>.txt\n"
        f"  2. Run: ./scripts/spawn-agent.sh {safe_flag}<task-id> <branch-name> /tmp/prompt-<branch>.txt\n"
        "  NOTE: spawn-agent.sh enforces REQUIRES/GATE checks — dispatch will FAIL if\n"
        "  required input artifacts are missing. This is intentional. Fix upstream first.\n\n"
        "Merge completed work:\n"
        "  ./scripts/merge-agent.sh <branch-name> <task-id>\n"
        "  NOTE: merge-agent.sh enforces PRODUCES checks — merge will FAIL if the agent\n"
        "  didn't create its declared output artifacts. Agent must fix and retry.\n\n"
        "Validation hooks (called automatically by spawn/merge, but available standalone):\n"
        "  ./scripts/figure-lint.sh <workspace>           # Verify all \\includegraphics refs resolve\n"
        "  ./scripts/convergence-gate.sh <workspace> <rigor>  # Multi-signal convergence check\n\n"
        "Monitor agents:\n"
        "  bd show <id> --json                                    # Task status\n"
        "  git log main..<branch> --oneline                      # Commits\n"
        "  tmux capture-pane -t $(jq -r .tmux_session .swarm-config.json):<branch>"
        " -p 2>/dev/null | tail -20\n\n"
        "Telegram notifications:\n"
        "  source ./scripts/notify-telegram.sh\n"
        '  notify_telegram "event_type" "your message"\n'
    )

    # -- Worker prompt instructions (code-assembled, not LLM-assembled) ------
    sections.append(
        "\n## Dispatching Workers — CONTEXT-EFFICIENT PROTOCOL\n\n"
        "Worker prompts are assembled BY CODE, not by you. This saves your context "
        "for reasoning instead of copying role files.\n\n"
        "**To dispatch a worker, write a compact dispatch spec to a JSON file:**\n"
        "```bash\n"
        'echo \'{"task_type": "investigation", "task_id": "bd-42", "branch": "agent-pilot",\n'
        '  "briefing": "Run the pilot experiment on scenarios 1-2...",\n'
        '  "strategic_context": "This tests whether encoding helps discovery...",\n'
        '  "produces": "output/pilot_results.json",\n'
        '  "requires": "demos/coupled-decisions/PROMPT.md",\n'
        '  "metric_contract": "PRIMARY=MBRS, higher_is_better, baseline=0.0",\n'
        '  "prompt_sections": "[copy ONLY the 5-15 lines relevant to this task]"\n'
        "}' > /tmp/dispatch-bd-42.json\n"
        "```\n\n"
        "Then run:\n"
        "```bash\n"
        "python3 -c \"\n"
        "import json; from voronoi.server.prompt import build_worker_prompt\n"
        "spec = json.load(open('/tmp/dispatch-bd-42.json'))\n"
        "prompt = build_worker_prompt(**spec)\n"
        "open('/tmp/prompt-agent-pilot.txt', 'w').write(prompt)\n"
        "\"\n"
        "./scripts/spawn-agent.sh bd-42 agent-pilot /tmp/prompt-agent-pilot.txt\n"
        "```\n\n"
        "**Task types** (determines which role file is loaded automatically):\n"
        "  - build/implementation → `.github/agents/worker-agent.agent.md`\n"
        "  - scout → `.github/agents/scout.agent.md`\n"
        "  - investigation/experiment → `.github/agents/investigator.agent.md`\n"
        "  - exploration/comparison → `.github/agents/explorer.agent.md`\n"
        "  - review_stats → `.github/agents/statistician.agent.md`\n"
        "  - review_critic → `.github/agents/critic.agent.md`\n"
        "  - review_method → `.github/agents/methodologist.agent.md`\n"
        "  - theory → `.github/agents/theorist.agent.md`\n"
        "  - synthesis → `.github/agents/synthesizer.agent.md`\n"
        "  - evaluation → `.github/agents/evaluator.agent.md`\n"
        "  - scribe → `.github/agents/scribe.agent.md`\n"
        "  - paper/compilation → `.github/agents/worker-agent.agent.md`\n\n"
        "**What you put in the briefing** (5-20 lines):\n"
        "- WHAT to do (specific, concrete)\n"
        "- Acceptance criteria\n"
        "- File scope (which directories/files the agent owns)\n"
        "- Any special instructions\n\n"
        "**What you do NOT need to include** (the code handles these):\n"
        "- Role definition (loaded from .github/agents/ automatically)\n"
        "- Full PROMPT.md content (agent is told to read relevant sections)\n"
        "- Git discipline boilerplate (injected automatically)\n"
        "- Skill file references (selected by task type automatically)\n\n"
        "**The briefing is the ONLY thing that costs you context tokens.**\n"
        "Keep it focused. ~200 words max.\n"
    )

    # -- Rules -------------------------------------------------------------
    sections.append(
        "\n## Rules\n\n"
        "- Read `.github/agents/swarm-orchestrator.agent.md` at startup\n"
        "- Read the FULL project brief ONCE at startup, then work from checkpoint\n"
        "- No overlapping file scopes between agents\n"
        "- Use `build_worker_prompt()` for dispatch — never copy role files yourself\n"
        "- Diagnose failures (check git log, tmux output) before retrying\n"
        "- Push all completed work to remote when done\n"
        f"- Max concurrent agents: {max_agents}\n"
        "- EVERY task MUST declare PRODUCES and REQUIRES in Beads notes\n"
        "- For investigation epics, create a BASELINE task as the FIRST subtask \u2014 "
        "all experimental tasks depend on it\n"
        "- Workers self-heal via verify loops \u2014 when they report VERIFY_EXHAUSTED, "
        "read their iteration log before re-dispatching\n"
        "- When a worker reports DESIGN_INVALID, dispatch Methodologist for post-mortem "
        "\u2192 create corrected experiment task\n"
        "- NEVER enter a worker's worktree to fix code yourself \u2014 "
        "dispatch a new agent or reassign the task\n"
        "- spawn-agent.sh will REJECT dispatch if REQUIRES files are missing\n"
        "- merge-agent.sh will REJECT merge if PRODUCES files are missing\n"
        "- Before declaring convergence, run: `./scripts/convergence-gate.sh . <rigor>`\n"
    )
    sections.append(_build_rigor_rules(rigor))

    # -- Eval score (for dispatcher convergence tracking) ------------------
    if rigor != "standard":
        sections.append(
            "\n## Evaluator Score Output\n\n"
            "When the Evaluator scores the deliverable, write the result to "
            "`.swarm/eval-score.json`:\n"
            "```json\n"
            '{"score": 0.82, "rounds": 1}\n'
            "```\n"
            "This file is read by the progress monitor to track convergence.\n"
        )

    return "".join(sections)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_science_sections(mode: str, rigor: str) -> str:
    """Build science-specific prompt sections based on mode and rigor."""
    sections: list[str] = []

    if mode in ("investigate", "explore", "hybrid"):
        sections.append(
            "\n## Phase 0: Scout\n\n"
            "Before planning tasks, dispatch a Scout agent "
            "(use `.github/agents/scout.agent.md` as its role) to research "
            "existing knowledge:\n"
            "- Search codebase, docs, logs for prior work on this topic\n"
            "- Produce a knowledge brief (`.swarm/scout-brief.md`)\n"
        )
        if rigor in ("scientific", "experimental"):
            sections.append(
                "- MUST include SOTA methodology for this problem type\n"
                "- WAIT for Scout to complete before generating hypotheses\n"
            )

    if mode in ("investigate", "hybrid") and rigor != "standard":
        sections.append(
            "\n## Hypothesis Management\n\n"
            "After Scout completes, generate hypotheses and create a belief map:\n"
            "1. Generate 3-7 hypotheses from Scout brief with prior probabilities\n"
            "2. Write belief map to `.swarm/belief-map.json`\n"
            "3. Prioritize by information gain: uncertainty × impact × testability\n"
            "4. Create investigation tasks for top-priority hypotheses\n"
        )
        if rigor in ("scientific", "experimental"):
            sections.append(
                "\nAt Scientific+ rigor:\n"
                "- Dispatch Theorist (`.github/agents/theorist.agent.md`) to refine "
                "hypotheses and propose competing theories\n"
                "- Dispatch Methodologist (`.github/agents/methodologist.agent.md`) "
                "to batch-review all experimental designs\n"
                "- WAIT for Methodologist approval before dispatching Investigators\n"
                "- Every investigation task MUST have pre-registration\n"
            )

    if rigor in ("analytical", "scientific", "experimental"):
        sections.append(
            "\n## Review Gates\n\n"
            "Findings MUST pass review gates before entering the knowledge store:\n"
            "- **Statistician** (`.github/agents/statistician.agent.md`): "
            "Reviews CI, effect sizes, test appropriateness, data integrity\n"
        )
        if rigor in ("scientific", "experimental"):
            sections.append(
                "- **Critic** (`.github/agents/critic.agent.md`): "
                "Adversarial review, partially blinded. Up to 3 rounds. "
                "Unresolved = CONTESTED (blocks convergence).\n"
            )
        sections.append(
            "- **Synthesizer** (`.github/agents/synthesizer.agent.md`): "
            "Consistency check against validated findings, claim-evidence registry\n"
            "- **Evaluator** (`.github/agents/evaluator.agent.md`): "
            "Score deliverable (Completeness, Coherence, Strength, Actionability) "
            "with claim-evidence traceability audit\n"
        )

    if rigor in ("analytical", "scientific", "experimental"):
        sections.append(
            "\n## Claim-Evidence Traceability — MANDATORY\n\n"
            "Before writing the deliverable, the Synthesizer MUST produce "
            "`.swarm/claim-evidence.json` with this structure:\n"
            "```json\n"
            '{"claims": [{"claim_id": "C1", "claim_text": "...", '
            '"finding_ids": ["bd-5", "bd-8"], "hypothesis_ids": ["H1"], '
            '"strength": "robust", "interpretation": "..."}], '
            '"orphan_findings": [], "unsupported_claims": [], "coverage_score": 0.95}\n'
            "```\n"
            "**Rules:**\n"
            "- Every claim in the deliverable MUST link to at least one finding ID\n"
            "- Every finding MUST be cited by at least one claim (no orphan findings)\n"
            "- Unsupported claims or orphan findings block convergence\n"
            "- The Evaluator checks this registry during Strength scoring\n"
            "- Strength labels: robust (sensitivity-tested), provisional (reviewed), "
            "weak (unreviewed), unsupported (no evidence)\n"
        )

    if rigor in ("analytical", "scientific", "experimental"):
        sections.append(
            "\n## Finding Interpretation — MANDATORY\n\n"
            "The Statistician MUST add interpretation metadata to each finding during review:\n"
            '```bash\n'
            'bd update <finding-id> --notes "INTERPRETATION:[what this means practically]"\n'
            'bd update <finding-id> --notes "PRACTICAL_SIGNIFICANCE:negligible|small|medium|large|very large"\n'
            'bd update <finding-id> --notes "SUPPORTS_HYPOTHESIS:[hypothesis ID and name]"\n'
            '```\n'
            "The final report auto-generates:\n"
            "- Finding-by-finding interpretation with practical significance\n"
            "- Cross-finding comparison (ranked by effect size)\n"
            "- Dedicated Negative Results section for refuted hypotheses\n"
            "- Auto-generated Limitations from fragile/wide-CI/unreviewed findings\n"
            "- Belief map trajectory (prior \u2192 posterior with evidence links)\n"
        )

    if rigor != "standard":
        sections.append("\n## Convergence Criteria\n\n")
        if rigor == "analytical":
            sections.append(
                "- All questions answered with quantitative evidence\n"
                "- Statistician reviewed all findings\n"
                "- No unresolved contradictions\n"
                "- Evaluator score ≥ 0.75 (max 2 improvement rounds)\n"
            )
        elif rigor == "scientific":
            sections.append(
                "- All hypotheses resolved (confirmed/refuted/inconclusive)\n"
                "- Causal model accounts for all findings\n"
                "- At least 1 competing theory ruled out\n"
                "- At least 1 novel prediction tested\n"
                "- No CONSISTENCY_CONFLICTs, no PARADIGM_STRESS\n"
                "- All findings ROBUST or FRAGILE-documented\n"
                "- Evaluator score ≥ 0.75 (max 2 improvement rounds)\n"
            )
        elif rigor == "experimental":
            sections.append(
                "- All Scientific criteria PLUS:\n"
                "- All high-impact findings replicated\n"
                "- Pre-registration compliance verified\n"
                "- Power analysis documented for every experiment\n"
            )

    return "".join(sections)


def _build_workflow_steps(mode: str, rigor: str, prompt_path: str) -> str:
    """Build mode-appropriate workflow steps."""
    steps = [f"1. Read `{prompt_path}` completely — understand the question fully\n"]
    steps.append("2. Read `.github/agents/swarm-orchestrator.agent.md` for your full protocol\n")

    if mode in ("investigate", "explore", "hybrid"):
        steps.append("3. Dispatch Scout → wait for `.swarm/scout-brief.md`\n")
        steps.append("4. Run `bd prime`, create an epic + tasks with dependencies "
                      "and artifact contracts\n")
        if rigor != "standard":
            steps.append("5. Generate hypotheses → write `.swarm/belief-map.json`\n")
            steps.append("6. Inject STRATEGIC_CONTEXT into each task's Beads notes\n")
            steps.append("7. Create `.swarm/experiments.tsv` with header row\n")
            ooda_step = 8
        else:
            steps.append("5. Create `.swarm/experiments.tsv` with header row\n")
            ooda_step = 6
    else:
        steps.append("3. Run `bd prime`, create an epic + tasks with dependencies "
                      "and artifact contracts\n")
        ooda_step = 4

    steps.append(
        f"{ooda_step}. OODA loop (checkpoint-driven):\n"
        "   - **Read** `.swarm/orchestrator-checkpoint.json` first\n"
        "   - **Observe**: `bd query \"status!=closed AND updated>30m\" --json`, "
        "check belief map, experiment ledger\n"
        "   - **Orient**:  Classify events, check convergence, update belief map\n"
        "   - **Decide**:  Prioritize by information gain from belief map\n"
        "   - **Act**:     Dispatch workers via `build_worker_prompt()`, merge work\n"
        "   - **Write** checkpoint with decisions + next actions\n"
        "   - Repeat until converged\n"
    )
    steps.append(
        f"{ooda_step + 1}. Synthesizer produces `.swarm/claim-evidence.json` mapping every claim to findings\n"
    )
    steps.append(
        f"{ooda_step + 2}. Write `.swarm/deliverable.md` and push results\n"
    )
    steps.append(
        f"{ooda_step + 3}. If the project produced LaTeX files, dispatch a final "
        "compilation agent to:\n"
        "   - READ `.github/skills/figure-generation/SKILL.md` and "
        "`.github/skills/compilation-protocol/SKILL.md` — follow them precisely\n"
        "   - This task MUST declare `REQUIRES:` for ALL figure source data files\n"
        "   - This task MUST declare `PRODUCES:.swarm/report.pdf`\n"
        "   - PHASE 1 (BLOCKING): Scan .tex files for \\includegraphics references.\n"
        "     For EACH referenced figure that doesn't exist on disk:\n"
        "     a. Check for plotting scripts (plot_*.py, generate_*.py, make_figures.py)\n"
        "     b. If script exists: run it, verify output path matches LaTeX reference\n"
        "     c. If no script: write a matplotlib script from available data\n"
        "     d. If no data: generate a placeholder with label '[DATA NOT AVAILABLE]'\n"
        "     e. Commit EACH figure individually before generating the next\n"
        "   - Run `./scripts/figure-lint.sh .` — this MUST pass before proceeding\n"
        "   - PHASE 2: Compile LaTeX (tectonic > latexmk > pdflatex)\n"
        "   - PHASE 3: Verify PDF (page count, no undefined refs, no blank boxes)\n"
        "   - Copy final PDF to `.swarm/report.pdf`, commit, push\n"
        "   - spawn-agent.sh will block this dispatch if REQUIRES data is missing\n"
        "   - merge-agent.sh will block merge if report.pdf is not produced\n"
    )
    return "".join(steps)


def _build_rigor_rules(rigor: str) -> str:
    """Build rigor-specific rules."""
    rules: list[str] = []
    if rigor in ("analytical", "scientific", "experimental"):
        rules.append("- Every finding MUST pass Statistician review\n")
        rules.append("- Every finding MUST include INTERPRETATION and PRACTICAL_SIGNIFICANCE\n")
        rules.append("- Synthesizer MUST produce `.swarm/claim-evidence.json` BEFORE deliverable\n")
        rules.append("- Every claim MUST trace to finding IDs; every finding MUST be cited\n")
        rules.append("- Every task MUST declare PRODUCES and REQUIRES artifact contracts\n")
    if rigor in ("scientific", "experimental"):
        rules.append("- Investigation tasks MUST have pre-registration BEFORE execution\n")
        rules.append("- Investigation tasks MUST have Methodologist approval BEFORE dispatch\n")
        rules.append("- Findings MUST pass Critic adversarial review (partially blinded)\n")
        rules.append("- Must propose competing theories with discriminating predictions\n")
    if rigor == "experimental":
        rules.append("- High-impact findings MUST be replicated before convergence\n")
        rules.append("- Power analysis MANDATORY for every experiment\n")
    return "".join(rules)


# ---------------------------------------------------------------------------
# Worker prompt assembly — code-built, not LLM-built
# ---------------------------------------------------------------------------

# Role file mapping: task type → .github/agents/ filename
ROLE_MAP: dict[str, str] = {
    "build": "worker-agent.agent.md",
    "implementation": "worker-agent.agent.md",
    "scout": "scout.agent.md",
    "investigation": "investigator.agent.md",
    "experiment": "investigator.agent.md",
    "exploration": "explorer.agent.md",
    "comparison": "explorer.agent.md",
    "review_stats": "statistician.agent.md",
    "review_critic": "critic.agent.md",
    "review_method": "methodologist.agent.md",
    "theory": "theorist.agent.md",
    "synthesis": "synthesizer.agent.md",
    "evaluation": "evaluator.agent.md",
    "scribe": "scribe.agent.md",
    "paper": "worker-agent.agent.md",
    "compilation": "worker-agent.agent.md",
}

# Skills to reference by task type
SKILL_MAP: dict[str, list[str]] = {
    "investigation": [
        ".github/skills/investigation-protocol/SKILL.md",
        ".github/skills/evidence-system/SKILL.md",
    ],
    "experiment": [
        ".github/skills/investigation-protocol/SKILL.md",
        ".github/skills/evidence-system/SKILL.md",
    ],
    "paper": [
        ".github/skills/figure-generation/SKILL.md",
        ".github/skills/compilation-protocol/SKILL.md",
    ],
    "compilation": [
        ".github/skills/figure-generation/SKILL.md",
        ".github/skills/compilation-protocol/SKILL.md",
    ],
}


def build_worker_prompt(
    *,
    task_type: str,
    task_id: str,
    branch: str,
    briefing: str,
    workspace_path: str = "",
    strategic_context: str = "",
    produces: str = "",
    requires: str = "",
    metric_contract: str = "",
    prompt_path: str = "",
    prompt_sections: str = "",
    extra_instructions: str = "",
) -> str:
    """Assemble a complete worker prompt from components.

    This runs in code, NOT in the orchestrator's LLM context.
    The orchestrator writes a compact dispatch spec; this function does the
    heavy lifting of reading role files and assembling the full prompt.

    Parameters
    ----------
    task_type : str
        One of the keys in ROLE_MAP (build, investigation, scout, etc.)
    task_id : str
        Beads task ID (e.g. "bd-42")
    branch : str
        Git branch name for the worktree
    briefing : str
        Task-specific instructions from the orchestrator. Should be 5-20 lines
        describing WHAT to do, acceptance criteria, and file scope.
    workspace_path : str
        Path to the investigation workspace (for reading files).
    strategic_context : str
        How this task fits the investigation (1-3 sentences).
    produces : str
        Comma-separated list of output files the agent MUST create.
    requires : str
        Comma-separated list of input files that must exist.
    metric_contract : str
        Metric shape + baseline + acceptance criteria (investigation tasks).
    prompt_path : str
        Path to PROMPT.md — the agent will be told to read relevant sections.
    prompt_sections : str
        Specific sections from the project brief to include verbatim.
        Keep this focused — only the sections relevant to this task.
    extra_instructions : str
        Any additional orchestrator-specific instructions.

    Returns
    -------
    str
        The complete prompt text, ready to write to a file.
    """
    # 1. Read the role definition file
    role_file = ROLE_MAP.get(task_type, "worker-agent.agent.md")
    role_content = _read_role_file(role_file, workspace_path)

    sections: list[str] = []

    # 2. Role definition (read from file, not from orchestrator context)
    if role_content:
        sections.append(role_content)
        sections.append("\n---\n")

    # 3. Task assignment
    sections.append(f"# Your Task: {task_id}\n\n")
    sections.append(f"Branch: `{branch}`\n")
    sections.append(f"Task ID: `{task_id}`\n\n")
    sections.append(briefing)
    sections.append("\n")

    # 4. Strategic context
    if strategic_context:
        sections.append(f"\n## Strategic Context\n\n{strategic_context}\n")

    # 5. Artifact contracts
    if produces:
        sections.append(f"\n## Output Files (PRODUCES)\n\nYou MUST create these files: {produces}\n")
    if requires:
        sections.append(f"\n## Input Files (REQUIRES)\n\nThese must exist before you start: {requires}\n")

    # 6. Metric contract (investigation tasks)
    if metric_contract:
        sections.append(f"\n## Metric Contract\n\n{metric_contract}\n")

    # 7. Project brief sections (only relevant parts, not the whole thing)
    if prompt_sections:
        sections.append(f"\n## Relevant Project Brief\n\n{prompt_sections}\n")
    elif prompt_path:
        sections.append(
            f"\n## Project Brief\n\nRead `{prompt_path}` for full context. "
            f"Focus on the sections relevant to your task.\n"
        )

    # 8. Skills to read
    skills = SKILL_MAP.get(task_type, [])
    if skills:
        sections.append("\n## Skills to Read\n\nBefore starting, read these:\n")
        for s in skills:
            sections.append(f"- `{s}`\n")

    # 9. Extra instructions
    if extra_instructions:
        sections.append(f"\n## Additional Instructions\n\n{extra_instructions}\n")

    # 10. Git discipline (always included)
    sections.append(
        "\n## Git Discipline — CRITICAL\n\n"
        "Commit after every meaningful unit of work — a new file, a completed function, "
        "a passing test. Do NOT wait until everything is done.\n"
        f"After each milestone: `git add -A && git commit -m '[msg]' && git push origin {branch}`\n"
        f"When done: `bd close {task_id} --reason '...'` then `git push origin {branch}`\n"
    )

    return "\n".join(sections)


def _read_role_file(filename: str, workspace_path: str = "") -> str:
    """Read a role definition file from .github/agents/."""
    candidates = []
    if workspace_path:
        candidates.append(Path(workspace_path) / ".github" / "agents" / filename)
    # Also try relative to this file (for editable installs)
    pkg_root = Path(__file__).resolve().parent.parent.parent.parent
    candidates.append(pkg_root / ".github" / "agents" / filename)

    for p in candidates:
        if p.exists():
            try:
                return p.read_text()
            except OSError:
                continue
    return ""
