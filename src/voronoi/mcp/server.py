"""Voronoi MCP Server — stdio-based MCP server for Beads + .swarm/ tools.

Run as: ``python -m voronoi.mcp``

Communicates over stdin/stdout using JSON-RPC (MCP protocol).
Each copilot agent instance gets its own server process.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from voronoi.mcp.validators import ValidationError

logger = logging.getLogger("voronoi.mcp.server")

# ---------------------------------------------------------------------------
# Tool registry — maps MCP tool names to implementations
# ---------------------------------------------------------------------------

TOOLS: dict[str, dict[str, Any]] = {}


def _register_tool(name: str, func, description: str,
                   params: dict[str, dict[str, str]],
                   required: list[str] | None = None) -> None:
    TOOLS[name] = {
        "func": func,
        "description": description,
        "params": params,
        "required": required or [],
    }


def _build_registry() -> None:
    """Register all tools. Called once at startup."""
    from voronoi.mcp import tools_beads, tools_swarm

    _register_tool(
        "voronoi_create_task", tools_beads.create_task,
        "Create a new Beads task with validated artifact contracts.",
        {
            "title": {"type": "string", "description": "Task title (required)"},
            "task_type": {"type": "string", "description": "Task type: build, investigation, scout, etc."},
            "parent": {"type": "string", "description": "Parent task/epic ID"},
            "produces": {"type": "string", "description": "Comma-separated output files the task MUST create"},
            "requires": {"type": "string", "description": "Comma-separated input files that must exist"},
        },
        required=["title"],
    )
    _register_tool(
        "voronoi_close_task", tools_beads.close_task,
        "Close a task after validating PRODUCES artifacts exist.",
        {
            "task_id": {"type": "string", "description": "Beads task ID to close"},
            "reason": {"type": "string", "description": "Closing reason/summary"},
        },
        required=["task_id"],
    )
    _register_tool(
        "voronoi_query_tasks", tools_beads.query_tasks,
        "Query Beads tasks with a filter expression.",
        {
            "filter_expr": {"type": "string", "description": "Query expression (e.g. 'status!=closed AND updated>30m')"},
        },
    )
    _register_tool(
        "voronoi_record_finding", tools_beads.record_finding,
        "Record a scientific finding with validated metadata. Verifies data file hash.",
        {
            "task_id": {"type": "string", "description": "Beads task ID"},
            "effect_size": {"type": "string", "description": "Effect size: 'd=X.XX' or 'r=X.XX'"},
            "ci_95": {"type": "string", "description": "95% CI as '[lo, hi]'"},
            "n": {"type": "integer", "description": "Sample size (positive)"},
            "stat_test": {"type": "string", "description": "Statistical test used"},
            "valence": {"type": "string", "description": "positive | negative | inconclusive"},
            "data_file": {"type": "string", "description": "Path to raw data file"},
            "data_hash": {"type": "string", "description": "SHA-256 hash (computed if omitted)"},
            "p_value": {"type": "string", "description": "P-value (optional)"},
            "confidence": {"type": "number", "description": "Subjective confidence 0.0-1.0 (optional)"},
            "robust": {"type": "string", "description": "'yes' or 'no' (optional)"},
            "interpretation": {"type": "string", "description": "Practical interpretation (optional)"},
        },
        required=["task_id", "effect_size", "ci_95", "n", "stat_test", "valence", "data_file"],
    )
    _register_tool(
        "voronoi_stat_review", tools_beads.stat_review,
        "Record statistician review of a finding.",
        {
            "finding_id": {"type": "string", "description": "Beads task ID of the finding"},
            "verdict": {"type": "string", "description": "APPROVED or REJECTED"},
            "interpretation": {"type": "string", "description": "Practical meaning"},
            "practical_significance": {"type": "string", "description": "negligible|small|medium|large|very_large"},
        },
        required=["finding_id", "verdict"],
    )
    _register_tool(
        "voronoi_pre_register", tools_beads.pre_register,
        "Pre-register an experiment design before execution (INV-10).",
        {
            "task_id": {"type": "string", "description": "Beads task ID"},
            "hypothesis": {"type": "string", "description": "Expected outcome/prediction"},
            "method": {"type": "string", "description": "Experimental method/design"},
            "controls": {"type": "string", "description": "Control conditions"},
            "expected_result": {"type": "string", "description": "Concrete expected outcome/prediction"},
            "sample_size": {"type": "integer", "description": "Planned sample size"},
            "stat_test": {"type": "string", "description": "Planned statistical test"},
            "effect_size": {"type": "string", "description": "Planned effect size for power analysis"},
            "alpha": {"type": "number", "description": "Significance level (default 0.05)"},
            "power": {"type": "number", "description": "Power target (default 0.80)"},
            "confounds": {"type": "string", "description": "Known confounds or threats to validity"},
            "sensitivity_plan": {"type": "string", "description": "Sensitivity analysis plan"},
        },
        required=[
            "task_id", "hypothesis", "method", "controls",
            "expected_result", "sample_size", "stat_test", "effect_size",
        ],
    )
    _register_tool(
        "voronoi_write_checkpoint", tools_swarm.write_checkpoint,
        "Write orchestrator checkpoint with schema validation.",
        {
            "cycle": {"type": "integer", "description": "OODA cycle number"},
            "phase": {"type": "string", "description": "Phase: starting|scouting|planning|investigating|reviewing|synthesizing|converging|complete"},
            "total_tasks": {"type": "integer", "description": "Total task count"},
            "closed_tasks": {"type": "integer", "description": "Closed task count"},
            "hypotheses_summary": {"type": "string", "description": "Compact hypothesis status"},
            "active_workers": {"type": "array", "description": "Branch names of running agents"},
            "recent_events": {"type": "array", "description": "Rolling window of events"},
            "recent_decisions": {"type": "array", "description": "Rolling window of decisions"},
            "dead_ends": {"type": "array", "description": "Approaches to not re-explore"},
            "next_actions": {"type": "array", "description": "Orchestrator TODO list"},
            "eval_score": {"type": "number", "description": "Evaluator quality score"},
            "context_window_remaining_pct": {"type": "number", "description": "Remaining context 0.0-1.0"},
        },
        required=["cycle", "phase"],
    )
    _register_tool(
        "voronoi_update_belief_map", tools_swarm.update_belief_map,
        "Update a hypothesis in the belief map with validated references.",
        {
            "hypothesis_id": {"type": "string", "description": "Hypothesis ID (e.g. 'H1')"},
            "name": {"type": "string", "description": "Hypothesis description"},
            "posterior": {"type": "number", "description": "Updated probability 0.0-1.0"},
            "evidence_ids": {"type": "array", "description": "Supporting/refuting finding IDs"},
            "status": {"type": "string", "description": "Hypothesis status (testing, confirmed, refuted)"},
        },
        required=["hypothesis_id"],
    )
    _register_tool(
        "voronoi_update_success_criteria", tools_swarm.update_success_criteria,
        "Update a success criterion status.",
        {
            "criteria_id": {"type": "string", "description": "Criterion ID (e.g. 'SC1')"},
            "met": {"type": "boolean", "description": "Whether the criterion is met"},
            "evidence": {"type": "string", "description": "Evidence or finding reference"},
            "description": {"type": "string", "description": "Criterion description (for initial creation)"},
        },
        required=["criteria_id"],
    )
    _register_tool(
        "voronoi_log_experiment", tools_swarm.log_experiment,
        "Append an experiment result to the ledger with validated status.",
        {
            "task_id": {"type": "string", "description": "Beads task ID"},
            "branch": {"type": "string", "description": "Git branch name"},
            "metric": {"type": "string", "description": "Metric name (e.g. 'MBRS')"},
            "value": {"type": "string", "description": "Metric value"},
            "experiment_status": {"type": "string", "description": "keep|discard|crash|running"},
            "description": {"type": "string", "description": "Brief experiment description"},
        },
        required=["task_id", "branch", "metric", "value", "experiment_status"],
    )


# ---------------------------------------------------------------------------
# MCP protocol handlers (JSON-RPC over stdio)
# ---------------------------------------------------------------------------

def _handle_initialize(params: dict) -> dict:
    """Handle MCP initialize request."""
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {
            "name": "voronoi-mcp",
            "version": "0.4.0",
        },
    }


def _handle_tools_list(params: dict) -> dict:
    """Handle tools/list request — return all registered tools."""
    tools_list = []
    for name, info in TOOLS.items():
        properties = {}
        for pname, pinfo in info["params"].items():
            properties[pname] = {
                "type": pinfo.get("type", "string"),
                "description": pinfo.get("description", ""),
            }
        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if info.get("required"):
            schema["required"] = info["required"]
        tools_list.append({
            "name": name,
            "description": info["description"],
            "inputSchema": schema,
        })
    return {"tools": tools_list}


def _handle_tools_call(params: dict) -> dict:
    """Handle tools/call request — dispatch to the appropriate tool."""
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    if tool_name not in TOOLS:
        return {
            "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
            "isError": True,
        }

    tool = TOOLS[tool_name]
    try:
        result = tool["func"](**arguments)
        return {
            "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
        }
    except ValidationError as e:
        return {
            "content": [{"type": "text", "text": f"Validation error: {e}"}],
            "isError": True,
        }
    except Exception as e:
        logger.exception("Tool %s failed", tool_name)
        return {
            "content": [{"type": "text", "text": f"Error: {e}"}],
            "isError": True,
        }


# Method dispatch table
_HANDLERS = {
    "initialize": _handle_initialize,
    "tools/list": _handle_tools_list,
    "tools/call": _handle_tools_call,
}


def _process_message(message: dict) -> dict | None:
    """Process a single JSON-RPC message and return a response."""
    method = message.get("method", "")
    msg_id = message.get("id")
    params = message.get("params", {})

    # Notifications (no id) — just acknowledge
    if msg_id is None:
        if method == "notifications/initialized":
            return None  # No response needed
        return None

    handler = _HANDLERS.get(method)
    if handler is None:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    try:
        result = handler(params)
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}
    except Exception as e:
        logger.exception("Handler for %s failed", method)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32000, "message": str(e)},
        }


def run_server() -> None:
    """Run the MCP server, reading JSON-RPC from stdin, writing to stdout."""
    _build_registry()

    # Set up logging to stderr (stdout is the MCP channel)
    logging.basicConfig(
        level=logging.WARNING,
        stream=sys.stderr,
        format="%(name)s: %(message)s",
    )

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = _process_message(message)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
