"""Science gate enforcement — the backbone of Voronoi's rigor system.

This package implements programmatic enforcement of scientific rigor gates.
It provides pre-registration validation, belief map management, convergence
detection, anti-fabrication checks, and more.

All public symbols are re-exported here so that ``from voronoi.science import X``
continues to work after the split into submodules.
"""

# --- Pre-registration ---
from voronoi.science.pre_registration import (
    PRE_REG_FIELDS,
    PRE_REG_SCIENTIFIC_FIELDS,
    PreRegComplianceResult,
    PreRegistration,
    audit_pre_registration_compliance,
    parse_pre_registration,
    validate_pre_registration,
)

# --- Belief map ---
from voronoi.science.belief_map import (
    BeliefMap,
    Hypothesis,
    load_belief_map,
    save_belief_map,
)

# --- Convergence ---
from voronoi.science.convergence import (
    ConvergenceResult,
    check_convergence,
    write_convergence,
)

# --- Evidence (consistency, claim-evidence, interpretation, paradigm stress) ---
from voronoi.science.evidence import (
    ClaimEvidence,
    ClaimEvidenceRegistry,
    ConsistencyConflict,
    ParadigmStressResult,
    assess_ci_quality,
    check_consistency,
    check_consistency_enhanced,
    check_paradigm_stress,
    classify_effect_size,
    interpret_finding,
    load_claim_evidence,
    save_claim_evidence,
)

# --- Fabrication detection ---
from voronoi.science.fabrication import (
    AntiFabricationResult,
    FabricationFlag,
    SimulationBypassResult,
    audit_all_findings,
    compute_data_hash,
    detect_simulation_bypass,
    format_fabrication_report,
    verify_data_hash,
    verify_finding_against_data,
)

# --- Gates (dispatch, merge, invariants, calibration, replication) ---
from voronoi.science.gates import (
    CalibrationResult,
    Invariant,
    InvariantCheckResult,
    ReplicationNeed,
    check_calibration,
    check_dispatch_gates,
    check_invariants,
    check_merge_gates,
    find_replication_needs,
    format_invariants_for_prompt,
    load_invariants,
    load_success_criteria,
    parse_revise_context,
    save_invariants,
    save_success_criteria,
    validate_data_invariants,
)

# --- Checkpoint ---
from voronoi.science.checkpoint import (
    OrchestratorCheckpoint,
    format_checkpoint_for_prompt,
    load_checkpoint,
    save_checkpoint,
)

# --- Heartbeat, lab notebook, judge ---
from voronoi.science.heartbeat import (
    Heartbeat,
    JudgeRubric,
    JudgeVerdict,
    LabNotebookEntry,
    append_lab_notebook,
    check_heartbeat_stall,
    format_judge_prompt,
    load_lab_notebook,
    log_judge_call,
    parse_judge_verdict,
    read_heartbeats,
    write_heartbeat,
)

__all__ = [
    # Pre-registration
    "PRE_REG_FIELDS", "PRE_REG_SCIENTIFIC_FIELDS",
    "PreRegistration", "PreRegComplianceResult",
    "parse_pre_registration", "validate_pre_registration",
    "audit_pre_registration_compliance",
    # Belief map
    "Hypothesis", "BeliefMap", "load_belief_map", "save_belief_map",
    # Convergence
    "ConvergenceResult", "check_convergence", "write_convergence",
    # Evidence
    "ConsistencyConflict", "check_consistency", "check_consistency_enhanced",
    "ClaimEvidence", "ClaimEvidenceRegistry",
    "load_claim_evidence", "save_claim_evidence",
    "classify_effect_size", "assess_ci_quality", "interpret_finding",
    "ParadigmStressResult", "check_paradigm_stress",
    "ReplicationNeed", "find_replication_needs",
    "load_success_criteria", "save_success_criteria",
    # Fabrication
    "FabricationFlag", "AntiFabricationResult", "SimulationBypassResult",
    "verify_data_hash", "compute_data_hash",
    "verify_finding_against_data", "audit_all_findings",
    "detect_simulation_bypass", "format_fabrication_report",
    # Gates
    "check_dispatch_gates", "check_merge_gates",
    "Invariant", "InvariantCheckResult",
    "load_invariants", "save_invariants",
    "format_invariants_for_prompt", "check_invariants",
    "validate_data_invariants",
    "CalibrationResult", "check_calibration", "parse_revise_context",
    # Checkpoint
    "OrchestratorCheckpoint",
    "load_checkpoint", "save_checkpoint", "format_checkpoint_for_prompt",
    # Heartbeat / notebook / judge
    "LabNotebookEntry", "load_lab_notebook", "append_lab_notebook",
    "Heartbeat", "write_heartbeat", "read_heartbeats", "check_heartbeat_stall",
    "JudgeVerdict", "JudgeRubric",
    "format_judge_prompt", "parse_judge_verdict", "log_judge_call",
]
