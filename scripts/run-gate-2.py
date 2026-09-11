#!/usr/bin/env python3
"""Gate 2 — COBOL Reader Runner (Version 2.2.0)

Executes single-file COBOL analysis on BANK-MAIN.CBL using Azure AI Foundry
Responses API with native Structured Outputs.

Enforces:
1. Safe run-label validation (re.fullmatch, no path traversal or aliases).
2. Strict environment checks (no non-empty PYTHONPATH/PYTHONHOME, no dirty baseline bypasses).
3. Mandatory isolated Python execution (sys.flags.isolated == 1) for baseline runs.
4. Exact canonical runtime/lock attestation (normalized-pkg-name==version).
5. Full git tracked tree byte comparison against HEAD (defeating assume-unchanged).
6. Detection and rejection of untracked/ignored executable overlays.
7. Post-import origin verification ensuring third-party packages originate from sys.prefix.
8. Frozen expected model/deployment identity checked before artifact reservation.
9. Source immutability and allowlist verification.
10. Dry-run executes preflights only without consuming live artifact directories.
11. Atomic run-directory reservation before any model invocation.
12. Full lifecycle state tracking via run-state.json with allowlist-based error safety.
13. Deterministic evaluation using Evaluator V2.2 and Golden Dataset V2.2.

Exit codes:
    0 = PASS
    1 = FAIL (or scope violation / pre-check failure)
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

SAFE_RUN_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

EXCLUDED_DISTRIBUTIONS = {
    "pip",
    "setuptools",
    "wheel",
    "agentic-legacy-modernization-poc",
}


def validate_run_label(run_label: str) -> None:
    """Validate that run_label contains only safe characters without path separators."""
    if not SAFE_RUN_LABEL_PATTERN.fullmatch(run_label):
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


def is_isolated_python() -> bool:
    """Return True if Python interpreter was invoked in isolated mode (-I)."""
    return sys.flags.isolated == 1


def verify_environment_variables(is_baseline_run: bool) -> None:
    """Ensure environment is not overridden with unsafe module paths or bypasses."""
    if os.environ.get("PYTHONPATH"):
        raise RuntimeError("Disallowed non-empty PYTHONPATH environment variable detected.")
    if os.environ.get("PYTHONHOME"):
        raise RuntimeError("Disallowed non-empty PYTHONHOME environment variable detected.")
    if is_baseline_run and os.environ.get("GATE2_ALLOW_DIRTY_WORKTREE") == "1":
        raise RuntimeError("GATE2_ALLOW_DIRTY_WORKTREE is strictly prohibited for baseline runs.")


def canonical_distribution_name(name: str) -> str:
    """Canonicalize Python package distribution name per PEP 503."""
    return re.sub(r"[-_.]+", "-", name).lower()


def get_canonical_runtime_manifest() -> dict[str, str]:
    """Generate canonical runtime package manifest from importlib.metadata."""
    manifest: dict[str, str] = {}
    for dist in importlib.metadata.distributions():
        raw_name = dist.metadata.get("Name")
        if not raw_name:
            continue
        cname = canonical_distribution_name(raw_name)
        if cname in EXCLUDED_DISTRIBUTIONS:
            continue
        manifest[cname] = dist.version
    return dict(sorted(manifest.items()))


def load_canonical_lockfile(lock_path: Path) -> dict[str, str]:
    """Load canonical package requirements from lockfile."""
    if not lock_path.is_file():
        raise FileNotFoundError(f"Lockfile not found at: {lock_path}")
    locked: dict[str, str] = {}
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("==")
        if len(parts) == 2:
            locked[canonical_distribution_name(parts[0])] = parts[1].strip()
    return dict(sorted(locked.items()))


def verify_runtime_environment(lock_path: Path) -> tuple[dict[str, str], str]:
    """Verify active runtime packages against exact canonical lockfile.

    Returns:
        Tuple of (canonical_runtime_manifest, manifest_sha256).
    """
    runtime = get_canonical_runtime_manifest()
    locked = load_canonical_lockfile(lock_path)

    missing = set(locked.keys()) - set(runtime.keys())
    unexpected = set(runtime.keys()) - set(locked.keys())
    mismatched = {
        k: (runtime[k], locked[k])
        for k in set(runtime.keys()) & set(locked.keys())
        if runtime[k] != locked[k]
    }

    errors: list[str] = []
    if missing:
        errors.append(f"Missing expected locked packages: {sorted(missing)}")
    if unexpected:
        errors.append(f"Unexpected disallowed packages in runtime: {sorted(unexpected)}")
    if mismatched:
        formatted = [
            f"{k} (installed={v[0]}, locked={v[1]})" for k, v in sorted(mismatched.items())
        ]
        errors.append(f"Version mismatches: {formatted}")

    if errors:
        raise RuntimeError("Runtime environment verification failed:\n" + "\n".join(errors))

    canonical_strings = [f"{k}=={v}" for k, v in runtime.items()]
    manifest_bytes = json.dumps(canonical_strings, sort_keys=True).encode("utf-8")
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    return runtime, manifest_sha


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


def verify_full_tracked_tree_against_head() -> dict[str, str]:
    """Verify that all tracked files on disk match git HEAD blobs byte-for-byte.

    Prevents git assume-unchanged and skip-worktree bypasses.
    """
    res = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    tracked_files = [f.decode("utf-8", errors="replace") for f in res.stdout.split(b"\x00") if f]
    verified: dict[str, str] = {}
    for rel_path in sorted(tracked_files):
        disk_path = REPO_ROOT / rel_path
        if not disk_path.is_file():
            raise RuntimeError(f"Tracked file missing from disk: {rel_path}")
        disk_bytes = disk_path.read_bytes()
        disk_sha = hashlib.sha256(disk_bytes).hexdigest()

        blob_res = subprocess.run(
            ["git", "show", f"HEAD:{rel_path}"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        )
        if blob_res.returncode != 0:
            raise RuntimeError(
                f"Failed to retrieve HEAD blob for tracked file '{rel_path}': "
                f"{blob_res.stderr.decode(errors='replace')}"
            )
        head_sha = hashlib.sha256(blob_res.stdout).hexdigest()
        if disk_sha.lower() != head_sha.lower():
            raise RuntimeError(
                f"Tracked file '{rel_path}' does not match git HEAD blob!\n"
                f"Disk SHA256: {disk_sha}\n"
                f"HEAD SHA256: {head_sha}"
            )
        verified[rel_path] = disk_sha
    return verified


def verify_no_executable_overlays(is_baseline_run: bool = False) -> None:
    """Detect untracked or ignored executable overlays that could hijack execution."""
    if not is_baseline_run:
        return

    res = subprocess.run(
        ["git", "status", "--porcelain", "--ignored"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked_res = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked_set = set(tracked_res.stdout.splitlines())

    disallowed_exact = {"sitecustomize.py", "usercustomize.py", "openai.py", "pydantic.py"}
    disallowed_patterns = re.compile(r"^.*\.(pyc|pyo|pyd)$", re.IGNORECASE)

    violations = []
    for line in res.stdout.splitlines():
        if len(line) < 4:
            continue
        status_code = line[:2]
        path_str = line[3:].strip()
        p = Path(path_str)
        parts = p.parts
        if parts and parts[0] in (".venv", ".git", "artifacts"):
            continue
        if parts and parts[0] in (".pytest_cache", ".ruff_cache", ".mypy_cache"):
            continue

        if p.name in disallowed_exact:
            violations.append(f"Disallowed overlay file: {path_str}")

        if (status_code == "??" or status_code.startswith("!")) and path_str.endswith(".py"):
            if path_str not in tracked_set:
                violations.append(f"Untracked python script overlay: {path_str}")

        if disallowed_patterns.match(p.name):
            if "sitecustomize" in p.name or "usercustomize" in p.name or "openai" in p.name:
                violations.append(f"Hijacking bytecode overlay: {path_str}")
            if p.parent.name != "__pycache__":
                violations.append(f"Loose bytecode overlay outside __pycache__: {path_str}")

    if violations:
        raise RuntimeError(
            "Executable or configuration overlays detected in workspace:\n" + "\n".join(violations)
        )


def verify_import_origins() -> None:
    """Verify that critical third-party libraries originate from active virtualenv."""
    import azure.ai.projects
    import azure.identity
    import openai
    import pydantic

    venv_path = Path(sys.prefix).resolve()
    modules_to_check = [
        ("openai", openai),
        ("pydantic", pydantic),
        ("azure.ai.projects", azure.ai.projects),
        ("azure.identity", azure.identity),
    ]
    for name, mod in modules_to_check:
        mod_file = getattr(mod, "__file__", None)
        if not mod_file:
            raise RuntimeError(f"Module {name} has no __file__ origin.")
        mod_path = Path(mod_file).resolve()
        try:
            mod_path.relative_to(venv_path)
        except ValueError:
            raise RuntimeError(
                f"Module {name} was imported from outside active virtualenv!\n"
                f"Origin: {mod_path}\n"
                f"Expected under: {venv_path}"
            )
        rel_to_repo = None
        try:
            rel_to_repo = mod_path.relative_to(REPO_ROOT.resolve())
        except ValueError:
            pass
        if rel_to_repo is not None:
            parts = rel_to_repo.parts
            if not parts or parts[0] != ".venv":
                raise RuntimeError(
                    f"Module {name} was imported from repository overlay: {mod_path}"
                )


def sanitize_console_message(msg: str) -> str:
    """Strip URLs, secret parameters, bearer tokens, and local paths from console messages."""
    s = re.sub(r"https?://[^\s'\"]+", "[REDACTED_URL]", msg)
    s = re.sub(r"Bearer\s+[A-Za-z0-9._~+/-]+", "Bearer [REDACTED]", s, flags=re.IGNORECASE)
    s = re.sub(r"api[-_]?key=[A-Za-z0-9._~+/-]+", "api-key=[REDACTED]", s, flags=re.IGNORECASE)
    s = re.sub(r"[A-Za-z]:\\[A-Za-z0-9_.\-\\]+", "[REDACTED_PATH]", s)
    s = re.sub(r"/(?:mnt|home|Users|tmp)/[A-Za-z0-9_.\-/]+", "[REDACTED_PATH]", s)
    return s


def atomic_write_json(file_path: Path, data: dict[str, Any]) -> None:
    """Atomically write JSON data to file using unique NamedTemporaryFile and atomic replace."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=file_path.parent,
        prefix=f"{file_path.stem}-",
        suffix=".tmp",
        mode="w",
        encoding="utf-8",
        delete=False,
    ) as tf:
        json.dump(data, tf, indent=2)
        tf.write("\n")
        tmp_name = tf.name
    os.replace(tmp_name, file_path)


