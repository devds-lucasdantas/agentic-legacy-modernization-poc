#!/usr/bin/env python3
"""Gate 2 — COBOL Reader Runner (Version 2.0.0)

Executes single-file COBOL analysis on BANK-MAIN.CBL using Azure AI Foundry
Responses API with native Structured Outputs.

Enforces:
1. Strict preflight verification (branch, clean worktree, mandatory
   expected-git-sha for baseline runs).
2. Source immutability and allowlist verification.
3. Atomic run-directory reservation before any model invocation (exclusive creation).
4. State tracking via run-state.json (STARTED -> COMPLETED / FAILED).
5. Safe secret and endpoint logging hygiene.
6. Deterministic evaluation using Evaluator V2 and Golden Dataset V2.

Exit codes:
    0 = PASS
    1 = FAIL (or scope violation / pre-check failure)
"""

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from agents.legacy_analyzer.agent import LegacyAnalyzerAgent  # noqa: E402
from agents.legacy_analyzer.config import load_config  # noqa: E402
from agents.legacy_analyzer.schemas.export import export_schema_to_file  # noqa: E402
from src.cobol.oracle import SourceSupportOracle  # noqa: E402
from src.cobol.source_reader import EXPECTED_BANK_MAIN_SHA256, prepare_source  # noqa: E402
from src.validation.evaluator_v2 import evaluate_assessment_v2, load_golden_dataset_v2  # noqa: E402


def check_git_branch() -> str:
    """Verify current git branch is feat/gate-2-cobol-reader."""
    res = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def get_git_commit_sha() -> str:
    """Get HEAD commit SHA for baseline execution provenance."""
    res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def verify_clean_worktree() -> None:
    """Verify that the git working tree has no uncommitted or staged changes."""
    import os

    if os.environ.get("GATE2_ALLOW_DIRTY_WORKTREE") == "1":
        return
    res = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    dirty_lines = [line for line in res.stdout.splitlines() if not line.startswith("??")]
    if dirty_lines:
        raise RuntimeError(
            "Git working tree is dirty! Tracked uncommitted changes detected:\n"
            + "\n".join(dirty_lines)
        )


