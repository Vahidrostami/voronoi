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

    # -- Verify loop guidance ----------------------------------------------
    sections.append(
        "\n## Self-Healing Agents (Verify Loop + EVA)\n\n"
        "Every worker agent runs an internal **verify loop** before declaring "
        "success or failure to you.  Workers retry against their own errors "
        "(test failures, lint, crashes) up to a role-specific limit before "
        "escalating.  This means:\n"
        "- Most execution errors are fixed autonomously by the worker\n"
        "- When a worker reports `VERIFY_EXHAUSTED`, check their verify "
        "iteration log in Beads notes before retrying or reassigning\n"
        "- Do NOT immediately re-dispatch a failed task \u2014 diagnose first\n"
        "- Workers also log verify iterations to Beads (VERIFY_ITER notes)\n\n"
        "**Experimental Validity Audit (EVA) \u2014 Investigation tasks only:**\n"
        "After the verify loop passes (experiment ran, metric extracted), "
        "Investigators run a mandatory EVA that checks:\n"
        "1. Was the independent variable actually varied across conditions?\n"
        "2. Did practical constraints (truncation, caching, resource limits) collapse the conditions?\n"
        "3. Is the effect size plausible, or does a ~0 delta indicate a broken manipulation?\n\n"
        "If EVA fails, the Investigator flags `DESIGN_INVALID` and escalates to you "
        "with a diagnosis and proposed fix. Your response:\n"
        "1. Dispatch Methodologist for post-mortem design review\n"
        "2. Wait for Methodologist's POSTMORTEM_DIAGNOSIS\n"
        "3. Create a corrected experiment task incorporating the redesign\n"
        "4. The corrected task must validate the fix before running the full experiment\n"
        "5. NEVER rationalize an invalid experiment as 'a finding to discuss' \u2014 fix and re-run\n"
        "6. NEVER enter a worker's worktree to fix code yourself \u2014 dispatch a new agent\n"
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

    # -- Worker prompt instructions (the key to using .github/agents) ------
    sections.append(
        "\n## Writing Worker Prompts — CRITICAL\n\n"
        "Each worker agent is autonomous — it only knows what you tell it.\n\n"
        "**You MUST include the appropriate role definition** in every worker prompt.  "
        "The role files live in `.github/agents/` in the workspace.  "
        "Before writing each worker prompt, read the role file and prepend its "
        "content to the worker's task-specific instructions.\n\n"
        "Role mapping:\n"
        "| Task type | Role file |\n"
        "|-----------|----------|\n"
        "| Build / implementation | `.github/agents/worker-agent.agent.md` |\n"
        "| Scout / prior research | `.github/agents/scout.agent.md` |\n"
        "| Investigation / experiment | `.github/agents/investigator.agent.md` |\n"
        "| Exploration / comparison | `.github/agents/explorer.agent.md` |\n"
        "| Statistical review | `.github/agents/statistician.agent.md` |\n"
        "| Adversarial critique | `.github/agents/critic.agent.md` |\n"
        "| Theory development | `.github/agents/theorist.agent.md` |\n"
        "| Methodology review | `.github/agents/methodologist.agent.md` |\n"
        "| Synthesis | `.github/agents/synthesizer.agent.md` |\n"
        "| Final evaluation | `.github/agents/evaluator.agent.md` |\n\n"
        "For each worker prompt, include:\n"
        "1. The FULL content of the matching `.github/agents/<role>.agent.md` file\n"
        "2. The task-specific instructions: WHAT to build/investigate, file scope, "
        "acceptance criteria\n"
        "3. FULL relevant context from the project brief (copy sections verbatim)\n"
        "4. STRATEGIC_CONTEXT: how this task fits the whole\n"
        "5. ARTIFACT CONTRACTS: list PRODUCES and REQUIRES files explicitly in the prompt\n"
        "6. METRIC_CONTRACT: for investigation tasks, include the metric shape, baseline reference, and acceptance criteria\n"
        "7. COMMIT CHECKPOINTS: after each milestone, run "
        "`git add -A && git commit -m '[msg]' && git push origin <branch>`\n"
        "8. Completion: `bd close <task-id> --reason \"...\"` then "
        "`git push origin <branch>`\n\n"
        "**Skills to reference in worker prompts** (tell agents to read these):\n"
        "| Skill | When to reference |"
        "\n|-------|-------------------|"
        "\n| `.github/skills/figure-generation/SKILL.md` | Any task producing figures or charts |"
        "\n| `.github/skills/compilation-protocol/SKILL.md` | LaTeX compilation tasks |"
        "\n| `.github/skills/investigation-protocol/SKILL.md` | Investigation/experiment tasks |"
        "\n| `.github/skills/evidence-system/SKILL.md` | Tasks producing findings |"
        "\n| `.github/skills/artifact-gates/SKILL.md` | Tasks with PRODUCES/REQUIRES contracts |\n"
    )

    # -- Rules -------------------------------------------------------------
    sections.append(
        "\n## Rules\n\n"
        "- Read `.github/agents/swarm-orchestrator.agent.md` at startup\n"
        "- Read the FULL project brief before planning\n"
        "- No overlapping file scopes between agents\n"
        "- Write detailed, context-rich worker prompts with role definitions\n"
        "- Diagnose failures (check git log, tmux output) before retrying\n"
        "- Push all completed work to remote when done\n"
        f"- Max concurrent agents: {max_agents}\n"
        "- EVERY task MUST declare PRODUCES and REQUIRES in Beads notes\n"
        "- For investigation epics, create a BASELINE task as the FIRST subtask \u2014 "
        "all experimental tasks depend on it\n"
        "- For investigation tasks, include METRIC_CONTRACT in Beads notes "
        "(metric shape, baseline reference, acceptance criteria)\n"
        "- Workers self-heal via verify loops \u2014 when they report VERIFY_EXHAUSTED, "
        "read their iteration log before re-dispatching\n"
        "- When a worker reports DESIGN_INVALID, dispatch Methodologist for post-mortem "
        "\u2192 create corrected experiment task\n"
        "- NEVER enter a worker's worktree to fix code yourself \u2014 "
        "dispatch a new agent or reassign the task\n"
        "- NEVER rationalize an invalid experiment as a finding \u2014 fix the design and re-run\n"
        "- spawn-agent.sh will REJECT dispatch if REQUIRES files are missing\n"
        "- merge-agent.sh will REJECT merge if PRODUCES files are missing\n"
        "- Include commit checkpoint instructions in EVERY worker prompt:\n"
        '  "After completing [milestone], run git add -A && git commit -m \'[msg]\' '
        "&& git push origin [branch] BEFORE continuing\"\n"
        "- For figure-producing tasks, reference `.github/skills/figure-generation/SKILL.md`\n"
        "- For LaTeX compilation tasks, reference `.github/skills/compilation-protocol/SKILL.md`\n"
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
        f"{ooda_step}. OODA loop:\n"
        "   - Observe: `bd ready --json`, check findings, belief map, git activity, "
        "experiment ledger (`.swarm/experiments.tsv`)\n"
        "   - Orient:  Classify events, update strategic context, check convergence\n"
        "   - Decide:  Prioritize by information gain, check review gates\n"
        "   - Act:     Spawn agents (with role definitions + METRIC_CONTRACT!), merge work, "
        "dispatch reviewers\n"
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
