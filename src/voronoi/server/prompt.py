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
    # The orchestrator's role file (.github/agents/swarm-orchestrator.agent.md)
    # contains the full OODA workflow, role selection tables, convergence
    # criteria, and review gate definitions.  We only add mode/rigor context.
    if mode in ("investigate", "explore", "hybrid") and rigor != "standard":
        sections.append(
            "\n## Science Mode Active\n\n"
            f"Mode: **{mode}** | Rigor: **{rigor}**\n\n"
            "Your role file has the complete protocol for this rigor level. "
            "Key reminders:\n"
        )
        if rigor in ("scientific", "experimental"):
            sections.append(
                "- Dispatch Scout first → wait for `.swarm/scout-brief.md`\n"
                "- Dispatch Theorist + Methodologist before investigators\n"
                "- Every investigation task MUST have pre-registration\n"
                "- Methodologist approval required before dispatch\n"
            )
        if rigor in ("analytical", "scientific", "experimental"):
            sections.append(
                "- Findings MUST pass Statistician review\n"
                "- Synthesizer MUST produce `.swarm/claim-evidence.json`\n"
                "- Evaluator score ≥ 0.75 required for convergence\n"
            )
        if rigor == "experimental":
            sections.append(
                "- High-impact findings MUST be replicated\n"
                "- Power analysis MANDATORY for every experiment\n"
            )

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
    sections.append(
        "\n## Workflow\n\n"
        f"1. Read `{prompt_path}` completely\n"
        "2. Read `.github/agents/swarm-orchestrator.agent.md` for your full protocol\n"
        "3. Follow the OODA loop defined in your role file\n"
        "4. Write `.swarm/orchestrator-checkpoint.json` after every cycle\n"
        "5. Synthesizer produces `.swarm/claim-evidence.json`\n"
        "6. Write `.swarm/deliverable.md` and push\n"
        "7. If LaTeX: dispatch compilation agent per `.github/skills/compilation-protocol/SKILL.md`\n"
    )

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
    # Rigor-specific rules are in the orchestrator role file — no duplication here.

    # -- Eval score (for dispatcher convergence tracking) ------------------
    if rigor != "standard":
        sections.append(
            "\n## Evaluator Score Output — STRUCTURED FEEDBACK\n\n"
            "When the Evaluator scores the deliverable, write the result to "
            "`.swarm/eval-score.json` with **section-level feedback**:\n"
            "```json\n"
            '{"score": 0.82, "rounds": 1,\n'
            ' "dimensions": {\n'
            '   "completeness": {"score": 0.85, "note": "Missing sensitivity analysis on param K"},\n'
            '   "coherence": {"score": 0.75, "note": "Section 3 contradicts Section 5 on direction"},\n'
            '   "strength": {"score": 0.70, "note": "Finding bd-43 has N=12, too small for claimed effect"},\n'
            '   "actionability": {"score": 0.90, "note": "Good — concrete parameter ranges provided"}\n'
            ' },\n'
            ' "remediations": [\n'
            '   "Run sensitivity analysis varying K from 0.1 to 1.0",\n'
            '   "Resolve Section 3 vs Section 5 contradiction",\n'
            '   "Increase sample size for bd-43 or downgrade confidence"\n'
            ' ]\n'
            '}\n'
            "```\n"
            "This file is read by the progress monitor to track convergence.\n\n"
            "**The remediations list is critical** — when the orchestrator creates "
            "improvement tasks, it uses these specific remediations as task briefs "
            "instead of guessing what needs to improve.  Be concrete and actionable.\n"
        )

    return "".join(sections)


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

    # 10. Self-verification protocol (Reflection pass + test loop)
    sections.append(
        "\n## Self-Verification — MANDATORY BEFORE CLOSING\n\n"
        "Before closing your task, run this verification sequence:\n\n"
        "**Step 1: Test loop (iterate until pass)**\n"
        "```bash\n"
        "# Run tests relevant to your work\n"
        "pytest <your-test-files> -x -q  # or the project's test command\n"
        "```\n"
        "If tests FAIL: read the failure output, fix the code, re-run. "
        "Repeat up to 3 times.\n"
        "If tests PASS: proceed to Step 2.\n"
        "If still failing after 3 attempts: update Beads:\n"
        "```bash\n"
        f"bd update {task_id} --notes 'VERIFY_EXHAUSTED:3 attempts, last error: <error>'\n"
        "```\n"
        "Do NOT close the task — the orchestrator will triage.\n\n"
        "**Step 2: Self-review checklist**\n"
        "Before closing, verify:\n"
        "1. All PRODUCES artifacts exist and are non-empty\n"
        "2. Reported metrics match the actual data (re-read your output files)\n"
        "3. No hardcoded test values or simulated data\n"
        "4. All commits are pushed to your branch\n\n"
        "If any check fails, fix it now — do NOT close the task.\n\n"
        "**Step 3: Incremental findings commit**\n"
        "If you discovered findings during your work, ensure they are recorded "
        "in Beads notes BEFORE closing. Do not rely on context memory — "
        "write observations to Beads as you go:\n"
        "```bash\n"
        f"bd update {task_id} --notes 'OBSERVATION:<what you found>'\n"
        "```\n"
    )

    # 11. Git discipline (always included)
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
