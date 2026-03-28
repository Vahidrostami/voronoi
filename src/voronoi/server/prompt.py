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
        One of discover, prove.
    rigor : str
        One of adaptive, scientific, experimental.
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
        "discover": "Discovery",
        "prove": "Proof",
    }
    verb = _MODE_VERB.get(mode, mode.title())
    label = codename or "Voronoi"

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
    if mode in ("discover", "prove"):
        sections.append(
            "\n## Science Mode Active\n\n"
            f"Mode: **{mode}** | Rigor: **{rigor}**\n\n"
            "Your role file has the complete protocol for this rigor level. "
            "Key reminders:\n"
        )
        if mode == "prove" or rigor in ("scientific", "experimental"):
            sections.append(
                "- Dispatch Scout first → wait for `.swarm/scout-brief.md`\n"
                "- Dispatch Theorist + Methodologist before investigators\n"
                "- Every investigation task MUST have pre-registration\n"
                "- Methodologist approval required before dispatch\n"
            )
            # Human gate instructions for high-rigor investigations
            sections.append(
                "\n**Human Review Gates (Scientific+ rigor):**\n"
                "At two key decision points, pause for human approval by writing "
                "`.swarm/human-gate.json`:\n\n"
                "**Gate 1: After pre-registration** (before running experiments):\n"
                "```json\n"
                '{\"gate\": \"pre-registration\", \"status\": \"pending\",\n'
                ' \"summary\": \"Hypothesis: [X]. Method: [Y]. N=[Z]. Ready to run experiments.\"}\n'
                "```\n"
                "Then poll `.swarm/human-gate.json` every 30s until `status` changes to "
                "`approved` or `revision_requested`.  If revision is requested, read `feedback` "
                "field and adjust the pre-registration accordingly.\n\n"
                "**Gate 2: Before convergence** (before finalizing deliverable):\n"
                "```json\n"
                '{\"gate\": \"convergence\", \"status\": \"pending\",\n'
                ' \"summary\": \"[summary of findings]. Score: [X]. Ready to converge.\"}\n'
                "```\n"
                "Same polling protocol.  Do NOT write deliverable.md until approved.\n"
            )
        if rigor in ("adaptive", "scientific", "experimental") or mode == "prove":
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

    # -- Creative Freedom (DISCOVER mode) ------------------------------------
    if mode in ("discover",) or (mode not in ("prove",) and rigor == "adaptive"):
        sections.append(
            "\n## Creative Freedom Protocol (DISCOVER Mode)\n\n"
            "This is free scientific exploration. You are NOT locked into a rigid sequence.\n\n"
            "**What to do:**\n"
            "- Cast roles DYNAMICALLY based on what you find — don't pre-commit to a fixed team\n"
            "- Let multiple agents pursue different hypotheses simultaneously\n"
            "- When an agent finds something unexpected, consider pivoting the investigation\n"
            "- Start with Scout + any agents that seem useful — no mandatory sequence\n\n"
            "**Adaptive rigor:** Start light (no pre-registration, no human gates). "
            "When testable hypotheses crystallize in the belief map, ESCALATE:\n"
            "- Engage Methodologist to review experimental design\n"
            "- Engage Statistician for quantitative findings\n"
            "- Require pre-registration for hypothesis tests\n"
            "- Activate review gates for completed experiments\n\n"
            "**SERENDIPITY handling:**\n"
            "When an agent flags `SERENDIPITY:<description>` in Beads notes:\n"
            "1. Read the description during your OODA Observe step\n"
            "2. Decide: pivot investigation, spawn follow-up agents, or note and continue\n"
            "3. NEVER discard unexpected findings — record them even if not pursued\n"
            "4. Update the belief map with any serendipitous hypotheses\n"
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

    # -- REVISE task support (details in skill) ----------------------------
    sections.append(
        "\n## REVISE Tasks & Calibration\n\n"
        "When a pilot experiment fails calibration, create a REVISE task (not a fresh task) "
        "that carries forward `REVISE_OF`, `PRIOR_RESULT`, `FAILURE_DIAGNOSIS`, and `REVISED_PARAMS`.\n"
        "Read `.github/skills/revise-calibration/SKILL.md` for the full protocol and "
        "calibration iteration caps.\n"
    )

    # -- OODA Protocol (collapsed from 4 sections) ------------------------
    sections.append(
        "\n## OODA Protocol\n\n"
        "Your role file (`.github/agents/swarm-orchestrator.agent.md`) has the full "
        "checkpoint-based OODA protocol, targeted query patterns, and context budget.\n\n"
        "**Each cycle:**\n"
        f"1. Read checkpoint + `.swarm/brief-digest.md` (NOT the full `{prompt_path}`)\n"
        "2. Read `.swarm/dispatcher-directive.json` if it exists — obey it:\n"
        "   - `context_advisory`: prioritize convergence\n"
        "   - `context_warning`: run `/compact` NOW to recover context budget, then delegate remaining work\n"
        "   - `context_critical`: run `/compact` NOW, write checkpoint, dispatch Scribe immediately\n"
        "3. Run targeted `bd query` (NEVER `bd list --json` in routine cycles)\n"
        "4. Orient → Decide → Act\n"
        "5. Write checkpoint, update belief map\n\n"
        "**At startup only:** Read `{prompt_path}` completely, then extract critical "
        "constraints into `.swarm/brief-digest.md` (~50 lines): success criteria, "
        "experimental design, hard constraints, mandated entry point. After that, "
        "work from checkpoint + brief-digest.\n"
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

    # -- Anti-simulation enforcement (expanded — this is critical) ----------
    sections.append(
        "\n## LLM Calls via Copilot CLI — MANDATORY\n\n"
        "When experiments need programmatic LLM calls (discovery, judge, etc.), "
        "agents MUST use:\n"
        "```bash\n"
        "# Read configured model from workspace config\n"
        "LLM_MODEL=$(jq -r '.worker_model // \"\"' .swarm-config.json 2>/dev/null)\n"
        "MODEL_FLAG=\"\"\n"
        "if [[ -n \"$LLM_MODEL\" ]]; then MODEL_FLAG=\"--model $LLM_MODEL\"; fi\n\n"
        "copilot $MODEL_FLAG -p \"<prompt>\" -s --no-color --allow-all\n"
        "```\n"
        "- Pass the prompt as a **direct argument** to `-p`, NOT via stdin.\n"
        "- **NEVER** use `echo \"...\" | copilot -p -` or pipe/stdin patterns — "
        "they produce empty/generic responses and silently break experiments.\n"
        "- **ALWAYS** include the `--model` flag from `.swarm-config.json` — without it, "
        "copilot uses its default model, not the one configured for this investigation.\n"
        "- Cache responses by SHA-256 hash of the prompt text.\n\n"
        "\n## Anti-Simulation — HARD GATE\n\n"
        "**NEVER create simulation/mock/fake files that replace real LLM calls.** "
        "This is a convergence-blocking violation.\n\n"
        "Specifically:\n"
        "- NEVER create files named `*sim*`, `*mock*`, `*fake*` that replace the mandated entry point\n"
        "- NEVER hardcode detection probabilities, effect sizes, or scores that the experiment "
        "is supposed to *measure* — this is circular reasoning\n"
        "- NEVER use `np.random` / `random` sampling as a substitute for real LLM calls\n"
        "- If the experiment requires too many LLM calls, **reduce N or k** — do NOT simulate\n"
        "- If real results are disappointing (e.g., p > 0.05), report them honestly and flag "
        "`RESULT_CONTRADICTS_HYPOTHESIS` — do NOT create a simulation to get better numbers\n\n"
        "**The convergence gate will BLOCK completion** if it detects:\n"
        "- Any `run_sim.py` / `run_mock.py` / `run_fake.py` runner scripts (CRITICAL)\n"
        "- Source files with simulation-bypass patterns (hardcoded probabilities, np.random.seed)\n"
        "- Insufficient LLM cache entries relative to the experiment design\n"
        "- `results.json` with simulation provenance markers\n\n"
        "**Provenance requirement:** Every `results.json` MUST include a `runner` field "
        "naming the script that produced it (e.g., `\"runner\": \"run_experiments.py\"`). "
        "The mandated entry point declared in PROMPT.md is the ONLY valid runner.\n"
    )

    # -- Tools & dispatch protocol are fully covered in the role file ----
    # The orchestrator role file has Tools & Systems, the full dispatch
    # spec format, and task type → role mapping.  No duplication here.

    # -- Manuscript delegation — MANDATORY ---------------------------------
    sections.append(
        "\n## Manuscript Writing — ALWAYS DELEGATE TO SCRIBE\n\n"
        "**NEVER write the manuscript/paper/deliverable yourself in the orchestrator session.**\n"
        "Manuscript writing is extremely context-heavy and WILL exhaust your context window "
        "if attempted inline — leading to session termination before the deliverable is written.\n\n"
        "**Mandatory workflow:**\n"
        "1. When all experiments are complete and success criteria are met, dispatch a "
        "**Scribe** worker (`task_type: \"scribe\"`) with a briefing that lists:\n"
        "   - All completed findings and their locations\n"
        "   - The success criteria status\n"
        "   - The target structure (e.g., academic paper sections)\n"
        "2. The Scribe writes the deliverable in its own worktree with a full context window\n"
        "3. After merge, verify the deliverable exists and dispatch the Evaluator\n\n"
        "**Why:** Your context is consumed by OODA cycles, experiment monitoring, and "
        "findings synthesis after hours of orchestration. The Scribe starts fresh with "
        "100% of its context available for writing — producing higher quality output "
        "and preventing session crashes.\n"
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
    )
    if safe:
        sections.append(
            "- **Safe mode active**: spawn workers with `./scripts/spawn-agent.sh --safe`\n"
        )
    sections.append(
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
    sections.append(
            "\n## Evaluator Score Output\n\n"
            "After the Evaluator scores the deliverable, write `.swarm/eval-score.json` "
            "with fields: `score` (0-1), `rounds`, `dimensions` (per-dimension scores "
            "and notes for completeness/coherence/strength/actionability), and "
            "`remediations` (list of concrete improvement actions).\n\n"
            "The `remediations` list is critical — improvement tasks use these as briefs. "
            "See `.github/agents/evaluator.agent.md` for the full evaluation protocol.\n"
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
        ".github/skills/context-management/SKILL.md",
    ],
    "experiment": [
        ".github/skills/investigation-protocol/SKILL.md",
        ".github/skills/evidence-system/SKILL.md",
        ".github/skills/context-management/SKILL.md",
    ],
    "paper": [
        ".github/skills/figure-generation/SKILL.md",
        ".github/skills/compilation-protocol/SKILL.md",
    ],
    "compilation": [
        ".github/skills/figure-generation/SKILL.md",
        ".github/skills/compilation-protocol/SKILL.md",
    ],
    "scout": [
        ".github/skills/deep-research/SKILL.md",
    ],
    "exploration": [
        ".github/skills/deep-research/SKILL.md",
        ".github/skills/context-management/SKILL.md",
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
        "4. If a remote named `origin` exists, all commits are pushed to your branch. "
        "If no remote exists in this workspace, keep the commits local and report `NO_REMOTE` in Beads instead of inventing a remote.\n\n"
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
        f"After each milestone: `git add -A && git commit -m '[msg]'`\n"
        f"If `origin` exists: `git push origin {branch}`\n"
        "If no `origin` exists: keep the commit local, Do NOT create a remote just to satisfy this rule, "
        f"and record `NO_REMOTE` in `bd update {task_id} --notes 'NO_REMOTE: local-only workspace'`.\n"
        f"When done: `bd close {task_id} --reason '...'`\n"
        f"If `origin` exists: `git push origin {branch}`\n"
    )

    return "\n".join(sections)


def _read_role_file(filename: str, workspace_path: str = "") -> str:
    """Read a role definition file from the agents directory.

    Searches:
    1. workspace_path/.github/agents/ (runtime investigation workspace)
    2. src/voronoi/data/agents/ (canonical source in this package)
    """
    candidates = []
    if workspace_path:
        candidates.append(Path(workspace_path) / ".github" / "agents" / filename)
    # Package data directory (canonical location for both editable and packaged installs)
    pkg_data = Path(__file__).resolve().parent.parent / "data"
    candidates.append(pkg_data / "agents" / filename)

    for p in candidates:
        if p.exists():
            try:
                return p.read_text()
            except OSError:
                continue
    return ""