def verify_legacy_source_diff() -> None:
    """Verify that legacy source directory has no git modifications."""
    res = subprocess.run(
        ["git", "diff", "--", "legacy/core-banking-system/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    if res.stdout.strip():
        raise RuntimeError("Modifications detected in legacy/core-banking-system/!")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gate 2 COBOL Reader Runner V2")
    parser.add_argument(
        "--run-label",
        default="baseline-v2",
        help="Label for this experiment run (default: 'baseline-v2')",
    )
    parser.add_argument(
        "--expected-git-sha",
        default=None,
        help="Expected HEAD Git SHA. Mandatory for baseline-* runs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute preflight checks and directory reservation without calling model.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print("======================================================================")
    print(" GATE 2 — COBOL READER RUNNER (V2)")
    print("======================================================================")
    print(f"Run label: {args.run_label}")
    print()

    # 1. Deterministic Preflight: Git Provenance
    print("--- Running Git Provenance & Worktree Verification ---")
    try:
        branch = check_git_branch()
        head_sha = get_git_commit_sha()
        verify_clean_worktree()
        verify_legacy_source_diff()
    except Exception as e:
        print(f"ERROR: Git provenance check failed: {e}")
        return 1

    print(f"Branch:         {branch}")
    print(f"HEAD Commit:    {head_sha}")

    if branch != "feat/gate-2-cobol-reader":
        print(f"ERROR: Expected branch 'feat/gate-2-cobol-reader', but found '{branch}'")
        return 1

    if args.run_label.startswith("baseline-"):
        if not args.expected_git_sha:
            print("ERROR: --expected-git-sha is mandatory for baseline runs.")
            return 1
        if head_sha.lower() != args.expected_git_sha.lower():
            print(
                f"ERROR: HEAD SHA mismatch! Expected '{args.expected_git_sha}', "
                f"but got '{head_sha}'"
            )
            return 1

    print("[OK] Git worktree is clean and commit provenance verified")
    print()

    # 2. Source Scope & Immutability Check
    target_rel_path = "legacy/core-banking-system/BANK-MAIN.CBL"
    prep = prepare_source(target_rel_path, repo_root=REPO_ROOT)
    print(f"Target file:    {prep.relative_path}")
    print(f"Source SHA256:  {prep.sha256}")
    print(f"Source lines:   {prep.line_count}")

    if prep.sha256.lower() != EXPECTED_BANK_MAIN_SHA256.lower():
        print(f"ERROR: Source SHA256 mismatch! Expected {EXPECTED_BANK_MAIN_SHA256}")
        return 1
    print("[OK] Source immutability and allowlist verified")
    print()

    # 3. Deterministic Source Support Oracle
    print("--- Initializing Deterministic Source Support Oracle ---")
    oracle = SourceSupportOracle(prep.raw_content.splitlines())
    print(f"Supported facts extracted by oracle: {len(oracle.supported_facts)}")
    print()

    # 4. Configuration Validation (Safe logging: no live endpoints or secrets)
    print("--- Validating Foundry Configuration ---")
    try:
        config = load_config()
        print(f"Configured Model: {config.foundry_model}")
        print("[OK] Azure Foundry configuration loaded (endpoint masked)")
    except Exception as e:
        print(f"ERROR: Failed to load Foundry configuration: {e}")
        return 1

    # 5. Atomic Run-Directory Reservation (Exclusive creation BEFORE model call)
    artifact_dir = REPO_ROOT / "artifacts" / "gate-2" / args.run_label
    print(f"Reserving run directory: {artifact_dir}")
    if artifact_dir.exists():
        print(f"ERROR: Run directory already exists: {artifact_dir}")
        print("Refusing to overwrite existing run artifacts. Aborting.")
        return 1

    try:
        artifact_dir.mkdir(parents=True, exist_ok=False)
    except Exception as e:
        print(f"ERROR: Failed to reserve run directory: {e}")
        return 1

    run_state_file = artifact_dir / "run-state.json"
    run_state_file.write_text(
        json.dumps(
            {
                "status": "STARTED",
                "run_label": args.run_label,
                "timestamp": datetime.now(UTC).isoformat(),
                "git_commit_sha": head_sha,
                "source_sha256": prep.sha256,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("[OK] Run directory reserved and run-state.json initialized to STARTED")
    print()

    if args.dry_run:
        print("[DRY RUN] Preflights passed, directory reserved, skipping live model call.")
        run_state_file.write_text(
            json.dumps(
                {
                    "status": "DRY_RUN_COMPLETED",
                    "run_label": args.run_label,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "git_commit_sha": head_sha,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return 0

    # 6. Model Invocation
    print("--- Executing Responses API Call ---")
    agent = LegacyAnalyzerAgent(config=config, reasoning_effort="low")
    try:
        assessment, metadata = agent.analyze_source(
            source_path=target_rel_path,
            run_label=args.run_label,
            repo_root=REPO_ROOT,
            git_commit_sha=head_sha,
        )
        print(f"[OK] Response received in {metadata.elapsed_seconds:.2f}s")
    except Exception as e:
        print(f"ERROR: Model execution failed: {e}")
        run_state_file.write_text(
            json.dumps(
                {
                    "status": "FAILED",
                    "run_label": args.run_label,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "git_commit_sha": head_sha,
                    "error": str(e),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return 1

    # 7. Save Artifacts & Deterministic Evaluation
    assessment_file = artifact_dir / "bank-main-assessment.json"
    metadata_file = artifact_dir / "run-metadata.json"
    schema_file = artifact_dir / "assessment-schema.json"
    eval_file = artifact_dir / "evaluation.json"

    assessment_file.write_text(assessment.model_dump_json(indent=2), encoding="utf-8")
    metadata_file.write_text(json.dumps(metadata.to_dict(), indent=2), encoding="utf-8")
    export_schema_to_file(schema_file)

    golden = load_golden_dataset_v2()
    report = evaluate_assessment_v2(
        assessment,
        golden_data=golden,
        source_lines=prep.raw_content.splitlines(),
        source_sha256_actual=prep.sha256,
    )
    eval_file.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

    run_state_file.write_text(
        json.dumps(
            {
                "status": "COMPLETED",
                "run_label": args.run_label,
                "timestamp": datetime.now(UTC).isoformat(),
                "git_commit_sha": head_sha,
                "gate_2_pass": report.gate_2_pass,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # 8. Report Summary
    print("======================================================================")
    print(" GATE 2 EVALUATION SUMMARY (V2)")
    print("======================================================================")
    print(f"Unique Predictions:      {report.unique_predicted_count}")
    print(f"Supported Predictions:   {report.supported_predicted_count}")
    print(f"Unsupported Predictions: {report.unsupported_predicted_count}")
    print(f"Duplicates:              {report.duplicate_prediction_count}")
    print(f"Contradictions:          {report.contradiction_count}")
    print(f"Invalid Evidence Count:  {report.invalid_evidence_count}")
    print(
        f"Matched Expected Facts:  {report.matched_expected_count} / {report.expected_fact_count}"
    )
    print(f"Recall:                  {report.recall:.2%}")
    print(f"Precision:               {report.precision:.2%}")
    print("----------------------------------------------------------------------")
    print(f"GATE 2 RESULT:           {'PASS' if report.gate_2_pass else 'FAIL'}")
    print("======================================================================")

    return 0 if report.gate_2_pass else 1


if __name__ == "__main__":
    sys.exit(main())
