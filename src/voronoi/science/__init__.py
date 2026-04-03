"""Science gate enforcement — the backbone of Voronoi's rigor system.

4 modules:
  - _helpers.py: Beads queries, consistency checks, finding interpretation
  - convergence.py: Belief map, checkpoint, convergence detection
  - fabrication.py: Anti-fabrication verification, simulation bypass
  - gates.py: Dispatch/merge gates, pre-registration, invariants, calibration

All public symbols re-exported here for ``from voronoi.science import X``.
"""

# --- Convergence (+ belief map + checkpoint) ---
from voronoi.science.convergence import (
    BeliefMap,
    ConvergenceResult,
    Hypothesis,
    OrchestratorCheckpoint,
    check_convergence,
    format_checkpoint_for_prompt,
    load_belief_map,
    load_checkpoint,
    save_belief_map,
    save_checkpoint,
    write_convergence,
)

# --- Helpers (consistency, paradigm stress, interpretation, claim-evidence) ---
from voronoi.science._helpers import (
    ClaimEvidence,
    ClaimEvidenceRegistry,
    ConsistencyConflict,
    ParadigmStressResult,
    assess_ci_quality,
    check_consistency,
    check_consistency_enhanced,
    check_heartbeat_stall,
    check_paradigm_stress,
    classify_effect_size,
    interpret_finding,
    load_claim_evidence,
    load_success_criteria,
    save_claim_evidence,
    save_success_criteria,
)

# --- Fabrication ---
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

# --- Gates (+ pre-registration + invariants + calibration + replication) ---
from voronoi.science.gates import (
    CalibrationResult,
    Invariant,
    InvariantCheckResult,
    PLAN_REVIEW_REVIEWERS,
    PRE_REG_FIELDS,
    PRE_REG_SCIENTIFIC_FIELDS,
    PlanReviewResult,
    PreRegComplianceResult,
    PreRegistration,
    ReplicationNeed,
    audit_pre_registration_compliance,
    check_calibration,
    check_dispatch_gates,
    check_invariants,
    check_merge_gates,
    check_plan_review_gate,
    find_replication_needs,
    format_invariants_for_prompt,
    load_invariants,
    parse_pre_registration,
    parse_revise_context,
    save_invariants,
    validate_data_invariants,
    validate_pre_registration,
    # Experiment Sentinel
    DegeneracyCheck,
    ExperimentContract,
    ManipulationCheck,
    PhaseGate,
    SentinelAuditResult,
    SentinelCheckResult,
    load_experiment_contract,
    save_experiment_contract,
    validate_experiment_contract,
    validate_phase_gate,
)

# --- Claims (cross-run scientific state) ---
from voronoi.science.claims import (
    Claim,
    ClaimArtifact,
    ClaimLedger,
    Objection,
    generate_self_critique,
    load_ledger,
    resolve_lineage_id,
    save_ledger,
)

__all__ = [
    # Convergence + belief map + checkpoint
    "Hypothesis", "BeliefMap", "load_belief_map", "save_belief_map",
    "OrchestratorCheckpoint", "load_checkpoint", "save_checkpoint", "format_checkpoint_for_prompt",
    "ConvergenceResult", "check_convergence", "write_convergence",
    # Helpers
    "ConsistencyConflict", "check_consistency", "check_consistency_enhanced",
    "ClaimEvidence", "ClaimEvidenceRegistry", "load_claim_evidence", "save_claim_evidence",
    "classify_effect_size", "assess_ci_quality", "interpret_finding",
    "ParadigmStressResult", "check_paradigm_stress",
    "check_heartbeat_stall",
    "load_success_criteria", "save_success_criteria",
    # Fabrication
    "FabricationFlag", "AntiFabricationResult", "SimulationBypassResult",
    "verify_data_hash", "compute_data_hash",
    "verify_finding_against_data", "audit_all_findings",
    "detect_simulation_bypass", "format_fabrication_report",
    # Gates + pre-reg + invariants + calibration + replication
    "PRE_REG_FIELDS", "PRE_REG_SCIENTIFIC_FIELDS",
    "PreRegistration", "PreRegComplianceResult",
    "parse_pre_registration", "validate_pre_registration", "audit_pre_registration_compliance",
    "check_dispatch_gates", "check_merge_gates",
    "PLAN_REVIEW_REVIEWERS", "PlanReviewResult", "check_plan_review_gate",
    "Invariant", "InvariantCheckResult",
    "load_invariants", "save_invariants", "format_invariants_for_prompt",
    "check_invariants", "validate_data_invariants",
    "CalibrationResult", "check_calibration", "parse_revise_context",
    "ReplicationNeed", "find_replication_needs",
    # Experiment Sentinel
    "ManipulationCheck", "DegeneracyCheck", "PhaseGate",
    "ExperimentContract", "SentinelCheckResult", "SentinelAuditResult",
    "load_experiment_contract", "save_experiment_contract",
    "validate_experiment_contract", "validate_phase_gate",
    # Claims (cross-run scientific state)
    "Claim", "ClaimArtifact", "ClaimLedger", "Objection",
    "load_ledger", "save_ledger", "resolve_lineage_id",
    "generate_self_critique",
]
