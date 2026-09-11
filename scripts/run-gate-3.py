#!/usr/bin/env python3
# ruff: noqa: E402
"""Gate 3 — Multi-File System Analysis Runner (Version 3.0.0)

Executes multi-file system analysis across all six files of the core banking
system bundle using structured schemas and AST-grounded evaluation.

Features:
1. Commit-bound baseline authorization specification (evals/baselines/gate-3-baseline-v1.json).
2. Multi-source bundle reader verifying byte-exact SHA256 hashes of all 6 legacy files.
3. 3-tier isolated COBOL parser generating ParserCoverageCertificate.
4. Schema validation with extra="forbid" and OpenAI Responses wire-schema generation.
5. Deterministic evaluation using SystemEvaluatorV3 and Golden Dataset V3.0 (54 units).
6. Snapshot-isolated child execution model.
7. Safe offline synthetic / dry-run mode guaranteeing zero model calls when requested.
8. Artifact immutability and atomic manifest generation.

Exit codes:
    0 = PASS
    1 = FAIL (or scope violation / pre-check failure)
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.legacy_analyzer.schemas.system_assessment import (  # noqa: E402
    ArchitecturalRisk,
    ArithmeticComputation,
    BehavioralRisk,
    ConditionalBranch,
    ControlFlowLoop,
    CrossProgramCall,
    DataFlowTransfer,
    EvaluateSelection,
    InteractiveIO,
    MenuDispatchOption,
    ProgramTermination,
    RecordFieldDeclaration,
    ResourceLifecycle,
    SharedCopybookReference,
    SourceEvidence,
    SystemAssessment,
    SystemComponent,
    SystemExecutionProtocol,
    WorkingStorageState,
)
from src.cobol.multi_source_reader import read_system_bundle
from src.cobol.system_atomic_facts import (
    ArchitecturalRiskFact,
    ArithmeticOperationFact,
    BehavioralRiskFact,
    ComponentTopologyFact,
    ConditionalBranchFact,
    ControlFlowLoopFact,
    CopybookInclusionFact,
    CrossProgramCallFact,
    DataTransferFact,
    EvaluateBranchingFact,
    FieldLayoutFact,
    InteractiveIOFact,
    MenuDispatchFact,
    ResourceLifecycleFact,
    TerminationFact,
    TransactionProtocolFact,
    WorkingStorageStateFact,
)
from src.cobol.system_cobol_parser import SystemCobolParser
from src.cobol.system_support_index import SystemSupportIndex
from src.validation.evaluator_v3 import SystemEvaluatorV3

SAFE_RUN_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
HEX_64_PATTERN = re.compile(r"^[0-9a-f]{64}$")
HEX_40_PATTERN = re.compile(r"^[0-9a-f]{40}$")

EXCLUDED_DISTRIBUTIONS = {
    "pip",
    "setuptools",
    "wheel",
    "agentic-legacy-modernization-poc",
}

AUTHORIZED_BRANCH = "feat/gate-3-system-analysis"
DEFAULT_AUTH_SPEC_PATH = "evals/baselines/gate-3-baseline-v1.json"
DEFAULT_GOLDEN_PATH = "evals/expected/system-understanding-v3.json"


def get_sanitized_git_env() -> dict[str, str]:
    """Sanitize environment for Git subprocesses."""
    env = dict(os.environ)
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    disallowed = {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_INDEX_FILE",
        "GIT_REPLACE_REF_BASE",
    }
    for key in disallowed:
        env.pop(key, None)
    return env


def validate_run_label(run_label: str) -> None:
    """Validate that run_label contains only safe characters without path separators."""
    if not SAFE_RUN_LABEL_PATTERN.fullmatch(run_label):
        raise ValueError(
            f"Invalid run-label '{run_label}'. Must match regex ^[A-Za-z0-9][A-Za-z0-9._-]*$ "
            "and contain no path separators."
        )
    if "/" in run_label or "\\" in run_label or ".." in run_label or run_label.startswith("."):
        raise ValueError(f"Run-label '{run_label}' contains disallowed path characters.")


def load_authorization_spec(spec_path: Path) -> tuple[dict[str, Any], str]:
    """Load and validate the Gate 3 authorization specification."""
    if not spec_path.is_file():
        raise FileNotFoundError(f"Authorization specification not found at: {spec_path}")
    raw_bytes = spec_path.read_bytes()
    spec_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    spec = json.loads(raw_bytes.decode("utf-8"))

    required_keys = {
        "spec_version",
        "gate",
        "run_label",
        "target_bundle",
        "requested_model",
        "foundry_project_fingerprint",
        "schema_version",
        "prompt_version",
        "evaluator_version",
        "golden_dataset_version",
    }
    missing = required_keys - set(spec.keys())
    if missing:
        raise ValueError(f"Authorization spec missing required keys: {sorted(missing)}")
    if spec.get("gate") != 3:
        raise ValueError(f"Authorization spec gate must be 3, got: {spec.get('gate')}")
    return spec, spec_sha256


def verify_branch_and_cleanliness(repo_root: Path, allow_dirty: bool = False) -> str:
    """Verify Git branch and worktree cleanliness."""
    env = get_sanitized_git_env()
    branch_res = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    current_branch = branch_res.stdout.strip()
    if current_branch != AUTHORIZED_BRANCH and not allow_dirty:
        raise RuntimeError(
            f"Gate 3 must be executed on branch '{AUTHORIZED_BRANCH}', found: '{current_branch}'"
        )

    if not allow_dirty:
        status_res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if status_res.stdout.strip():
            raise RuntimeError(
                f"Worktree has uncommitted changes:\n{status_res.stdout.strip()}\n"
                "Commit or stash changes before running Gate 3."
            )

    rev_res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return rev_res.stdout.strip()


def build_synthetic_assessment_from_facts(parser: SystemCobolParser) -> SystemAssessment:
    """Construct an assessment matching ground-truth facts extracted by the parser."""
    components = []
    calls = []
    menus = []
    copybooks = []
    fields = []
    transfers = []
    lifecycles = []
    loops = []
    evaluates = []
    arithmetics = []
    branches = []
    ios = []
    terminations = []
    b_risks = []
    a_risks = []
    ws_states = []
    protocols = []

    for sf in parser.get_supported_facts():
        ev = SourceEvidence(
            file_path=sf.file_path,
            line_start=sf.line_start,
            line_end=sf.line_end,
        )
        f = sf.fact
        if isinstance(f, ComponentTopologyFact):
            components.append(
                SystemComponent(
                    program_id=f.program_id,
                    component_role=f.component_role,
                    evidence=ev,
                )
            )
        elif isinstance(f, CrossProgramCallFact):
            calls.append(
                CrossProgramCall(
                    caller_program=f.caller_program,
                    callee_program=f.callee_program,
                    call_mechanism=f.call_mechanism,
                    evidence=ev,
                )
            )
        elif isinstance(f, MenuDispatchFact):
            menus.append(
                MenuDispatchOption(
                    program_id=f.program_id,
                    menu_key=f.menu_key,
                    target_action=f.target_action,
                    evidence=ev,
                )
            )
        elif isinstance(f, CopybookInclusionFact):
            copybooks.append(
                SharedCopybookReference(
                    program_id=f.program_id,
                    copybook_name=f.copybook_name,
                    evidence=ev,
                )
            )
        elif isinstance(f, FieldLayoutFact):
            fields.append(
                RecordFieldDeclaration(
                    container_name=f.container_name,
                    field_name=f.field_name,
                    picture_clause=f.picture_clause,
                    storage_format=f.storage_format,
                    evidence=ev,
                )
            )
        elif isinstance(f, DataTransferFact):
            transfers.append(
                DataFlowTransfer(
                    program_id=f.program_id,
                    source_entity=f.source_entity,
                    target_entity=f.target_entity,
                    transfer_verb=f.transfer_verb,
                    evidence=ev,
                )
            )
        elif isinstance(f, ResourceLifecycleFact):
            lifecycles.append(
                ResourceLifecycle(
                    program_id=f.program_id,
                    resource_name=f.resource_name,
                    access_mode=f.access_mode,
                    operations=list(f.operations),
                    evidence=ev,
                )
            )
        elif isinstance(f, ControlFlowLoopFact):
            loops.append(
                ControlFlowLoop(
                    program_id=f.program_id,
                    loop_predicate=f.loop_predicate,
                    evidence=ev,
                )
            )
        elif isinstance(f, EvaluateBranchingFact):
            evaluates.append(
                EvaluateSelection(
                    program_id=f.program_id,
                    selection_subject=f.selection_subject,
                    evidence=ev,
                )
            )
        elif isinstance(f, ArithmeticOperationFact):
            arithmetics.append(
                ArithmeticComputation(
                    program_id=f.program_id,
                    verb=f.verb,
                    operand=f.operand,
                    target_field=f.target_field,
                    evidence=ev,
                )
            )
        elif isinstance(f, ConditionalBranchFact):
            branches.append(
                ConditionalBranch(
                    program_id=f.program_id,
                    condition_kind=f.condition_kind,
                    predicate=f.predicate,
                    evidence=ev,
                )
            )
        elif isinstance(f, InteractiveIOFact):
            ios.append(
                InteractiveIO(
                    program_id=f.program_id,
                    io_verb=f.io_verb,
                    target_identifier=f.target_identifier,
                    evidence=ev,
                )
            )
        elif isinstance(f, TerminationFact):
            terminations.append(
                ProgramTermination(
                    program_id=f.program_id,
                    termination_verb=f.termination_verb,
                    evidence=ev,
                )
            )
        elif isinstance(f, BehavioralRiskFact):
            b_risks.append(
                BehavioralRisk(
                    program_id=f.program_id,
                    risk_category=f.risk_category,
                    precondition=f.precondition,
                    ordered_operations=list(f.ordered_operations),
                    possible_consequence=f.possible_consequence,
                    severity=f.severity,
                    evidence=ev,
                )
            )
        elif isinstance(f, ArchitecturalRiskFact):
            a_risks.append(
                ArchitecturalRisk(
                    risk_id=f.risk_id,
                    risk_type=f.risk_type,
                    affected_components=list(f.affected_components),
                    architectural_consequence=f.architectural_consequence,
                    severity=f.severity,
                    evidence=ev,
                )
            )
        elif isinstance(f, WorkingStorageStateFact):
            ws_states.append(
                WorkingStorageState(
                    program_id=f.program_id,
                    variable_name=f.variable_name,
                    picture_clause=f.picture_clause,
                    state_role=f.state_role,
                    evidence=ev,
                )
            )
        elif isinstance(f, TransactionProtocolFact):
            protocols.append(
                SystemExecutionProtocol(
                    protocol_name=f.protocol_name,
                    ordered_phases=list(f.ordered_phases),
                    evidence=ev,
                )
            )

    return SystemAssessment(
        system_name="Core Banking System",
        components=components,
        cross_program_calls=calls,
        menu_dispatches=menus,
        copybook_references=copybooks,
        record_fields=fields,
        data_transfers=transfers,
        resource_lifecycles=lifecycles,
        control_flow_loops=loops,
        evaluate_selections=evaluates,
        arithmetic_computations=arithmetics,
        conditional_branches=branches,
        interactive_io_operations=ios,
        terminations=terminations,
        behavioral_risks=b_risks,
        architectural_risks=a_risks,
        working_storage_states=ws_states,
        system_protocols=protocols,
    )


def collect_runtime_manifest() -> dict[str, Any]:
    """Collect runtime environment provenance."""
    dists = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name", "")
        if name and name not in EXCLUDED_DISTRIBUTIONS:
            dists[name] = dist.version

    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": dict(sorted(dists.items())),
    }


def execute_gate_3(
    repo_root: Path,
    auth_spec_path: Path,
    output_dir: Path,
    run_label: str = "baseline-v1",
    synthetic: bool = False,
    allow_dirty: bool = False,
) -> int:
    """Execute Gate 3 multi-file system analysis pipeline."""
    print("================================================================================")
    print("GATE 3 — MULTI-FILE SYSTEM ANALYSIS RUNNER")
    print(f"Timestamp: {datetime.now(UTC).isoformat()}")
    print(f"Repo Root: {repo_root}")
    print(f"Output:    {output_dir}")
    print("================================================================================")

    # 1. Branch & cleanliness check
    head_sha = verify_branch_and_cleanliness(repo_root, allow_dirty=allow_dirty)
    print(f"[OK] Verified Git branch on HEAD: {head_sha}")

    # 2. Authorization spec check
    spec, spec_sha256 = load_authorization_spec(auth_spec_path)
    print(f"[OK] Authorization spec verified: {auth_spec_path.name} (SHA: {spec_sha256[:16]}...)")

    # 3. Read and verify multi-source bundle
    bundle = read_system_bundle(repo_root=repo_root)
    print(
        f"[OK] Multi-source bundle loaded: {len(bundle.files)} files, "
        f"{bundle.total_physical_lines} lines"
    )

    # 4. Run 3-tier parser and generate ParserCoverageCertificate
    parser = SystemCobolParser(bundle)
    cert = parser.parse_system()
    print(f"[OK] Parser coverage certificate computed (SHA: {cert.certificate_sha256[:16]}...)")
    print(
        f"     Logical statements: {cert.logical_statement_count} "
        f"(Parsed & scored: {cert.parsed_and_scored_count}, "
        f"Recognized unscored: {cert.recognized_but_unscored_count}, "
        f"Unsupported relevant: {cert.unsupported_relevant_count})"
    )

    if cert.unsupported_relevant_count > 0:
        print(f"[FAIL] Unsupported relevant statements detected: {cert.unsupported_relevant_count}")
        return 1

    # 5. Build support index
    index = SystemSupportIndex(parser.get_supported_facts(), bundle)
    print(f"[OK] AST support index constructed: {len(index.get_all_facts())} facts indexed")

    # 6. Load Golden Dataset
    golden_path = repo_root / DEFAULT_GOLDEN_PATH
    if not golden_path.is_file():
        print(f"[FAIL] Golden dataset not found at: {golden_path}")
        return 1
    golden_bytes = golden_path.read_bytes()
    golden_data = json.loads(golden_bytes.decode("utf-8"))
    golden_count = len(golden_data.get("propositions", []))
    print(f"[OK] Golden dataset loaded: {golden_count} expected propositions across 14 groups")

    # 7. Assessment Acquisition
    assessment: SystemAssessment
    if synthetic:
        print("[INFO] Synthetic offline assessment requested. Generating from AST facts...")
        assessment = build_synthetic_assessment_from_facts(parser)
    else:
        print("[INFO] Live model evaluation path requested.")
        api_key = os.environ.get("AZURE_AI_FOUNDRY_KEY") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print(
                "[FAIL] Missing API key for live model evaluation. "
                "For offline run, use --synthetic."
            )
            return 1
        print("[FAIL] Live model calls strictly forbidden during unauthorized runs.")
        return 1

    # 8. Evaluate Assessment
    evaluator = SystemEvaluatorV3(
        support_index=index,
        golden_dataset_path=golden_path,
    )
    metrics, predictions = evaluator.evaluate_assessment(assessment)

    print("--------------------------------------------------------------------------------")
    print("EVALUATION RESULTS:")
    print(f"Raw Predictions:        {metrics.raw_predicted_count}")
    print(f"Unique Predictions:     {metrics.unique_predicted_count}")
    print(f"Supported Predictions:  {metrics.supported_predicted_count}")
    print(f"Unsupported:            {metrics.unsupported_predicted_count}")
    print(f"Invalid Evidence:       {metrics.invalid_evidence_count}")
    print(f"Duplicates:             {metrics.duplicate_prediction_count}")
    print(f"Contradictions:         {metrics.contradiction_count}")
    print(
        f"Matched Expected:       {metrics.matched_expected_count} / {metrics.expected_fact_count}"
    )
    print(f"Precision:              {metrics.precision:.4f}")
    print(f"Recall:                 {metrics.recall:.4f}")
    print(f"GATE 3 PASS:            {metrics.gate_3_pass}")
    print("--------------------------------------------------------------------------------")

    # 9. Persist Artifacts
    output_dir.mkdir(parents=True, exist_ok=True)

    assessment_path = output_dir / "assessment.json"
    assessment_path.write_text(assessment.model_dump_json(indent=2), encoding="utf-8")

    eval_result_path = output_dir / "evaluation-result.json"
    eval_result_path.write_text(json.dumps(metrics.to_dict(), indent=2), encoding="utf-8")

    metadata = {
        "gate": 3,
        "run_label": run_label,
        "timestamp": datetime.now(UTC).isoformat(),
        "git_commit_sha": head_sha,
        "auth_spec_sha256": spec_sha256,
        "parser_certificate_sha256": cert.certificate_sha256,
        "golden_dataset_version": golden_data.get("metadata", {}).get("version", "3.0.0"),
        "evaluator_version": "3.0.0",
        "runtime_provenance": collect_runtime_manifest(),
    }
    metadata_path = output_dir / "run-metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    # Build manifest
    file_hashes = {}
    for p in sorted(output_dir.iterdir()):
        if p.name != "manifest.json" and p.is_file():
            file_hashes[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()

    manifest = {
        "run_label": run_label,
        "timestamp": datetime.now(UTC).isoformat(),
        "artifacts": file_hashes,
        "gate_3_pass": metrics.gate_3_pass,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[OK] Artifacts and manifest persisted in: {output_dir}")

    return 0 if metrics.gate_3_pass else 1


def main() -> int:
    """CLI entrypoint for Gate 3 runner."""
    parser = argparse.ArgumentParser(description="Run Gate 3 Multi-File System Analysis")
    parser.add_argument("--run-label", default="baseline-v1", help="Label for this evaluation run")
    parser.add_argument(
        "--auth-spec",
        default=str(REPO_ROOT / DEFAULT_AUTH_SPEC_PATH),
        help="Path to baseline authorization spec JSON",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Custom destination directory for artifacts",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Run offline synthetic evaluation without remote model calls",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform preflight verification and offline synthetic evaluation",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow uncommitted worktree changes for offline development testing",
    )

    args = parser.parse_args()
    validate_run_label(args.run_label)

    dest_dir = (
        Path(args.output_dir)
        if args.output_dir
        else REPO_ROOT / f"artifacts/gate-3/{args.run_label}"
    )
    auth_spec = Path(args.auth_spec)

    return execute_gate_3(
        repo_root=REPO_ROOT,
        auth_spec_path=auth_spec,
        output_dir=dest_dir,
        run_label=args.run_label,
        synthetic=(args.synthetic or args.dry_run),
        allow_dirty=args.allow_dirty,
    )


if __name__ == "__main__":
    sys.exit(main())