def write_failure_run_state(
    run_state_file: Path,
    failed_phase: str,
    exc: Exception,
    git_sha: str = "",
) -> dict[str, Any]:
    """Write strictly allowlist-based failure state to run-state.json.

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
        description="Gate 2 COBOL Reader runner with verifiable provenance (V2.2)."
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
        "--expected-model",
        help="Expected Azure AI Foundry model/deployment identifier (mandatory for baseline runs).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run preflight checks only; skip model invocation and artifact creation.",
    )

    args = parser.parse_args()

    print("======================================================================")
    print(" GATE 2 — COBOL READER RUNNER (V2.2)")
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

    # 2. Isolated Python Flag Check (Mandatory for Baseline Runs)
    if is_baseline:
        if not is_isolated_python():
            print(
                "ERROR: Baseline runs require Python executed in isolated mode.\n"
                "Execute with: .venv/bin/python -I scripts/run-gate-2.py ..."
            )
            return 1
        if not args.expected_model:
            print("ERROR: --expected-model is mandatory for baseline runs.")
            return 1

    # 3. Environment Variable Validation
    try:
        verify_environment_variables(is_baseline)
    except Exception as e:
        print(f"ERROR: Environment validation failed: {e}")
        return 1

    # 4. Canonical Runtime/Lock Attestation
    print("--- Verifying Canonical Runtime Environment ---")
    lock_file = REPO_ROOT / "requirements-lock.txt"
    try:
        runtime_manifest, runtime_manifest_sha = verify_runtime_environment(lock_file)
        print(
            f"[OK] Runtime packages match requirements-lock.txt exactly "
            f"({len(runtime_manifest)} packages, SHA256: {runtime_manifest_sha[:12]}...)"
        )
    except Exception as e:
        print(f"ERROR: Runtime environment verification failed: {sanitize_console_message(str(e))}")
        return 1

    # 5. Git Provenance & Worktree Checks
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

    # 6. Full Tracked Tree & Overlay Verification
    verified_hashes: dict[str, str] = {}
    if is_baseline:
        print("--- Verifying All Tracked Files Against Git HEAD ---")
        try:
            verified_hashes = verify_full_tracked_tree_against_head()
            print(f"[OK] {len(verified_hashes)} tracked files match git HEAD exactly")
        except Exception as e:
            print(f"ERROR: Tracked tree verification failed: {sanitize_console_message(str(e))}")
            return 1

        print("--- Scanning for Disallowed Overlays ---")
        try:
            verify_no_executable_overlays(is_baseline_run=True)
            print("[OK] No untracked or ignored executable overlays detected")
        except Exception as e:
            print(f"ERROR: Overlay scan failed: {sanitize_console_message(str(e))}")
            return 1

    # 7. Source Immutability Check
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

    # LATE IMPORTS: Explicitly add verified repository root only AFTER provenance preflight
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    # 8. Post-Import Origin Verification
    try:
        verify_import_origins()
        print("[OK] Import origins verified (critical libraries from active venv)")
    except Exception as e:
        print(f"ERROR: Import origin verification failed: {sanitize_console_message(str(e))}")
        return 1

    from agents.legacy_analyzer.agent import LegacyAnalyzerAgent
    from agents.legacy_analyzer.config import load_config
    from agents.legacy_analyzer.schemas.export import (
        export_schema_to_file,
        export_wire_schema_to_file,
    )
    from src.cobol.source_reader import prepare_source
    from src.validation.evaluator_v2 import evaluate_assessment_v2, load_golden_dataset_v2

    prep = prepare_source(target_rel_path, repo_root=REPO_ROOT)

    # 9. Validate Foundry Configuration & Freeze Model Identity
    print("--- Validating Foundry Configuration ---")
    try:
        config = load_config()
        print(f"Configured Model: {config.foundry_model}")
        if is_baseline and args.expected_model:
            if config.foundry_model != args.expected_model:
                print(
                    f"ERROR: Model mismatch! Expected '{args.expected_model}', "
                    f"but configured model is '{config.foundry_model}'"
                )
                return 1
        print("[OK] Azure Foundry configuration loaded and model verified (endpoint masked)")
    except Exception as e:
        print(f"ERROR: Failed to load Foundry configuration: {sanitize_console_message(str(e))}")
        return 1

    # DRY-RUN CHECK: Exits cleanly without creating or reserving live run directory
    if args.dry_run:
        print("======================================================================")
        print(" [DRY RUN] All preflight checks passed successfully.")
        print(" Live model call skipped. Artifact directory NOT reserved.")
        print("======================================================================")
        return 0

    # 10. Atomic Run-Directory Reservation
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
            "requested_model": config.foundry_model,
        },
    )
    print("[OK] Run directory reserved and run-state.json initialized to RESERVED")
    print()

    # 11. Model Invocation & Evaluation Lifecycle with Allowlist-Based Error Persistence
    try:
        current_phase = "MODEL_INVOCATION"
        atomic_write_json(
            run_state_file,
            {
                "status": "MODEL_INVOCATION",
                "run_label": args.run_label,
                "timestamp": datetime.now(UTC).isoformat(),
                "git_commit_sha": head_sha,
                "requested_model": config.foundry_model,
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
        wire_schema_file = artifact_dir / "openai-wire-schema.json"
        runtime_manifest_file = artifact_dir / "runtime-manifest.json"
        eval_file = artifact_dir / "evaluation.json"

        # Persist runtime manifest
        atomic_write_json(
            runtime_manifest_file,
            {
                "manifest_version": "2.2.0",
                "package_count": len(runtime_manifest),
                "packages": runtime_manifest,
                "canonical_strings": [f"{k}=={v}" for k, v in runtime_manifest.items()],
                "manifest_sha256": runtime_manifest_sha,
            },
        )

        assessment_file.write_text(assessment.model_dump_json(indent=2), encoding="utf-8")
        meta_dict = metadata.to_dict()
        meta_dict["runtime_manifest_sha256"] = runtime_manifest_sha
        if verified_hashes:
            meta_dict["verified_tracked_files_count"] = len(verified_hashes)
        metadata_file.write_text(json.dumps(meta_dict, indent=2), encoding="utf-8")
        export_schema_to_file(schema_file)
        export_wire_schema_to_file(wire_schema_file)

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
                "requested_model": config.foundry_model,
                "response_model_id": metadata.response_model_id,
            },
        )

        # Report Summary
        print("======================================================================")
        print(" GATE 2 EVALUATION SUMMARY (V2.2)")
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
        write_failure_run_state(run_state_file, current_phase, e, head_sha)
        return 1


if __name__ == "__main__":
    sys.exit(main())
