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
    max_agents: int = 6,
    safe: bool = False,
    prior_context: dict | None = None,
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
    prior_context : dict | None
        If set, contains warm-start data from prior runs:
        - ``ledger_summary``: formatted claim ledger for the prompt
        - ``pi_feedback``: verbatim human feedback
        - ``cycle_number``: which round this is
        - ``immutable_paths``: artifact paths that must not be modified
        - ``artifact_manifest``: reusable artifacts description
        - ``round_summary``: structured summary of prior round outcomes
        - ``state_digest``: compact state digest from prior round
        - ``success_criteria_status``: dict with ``met`` and ``total`` counts
    """
    _MODE_VERB = {
        "discover": "Discovery",
        "prove": "Proof",
    }
    verb = _MODE_VERB.get(mode, mode.title())
    label = codename or "Voronoi"

    sections: list[str] = []

    # -- Stall directive (highest priority — inject before anything else) --
    # When the dispatcher escalates a learning stall, it writes
    # .swarm/stall-signal.json. Surface the instruction at the very top so
    # the orchestrator sees it before the rest of the prompt.
    # Each strike (1-3) also carries a `diagnosis` block — a belief snapshot
    # the orchestrator uses to self-steer on the next OODA cycle.
    # See docs/SERVER.md §3 (Stall Escalation).
    if workspace_path:
        signal_path = Path(workspace_path) / ".swarm" / "stall-signal.json"
        if signal_path.exists():
            try:
                import json as _json
                signal = _json.loads(signal_path.read_text())
                instruction = signal.get("instruction", "").strip()
                level = signal.get("level")
                directive = signal.get("directive", "")
                diagnosis = signal.get("diagnosis") or {}
                if instruction:
                    block = (
                        f"## ⚠ STALL DIRECTIVE — LEVEL {level} "
                        f"({directive})\n\n"
                        f"{instruction}\n\n"
                    )
                    if isinstance(diagnosis, dict) and diagnosis:
                        block += "**Belief snapshot (from your last checkpoint):**\n"
                        # Render a compact, stable-ordered view.
                        _order = [
                            "elapsed_minutes", "phase", "lifecycle_phase",
                            "tasks_in_progress", "tasks_open",
                            "active_workers", "next_actions",
                        ]
                        for key in _order:
                            if key not in diagnosis:
                                continue
                            val = diagnosis[key]
                            if isinstance(val, list):
                                if not val:
                                    continue
                                block += f"- {key}:\n"
                                for item in val:
                                    block += f"  - {item}\n"
                            else:
                                block += f"- {key}: {val}\n"
                        block += "\n"
                    block += (
                        "This directive overrides default OODA behaviour. "
                        "Obey it on this cycle.\n\n"
                    )
                    sections.append(block)
            except (OSError, ValueError):
                pass

    # -- Identity & Lifecycle (top-level — read first) --------------------
    sections.append(
        "You are the Voronoi swarm orchestrator — a strategist called in when "
        "scientific decisions are needed.\n\n"
        "**Lifecycle:** Each session is one strategic pass. Read checkpoint → "
        "run OODA cycles → dispatch workers → write checkpoint → exit. "
        "The dispatcher monitors workers and relaunches you when results arrive, "
        "anomalies occur, or decisions are needed. Do NOT idle-loop, sleep-poll, "
        "or monitor processes — that is infrastructure work, not science.\n"
    )

    # -- Role protocol (the critical link to .github/agents) ---------------
    sections.append(
        "\n## Your Full Protocol\n\n"
        "Read `.github/agents/swarm-orchestrator.agent.md` NOW — it contains your "
        "complete role definition including OODA workflow, role selection tables, "
        "convergence criteria, paradigm checks, bias monitoring, and the macro "
        "retry loop.  Follow it precisely.\n"
    )

    # -- Worker dispatch (the critical skill) ------------------------------
    sections.append(
        "\n## Worker Dispatch — MANDATORY\n\n"
        "**Before dispatching any worker**, read `.github/skills/worker-lifecycle/SKILL.md`. "
        "It has the complete step-by-step recipe: `build_worker_prompt()` → "
        "`spawn-agent.sh` → checkpoint → merge.\n\n"
        "**NEVER use Copilot's built-in agent tools** (General-purpose agent, etc.) "
        "to run experiments or tasks. They run inline in YOUR session, consuming "
        "YOUR context window. ALWAYS use `./scripts/spawn-agent.sh` — it creates "
        "an isolated tmux window with a fresh Copilot instance.\n\n"
        "**After dispatching workers with no immediate work remaining:**\n"
        "Write `.swarm/orchestrator-checkpoint.json` with `active_workers` list "
        "and `next_actions`, then EXIT cleanly. The dispatcher accumulates events "
        "(worker completions, findings, serendipity, DESIGN_INVALID) while you "
        "are away and delivers them in your next resume prompt.\n\n"
        "**Do NOT:**\n"
        "- Sleep, poll, or use `ps aux | grep` to monitor workers\n"
        "- Launch experiments via `nohup` or background subprocesses\n"
        "- Run long-running scripts inline — delegate to workers\n"
    )

    # -- Mission -----------------------------------------------------------
    sections.append(f"\n## {verb}\n\n")
    if workspace_path:
        sections.append(f"**Workspace:** {workspace_path}\n")
    sections.append(
        f"**Mode:** {mode}\n"
        f"**Rigor:** {rigor}\n"
        f"**Max parallel hypothesis-tranches:** {max_agents}\n"
    )
    sections.append(
        "\n### Hypothesis-Tranche Parallelism — Evidence-Gated Scaling\n\n"
        "Think in **tranches**, not in workers. A *tranche* is one hypothesis arm "
        "(a lead hypothesis + its controls + its sensitivity variants) dispatched "
        "as a coherent unit. A tranche may internally fan out to several worker "
        "agents (e.g. one runner per variant), but scientifically it counts as "
        "ONE arm of comparison.\n\n"
        "**Evidence-gated scaling:** You operate in **epochs**. Each epoch earns "
        "the right to scale by producing evidence.\n\n"
        "- **Epoch 1** (start): Max 2 tranches. Prove the approach works.\n"
        "- **Epoch 2** (after evidence): Max 4 tranches. Evidence supports scaling.\n"
        "- **Epoch 3+** (validated): Full budget.\n\n"
        "The dispatcher tracks epoch state in `.swarm/epoch-state.json` and "
        "auto-advances when findings move the belief map. Read it each OODA cycle.\n\n"
        "**CRITICAL:** Do NOT dispatch more tranches than `max_tranches` in "
        "`epoch-state.json`. If the file says `max_tranches: 2`, you may NOT "
        "run 6 hypotheses in parallel — even if you have ideas for all 6. "
        "Pick the 2 highest information-gain hypotheses.\n\n"
        "**Minimum viable experiment (epoch 1):** Your FIRST dispatch in a new "
        "investigation MUST be a single concrete experiment that:\n"
        "- Can complete in <30 minutes\n"
        "- Produces ONE measurable outcome\n"
        "- Tests the core assumption of the investigation\n\n"
        "This is your pilot study. If it doesn't produce a result, diagnose why "
        "before dispatching anything else. Do NOT scale to multiple tranches "
        "until the MVE succeeds.\n\n"
        f"**Hard cap:** {max_agents} tranches maximum (all epochs). "
        "Prefer running hypotheses simultaneously on the same held-out data "
        "and same seeds. When a tranche finishes, use its slot for a new "
        "tranche rather than for a new variant of an already-finished arm.\n"
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
    is_continuation = prior_context is not None
    if mode in ("discover", "prove"):
        sections.append(
            "\n## Science Mode Active\n\n"
            f"Mode: **{mode}** | Rigor: **{rigor}**\n\n"
            "Your role file has the complete protocol for this rigor level. "
            "Key reminders:\n"
        )
        if mode == "prove" or rigor in ("scientific", "experimental"):
            if is_continuation:
                # Continuation: skip Scout/Theorist if they already ran
                sections.append(
                    "- If `.swarm/scout-brief.md` already exists, do NOT re-dispatch "
                    "the Scout — read the existing brief\n"
                    "- If `.swarm/novelty-gate.json` is missing, treat Scout setup "
                    "as BLOCKED and dispatch Scout follow-up before other work\n"
                    "- If `.swarm/belief-map.json` already exists, do NOT re-dispatch "
                    "Theorist — build on the existing belief map\n"
                    "- Only re-dispatch Methodologist if PI feedback requires design changes\n"
                    "- Pre-registration still required for NEW experiments\n"
                    "- Scientific rigor: Methodologist review is advisory; "
                    "Experimental rigor: approval required before dispatch\n"
                )
            else:
                sections.append(
                    "- Dispatch Scout first → wait for `.swarm/scout-brief.md` "
                    "AND `.swarm/novelty-gate.json`\n"
                    "- Dispatch Theorist + Methodologist before investigators\n"
                    "- Every investigation task MUST have pre-registration\n"
                    "- Scientific rigor: Methodologist review is advisory; "
                    "Experimental rigor: approval required before dispatch\n"
                )
            # Human gate instructions for high-rigor investigations.
            # The orchestrator MUST NOT poll — it writes the gate, writes a
            # park checkpoint, and EXITS.  The dispatcher detects the gate
            # via check_human_gates(), kills the session if still alive,
            # and resumes the orchestrator after /approve or /revise.
            sections.append(
                "\n**Human Review Gates (Scientific+ rigor) — PARK, DO NOT POLL:**\n"
                "At two key decision points, pause for human approval by writing "
                "`.swarm/human-gate.json`, then park and EXIT. The dispatcher wakes "
                "you after the human approves or requests revision.\n\n"
                "**Protocol (both gates):**\n"
                "1. Write `.swarm/human-gate.json` with `status: \"pending\"`.\n"
                "2. Write `.swarm/orchestrator-checkpoint.json` with "
                "`active_workers: []`, `phase: \"awaiting-human-gate\"`, and a "
                "`next_actions` list describing what to do once approved.\n"
                "3. EXIT cleanly. Do NOT sleep, poll, `cat`, or re-read the gate "
                "file. Your process must terminate — otherwise the dispatcher "
                "cannot route the approval back to a fresh session.\n"
                "4. On wake, read the gate file: if `status == \"approved\"` proceed; "
                "if `status == \"revision_requested\"` read `feedback` and adjust.\n\n"
                "**Gate 1: After pre-registration** (before running experiments):\n"
                "```json\n"
                '{\"gate\": \"pre-registration\", \"status\": \"pending\",\n'
                ' \"summary\": \"Hypothesis: [X]. Method: [Y]. N=[Z]. Ready to run experiments.\"}\n'
                "```\n\n"
                "**Gate 2: Before convergence** (before finalizing deliverable):\n"
                "```json\n"
                '{\"gate\": \"convergence\", \"status\": \"pending\",\n'
                ' \"summary\": \"[summary of findings]. Score: [X]. Ready to converge.\"}\n'
                "```\n"
                "Do NOT write deliverable.md until the gate is approved on a "
                "subsequent session.\n"
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

    # -- Problem Positioning (science modes) --------------------------------
    if mode in ("discover", "prove"):
        sections.append(
            "\n## Problem Positioning — DO NOT REPEAT KNOWN SCIENCE\n\n"
            "After the Scout delivers `.swarm/scout-brief.md`, read the "
            "**Problem Positioning** section. All agents MUST:\n"
            "- Frame results as DELTA from the known frontier — not standalone claims\n"
            "- Never re-derive or re-prove published results — cite them\n"
            "- The deliverable's introduction MUST use the Scout's field context "
            "and gap statement\n"
            "- If a result matches a cited paper's finding, acknowledge it as "
            "replication, not discovery\n\n"
            "**Novelty gate:** After Scout completes, `.swarm/novelty-gate.json` "
            "is REQUIRED. If it is missing, this is BLOCKED setup — dispatch "
            "Scout follow-up and do not proceed to other agents. If it exists "
            "with `status: blocked`, HALT. Write `.swarm/human-gate.json` "
            "with `gate: novelty` and wait for human decision "
            "(approved / pivot / abort). Only proceed when the gate exists "
            "with `status: clear`.\n"
        )

    # -- Creative Freedom (DISCOVER mode) ------------------------------------
    if mode in ("discover",) or (mode not in ("prove",) and rigor == "adaptive"):
        sections.append(
            "\n## Creative Freedom Protocol (DISCOVER Mode)\n\n"
            "This is free scientific exploration. You are NOT locked into a rigid sequence.\n\n"
            "**What to do:**\n"
            "- Start with Scout only. Wait for `.swarm/scout-brief.md` and "
            "a clear `.swarm/novelty-gate.json` before dispatching other "
            "investigation agents\n"
            "- Cast roles DYNAMICALLY based on what you find — don't pre-commit to a fixed team\n"
            "- After the novelty gate is clear, let multiple agents pursue "
            "different hypotheses simultaneously\n"
            "- When an agent finds something unexpected, consider pivoting the investigation\n"
            "**Adaptive rigor:** Start light (no pre-registration, no human gates). "
            "When testable hypotheses crystallize in the belief map, ESCALATE:\n"
            "- Engage Methodologist to review experimental design\n"
            "- Engage Statistician for quantitative findings\n"
            "- Require pre-registration for hypothesis tests\n"
            "- Activate review gates for completed experiments\n\n"
            "**Belief map confidence tiers** (use instead of raw probabilities):\n"
            "- `unknown`: no evidence yet (max priority)\n"
            "- `hunch`: slight lean after literature/reasoning\n"
            "- `supported`: evidence points this way\n"
            "- `strong`: multiple independent lines agree\n"
            "- `resolved`: confirmed or refuted (done)\n"
            "Always include `rationale` (cite findings) and `next_test` (what would change your mind).\n\n"
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

    # -- OODA Protocol (lean — role file has the full protocol) --------
    sections.append(
        "\n## OODA Protocol\n\n"
        "Your role file (`.github/agents/swarm-orchestrator.agent.md`) has the full "
        "checkpoint-based OODA protocol.  Follow it precisely.\n\n"
        "**Dispatcher integration (not in role file):**\n"
        "- Read `.swarm/dispatcher-directive.json` each cycle — obey it:\n"
        "  - `context_advisory`: prioritize convergence\n"
        "  - `context_warning`: run `/compact` NOW, then delegate remaining work\n"
        "  - `context_critical`: run `/compact` NOW, write checkpoint, dispatch Scribe immediately\n"
        "- Run `/context` each cycle and include the snapshot in your checkpoint (`context_snapshot` field).\n"
        "  This gives the dispatcher ground-truth token data for pressure directives.\n\n"
        f"**Brief-digest rule:** At startup, read `{prompt_path}` fully, then extract "
        "critical constraints into `.swarm/brief-digest.md` (~50 lines). After that, "
        f"work from checkpoint + brief-digest (NOT the full `{prompt_path}`).\n\n"
        "**On resume (checkpoint exists):** Read ONLY: (1) checkpoint, (2) brief-digest, "
        "(3) dispatcher-directive, (4) `bd ready`. Do NOT re-read agent definitions, "
        "belief map, or other artifacts unless the checkpoint indicates they changed.\n"
    )

    # -- Success criteria ---------------------------------------------------
    if is_continuation:
        sections.append(
            "\n## Success Criteria Tracking\n\n"
            "**Continuation round:** `.swarm/success-criteria.json` already exists "
            "from the prior round. Read it — do NOT overwrite it. Update `met` fields "
            "as new evidence arrives. Only add NEW criteria if the PI's feedback "
            "introduces new requirements.\n\n"
        )
    else:
        sections.append(
            "\n## Success Criteria Tracking\n\n"
            "At investigation start, write `.swarm/success-criteria.json` capturing "
            "the PROMPT's measurable success criteria.  Format:\n"
            "```json\n"
            "[{\"id\": \"SC1\", \"description\": \"L4 outperforms L1 on F1\", \"met\": false},\n"
            " {\"id\": \"SC2\", \"description\": \"Pipeline compresses >=10x\", \"met\": false}]\n"
            "```\n\n"
        )
    sections.append(
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
        "4. Only proceed to paper after the revised experiment passes its gate\n\n"
        "**Sentinel alerts and DESIGN_INVALID — IMPORTANT:**\n"
        "When you see a `sentinel_violation` directive in `.swarm/dispatcher-directive.json`, "
        "this IS a DESIGN_INVALID event.  The sentinel has already detected and flagged it.  "
        "Do NOT create a separate DESIGN_INVALID task — the sentinel's alert is the flag.  "
        "Read `.swarm/sentinel-audit.json` first. If `critical_failures` contains "
        "`CONTRACT_SCHEMA`, the contract file itself is malformed — rewrite it in the "
        "schema documented in §Experiment Contract below. Do NOT dispatch Methodologist "
        "for a schema error.  For any other failure: dispatch Methodologist, create "
        "REVISE task, do NOT fix code yourself.\n"
    )

    # -- LLM calls (skill ref) --------------------------------------------
    sections.append(
        "\n## LLM Calls & Anti-Simulation\n\n"
        "Read `.github/skills/copilot-cli-usage/SKILL.md` for the correct "
        "Copilot CLI invocation pattern.\n\n"
        "**Hard gate:** NEVER create simulation/mock/fake files that replace real "
        "LLM calls. NEVER hardcode detection probabilities or effect sizes the "
        "experiment is supposed to measure.  If real results are disappointing, "
        "report them honestly — do NOT simulate better numbers.\n\n"
        "**Provenance:** Every `results.json` MUST include a `runner` field "
        "naming the script that produced it.\n"
    )

    # -- Delegation rules (compact) ----------------------------------------
    sections.append(
        "\n## Delegation Rules\n\n"
        "- **NEVER run experiments** (>5min) in the orchestrator session — dispatch a worker\n"
        "- **NEVER write >20 lines of code** in the orchestrator — dispatch a worker\n"
        "- **NEVER write the manuscript** yourself — dispatch a Scribe worker "
        "(`task_type: \"scribe\"`). The Scribe writes LaTeX, not Markdown.\n"
        "- After Scribe, verify `paper.tex` + `paper.pdf` exist, then dispatch Evaluator\n"
        "- The Scribe writes `.swarm/deliverable.md` as a SUMMARY for convergence "
        "— this is NOT the paper itself\n"
    )

    # -- Experiment Contract (Sentinel) — compact ref -----------------------
    sections.append(
        "\n## Experiment Contract (Sentinel)\n\n"
        "After experiment design, write `.swarm/experiment-contract.json` declaring "
        "structural validity checks. The dispatcher runs an autonomous Sentinel that "
        "verifies outputs against this contract.\n\n"
        "**REQUIRED schema — top-level keys are FIXED.** The Sentinel parses ONLY "
        "these keys; any other top-level shape (e.g. `studies`, `phases`, "
        "`hard_gates`, `primary_metric`, `runner`) is rejected with "
        "`CONTRACT_SCHEMA: unparseable or unknown shape` and writes a "
        "`sentinel_violation` directive on every poll. Use this exact shape:\n\n"
        "```json\n"
        "{\n"
        '  "experiment_id": "<id>",\n'
        '  "independent_variable": "<name of the IV>",\n'
        '  "conditions": ["<cond1>", "<cond2>", "..."],\n'
        '  "manipulation_checks": [\n'
        '    {"check_type": "hash_distinct", "target": "<file glob>", '
        '"field": "<json path>", "conditions": ["<cond1>", "<cond2>"]}\n'
        "  ],\n"
        '  "required_outputs": [\n'
        '    {"path": "<relative/path/to/output>", "description": "<what it is>"}\n'
        "  ],\n"
        '  "degeneracy_checks": [\n'
        '    {"check_type": "min_variance", "target": "<file>", '
        '"field": "<path>", "min_std": 0.01}\n'
        "  ],\n"
        '  "phase_gates": [\n'
        '    {"from_phase": "<phase>", "to_phase": "<next>", "checks": [...]}\n'
        "  ]\n"
        "}\n"
        "```\n\n"
        "Encode multi-study or multi-phase designs by enumerating conditions and "
        "using `phase_gates` — do NOT invent a nested `studies`/`phases` wrapper.\n\n"
        "Available check types: `hash_distinct`, `value_range`, `metric_range`, "
        "`not_identical`, `min_distinct_values`, `min_variance`.\n\n"
        "If the Sentinel detects a violation, it writes `.swarm/sentinel-audit.json` "
        "and a `sentinel_violation` directive. When you see this:\n"
        "1. STOP — do not dispatch new workers or cross phase gates\n"
        "2. Read `.swarm/sentinel-audit.json`\n"
        "3. If the failure is `CONTRACT_SCHEMA`, the contract itself is malformed "
        "— rewrite `.swarm/experiment-contract.json` in the schema above. Do NOT "
        "dispatch a Methodologist for a schema error; just fix the file.\n"
        "4. For any other failure: dispatch Methodologist for post-mortem and "
        "create a REVISE task — do NOT fix experiment code yourself.\n"
    )

    # -- Rules (compact) ---------------------------------------------------
    sections.append(
        "\n## Rules\n\n"
        "- Read `.github/agents/swarm-orchestrator.agent.md` at startup\n"
        "- Read `.github/skills/worker-lifecycle/SKILL.md` before dispatching workers\n"
        "- Read the FULL project brief ONCE, then work from checkpoint + brief-digest\n"
        "- No overlapping file scopes between agents\n"
        "- Diagnose failures (check git log, tmux output) before retrying\n"
        "- Push all completed work to remote when done\n"
        f"- Max parallel hypothesis-tranches: {max_agents}\n"
    )
    if safe:
        sections.append(
            "- **Safe mode active**: spawn workers with `./scripts/spawn-agent.sh --safe`\n"
        )
    sections.append(
        "- EVERY task MUST declare PRODUCES and REQUIRES in Beads notes\n"
        "- BASELINE task is FIRST subtask \u2014 all experimental tasks depend on it\n"
        "- NEVER enter a worker's worktree to fix code \u2014 dispatch a new agent\n"
        "- `spawn-agent.sh` REJECTS dispatch if REQUIRES files are missing\n"
        "- `merge-agent.sh` REJECTS merge if PRODUCES files are missing\n"
        "- Before convergence: `./scripts/convergence-gate.sh . <rigor>`\n"
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

    # -- Warm-Start Brief (multi-run context) ------------------------------
    if prior_context:
        cycle = prior_context.get("cycle_number", 2)
        sections.append(
            f"\n## Round {cycle} — Continuation\n\n"
            f"This is round {cycle} of an iterative investigation. "
            "Prior rounds established findings that are summarized below. "
            "Your job: address the PI's feedback while preserving confirmed results.\n\n"
            "**Critical rules for continuation rounds:**\n"
            "- Do NOT re-run experiments whose results are not challenged\n"
            "- Do NOT regenerate data that locked claims depend on\n"
            "- If you need additional data, create NEW files — don't modify existing ones\n"
            "- Locked claims are constraints — treat them as established facts\n"
            "- Challenged claims are your priority — investigate and resolve them\n"
        )

        # Explicit startup instructions for continuation (BUG-004)
        sections.append(
            "\n**Continuation startup sequence** (do this FIRST, before any dispatch):\n"
            "1. Read `.swarm/brief-digest.md` (if it exists) — compressed project constraints\n"
            "2. Read `.swarm/success-criteria.json` — current SC status (do NOT overwrite)\n"
            "3. Read `.swarm/belief-map.json` — current hypotheses and confidence tiers\n"
            "4. Read `.swarm/scout-brief.md` — field context from prior Scout (do NOT re-scout)\n"
            "5. Read `.swarm/experiments.tsv` — what experiments ran and their status\n"
            "6. Read `.swarm/state-digest.md` (if it exists) — compact state from prior round\n"
            "7. Read `.swarm/archive/run-{N}/` — archived checkpoint and artifacts for reference\n"
            "Then plan your actions based on what was accomplished vs what remains.\n"
        )

        # Round summary from prior checkpoint/SC/experiments (BUG-001, BUG-005)
        round_summary = prior_context.get("round_summary", "")
        if round_summary:
            sections.append(
                f"\n## Round {cycle - 1} Summary — What Was Accomplished\n\n"
                + round_summary + "\n"
            )

        # State digest from prior round (BUG-001)
        state_digest = prior_context.get("state_digest", "")
        if state_digest:
            sections.append(
                f"\n## State Digest from Round {cycle - 1}\n\n"
                + state_digest + "\n"
            )

        ledger_summary = prior_context.get("ledger_summary", "")
        if ledger_summary:
            sections.append(
                "\n## Claim Ledger — Prior State of Knowledge\n\n"
                + ledger_summary + "\n"
            )

        pi_feedback = prior_context.get("pi_feedback", "")
        if pi_feedback:
            sections.append(
                "\n## PI Feedback\n\n"
                "The principal investigator provided this feedback after the last round. "
                "Address each concern:\n\n"
                + pi_feedback + "\n"
            )

        immutable_paths = prior_context.get("immutable_paths", [])
        if immutable_paths:
            sections.append(
                "\n## Immutable Artifacts — DO NOT MODIFY\n\n"
                "The following files support locked claims. Modifying them will block convergence:\n"
            )
            for p in immutable_paths:
                sections.append(f"- `{p}`\n")

        artifact_manifest = prior_context.get("artifact_manifest", "")
        if artifact_manifest:
            sections.append(
                "\n## Reusable Artifacts from Prior Rounds\n\n"
                + artifact_manifest + "\n"
            )

        failure_diagnosis = prior_context.get("failure_diagnosis")
        if isinstance(failure_diagnosis, dict):
            sections.append(
                "\n## Failure Diagnosis from Prior Round — READ CAREFULLY\n\n"
                "The prior round's automated diagnosis identified these issues. "
                "Your continuation plan MUST address them:\n\n"
            )
            systemic = failure_diagnosis.get("systemic_issues", [])
            if systemic:
                sections.append("**Systemic issues:**\n")
                for issue in systemic:
                    sections.append(f"- {issue}\n")
            unmet = failure_diagnosis.get("unmet_criteria", [])
            if unmet:
                sections.append("\n**Unmet criteria:**\n")
                for c in unmet:
                    if isinstance(c, dict):
                        cid = c.get("id", "?")
                        diag = c.get("diagnosis", "unknown")
                        rec = c.get("recommendation", "")
                        sections.append(f"- **{cid}** ({diag}): {rec}\n")
            proposed = failure_diagnosis.get("proposed_action", "")
            if proposed:
                sections.append(f"\n**Proposed action:** {proposed}\n")

    return "".join(sections)


# ---------------------------------------------------------------------------
# Warm-Start Brief builder
# ---------------------------------------------------------------------------


def build_warm_start_context(
    lineage_id: int,
    cycle_number: int,
    pi_feedback: str = "",
    base_dir: Path | None = None,
    workspace: Path | None = None,
) -> dict:
    """Build the prior_context dict for build_orchestrator_prompt.

    Reads the Claim Ledger, success criteria, experiments, archived
    checkpoint, and workspace artifacts to produce a structured context dict
    that the prompt builder can inject into continuation prompts.

    The round summary ensures the continuation orchestrator has meaningful
    context even when the Claim Ledger is empty (e.g. the prior round ended
    before experiments completed).
    """
    from voronoi.science.claims import load_ledger

    ledger = load_ledger(lineage_id, base_dir=base_dir)

    context: dict = {
        "cycle_number": cycle_number,
        "ledger_summary": ledger.format_for_prompt(),
        "pi_feedback": pi_feedback,
        "immutable_paths": ledger.get_immutable_paths(),
    }

    # Build artifact manifest and round summary from workspace
    if workspace and workspace.exists():
        manifest_lines: list[str] = []
        summary_lines: list[str] = []
        swarm = workspace / ".swarm"

        # -- Success criteria status from prior round ---
        sc_path = swarm / "success-criteria.json"
        if sc_path.exists():
            try:
                import json
                sc_data = json.loads(sc_path.read_text())
                if isinstance(sc_data, list) and sc_data:
                    met = sum(1 for s in sc_data if s.get("met"))
                    total = len(sc_data)
                    summary_lines.append(f"- Success criteria: {met}/{total} met")
                    unmet = [s for s in sc_data if not s.get("met")]
                    for s in unmet[:5]:
                        sid = s.get("id", "?")
                        desc = s.get("description", "")[:80]
                        summary_lines.append(f"  - {sid} UNMET: {desc}")
                    context["success_criteria_status"] = {
                        "met": met, "total": total,
                    }
            except (OSError, json.JSONDecodeError, TypeError):
                pass

        # -- Experiment details from experiments.tsv ---
        experiments = swarm / "experiments.tsv"
        if experiments.exists():
            try:
                lines = experiments.read_text().strip().splitlines()
                if len(lines) > 1:
                    keep_count = sum(1 for l in lines[1:] if "\tkeep\t" in l)
                    manifest_lines.append(
                        f"- Experiments: {len(lines) - 1} total, {keep_count} kept results"
                    )
                    # Parse experiment names/descriptions for summary
                    for row in lines[1:6]:  # first 5 experiments
                        cols = row.split("\t")
                        if len(cols) >= 2:
                            exp_name = cols[0][:60]
                            exp_status = cols[2] if len(cols) > 2 else "unknown"
                            summary_lines.append(
                                f"- Experiment `{exp_name}`: {exp_status}"
                            )
            except OSError:
                pass

        # -- Archived checkpoint for strategy context ---
        prior_round = cycle_number - 1
        archive = swarm / "archive" / f"run-{prior_round}"
        if archive.is_dir():
            ckpt_path = archive / "orchestrator-checkpoint.json"
            if ckpt_path.exists():
                try:
                    import json
                    ckpt = json.loads(ckpt_path.read_text())
                    # Extract strategy summary from checkpoint
                    next_actions = ckpt.get("next_actions", [])
                    if next_actions:
                        summary_lines.append("- Planned next actions (from prior checkpoint):")
                        for action in next_actions[:5]:
                            if isinstance(action, str):
                                summary_lines.append(f"  - {action[:100]}")
                    active = ckpt.get("active_workers", [])
                    if active:
                        summary_lines.append(
                            f"- Active workers at end of round: {len(active)}"
                        )
                except (OSError, json.JSONDecodeError, TypeError):
                    pass

        # -- State digest from prior round ---
        digest_path = swarm / "state-digest.md"
        if digest_path.exists():
            try:
                digest_text = digest_path.read_text().strip()
                if digest_text:
                    # Truncate to ~500 chars to fit in prompt
                    if len(digest_text) > 500:
                        digest_text = digest_text[:500] + "…"
                    context["state_digest"] = digest_text
            except OSError:
                pass

        # -- Check for existing data directories ---
        for data_dir in ("data", "data/raw", "data/synthetic", "output"):
            dp = workspace / data_dir
            if dp.is_dir():
                files = list(dp.iterdir())
                if files:
                    manifest_lines.append(
                        f"- `{data_dir}/`: {len(files)} files (DO NOT REGENERATE)"
                    )

        # -- Failure diagnosis from prior round ---
        diag_path = swarm / "failure-diagnosis.json"
        if diag_path.exists():
            try:
                import json
                diag = json.loads(diag_path.read_text())
                if isinstance(diag, dict):
                    context["failure_diagnosis"] = diag
            except (OSError, json.JSONDecodeError):
                pass

        if manifest_lines:
            context["artifact_manifest"] = "\n".join(manifest_lines)
        if summary_lines:
            context["round_summary"] = "\n".join(summary_lines)

    return context


# ---------------------------------------------------------------------------
# Worker prompt assembly — code-built, not LLM-built
# ---------------------------------------------------------------------------

# Role file mapping: task type → .github/agents/ filename
ROLE_MAP: dict[str, str] = {
    "build": "worker-agent.agent.md",
    "worker": "worker-agent.agent.md",
    "builder": "worker-agent.agent.md",
    "implementation": "worker-agent.agent.md",
    "scout": "scout.agent.md",
    "investigation": "investigator.agent.md",
    "investigator": "investigator.agent.md",
    "experiment": "investigator.agent.md",
    "exploration": "explorer.agent.md",
    "explorer": "explorer.agent.md",
    "comparison": "explorer.agent.md",
    "review_stats": "statistician.agent.md",
    "statistician": "statistician.agent.md",
    "review_critic": "critic.agent.md",
    "critic": "critic.agent.md",
    "review_method": "methodologist.agent.md",
    "methodologist": "methodologist.agent.md",
    "theory": "theorist.agent.md",
    "theorist": "theorist.agent.md",
    "synthesis": "synthesizer.agent.md",
    "synthesizer": "synthesizer.agent.md",
    "evaluation": "evaluator.agent.md",
    "evaluator": "evaluator.agent.md",
    "scribe": "scribe.agent.md",
    "paper": "worker-agent.agent.md",
    "compilation": "worker-agent.agent.md",
    # Paper-track roles (manuscript production pipeline)
    "outline": "outliner.agent.md",
    "lit_synthesis": "lit-synthesizer.agent.md",
    "figure_critic": "figure-critic.agent.md",
    "refine": "refiner.agent.md",
}

TASK_TYPE_ALIASES: dict[str, str] = {
    "worker": "build",
    "builder": "build",
    "investigator": "investigation",
    "explorer": "exploration",
    "critic": "review_critic",
    "statistician": "review_stats",
    "methodologist": "review_method",
    "theorist": "theory",
    "synthesizer": "synthesis",
    "evaluator": "evaluation",
}

INVESTIGATION_SKILLS = [
    ".github/skills/investigation-protocol/SKILL.md",
    ".github/skills/evidence-system/SKILL.md",
    ".github/skills/context-management/SKILL.md",
]
COMPILATION_SKILLS = [
    ".github/skills/figure-generation/SKILL.md",
    ".github/skills/compilation-protocol/SKILL.md",
]
EXPLORATION_SKILLS = [
    ".github/skills/deep-research/SKILL.md",
    ".github/skills/context-management/SKILL.md",
]

# Skills to reference by task type
SKILL_MAP: dict[str, list[str]] = {
    "investigation": INVESTIGATION_SKILLS,
    "investigator": INVESTIGATION_SKILLS,
    "experiment": INVESTIGATION_SKILLS,
    "scribe": [
        ".github/skills/compilation-protocol/SKILL.md",
        ".github/skills/figure-generation/SKILL.md",
    ],
    "paper": COMPILATION_SKILLS,
    "compilation": COMPILATION_SKILLS,
    "scout": [
        ".github/skills/deep-research/SKILL.md",
    ],
    "exploration": EXPLORATION_SKILLS,
    "explorer": EXPLORATION_SKILLS,
    "comparison": EXPLORATION_SKILLS,
    # Paper-track skills
    "outline": [
        ".github/skills/context-management/SKILL.md",
    ],
    "lit_synthesis": [
        ".github/skills/deep-research/SKILL.md",
    ],
    "figure_critic": [
        ".github/skills/figure-generation/SKILL.md",
    ],
    "refine": [
        ".github/skills/compilation-protocol/SKILL.md",
    ],
}


def _normalize_task_type(task_type: str) -> str:
    normalized = task_type.strip().lower().replace("-", "_")
    canonical = TASK_TYPE_ALIASES.get(normalized, normalized)
    if canonical not in ROLE_MAP:
        known = ", ".join(sorted(ROLE_MAP))
        raise ValueError(f"Unknown task_type '{task_type}'. Expected one of: {known}")
    return canonical


def build_red_team_prompt(
    *,
    workspace_path: str,
    codename: str = "",
    rigor: str = "scientific",
) -> str:
    """Build a COLD-CONTEXT prompt for the Red Team adversarial reviewer.

    The Red Team is invoked once at the end of a Scientific+ investigation.
    It must review the deliverable on its own merits, without having read
    the investigation history, worker logs, orchestrator checkpoint, or
    any agent chatter.  Therefore this prompt deliberately omits the
    brief digest, belief map, OODA state, and task snapshots that the
    orchestrator and worker prompts include.

    The only inputs the Red Team receives beyond this prompt are:
      - `.swarm/deliverable.md` (the final claims)
      - `.swarm/claim-ledger.json` (asserted/locked claims with provenance)
      - `output/**` (raw artifacts referenced by the deliverable)

    Output: a single JSON verdict at `.swarm/red-team-verdict.json` that
    gates convergence (see INV-47 and `science/convergence.py`).
    """
    label = codename or "Red Team"
    sections: list[str] = [
        "# Red Team Review — Cold Context\n\n",
        (
            "You are the **Red Team**, an independent adversarial reviewer. "
            "You have NOT read the investigation history, worker logs, "
            "orchestrator checkpoint, or agent discussions. This is "
            "deliberate: judge the deliverable the way a skeptical peer "
            "reviewer would judge a paper — on its own merits.\n\n"
        ),
        f"**Reviewer codename:** {label}\n",
        f"**Workspace:** {workspace_path}\n",
        f"**Rigor:** {rigor}\n\n",
        "## Read ONLY These Files\n\n"
        f"1. `{workspace_path}/.swarm/deliverable.md`\n"
        f"2. `{workspace_path}/.swarm/claim-ledger.json`\n"
        f"3. `{workspace_path}/output/**` (artifacts cited by the deliverable)\n\n"
        "Do NOT read `.swarm/brief-digest.md`, `.swarm/checkpoint*.json`, "
        "worker logs, or Beads task history. If the deliverable does not "
        "stand on its own, that is itself a finding.\n\n"
        "## Role File\n\n"
        "Read `.github/agents/red-team.agent.md` for the full checklist "
        "(EVIDENCE, PROVENANCE, ALTERNATIVES, CONFOUNDS, REPLICATION, "
        "FABRICATION, STATISTICS, SCOPE).\n\n"
        "## Output\n\n"
        f"Write exactly one JSON file: `{workspace_path}/.swarm/red-team-verdict.json`\n\n"
        "```json\n"
        "{\n"
        '  "verdict": "pass" | "pass_with_caveats" | "fatal_flaw",\n'
        '  "reviewed_claims": ["..."],\n'
        '  "findings": [\n'
        '    {"claim_id": "...", "severity": "info|minor|major|fatal",\n'
        '     "check": "EVIDENCE|PROVENANCE|ALTERNATIVES|CONFOUNDS|REPLICATION|FABRICATION|STATISTICS|SCOPE",\n'
        '     "comment": "..."}\n'
        "  ],\n"
        '  "reason": "one-line summary",\n'
        '  "reviewed_at": "<ISO-8601>"\n'
        "}\n"
        "```\n\n"
        "A `fatal_flaw` verdict BLOCKS convergence. Err on the side of "
        "calling out weaknesses: a minor finding costs the PI a few "
        "minutes; a missed fatal flaw costs the PI a paper.\n",
    ]
    return "".join(sections)


def build_tribunal_prompt(
    *,
    finding_id: str,
    trigger: str,
    hypothesis_id: str = "",
    expected: str = "",
    observed: str = "",
    causal_dag_summary: str = "",
    belief_map_summary: str = "",
    workspace_path: str = "",
) -> str:
    """Build a prompt for the Judgment Tribunal session.

    The Tribunal is a multi-agent deliberation: Theorist + Statistician +
    Methodologist (+ Critic at pre-convergence) that evaluates whether
    a surprising finding makes scientific sense.

    Parameters
    ----------
    finding_id : str
        The Beads finding ID that triggered the tribunal.
    trigger : str
        Why the tribunal was triggered: refuted_reversed, surprising,
        contradiction, pre_convergence.
    hypothesis_id : str
        Which hypothesis is affected.
    expected : str
        What the causal model predicted.
    observed : str
        What was actually observed.
    causal_dag_summary : str
        Summary of the causal DAG edges relevant to this finding.
    belief_map_summary : str
        Current state of the belief map.
    workspace_path : str
        Path to the investigation workspace.
    """
    sections: list[str] = [
        "# Judgment Tribunal\n\n",
        "You are participating in a **Judgment Tribunal** — a structured "
        "multi-agent deliberation to evaluate whether a surprising finding "
        "makes scientific sense.\n\n",
    ]

    sections.append(f"## Trigger: `{trigger}`\n\n")
    if finding_id:
        sections.append(f"- **Finding**: `{finding_id}`\n")
    if hypothesis_id:
        sections.append(f"- **Hypothesis**: `{hypothesis_id}`\n")
    if expected:
        sections.append(f"- **Expected (pre-registered)**: {expected}\n")
    if observed:
        sections.append(f"- **Observed**: {observed}\n")
    sections.append("\n")

    if causal_dag_summary:
        sections.append(f"## Causal Model Context\n\n{causal_dag_summary}\n\n")
    if belief_map_summary:
        sections.append(f"## Current Belief Map\n\n{belief_map_summary}\n\n")

    sections.append(
        "## Your Task\n\n"
        "### 1. Explanation Audit (Theorist)\n"
        "Given the causal model, can this result be explained?\n"
        "- Generate 2-3 competing explanations\n"
        "- For each: what minimal experiment would test it?\n"
        "- Classify effort: trivial (existing data) | moderate (new condition) | substantial (new experiment)\n\n"
        "### 2. Robustness Check (Statistician)\n"
        "Is this result robust to analysis choices?\n"
        "- Sensitivity analysis, alternative stat tests, subset analyses\n"
        "- Is this powered enough to trust?\n"
        "- Verify the direction classification is correct\n\n"
        "### 3. Design Artifact Check (Methodologist)\n"
        "Could this be a design artifact?\n"
        "- Confound analysis\n"
        "- Operationalization validity\n"
        "- Could the manipulation have degraded?\n\n"
        "## Output\n\n"
        "Write your verdict to `.swarm/tribunal-verdicts.json` as a JSON object:\n"
        "```json\n"
        "{\n"
        f'  "finding_id": "{finding_id}",\n'
        '  "verdict": "explained | anomaly_unresolved | artifact | trivial",\n'
        '  "explanations": [\n'
        '    {"id": "E1", "theory": "...", "test": "...", "effort": "trivial|moderate|substantial", "tested": false}\n'
        "  ],\n"
        '  "recommended_action": "test_E1_before_convergence",\n'
        '  "trivial_to_resolve": true,\n'
        '  "tribunal_agents": ["theorist", "statistician", "methodologist"]\n'
        "}\n"
        "```\n\n"
        "**Verdict meanings:**\n"
        "- `explained`: Coherent explanation found and testable from existing data\n"
        "- `anomaly_unresolved`: No satisfying explanation — needs new experiment (BLOCKS convergence)\n"
        "- `artifact`: Design flaw in the experiment — DESIGN_INVALID escalation\n"
        "- `trivial`: Result is expected/obvious — downgrade in deliverable\n"
    )

    return "".join(sections)


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
    canonical_task_type = _normalize_task_type(task_type)

    # 1. Read the role definition file
    role_file = ROLE_MAP[canonical_task_type]
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
    skills = SKILL_MAP.get(canonical_task_type, [])
    if skills:
        sections.append("\n## Skills to Read\n\nBefore starting, read these:\n")
        for s in skills:
            sections.append(f"- `{s}`\n")

    # 9. Extra instructions
    if extra_instructions:
        sections.append(f"\n## Additional Instructions\n\n{extra_instructions}\n")

    # 9a. Scribe: LaTeX format enforcement (overrides any contradictory briefing)
    if canonical_task_type == "scribe":
        sections.append(
            "\n## Output Format — MANDATORY\n\n"
            "**Write LaTeX (`paper.tex`), NOT Markdown.**\n"
            "Your role file specifies LaTeX output. This section reinforces it "
            "because the orchestrator's briefing may inadvertently say 'Markdown' — "
            "ignore any such instruction.\n\n"
            "1. The paper MUST be named `paper.tex` — this is the Voronoi convention\n"
            "2. Compile to `paper.pdf` using the compilation-protocol skill\n"
            "3. Place the paper, PDF, and figures in the output directory specified "
            "by the project brief (typically `demos/<name>/output/paper/`)\n"
            "4. After the paper is complete, write `.swarm/deliverable.md` as a SHORT "
            "summary (abstract + key findings) — this is the convergence signal, "
            "NOT the paper itself\n"
        )

    # 9b. Scout: reinforce mandatory artifact contract from the role file.
    if canonical_task_type == "scout":
        sections.append(
            "\n## Scout Output Contract — MANDATORY\n\n"
            "Before closing this task, you MUST produce both files:\n"
            "1. `.swarm/scout-brief.md`\n"
            "2. `.swarm/novelty-gate.json`\n\n"
            "Verify `novelty-gate.json` contains `status` (`clear` or `blocked`) "
            "and `assessment` (`novel`, `incremental`, or `redundant`). A missing "
            "or malformed novelty gate means the Scout task is NOT complete.\n"
        )

    # 9c. Experiment worker: anti-polling guidance
    if canonical_task_type in ("investigation", "experiment"):
        sections.append(
            "\n## Running Experiments — Block, Don't Poll\n\n"
            "When running a long experiment script:\n"
            "- Run it **synchronously** (let it block your session) — do NOT background it "
            "and poll with `sleep && check`\n"
            "- If the script takes hours, that's fine — your worktree is isolated\n"
            "- After it finishes, read the results, commit, close your task, and exit\n"
            "- NEVER run `sleep 600 && find .llm_cache | wc -l` loops — they waste "
            "your context window for zero value\n"
        )

    # 10. Findings commit reminder (parametric — role file owns verify loop)
    sections.append(
        "\n## Record Findings Before Closing\n\n"
        "Write observations to Beads as you go — do not rely on context memory:\n"
        "```bash\n"
        f"bd update {task_id} --notes 'OBSERVATION:<what you found>'\n"
        "```\n"
    )

    # 11. Git discipline (parametric branch/task — role file owns commit cadence)
    sections.append(
        "\n## Git Discipline\n\n"
        f"Your branch: `{branch}`\n"
        f"After each milestone: `git add -A && git commit -m '[msg]'`\n"
        f"If `origin` exists: `git push origin {branch}`\n"
        f"If no `origin` exists: commit locally, record `NO_REMOTE` in "
        f"`bd update {task_id} --notes 'NO_REMOTE: local-only workspace'`.\n"
        f"When done: `bd close {task_id} --reason '...'`\n"
    )

    return "\n".join(sections)


def _read_role_file(filename: str, workspace_path: str = "") -> str:
    """Read a role definition file from the agents directory.

    Strips YAML frontmatter (``---`` ... ``---``) before returning,
    since the frontmatter metadata is not useful as prompt text and
    wastes context tokens.

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
                content = p.read_text()
                return _strip_frontmatter(content)
            except OSError:
                continue
    return ""


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter (``---`` delimited) from a markdown file."""
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    # Skip past the closing --- and any blank line after it
    return text[end + 4:].lstrip("\n")
