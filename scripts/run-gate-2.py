#!/usr/bin/env python3
"""Gate 2 — COBOL Reader Runner (Version 2.1.0)

Executes single-file COBOL analysis on BANK-MAIN.CBL using Azure AI Foundry
Responses API with native Structured Outputs.

Enforces:
1. Safe run-label validation (strict regex, no path traversal or aliases).
2. Strict environment checks (no non-empty PYTHONPATH/PYTHONHOME, no dirty baseline bypasses).
3. Working tree verification against HEAD git blobs for all critical files.
4. Source immutability and allowlist verification.
5. Dry-run executes preflights only without consuming live artifact directories.
6. Atomic run-directory reservation before any model invocation.
7. Full lifecycle state tracking via run-state.json with allowlist-based error safety.
8. Late application imports strictly following provenance preflight.
9. Deterministic evaluation using Evaluator V2.1 and Golden Dataset V2.1.

Exit codes:
    0 = PASS
    1 = FAIL (or scope violation / pre-check failure)
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Pure standard library setup before provenance checks
REPO_ROOT = Path(__file__).resolve().parent.parent

SAFE_RUN_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

CRITICAL_BENCHMARK_FILES: list[str] = [
    "scripts/run-gate-2.py",
    "agents/legacy_analyzer/agent.py",
    "agents/legacy_analyzer/prompts/system.md",
    "agents/legacy_analyzer/schemas/assessment.py",
    "src/cobol/atomic_facts.py",
    "src/cobol/fact_extractor.py",
    "src/cobol/support_index.py",
    "src/cobol/source_reader.py",
    "src/validation/evaluator_core.py",
    "src/validation/evaluator_v2.py",
    "src/validation/evidence_validator.py",
    "evals/expected/bank-main-single-v2.json",
    "legacy/core-banking-system/BANK-MAIN.CBL",
    "requirements-lock.txt",
]


def validate_run_label(run_label: str) -> None:
    """Validate that run_label contains only safe characters without path separators."""
    if not SAFE_RUN_LABEL_PATTERN.match(run_label):
        raise ValueError(
            f"Invalid run-label '{run_label}'. Must match regex ^[A-Za-z0-9][A-Za-z0-9._-]*$ "
            "and contain no path separators or traversal aliases."
        )
    if "/" in run_label or "\\" in run_label or ".." in run_label or run_label.startswith("."):
        raise ValueError(f"Run-label '{run_label}' contains disallowed path characters.")


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


def verify_environment_variables(is_baseline_run: bool) -> None:
    """Ensure environment is not overridden with unsafe module paths or bypasses."""
    if os.environ.get("PYTHONPATH"):
        raise RuntimeError("Disallowed non-empty PYTHONPATH environment variable detected.")
    if os.environ.get("PYTHONHOME"):
        raise RuntimeError("Disallowed non-empty PYTHONHOME environment variable detected.")
    if is_baseline_run and os.environ.get("GATE2_ALLOW_DIRTY_WORKTREE") == "1":
        raise RuntimeError("GATE2_ALLOW_DIRTY_WORKTREE is strictly prohibited for baseline runs.")


def verify_clean_worktree(is_baseline_run: bool = False) -> None:
    """Verify that the git working tree has no uncommitted changes or executable overlays."""
    res = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    lines = res.stdout.splitlines()
    tracked_dirty = [entry for entry in lines if not entry.startswith("??")]
    if tracked_dirty:
        if not is_baseline_run and os.environ.get("GATE2_ALLOW_DIRTY_WORKTREE") == "1":
            print(
                "WARNING: GATE2_ALLOW_DIRTY_WORKTREE set. "
                "Proceeding with dirty worktree for non-baseline run."
            )
        else:
            raise RuntimeError(
                "Git working tree is dirty! Tracked uncommitted changes detected:\n"
                + "\n".join(tracked_dirty)
            )

    if is_baseline_run:
        # Check untracked files in executable/import paths
        disallowed_prefixes = ("agents/", "src/", "scripts/", "tests/", "evals/")
        disallowed_files = ("pyproject.toml", "requirements-lock.txt", ".env")
        suspicious_untracked = []
        for line in lines:
            if line.startswith("??"):
                path_str = line[3:].strip()
                if path_str.startswith(disallowed_prefixes) or path_str in disallowed_files:
                    suspicious_untracked.append(path_str)

        if suspicious_untracked:
            raise RuntimeError(
                "Untracked executable or configuration overlays detected in working tree:\n"
                + "\n".join(suspicious_untracked)
            )


def verify_head_provenance_for_critical_files() -> dict[str, str]:
    """Verify that all benchmark-critical files match git HEAD blobs exactly."""
    verified_hashes: dict[str, str] = {}
    for rel_path in CRITICAL_BENCHMARK_FILES:
        disk_path = REPO_ROOT / rel_path
        if not disk_path.is_file():
            raise RuntimeError(f"Critical benchmark file missing from disk: {rel_path}")

        disk_bytes = disk_path.read_bytes()
        disk_sha = hashlib.sha256(disk_bytes).hexdigest()

        # Fetch blob directly from git HEAD
        res = subprocess.run(
            ["git", "show", f"HEAD:{rel_path}"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        )
        if res.returncode != 0:
            # File may be newly added in current uncommitted session during offline dev,
            # but for baseline verification, it must match HEAD.
            raise RuntimeError(
                f"Failed to retrieve HEAD blob for critical file '{rel_path}': "
                f"{res.stderr.decode(errors='replace')}"
            )

        head_sha = hashlib.sha256(res.stdout).hexdigest()
        if disk_sha.lower() != head_sha.lower():
            raise RuntimeError(
                f"Working tree file '{rel_path}' does not match git HEAD!\n"
                f"Disk SHA256: {disk_sha}\n"
                f"HEAD SHA256: {head_sha}"
            )
        verified_hashes[rel_path] = disk_sha

    return verified_hashes


def sanitize_console_message(msg: str) -> str:
    """Strip URLs, secret parameters, bearer tokens, and local paths from console messages."""
    s = re.sub(r"https?://[^\s'\"]+", "[REDACTED_URL]", msg)
    s = re.sub(r"Bearer\s+[A-Za-z0-9._~+/-]+", "Bearer [REDACTED]", s, flags=re.IGNORECASE)
    s = re.sub(r"api[-_]?key=[A-Za-z0-9._~+/-]+", "api-key=[REDACTED]", s, flags=re.IGNORECASE)
    s = re.sub(r"[A-Za-z]:\\[A-Za-z0-9_.\-\\]+", "[REDACTED_PATH]", s)
    s = re.sub(r"/(?:mnt|home|Users|tmp)/[A-Za-z0-9_.\-/]+", "[REDACTED_PATH]", s)
    return s


def atomic_write_json(file_path: Path, data: dict[str, Any]) -> None:
    """Atomically write JSON data to file using temporary file and atomic replace."""
    tmp_path = file_path.with_suffix(".tmp")
    content = json.dumps(data, indent=2) + "\n"
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, file_path)


def write_failure_run_state(
    run_state_file: Path,
    failed_phase: str,
    exc: Exception,
    git_sha: str = "",
) -> dict[str, Any]:
    """Write strictly allowlist-based failure state to run-state.json (Amendment 4).

    Guarantees no raw exception strings, SDK reprs, endpoints, headers, or keys
    are persisted to disk artifacts.
    """
    error_type = exc.__class__.__name__
    payload = {
        "status": "FAILED",
        "failed_phase": failed_phase,
        "error_type": error_type,
        "safe_message": f"Execution failed during {failed_phase}: {error_type}",
        "timestamp": datetime.now(UTC).isoformat(),
        "git_sha": git_sha,
    }
    atomic_write_json(run_state_file, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate 2 COBOL Reader runner with verifiable provenance (V2.1)."
    )
    parser.add_argument(
        "--run-label",
        required=True,
        help="Unique run identifier (e.g., 'baseline-v2', 'trial-01').",
    )
    parser.add_argument(
        "--expected-git-sha",
        help="Expected HEAD commit SHA. Required for baseline runs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run preflight checks only; skip model invocation and artifact creation.",
    )

    args = parser.parse_args()

    print("======================================================================")
    print(" GATE 2 — COBOL READER RUNNER (V2.1)")
    print("======================================================================")
    print(f"Run label: {args.run_label}")
    print()

    # 1. Safe Run-Label Validation
    try:
        validate_run_label(args.run_label)
    except Exception as e:
        print(f"ERROR: Run-label validation failed: {e}")
        return 1

    is_baseline = args.run_label.startswith("baseline-")

    # 2. Environment Variable Validation
    try:
        verify_environment_variables(is_baseline)
    except Exception as e:
        print(f"ERROR: Environment validation failed: {e}")
        return 1

    # 3. Git Provenance & Worktree Checks
    print("--- Running Git Provenance & Worktree Verification ---")
    try:
        branch = check_git_branch()
        head_sha = get_git_commit_sha()
        verify_clean_worktree(is_baseline)
    except Exception as e:
        print(f"ERROR: Git provenance check failed: {sanitize_console_message(str(e))}")
        return 1

    print(f"Branch:         {branch}")
    print(f"HEAD Commit:    {head_sha}")

    if branch != "feat/gate-2-cobol-reader":
        print(f"ERROR: Expected branch 'feat/gate-2-cobol-reader', but found '{branch}'")
        return 1

    if args.expected_git_sha:
        if head_sha.lower() != args.expected_git_sha.lower():
            print(
                f"ERROR: HEAD SHA mismatch! Expected '{args.expected_git_sha}', "
                f"but got '{head_sha}'"
            )
            return 1
    elif is_baseline:
        print("ERROR: --expected-git-sha is mandatory for baseline runs.")
        return 1

    print("[OK] Git worktree is clean and commit provenance verified")

    # 4. Working Tree vs HEAD File Verification
    verified_hashes: dict[str, str] = {}
    if is_baseline:
        print("--- Verifying Critical Benchmark Files Against Git HEAD ---")
        try:
            verified_hashes = verify_head_provenance_for_critical_files()
            print(f"[OK] {len(verified_hashes)} critical benchmark files match HEAD exactly")
        except Exception as e:
            print(f"ERROR: HEAD provenance verification failed: {sanitize_console_message(str(e))}")
            return 1

    # 5. Source Immutability Check
    target_rel_path = "legacy/core-banking-system/BANK-MAIN.CBL"
    source_disk_path = REPO_ROOT / target_rel_path
    if not source_disk_path.is_file():
        print(f"ERROR: Source file missing: {target_rel_path}")
        return 1

    source_bytes = source_disk_path.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    expected_bank_main_sha = "b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028"

    if source_sha.lower() != expected_bank_main_sha.lower():
        print(f"ERROR: Source SHA256 mismatch! Expected {expected_bank_main_sha}")
        return 1
    print("[OK] Source immutability verified")
    print()

    # Pre-check run directory existence (even for dry-run)
    artifact_dir = REPO_ROOT / "artifacts" / "gate-2" / args.run_label
    if artifact_dir.exists():
        print(f"ERROR: Run directory already exists: {artifact_dir}")
        print("Refusing to overwrite existing run artifacts. Aborting.")
        return 1

    # DRY-RUN CHECK: Exits cleanly without creating or reserving live run directory
    if args.dry_run:
        print("======================================================================")
        print(" [DRY RUN] All preflight checks passed successfully.")
        print(" Live model call skipped. Artifact directory NOT reserved.")
        print("======================================================================")
        return 0

    # LATE IMPORTS: Application code is imported strictly AFTER provenance verification
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    from agents.legacy_analyzer.agent import LegacyAnalyzerAgent
    from agents.legacy_analyzer.config import load_config
    from agents.legacy_analyzer.schemas.export import export_schema_to_file
    from src.cobol.source_reader import prepare_source
    from src.validation.evaluator_v2 import evaluate_assessment_v2, load_golden_dataset_v2

    prep = prepare_source(target_rel_path, repo_root=REPO_ROOT)

    # 6. Validate Foundry Configuration
    print("--- Validating Foundry Configuration ---")
    try:
        config = load_config()
        print(f"Configured Model: {config.foundry_model}")
        print("[OK] Azure Foundry configuration loaded (endpoint masked)")
    except Exception as e:
        print(f"ERROR: Failed to load Foundry configuration: {sanitize_console_message(str(e))}")
        return 1

    # 7. Atomic Run-Directory Reservation
    print(f"Reserving run directory: {artifact_dir}")
    try:
        artifact_dir.mkdir(parents=True, exist_ok=False)
    except Exception as e:
        print(f"ERROR: Failed to reserve run directory: {sanitize_console_message(str(e))}")
        return 1

    run_state_file = artifact_dir / "run-state.json"
    current_phase = "RESERVED"

    atomic_write_json(
        run_state_file,
        {
            "status": "RESERVED",
            "run_label": args.run_label,
            "timestamp": datetime.now(UTC).isoformat(),
            "git_commit_sha": head_sha,
            "source_sha256": prep.sha256,
        },
    )
    print("[OK] Run directory reserved and run-state.json initialized to RESERVED")
    print()

    # 8. Model Invocation & Evaluation Lifecycle with Allowlist-Based Error Persistence
    try:
        current_phase = "MODEL_INVOCATION"
        atomic_write_json(
            run_state_file,
            {
                "status": "MODEL_INVOCATION",
                "run_label": args.run_label,
                "timestamp": datetime.now(UTC).isoformat(),
                "git_commit_sha": head_sha,
            },
        )

        print("--- Executing Responses API Call ---")
        agent = LegacyAnalyzerAgent(config=config, reasoning_effort="low")
        assessment, metadata = agent.analyze_source(
            source_path=target_rel_path,
            run_label=args.run_label,
            repo_root=REPO_ROOT,
            git_commit_sha=head_sha,
        )
        print(f"[OK] Response received in {metadata.elapsed_seconds:.2f}s")

        current_phase = "PERSIST_ASSESSMENT"
        assessment_file = artifact_dir / "bank-main-assessment.json"
        metadata_file = artifact_dir / "run-metadata.json"
        schema_file = artifact_dir / "assessment-schema.json"
        eval_file = artifact_dir / "evaluation.json"

        assessment_file.write_text(assessment.model_dump_json(indent=2), encoding="utf-8")
        meta_dict = metadata.to_dict()
        if verified_hashes:
            meta_dict["verified_critical_input_hashes"] = verified_hashes
        metadata_file.write_text(json.dumps(meta_dict, indent=2), encoding="utf-8")
        export_schema_to_file(schema_file)

        current_phase = "EVALUATION"
        golden = load_golden_dataset_v2()
        report = evaluate_assessment_v2(
            assessment,
            golden_data=golden,
            source_lines=prep.raw_content.splitlines(),
            source_sha256_actual=prep.sha256,
        )

        current_phase = "PERSIST_RESULTS"
        eval_file.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

        # Terminal state: COMPLETED (even if Gate FAIL)
        current_phase = "COMPLETED"
        atomic_write_json(
            run_state_file,
            {
                "status": "COMPLETED",
                "run_label": args.run_label,
                "timestamp": datetime.now(UTC).isoformat(),
                "git_commit_sha": head_sha,
                "gate_2_pass": report.gate_2_pass,
            },
        )

        # Report Summary
        print("======================================================================")
        print(" GATE 2 EVALUATION SUMMARY (V2.1)")
        print("======================================================================")
        print(f"Unique Predictions:      {report.unique_predicted_count}")
        print(f"Supported Predictions:   {report.supported_predicted_count}")
        print(f"Unsupported Predictions: {report.unsupported_predicted_count}")
        print(f"Duplicates:              {report.duplicate_prediction_count}")
        print(f"Contradictions:          {report.contradiction_count}")
        print(f"Invalid Evidence Count:  {report.invalid_evidence_count}")
        matched_s = f"{report.matched_expected_count} / {report.expected_fact_count}"
        print(f"Matched Expected Facts:  {matched_s}")
        print(f"Recall:                  {report.recall:.2%}")
        print(f"Precision:               {report.precision:.2%}")
        print("----------------------------------------------------------------------")
        print(f"GATE 2 RESULT:           {'PASS' if report.gate_2_pass else 'FAIL'}")
        print("======================================================================")

        return 0 if report.gate_2_pass else 1

    except Exception as e:
        safe_msg = sanitize_console_message(str(e))
        print(f"ERROR: Execution failed during phase '{current_phase}': {safe_msg}")

        # Allowlist-based error persistence (Amendment 4):
        # Never write raw exception repr, response repr, endpoints, or local paths to run-state.json
        write_failure_run_state(run_state_file, current_phase, e, head_sha)
        return 1


if __name__ == "__main__":
    sys.exit(main())
