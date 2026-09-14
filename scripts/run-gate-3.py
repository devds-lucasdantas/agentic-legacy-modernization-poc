#!/usr/bin/env python3
"""Gate 3 — Multi-File System Analysis Runner (Version 3.4.3)

Executes multi-file system analysis across all six files of the core banking
system bundle using structured schemas, Responses API Structured Outputs,
and AST-grounded evaluation.

Enforces:
1. Commit-bound baseline authorization specification (evals/baselines/gate-3-baseline-v1.json).
2. Self-Authorizing Child Trust Model: every execution path reaching model invocation,
   including direct internal child execution, must independently establish and satisfy
   the complete baseline authorization contract.
3. Provenance Git repository supplied explicitly by the parent.
4. Runner bootstrap self-verification against committed runner blob in authorized Git SHA.
5. Snapshot byte identity verified against Git object blobs (git cat-file blob <object-id>).
6. Child-derived multi-source bundle identity recomputed from verified snapshot bytes (6 files).
7. Deterministic canonical artifact destination binding
   (provenance_repo/artifacts/gate-3/run_label).
8. Canonical runtime/lock attestation strictly before model invocation.
9. Prompt, wire schema, and bundle manifest SHA256 integrity verification.
10. Strict child verification ordering guaranteeing zero model calls on preflight failure.
11. Host-owned Python runtime provenance persistence in run-metadata.json.
12. Exact single-attempt execution contract: openai_client_max_retries=0, max_attempts=1.
13. Safe offline synthetic / dry-run mode guaranteeing zero model calls when requested.
14. Deterministic evaluation using SystemEvaluatorV3 and Golden Dataset V3.4 (59 units).
15. Two-layer state model: mutable reservation coordination file (reservation-state.json)
    separated from immutable terminal execution record (terminal-result.json).
16. Raw provider boundary: raw response serialized and persisted before
    status/refusal/Pydantic validation.
17. Evidence-based exact model match: response_model == requested_model (gpt-5-mini).

Exit codes:
    0 = PASS
    1 = FAIL (or scope violation / pre-check failure)
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

SPEC_VERSION = "3.5.3"
SCHEMA_VERSION = "3.5.3"
PROMPT_VERSION = "3.5.3"
EVALUATOR_VERSION = "3.5.3"
GOLDEN_DATASET_VERSION = "3.5.3"
SUPPORTED_CONTRACT_VERSIONS = {"3.4.3", "3.5.0", "3.5.1", "3.5.2", "3.5.3"}

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
CANONICAL_BASELINE_SPEC_V1 = "evals/baselines/gate-3-baseline-v1.json"
CANONICAL_BASELINE_SPEC_V2 = "evals/baselines/gate-3-baseline-v2.json"
CANONICAL_BASELINE_SPEC_V3 = "evals/baselines/gate-3-baseline-v3.json"
CANONICAL_BASELINE_SPECS = {
    CANONICAL_BASELINE_SPEC_V1,
    CANONICAL_BASELINE_SPEC_V2,
    CANONICAL_BASELINE_SPEC_V3,
}
CANONICAL_BASELINE_SPEC = CANONICAL_BASELINE_SPEC_V3
DEFAULT_AUTH_SPEC_PATH = CANONICAL_BASELINE_SPEC_V3
DEFAULT_GOLDEN_PATH = "evals/expected/system-understanding-v3.json"
RESERVATION_STATE_FILE = "reservation-state.json"
TERMINAL_RESULT_FILE = "terminal-result.json"
ATTEMPT_CLAIM_FILE = "attempt-claim.json"


class ReservationCollisionError(RuntimeError):
    """Raised when an initial parent reservation file already exists, indicating run claimed."""


def create_initial_reservation_exclusive(reservation_file: Path, data: dict[str, Any]) -> None:
    """Exclusively create initial reservation file with O_CREAT | O_EXCL.

    The exclusive creation is the parent ownership decision.
    If creation fails with EEXIST / FileExistsError, raises ReservationCollisionError.
    If creation succeeds, payload is written, flushed, and fsynced.
    If writing payload fails, the file is NOT unlinked; it remains fail-closed.
    """
    reservation_file.parent.mkdir(parents=True, exist_ok=True)
    payload_bytes = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC

    try:
        fd = os.open(str(reservation_file), flags, 0o600)
    except FileExistsError:
        raise ReservationCollisionError(
            f"Reservation file '{reservation_file}' already exists. "
            "Another parent process owns this run."
        )
    except OSError as e:
        if e.errno == errno.EEXIST:
            raise ReservationCollisionError(
                f"Reservation file '{reservation_file}' already exists. "
                "Another parent process owns this run."
            )
        raise

    # File descriptor is exclusively acquired; parent owns the run.
    # Write payload, fsync, and close. If this fails, leave file in place.
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload_bytes)
            f.flush()
            os.fsync(f.fileno())
    except Exception as write_err:
        # DO NOT unlink or retry. File remains in place fail-closed.
        raise RuntimeError(
            f"Failed to write initial reservation payload to '{reservation_file}' "
            f"after exclusive creation: {write_err}. "
            "Reservation remains consumed/fail-closed; launch is aborted."
        ) from write_err


class AttemptClaimCollisionError(RuntimeError):
    """Raised when an attempt claim file already exists, indicating attempt consumed."""


class FailureFinalizationResult:
    """Outcome of centralized post-invocation failure finalization (H-07 / H-08)."""

    def __init__(
        self,
        sealed: bool,
        reservation_updated: bool,
        status: str,
        error_phase: str,
        verified_artifacts: dict[str, str] | None = None,
        failure_details: list[dict[str, str]] | None = None,
    ) -> None:
        self.sealed = sealed
        self.reservation_updated = reservation_updated
        self.status = status
        self.error_phase = error_phase
        self.verified_artifacts = verified_artifacts if verified_artifacts is not None else {}
        self.failure_details = failure_details if failure_details is not None else []

    def __repr__(self) -> str:
        return (
            f"FailureFinalizationResult(sealed={self.sealed!r}, "
            f"reservation_updated={self.reservation_updated!r}, "
            f"status={self.status!r}, "
            f"error_phase={self.error_phase!r}, "
            f"verified_artifacts={self.verified_artifacts!r}, "
            f"failure_details={self.failure_details!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FailureFinalizationResult):
            return NotImplemented
        return (
            self.sealed == other.sealed
            and self.reservation_updated == other.reservation_updated
            and self.status == other.status
            and self.error_phase == other.error_phase
            and self.verified_artifacts == other.verified_artifacts
            and self.failure_details == other.failure_details
        )


def acquire_atomic_attempt_claim(
    artifact_dir: Path,
    gate: int,
    run_label: str,
    candidate_sha: str,
    authorization_commit_sha: str,
) -> None:
    """Acquire the irrevocable, existence-based atomic attempt claim file.

    Uses os.open with O_CREAT | O_EXCL to ensure exactly-once claim creation.
    Once creation succeeds, the attempt is permanently consumed.
    If acquisition fails with EEXIST, raises AttemptClaimCollisionError without
    modifying shared state.
    """
    artifact_dir.mkdir(parents=True, exist_ok=True)
    claim_path = artifact_dir / ATTEMPT_CLAIM_FILE

    claim_payload = json.dumps(
        {
            "gate": gate,
            "run_label": run_label,
            "candidate_git_sha": candidate_sha,
            "authorization_commit_sha": authorization_commit_sha,
            "pid": os.getpid(),
            "timestamp": datetime.now(UTC).isoformat(),
        },
        indent=2,
        sort_keys=True,
    ).encode("utf-8")

    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC

    try:
        fd = os.open(str(claim_path), flags, 0o600)
    except FileExistsError:
        raise AttemptClaimCollisionError(
            f"Attempt claim file '{claim_path}' already exists. Attempt is permanently consumed."
        )
    except OSError as e:
        if e.errno == errno.EEXIST:
            raise AttemptClaimCollisionError(
                f"Attempt claim file '{claim_path}' already exists. "
                "Attempt is permanently consumed."
            )
        raise

    # File descriptor is exclusively acquired; attempt is now consumed.
    # Write payload, fsync, and close. If this fails, leave file in place.
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(claim_payload)
            f.flush()
            os.fsync(f.fileno())
    except Exception as write_err:
        # DO NOT unlink or retry. Attempt remains permanently consumed.
        raise RuntimeError(
            f"Failed to write attempt claim payload to '{claim_path}' "
            f"after exclusive creation: {write_err}. "
            "Claim remains permanently consumed; live model invocation is forbidden."
        ) from write_err


def safe_preserve_artifact(
    artifact_path: Path,
    data: Any,
    is_json: bool = True,
    failures: list[dict[str, str]] | None = None,
) -> bool:
    """Best-effort artifact write that records failures instead of crashing."""
    try:
        if is_json:
            atomic_write_json(artifact_path, data)
        else:
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            temp_file = artifact_path.with_suffix(f".tmp.{os.getpid()}")
            temp_file.write_text(str(data), encoding="utf-8")
            temp_file.replace(artifact_path)
        return True
    except Exception as e:
        if failures is not None:
            failures.append({"file": artifact_path.name, "error": str(e)})
        return False


def get_sanitized_git_env() -> dict[str, str]:
    """Sanitize environment for Git subprocesses to bypass object replacement and redirection."""
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
            "and contain no path separators or traversal aliases."
        )
    if "/" in run_label or "\\" in run_label or ".." in run_label or run_label.startswith("."):
        raise ValueError(f"Run-label '{run_label}' contains disallowed path characters.")


def validate_project_fingerprint_format(fingerprint: str) -> None:
    """Validate project fingerprint format as exactly 64 lowercase hexadecimal characters."""
    if not HEX_64_PATTERN.fullmatch(fingerprint):
        raise ValueError(
            f"Invalid project fingerprint '{fingerprint}'. "
            "Must be exactly 64 lowercase hex characters."
        )


def is_isolated_python() -> bool:
    """Return True if Python interpreter was invoked in isolated mode (-I)."""
    return sys.flags.isolated == 1


def is_bytecode_writing_disabled() -> bool:
    """Return True if Python interpreter was invoked with -B (dont_write_bytecode)."""
    return sys.flags.dont_write_bytecode == 1


def canonical_distribution_name(name: str) -> str:
    """Canonicalize Python package distribution name per PEP 503."""
    return re.sub(r"[-_.]+", "-", name).lower()


def get_canonical_runtime_manifest() -> dict[str, str]:
    """Generate canonical runtime package manifest from importlib.metadata."""
    runtime: dict[str, str] = {}
    for dist in importlib.metadata.distributions():
        canon = canonical_distribution_name(dist.metadata["Name"])
        if canon in EXCLUDED_DISTRIBUTIONS:
            continue
        runtime[canon] = dist.version
    return dict(sorted(runtime.items()))


def verify_runtime_environment(
    lock_file: Path, spec: dict[str, Any] | None = None
) -> tuple[dict[str, str], str]:
    """Verify runtime environment strictly matches requirements-lock.txt."""
    if not lock_file.is_file():
        raise RuntimeError(f"Lock file not found: {lock_file}")

    lock_bytes = lock_file.read_bytes()
    if spec and "dependency_lock_sha256" in spec:
        actual_lock_sha = hashlib.sha256(lock_bytes).hexdigest()
        if actual_lock_sha.lower() != spec["dependency_lock_sha256"].lower():
            raise RuntimeError(
                f"Dependency lock SHA mismatch: actual={actual_lock_sha}, "
                f"expected={spec['dependency_lock_sha256']}"
            )

    locked: dict[str, str] = {}
    for line in lock_bytes.decode("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" in line:
            name, ver = line.split("==", 1)
            canon = canonical_distribution_name(name.strip())
            if canon not in EXCLUDED_DISTRIBUTIONS:
                locked[canon] = ver.strip()

    runtime = get_canonical_runtime_manifest()
    missing = set(locked.keys()) - set(runtime.keys())
    extra = set(runtime.keys()) - set(locked.keys())
    mismatched = {
        k: (runtime[k], locked[k]) for k in locked if k in runtime and runtime[k] != locked[k]
    }

    errors = []
    if missing:
        errors.append(f"Missing packages: {sorted(missing)}")
    if extra:
        errors.append(f"Unauthorized extra packages: {sorted(extra)}")
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


def normalize_foundry_endpoint(endpoint: str) -> str:
    """Canonical normalization of Azure AI Foundry project endpoint."""
    s = endpoint.strip()
    if not s:
        raise ValueError("Foundry endpoint string is empty.")

    parsed = urllib.parse.urlsplit(s)
    scheme = parsed.scheme.lower()
    if scheme != "https":
        raise ValueError(f"Disallowed endpoint scheme '{parsed.scheme}'. Only HTTPS is permitted.")
    if parsed.username or parsed.password:
        raise ValueError("Foundry endpoint contains disallowed userinfo credentials.")
    if parsed.query or parsed.fragment:
        raise ValueError("Foundry endpoint contains disallowed query or fragment.")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("Foundry endpoint is missing valid hostname.")

    port = parsed.port
    netloc = f"{hostname}:{port}" if port is not None and port != 443 else hostname
    path = parsed.path
    if path.endswith("/") and len(path) > 1:
        path = path[:-1]
    elif path == "/":
        path = ""
    return f"https://{netloc}{path}"


def compute_foundry_project_fingerprint(endpoint: str) -> str:
    """Compute SHA256 hex digest of canonically normalized Foundry project endpoint."""
    norm = normalize_foundry_endpoint(endpoint)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def verify_clean_worktree(repo_root: Path, allow_dirty: bool = False) -> None:
    """Verify that the git working tree has no uncommitted changes or overlays."""
    if allow_dirty:
        return
    env = get_sanitized_git_env()
    res = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    lines = res.stdout.splitlines()
    tracked_dirty = [entry for entry in lines if not entry.startswith("??")]
    if tracked_dirty:
        raise RuntimeError(
            "Git working tree is dirty! Tracked changes:\n" + "\n".join(tracked_dirty)
        )


def verify_no_executable_overlays(repo_root: Path, allow_dirty: bool = False) -> None:
    """Detect untracked or ignored executable overlays that could hijack execution."""
    if allow_dirty:
        return
    env = get_sanitized_git_env()
    res = subprocess.run(
        ["git", "status", "--porcelain", "--ignored"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked_res = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked_set = set(tracked_res.stdout.splitlines())
    disallowed_exact = {"sitecustomize.py", "usercustomize.py", "openai.py", "pydantic.py"}

    violations = []
    for line in res.stdout.splitlines():
        if len(line) < 4:
            continue
        status_code = line[:2]
        path_str = line[3:].strip()
        p = Path(path_str)
        parts = p.parts
        if parts and parts[0] in (
            ".venv",
            ".git",
            "artifacts",
            "scratch",
            ".pytest_cache",
            ".ruff_cache",
            ".mypy_cache",
        ):
            continue
        if p.name in disallowed_exact:
            violations.append(f"Disallowed overlay file: {path_str}")
        if (status_code == "??" or status_code.startswith("!")) and path_str.endswith(".py"):
            if path_str not in tracked_set:
                violations.append(f"Untracked python script overlay: {path_str}")

    if violations:
        raise RuntimeError("Executable overlays detected:\n" + "\n".join(violations))


def verify_trusted_runner_bootstrap(
    provenance_repo: Path, authorized_git_sha: str, executing_file: Path
) -> None:
    """Verify executing runner matches committed runner for authorized Git SHA."""
    sanitized_env = get_sanitized_git_env()
    rev_res = subprocess.run(
        ["git", "rev-parse", "--verify", f"{authorized_git_sha}^{{commit}}"],
        cwd=provenance_repo,
        env=sanitized_env,
        capture_output=True,
        text=True,
        check=False,
    )
    if rev_res.returncode != 0:
        raise RuntimeError(
            f"Authorized Git commit SHA '{authorized_git_sha}' does not resolve: "
            f"{rev_res.stderr.strip()}"
        )

    runner_blob_res = subprocess.run(
        ["git", "show", f"{authorized_git_sha}:scripts/run-gate-3.py"],
        cwd=provenance_repo,
        env=sanitized_env,
        capture_output=True,
        check=False,
    )
    if runner_blob_res.returncode != 0:
        raise RuntimeError(
            f"Failed to retrieve committed runner blob for "
            f"'{authorized_git_sha}:scripts/run-gate-3.py'"
        )
    committed_bytes = runner_blob_res.stdout
    executing_bytes = executing_file.resolve().read_bytes()

    if executing_bytes != committed_bytes:
        executing_sha = hashlib.sha256(executing_bytes).hexdigest()
        committed_sha = hashlib.sha256(committed_bytes).hexdigest()
        raise RuntimeError(
            "Executing runner does not match committed runner blob in authorized Git commit!\n"
            f"Executing runner SHA256: {executing_sha}\n"
            f"Committed blob SHA256:   {committed_sha}"
        )


def verify_snapshot_against_git_objects(
    provenance_repo: Path,
    authorized_git_sha: str,
    snapshot_dir: Path,
) -> set[str]:
    """Verify snapshot regular-file bytes against Git object blobs byte-for-byte."""
    sanitized_env = get_sanitized_git_env()
    ls_tree_res = subprocess.run(
        ["git", "ls-tree", "-r", "-z", authorized_git_sha],
        cwd=provenance_repo,
        env=sanitized_env,
        capture_output=True,
        check=False,
    )
    if ls_tree_res.returncode != 0:
        raise RuntimeError(f"git ls-tree failed for commit '{authorized_git_sha}'")

    expected_files: set[str] = set()
    expected_dirs: set[str] = set()
    raw_entries = [e for e in ls_tree_res.stdout.split(b"\x00") if e]

    for entry in raw_entries:
        parts = entry.split(b"\t", 1)
        if len(parts) != 2:
            continue
        meta_bytes, path_bytes = parts
        meta_parts = meta_bytes.split(b" ")
        if len(meta_parts) != 3:
            continue
        mode_bytes, type_bytes, obj_id_bytes = meta_parts
        mode = mode_bytes.decode("ascii")
        typ = type_bytes.decode("ascii")
        obj_id = obj_id_bytes.decode("ascii")
        rel_path = path_bytes.decode("utf-8", errors="replace")

        if mode == "120000":
            raise RuntimeError(f"Unauthorized symlink in Git tree: '{rel_path}'")

        if mode not in ("100644", "100755") or typ != "blob":
            continue

        expected_files.add(rel_path)
        p = Path(rel_path).parent
        while p != Path(".") and p.as_posix() != ".":
            expected_dirs.add(p.as_posix())
            p = p.parent

        file_path = snapshot_dir / rel_path
        if not file_path.is_file() or file_path.is_symlink():
            raise RuntimeError(f"Committed file missing or is symlink in snapshot: {rel_path}")

        disk_bytes = file_path.read_bytes()
        blob_proc = subprocess.run(
            ["git", "cat-file", "blob", obj_id],
            cwd=provenance_repo,
            env=sanitized_env,
            capture_output=True,
            check=False,
        )
        if blob_proc.returncode != 0:
            raise RuntimeError(f"Failed to retrieve committed blob for '{rel_path}' ({obj_id})")
        committed_bytes = blob_proc.stdout

        if disk_bytes != committed_bytes:
            raise RuntimeError(
                f"Snapshot file '{rel_path}' does not match committed Git object bytes!"
            )

    # Recursively inspect snapshot_dir; walk must not follow symlinks
    actual_files: set[str] = set()
    actual_dirs: set[str] = set()
    for root, dirs, files in os.walk(str(snapshot_dir), followlinks=False):
        root_path = Path(root)
        for d in dirs:
            dir_path = root_path / d
            rel_dir = dir_path.relative_to(snapshot_dir).as_posix()
            if dir_path.is_symlink():
                raise RuntimeError(f"Unauthorized symlink directory in snapshot: {rel_dir}")
            actual_dirs.add(rel_dir)
        for f in files:
            file_path = root_path / f
            rel = file_path.relative_to(snapshot_dir).as_posix()
            if file_path.is_symlink():
                raise RuntimeError(f"Unauthorized symlink in snapshot: {rel}")
            if not file_path.is_file():
                raise RuntimeError(f"Unauthorized special non-regular file in snapshot: {rel}")
            actual_files.add(rel)

    # For official execution: actual authorized directories == expected committed directories
    extra_dirs = actual_dirs - expected_dirs
    if extra_dirs:
        raise RuntimeError(f"Unauthorized extra directory in snapshot: {sorted(extra_dirs)}")

    missing_dirs = expected_dirs - actual_dirs
    if missing_dirs:
        raise RuntimeError(f"Committed directory missing from snapshot: {sorted(missing_dirs)}")

    # For official execution: actual authorized regular files == committed regular files
    extra_files = actual_files - expected_files
    if extra_files:
        sorted_extras = sorted(extra_files)
        for extra in sorted_extras:
            base = Path(extra).name
            if base == "__init__.py":
                raise RuntimeError(
                    f"Unauthorized extra Python package initializer in snapshot: '{extra}'"
                )
            if base in ("sitecustomize.py", "usercustomize.py"):
                raise RuntimeError(
                    f"Unauthorized Python customization module in snapshot: '{extra}'"
                )
            if base.endswith(".pth"):
                raise RuntimeError(f"Unauthorized Python .pth file in snapshot: '{extra}'")
            if base.endswith((".py", ".pyc", ".pyo", ".pyd")):
                raise RuntimeError(f"Unauthorized importable Python module in snapshot: '{extra}'")
            if base.endswith((".sh", ".exe", ".bat", ".cmd", ".bin")):
                raise RuntimeError(f"Unauthorized executable file in snapshot: '{extra}'")
        raise RuntimeError(f"Unauthorized extra regular file(s) in snapshot: {sorted_extras}")

    missing_files = expected_files - actual_files
    if missing_files:
        raise RuntimeError(f"Committed file(s) missing from snapshot: {sorted(missing_files)}")

    return expected_files


def create_git_snapshot_archive(
    candidate_git_sha: str, temp_dir: Path, repo_root: Path = REPO_ROOT, allow_dirty: bool = False
) -> Path:
    """Extract application snapshot from authorized Git commit tree via git archive."""
    sanitized_env = get_sanitized_git_env()
    archive_proc = subprocess.Popen(
        ["git", "archive", "--format=tar", candidate_git_sha],
        cwd=repo_root,
        env=sanitized_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if archive_proc.stdout is None:
        raise RuntimeError("Failed to open pipe from git archive")

    with tarfile.open(fileobj=archive_proc.stdout, mode="r|") as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(path=temp_dir, filter="data")
        else:
            tar.extractall(path=temp_dir)

    returncode = archive_proc.wait()
    if returncode != 0:
        stderr_msg = (
            archive_proc.stderr.read().decode("utf-8", errors="replace")
            if archive_proc.stderr
            else ""
        )
        raise RuntimeError(f"git archive failed (exit {returncode}): {stderr_msg}")

    if allow_dirty:
        excluded_dirs = {
            ".git",
            ".venv",
            "artifacts",
            "scratch",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            ".mypy_cache",
        }
        for root, dirs, files in os.walk(repo_root):
            dirs[:] = [d for d in dirs if d not in excluded_dirs]
            rel_root = Path(root).relative_to(repo_root)
            for f in files:
                if f.endswith((".pyc", ".pyo")):
                    continue
                src_file = Path(root) / f
                dst_file = temp_dir / rel_root / f
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                dst_file.write_bytes(src_file.read_bytes())

    return temp_dir


def validate_authorization_spec_dict(spec: dict[str, Any]) -> dict[str, Any]:
    """Validate all contract fields of the Gate 3 authorization specification dictionary."""
    if not isinstance(spec, dict):
        raise ValueError("Authorization spec must be a JSON object / dict.")

    required_keys = {
        "spec_version",
        "gate",
        "run_label",
        "reasoning_effort",
        "prompt_sha256",
        "wire_schema_sha256",
        "source_manifest_sha256",
        "bundle_serialization_version",
        "bundle_sha256",
        "dependency_lock_sha256",
        "requested_model",
        "foundry_project_fingerprint",
        "openai_client_max_retries",
        "application_model_retries",
        "maximum_model_attempts",
        "maximum_logical_invocation_count",
        "schema_version",
        "prompt_version",
        "evaluator_version",
        "golden_dataset_version",
        "golden_dataset_sha256",
        "target_bundle",
    }
    missing = required_keys - set(spec.keys())
    if missing:
        raise ValueError(f"Authorization spec missing required keys: {sorted(missing)}")
    if "candidate_git_sha" not in spec:
        raise ValueError("Authorization spec must contain 'candidate_git_sha'")
    if "expected_git_sha" in spec:
        raise ValueError("Authorization spec must not contain legacy 'expected_git_sha'")

    if spec.get("gate") != 3:
        raise ValueError(f"Authorization spec gate must be 3, got: {spec.get('gate')}")
    spec_ver = spec.get("spec_version")
    if spec_ver not in SUPPORTED_CONTRACT_VERSIONS:
        raise ValueError(
            f"spec_version must be one of {sorted(SUPPORTED_CONTRACT_VERSIONS)}, got: {spec_ver}"
        )
    if spec.get("schema_version") != spec_ver:
        raise ValueError(f"schema_version must be '{spec_ver}', got: {spec.get('schema_version')}")
    if spec.get("prompt_version") != spec_ver:
        raise ValueError(f"prompt_version must be '{spec_ver}', got: {spec.get('prompt_version')}")
    if spec.get("evaluator_version") != spec_ver:
        raise ValueError(
            f"evaluator_version must be '{spec_ver}', got: {spec.get('evaluator_version')}"
        )
    if spec.get("golden_dataset_version") != spec_ver:
        raise ValueError(
            f"golden_dataset_version must be '{spec_ver}', "
            f"got: {spec.get('golden_dataset_version')}"
        )
    if spec.get("openai_client_max_retries") != 0:
        raise ValueError("openai_client_max_retries must be 0")
    if spec.get("application_model_retries") != 0:
        raise ValueError("application_model_retries must be 0")
    if spec.get("maximum_model_attempts") != 1:
        raise ValueError("maximum_model_attempts must be 1")
    if spec.get("maximum_logical_invocation_count") != 1:
        raise ValueError("maximum_logical_invocation_count must be 1")
    if spec.get("reasoning_effort") != "low":
        raise ValueError("reasoning_effort must be 'low'")
    if spec.get("requested_model") != "gpt-5-mini":
        raise ValueError(
            f"requested_model must be 'gpt-5-mini', got: {spec.get('requested_model')}"
        )

    # Format validations
    validate_run_label(str(spec.get("run_label", "")))
    validate_project_fingerprint_format(str(spec.get("foundry_project_fingerprint", "")))

    for h_field in (
        "prompt_sha256",
        "wire_schema_sha256",
        "source_manifest_sha256",
        "bundle_sha256",
        "dependency_lock_sha256",
        "golden_dataset_sha256",
    ):
        h_val = str(spec.get(h_field, ""))
        if not HEX_64_PATTERN.fullmatch(h_val):
            raise ValueError(
                f"{h_field} must be exactly 64 lowercase hex characters, got: '{h_val}'"
            )

    candidate_sha = str(spec.get("candidate_git_sha", "")).strip()
    if candidate_sha and not HEX_40_PATTERN.fullmatch(candidate_sha):
        raise ValueError(
            "candidate_git_sha must be empty or 40 lowercase hex characters, "
            f"got: '{candidate_sha}'"
        )

    tb = spec.get("target_bundle")
    if not isinstance(tb, list) or len(tb) != 6:
        raise ValueError(f"target_bundle must be a list of exactly 6 items, got: {type(tb)}")
    for idx, item in enumerate(tb):
        if not isinstance(item, dict) or "path" not in item or "sha256" not in item:
            raise ValueError(f"target_bundle item {idx} missing 'path' or 'sha256'")
        sha_item = str(item.get("sha256", ""))
        if not HEX_64_PATTERN.fullmatch(sha_item):
            raise ValueError(
                f"target_bundle item {idx} ({item.get('path')}) sha256 must be 64 hex characters, "
                f"got: '{sha_item}'"
            )

    return spec


def load_authorization_spec_from_git(
    repo_root: Path, commit_sha: str, rel_path: str
) -> tuple[dict[str, Any], str]:
    """Retrieve and validate authorization spec directly from Git commit object plumbing."""
    sanitized_env = get_sanitized_git_env()
    proc = subprocess.run(
        ["git", "show", f"{commit_sha}:{rel_path}"],
        cwd=repo_root,
        env=sanitized_env,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Failed to retrieve authorization spec from git object '{commit_sha}:{rel_path}': "
            f"{proc.stderr.decode('utf-8', errors='replace')}"
        )
    raw_bytes = proc.stdout
    spec_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    try:
        spec = json.loads(raw_bytes.decode("utf-8"))
    except Exception as e:
        raise ValueError(
            f"Committed authorization spec in '{commit_sha}:{rel_path}' is malformed JSON: {e}"
        ) from e
    validate_authorization_spec_dict(spec)
    return spec, spec_sha256


def load_authorization_spec(spec_path: Path) -> tuple[dict[str, Any], str]:
    """Load and validate the Gate 3 authorization specification from a filesystem path."""
    if not spec_path.is_file():
        raise FileNotFoundError(f"Authorization specification not found at: {spec_path}")
    raw_bytes = spec_path.read_bytes()
    spec_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    try:
        spec = json.loads(raw_bytes.decode("utf-8"))
    except Exception as e:
        raise ValueError(
            f"Authorization specification at '{spec_path}' is malformed JSON: {e}"
        ) from e
    validate_authorization_spec_dict(spec)
    return spec, spec_sha256


def validate_authorization_contract(
    repo_root: Path,
    candidate_sha: str,
    authorization_commit_sha: str,
    auth_spec_path: Path,
    allow_dirty: bool = False,
    is_live: bool = False,
) -> None:
    """Validate strict authorization contract shared across parent and child paths."""
    if is_live and not candidate_sha:
        raise RuntimeError(
            "Candidate commit is not frozen: candidate_git_sha is empty in authorization spec. "
            "Refusing live execution on un-frozen candidate."
        )

    if is_live and allow_dirty:
        raise RuntimeError("Live execution with --allow-dirty is strictly prohibited.")

    canonical_spec_paths = {(repo_root / p).resolve() for p in CANONICAL_BASELINE_SPECS}
    if not allow_dirty and auth_spec_path.resolve() not in canonical_spec_paths:
        specs_str = sorted(CANONICAL_BASELINE_SPECS)
        raise ValueError(
            f"Authorization specification must use canonical path in {specs_str}. "
            f"Got: '{auth_spec_path}'"
        )

    if candidate_sha and authorization_commit_sha and not allow_dirty:
        env = get_sanitized_git_env()

        # In live execution, verify that git rev-parse HEAD == authorization_commit_sha
        if is_live:
            head_proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            head_sha = head_proc.stdout.strip()
            if head_sha != authorization_commit_sha:
                raise RuntimeError(
                    f"Current HEAD commit '{head_sha}' does not match authorization commit "
                    f"'{authorization_commit_sha}'"
                )
            verify_clean_worktree(repo_root, allow_dirty=allow_dirty)
            verify_no_executable_overlays(repo_root, allow_dirty=allow_dirty)

        # Direct child parentage verification: A^ == C
        parent_proc = subprocess.run(
            ["git", "rev-parse", "--verify", f"{authorization_commit_sha}^"],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if parent_proc.returncode != 0:
            raise RuntimeError(
                f"Failed to resolve parent commit of auth commit '{authorization_commit_sha}'"
            )
        parent_sha = parent_proc.stdout.strip()
        if parent_sha != candidate_sha:
            raise RuntimeError(
                f"Authorization commit '{authorization_commit_sha}' must be a direct child of "
                f"candidate commit '{candidate_sha}'. Resolved parent is '{parent_sha}'."
            )

        # Diff must strictly touch ONLY the exact selected canonical authorization spec
        diff_proc = subprocess.run(
            ["git", "diff", "--name-only", candidate_sha, authorization_commit_sha],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        changed_files = [f.strip() for f in diff_proc.stdout.splitlines() if f.strip()]
        try:
            rel_spec_path = auth_spec_path.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            rel_spec_path = auth_spec_path.as_posix()

        if changed_files != [rel_spec_path]:
            raise RuntimeError(
                f"Authorization commit '{authorization_commit_sha}' must modify strictly and only "
                f"the selected authorization spec '{rel_spec_path}'. Got: {changed_files}"
            )


def verify_bundle_integrity(
    snapshot_dir: Path, spec: dict[str, Any]
) -> tuple[list[dict[str, str]], str, str]:
    """Verify all files in target_bundle exist and compute composite hashes."""
    target_bundle = spec.get("target_bundle", [])
    if len(target_bundle) != 6:
        raise ValueError(f"Expected 6 files in target_bundle, got: {len(target_bundle)}")

    recomputed_entries: list[dict[str, str]] = []
    h_bundle = hashlib.sha256()

    for item in sorted(target_bundle, key=lambda x: x["path"]):
        rel_path = item["path"]
        expected_sha = item["sha256"]
        file_path = snapshot_dir / rel_path
        if not file_path.is_file() or file_path.is_symlink():
            raise RuntimeError(f"Bundle file missing or is symlink: {rel_path}")

        file_bytes = file_path.read_bytes()
        actual_sha = hashlib.sha256(file_bytes).hexdigest()
        if actual_sha.lower() != expected_sha.lower():
            raise RuntimeError(
                f"SHA mismatch for bundle file {rel_path}: "
                f"actual={actual_sha}, expected={expected_sha}"
            )

        recomputed_entries.append({"path": rel_path, "sha256": actual_sha})
        h_bundle.update(rel_path.encode("utf-8"))
        h_bundle.update(file_bytes)

    actual_bundle_sha = h_bundle.hexdigest()
    if actual_bundle_sha.lower() != spec["bundle_sha256"].lower():
        raise RuntimeError(
            f"Composite bundle SHA mismatch: "
            f"actual={actual_bundle_sha}, expected={spec['bundle_sha256']}"
        )

    manifest_bytes = json.dumps(recomputed_entries, sort_keys=True).encode("utf-8")
    actual_manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if actual_manifest_sha.lower() != spec["source_manifest_sha256"].lower():
        raise RuntimeError(
            f"Source manifest SHA mismatch: "
            f"actual={actual_manifest_sha}, expected={spec['source_manifest_sha256']}"
        )

    return recomputed_entries, actual_bundle_sha, actual_manifest_sha


def verify_schema_and_prompt_hashes(snapshot_dir: Path, spec: dict[str, Any]) -> None:
    """Verify prompt and wire schema hashes match committed authorization spec."""
    prompt_file = snapshot_dir / "agents" / "legacy_analyzer" / "prompts" / "system_v3.md"
    if not prompt_file.is_file():
        raise RuntimeError(f"Prompt file missing: {prompt_file}")
    actual_prompt_sha = hashlib.sha256(prompt_file.read_bytes()).hexdigest()
    if actual_prompt_sha.lower() != spec["prompt_sha256"].lower():
        raise RuntimeError(
            f"Prompt SHA mismatch: actual={actual_prompt_sha}, expected={spec['prompt_sha256']}"
        )

    from agents.legacy_analyzer.schemas.system_export import get_system_openai_wire_schema

    wire = get_system_openai_wire_schema()
    wire_bytes = json.dumps(wire, sort_keys=True).encode("utf-8")
    actual_wire_sha = hashlib.sha256(wire_bytes).hexdigest()
    if actual_wire_sha.lower() != spec["wire_schema_sha256"].lower():
        raise RuntimeError(
            f"Wire schema SHA mismatch: "
            f"actual={actual_wire_sha}, expected={spec['wire_schema_sha256']}"
        )


def atomic_write_json(destination: Path, data: Any) -> None:
    """Atomically write JSON data to destination file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_file = destination.with_suffix(f".tmp.{os.getpid()}")
    temp_file.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    temp_file.replace(destination)


def check_existing_reservation(out_dir: Path, run_label: str) -> None:
    """Check attempt-claim.json, reservation-state.json, and run-state.json for reservations."""
    claim_path = out_dir / ATTEMPT_CLAIM_FILE
    if claim_path.exists():
        raise RuntimeError(
            f"Irrevocable reservation error: Attempt claim file '{claim_path}' already exists. "
            f"Run label '{run_label}' in '{out_dir}' has consumed its attempt. "
            "Re-entry is strictly refused."
        )

    state_candidates = [
        out_dir / RESERVATION_STATE_FILE,
        out_dir / "run-state.json",
    ]
    for state_file in state_candidates:
        if state_file.exists():
            try:
                st_data = json.loads(state_file.read_text(encoding="utf-8"))
                st = (
                    st_data.get("status", "CORRUPTED") if isinstance(st_data, dict) else "CORRUPTED"
                )
            except Exception:
                st = "CORRUPTED"
            raise RuntimeError(
                f"Irrevocable reservation error: State file '{state_file}' already exists "
                f"with status '{st}'. Run label '{run_label}' in '{out_dir}' has consumed its "
                "reservation. Re-entry is strictly refused."
            )


def execute_gate_3(
    repo_root: Path,
    auth_spec_path: Path,
    output_dir: Path | None = None,
    run_label: str | None = None,
    synthetic: bool = False,
    dry_run: bool = False,
    allow_dirty: bool = False,
    golden_path: Path | None = None,
) -> int:
    """Parent execution path: orchestrate preflight and execute isolated child."""
    # 1. Load authorization spec early so run_label can be derived if omitted
    spec, spec_sha = load_authorization_spec(auth_spec_path)

    # Derive effective run_label if omitted, or enforce matching if provided
    if run_label is None:
        run_label = spec.get("run_label", "baseline-v3")
    elif spec.get("run_label") != run_label:
        raise ValueError(f"Run label mismatch: CLI={run_label}, spec={spec.get('run_label')}")

    validate_run_label(run_label)

    is_live = not (synthetic or dry_run)
    canonical_out = (repo_root / "artifacts" / "gate-3" / run_label).resolve()

    if run_label.startswith("baseline-") and not allow_dirty and not synthetic:
        if output_dir and output_dir.resolve() != canonical_out:
            raise ValueError(
                f"Baseline run '{run_label}' must write to canonical directory '{canonical_out}', "
                f"got '{output_dir}'"
            )

    # 2. Verify worktree cleanliness and overlays
    verify_clean_worktree(repo_root, allow_dirty=allow_dirty)
    verify_no_executable_overlays(repo_root, allow_dirty=allow_dirty)

    # 3. Get git HEAD SHA
    env = get_sanitized_git_env()
    rev_res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    head_sha = rev_res.stdout.strip()

    candidate_sha = spec["candidate_git_sha"].strip()

    validate_authorization_contract(
        repo_root=repo_root,
        candidate_sha=candidate_sha,
        authorization_commit_sha=head_sha,
        auth_spec_path=auth_spec_path,
        allow_dirty=allow_dirty,
        is_live=is_live,
    )

    # 4. Determine artifact destination & enforce irrevocable reservation
    out_dir = output_dir or canonical_out
    check_existing_reservation(out_dir, run_label)

    if not allow_dirty and run_label.startswith("baseline-") and out_dir.exists():
        if any(out_dir.iterdir()):
            raise RuntimeError(
                f"Irrevocable reservation error: Artifact directory '{out_dir}' "
                f"already exists and is non-empty for baseline run. "
                f"Re-use of official baseline label/directory is strictly forbidden."
            )

    out_dir.mkdir(parents=True, exist_ok=True)

    # 5. Exclusively create initial RESERVED state file
    reservation_file = out_dir / RESERVATION_STATE_FILE
    try:
        create_initial_reservation_exclusive(
            reservation_file,
            {
                "status": "RESERVED",
                "run_label": run_label,
                "gate": 3,
                "timestamp": datetime.now(UTC).isoformat(),
                "candidate_git_sha": candidate_sha,
                "authorization_commit_sha": head_sha,
                "git_commit_sha": candidate_sha or head_sha,
                "bundle_sha256": spec["bundle_sha256"],
                "requested_model": spec["requested_model"],
                "foundry_project_fingerprint": spec["foundry_project_fingerprint"],
            },
        )
    except ReservationCollisionError as col_err:
        print(f"ERROR: Irrevocable parent reservation collision: {col_err}", file=sys.stderr)
        return 1

    # 6. Execute child in isolated mode from candidate C snapshot
    snapshot_target_sha = candidate_sha if candidate_sha else head_sha
    with tempfile.TemporaryDirectory(prefix="gate3_snapshot_") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        create_git_snapshot_archive(
            snapshot_target_sha, temp_dir, repo_root=repo_root, allow_dirty=allow_dirty
        )

        child_args = [
            sys.executable,
            "-I",
            "-B",
            str(temp_dir / "scripts" / "run-gate-3.py"),
            "--internal-child",
            "--provenance-repo",
            str(repo_root.resolve()),
            "--snapshot-dir",
            str(temp_dir.resolve()),
            "--artifact-dir",
            str(out_dir.resolve()),
            "--authorized-git-sha",
            candidate_sha or head_sha,
            "--authorization-commit-sha",
            head_sha,
            "--auth-spec",
            str(auth_spec_path.resolve()),
            "--run-label",
            run_label,
        ]
        if synthetic:
            child_args.append("--synthetic")
        if dry_run:
            child_args.append("--dry-run")
        if allow_dirty:
            child_args.append("--allow-dirty")
        if golden_path:
            child_args.extend(["--golden-path", str(golden_path.resolve())])

        child_proc = subprocess.run(
            child_args,
            cwd=temp_dir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        print(child_proc.stdout)
        if child_proc.stderr:
            print(child_proc.stderr, file=sys.stderr)

        return child_proc.returncode


def finalize_post_model_failure(
    artifact_dir: Path,
    reservation_file: Path,
    error_phase: str,
    error: Exception | str,
    spec: dict[str, Any] | None,
    candidate_sha: str,
    authorization_commit_sha: str,
    authorized_sha: str,
    run_label: str,
    bundle: Any | None = None,
    parser: Any | None = None,
    runtime_manifest: dict[str, str] | None = None,
    metadata: Any | None = None,
    assessment: Any | None = None,
    raw_response_content: Any | None = None,
    evaluation_result: Any | None = None,
    evaluated_predictions: Any | None = None,
    spec_sha: str | None = None,
    runtime_manifest_sha: str | None = None,
) -> FailureFinalizationResult:
    """Centralized post-invocation failure finalizer.

    Preserves all obtainable immutable evidence artifacts, writes terminal-result.json with
    status=FAILED, generates manifest.json over preserved immutable artifacts, performs
    read-back verification (H-07), and transitions reservation-state.json to FAILED or
    FAILED_UNSEALED (H-08 Case A / Case B).
    """
    try:
        artifact_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    error_type = type(error).__name__ if isinstance(error, Exception) else "Error"
    error_message = str(error)
    response_id = getattr(metadata, "response_id", None) if metadata else None
    response_model_id = getattr(metadata, "response_model_id", None) if metadata else None

    if spec_sha is None and spec is not None:
        try:
            spec_sha = hashlib.sha256(json.dumps(spec, sort_keys=True).encode("utf-8")).hexdigest()
        except Exception:
            pass
    if runtime_manifest_sha is None and runtime_manifest is not None:
        try:
            runtime_manifest_sha = hashlib.sha256(
                json.dumps(runtime_manifest, sort_keys=True).encode("utf-8")
            ).hexdigest()
        except Exception:
            pass

    failures: list[dict[str, str]] = []

    # 1. raw-response.json
    raw_resp_path = artifact_dir / "raw-response.json"
    if not raw_resp_path.exists() and raw_response_content is not None:
        if isinstance(raw_response_content, (dict, list)):
            safe_preserve_artifact(
                raw_resp_path, raw_response_content, is_json=True, failures=failures
            )
        else:
            try:
                parsed_raw = json.loads(raw_response_content)
                safe_preserve_artifact(raw_resp_path, parsed_raw, is_json=True, failures=failures)
            except Exception:
                safe_preserve_artifact(
                    raw_resp_path, str(raw_response_content), is_json=False, failures=failures
                )

    # 2. run-metadata.json
    run_meta_path = artifact_dir / "run-metadata.json"
    if not run_meta_path.exists():
        if metadata is not None:
            try:
                meta_dict = metadata.to_dict() if hasattr(metadata, "to_dict") else dict(metadata)
                meta_dict["candidate_git_sha"] = candidate_sha
                meta_dict["authorization_commit_sha"] = authorization_commit_sha
                meta_dict["git_commit_sha"] = authorized_sha
                if spec_sha:
                    meta_dict.setdefault("auth_spec_sha256", spec_sha)
                if spec and "bundle_sha256" in spec:
                    meta_dict.setdefault("bundle_sha256", spec["bundle_sha256"])
                if runtime_manifest_sha:
                    meta_dict.setdefault("runtime_manifest_sha256", runtime_manifest_sha)
                safe_preserve_artifact(run_meta_path, meta_dict, is_json=True, failures=failures)
            except Exception as e:
                failures.append({"file": "run-metadata.json", "error": str(e)})
        else:
            try:
                meta_dict = {
                    "run_label": run_label,
                    "gate": 3,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "status": "FAILED",
                    "error_phase": error_phase,
                    "error_type": error_type,
                    "error_message": error_message,
                    "candidate_git_sha": candidate_sha,
                    "authorization_commit_sha": authorization_commit_sha,
                    "git_commit_sha": authorized_sha,
                }
                if spec is not None:
                    meta_dict["requested_model"] = spec.get("requested_model")
                    meta_dict["bundle_sha256"] = spec.get("bundle_sha256")
                    meta_dict["evaluator_version"] = spec.get("evaluator_version")
                    meta_dict["prompt_version"] = spec.get("prompt_version")
                if spec_sha:
                    meta_dict["auth_spec_sha256"] = spec_sha
                if runtime_manifest_sha:
                    meta_dict["runtime_manifest_sha256"] = runtime_manifest_sha
                safe_preserve_artifact(run_meta_path, meta_dict, is_json=True, failures=failures)
            except Exception as e:
                failures.append({"file": "run-metadata.json", "error": str(e)})

    # 3. model-assessment.json (if parsing succeeded)
    if assessment is not None and not (artifact_dir / "model-assessment.json").exists():
        try:
            dump = assessment.model_dump() if hasattr(assessment, "model_dump") else assessment
            safe_preserve_artifact(
                artifact_dir / "model-assessment.json", dump, is_json=True, failures=failures
            )
        except Exception as e:
            failures.append({"file": "model-assessment.json", "error": str(e)})

    # 3b. enriched-assessment.json (if assessment is available)
    if assessment is not None and not (artifact_dir / "enriched-assessment.json").exists():
        try:
            dump = assessment.model_dump() if hasattr(assessment, "model_dump") else assessment
            safe_preserve_artifact(
                artifact_dir / "enriched-assessment.json", dump, is_json=True, failures=failures
            )
        except Exception as e:
            failures.append({"file": "enriched-assessment.json", "error": str(e)})

    # 3c. evaluation.json (if already computed in memory)
    if (
        evaluation_result is not None
        and evaluated_predictions is not None
        and not (artifact_dir / "evaluation.json").exists()
    ):
        try:
            eval_dict = {
                "metric_summary": evaluation_result.to_dict()
                if hasattr(evaluation_result, "to_dict")
                else evaluation_result,
                "predictions": [
                    p.to_dict() if hasattr(p, "to_dict") else p for p in evaluated_predictions
                ],
            }
            safe_preserve_artifact(
                artifact_dir / "evaluation.json", eval_dict, is_json=True, failures=failures
            )
        except Exception as e:
            failures.append({"file": "evaluation.json", "error": str(e)})

    # 4. authorization-spec.json
    if spec is not None and not (artifact_dir / "authorization-spec.json").exists():
        safe_preserve_artifact(
            artifact_dir / "authorization-spec.json", spec, is_json=True, failures=failures
        )

    # 5. production-prompt.md
    if not (artifact_dir / "production-prompt.md").exists():
        try:
            from agents.legacy_analyzer.system_agent import load_system_v3_prompt

            safe_preserve_artifact(
                artifact_dir / "production-prompt.md",
                load_system_v3_prompt(),
                is_json=False,
                failures=failures,
            )
        except Exception as e:
            failures.append({"file": "production-prompt.md", "error": str(e)})

    # 6. wire-schema.json
    if not (artifact_dir / "wire-schema.json").exists():
        try:
            from agents.legacy_analyzer.schemas.system_export import (
                get_system_openai_wire_schema,
            )

            safe_preserve_artifact(
                artifact_dir / "wire-schema.json",
                get_system_openai_wire_schema(),
                is_json=True,
                failures=failures,
            )
        except Exception as e:
            failures.append({"file": "wire-schema.json", "error": str(e)})

    # 7. source-manifest.json & canonical-input-bundle.txt
    if bundle is not None:
        if not (artifact_dir / "source-manifest.json").exists():
            try:
                source_manifest = {
                    rel_path: {
                        "size": len(f.raw_content.encode("utf-8")),
                        "lines": f.line_count,
                        "sha256": f.sha256,
                    }
                    for rel_path, f in bundle.files.items()
                }
                safe_preserve_artifact(
                    artifact_dir / "source-manifest.json",
                    source_manifest,
                    is_json=True,
                    failures=failures,
                )
            except Exception as e:
                failures.append({"file": "source-manifest.json", "error": str(e)})
        if not (artifact_dir / "canonical-input-bundle.txt").exists():
            try:
                safe_preserve_artifact(
                    artifact_dir / "canonical-input-bundle.txt",
                    bundle.formatted_prompt_payload,
                    is_json=False,
                    failures=failures,
                )
            except Exception as e:
                failures.append({"file": "canonical-input-bundle.txt", "error": str(e)})

    # 8. parser-coverage-certificate.json
    if parser is not None and not (artifact_dir / "parser-coverage-certificate.json").exists():
        try:
            coverage_cert = parser.get_parser_coverage_certificate()
            safe_preserve_artifact(
                artifact_dir / "parser-coverage-certificate.json",
                coverage_cert.to_dict(),
                is_json=True,
                failures=failures,
            )
        except Exception as e:
            failures.append({"file": "parser-coverage-certificate.json", "error": str(e)})

    # 9. runtime-manifest.json
    if runtime_manifest is not None and not (artifact_dir / "runtime-manifest.json").exists():
        safe_preserve_artifact(
            artifact_dir / "runtime-manifest.json",
            runtime_manifest,
            is_json=True,
            failures=failures,
        )

    # 10. terminal-result.json (immutable failure outcome, written before manifest)
    terminal_result: dict[str, Any] = {
        "gate": 3,
        "run_label": run_label,
        "status": "FAILED",
        "error_phase": error_phase,
        "error_type": error_type,
        "error_message": error_message,
        "candidate_git_sha": candidate_sha,
        "authorization_commit_sha": authorization_commit_sha,
        "git_commit_sha": authorized_sha,
        "response_id": response_id,
        "response_model_id": response_model_id,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if evaluation_result is not None:
        terminal_result["gate_3_pass"] = getattr(evaluation_result, "gate_3_pass", False)
        terminal_result["precision"] = getattr(evaluation_result, "precision", 0.0)
        terminal_result["recall"] = getattr(evaluation_result, "recall", 0.0)
        terminal_result["matched_expected_count"] = getattr(
            evaluation_result, "matched_expected_count", 0
        )
        terminal_result["expected_fact_count"] = getattr(
            evaluation_result, "expected_fact_count", 0
        )
    if failures:
        terminal_result["artifact_write_failures"] = list(failures)
    safe_preserve_artifact(
        artifact_dir / TERMINAL_RESULT_FILE,
        terminal_result,
        is_json=True,
        failures=failures,
    )

    # 11. manifest.json (written LAST of immutable set)
    excluded_from_manifest = {
        "manifest.json",
        RESERVATION_STATE_FILE,
        "run-state.json",
        ATTEMPT_CLAIM_FILE,
        "coordination-failure.json",
    }
    manifest_shas: dict[str, str] = {}
    try:
        for fname in sorted(os.listdir(artifact_dir)):
            if fname in excluded_from_manifest or fname.endswith(".tmp") or ".tmp." in fname:
                continue
            fpath = artifact_dir / fname
            if fpath.is_file():
                manifest_shas[fname] = hashlib.sha256(fpath.read_bytes()).hexdigest()
    except Exception as e:
        failures.append({"file": "manifest_scan", "error": str(e)})

    manifest: dict[str, Any] = {
        "gate": 3,
        "run_label": run_label,
        "status": "FAILED",
        "timestamp": datetime.now(UTC).isoformat(),
        "candidate_git_sha": candidate_sha,
        "authorization_commit_sha": authorization_commit_sha,
        "git_commit_sha": authorized_sha,
        "gate_3_pass": False,
        "artifacts": manifest_shas,
    }
    safe_preserve_artifact(
        artifact_dir / "manifest.json", manifest, is_json=True, failures=failures
    )

    # 12. READ-BACK VERIFICATION of sealed failure evidence (H-07)
    verification_errors: list[dict[str, str]] = []
    verified_artifacts: dict[str, str] = {}
    is_sealed = False

    term_path = artifact_dir / TERMINAL_RESULT_FILE
    man_path = artifact_dir / "manifest.json"

    try:
        if not term_path.is_file():
            verification_errors.append(
                {"file": TERMINAL_RESULT_FILE, "error": "File does not exist on disk"}
            )
        else:
            term_data = json.loads(term_path.read_text(encoding="utf-8"))
            if not isinstance(term_data, dict):
                verification_errors.append(
                    {"file": TERMINAL_RESULT_FILE, "error": "Not a JSON object"}
                )
            else:
                if term_data.get("status") != "FAILED":
                    verification_errors.append(
                        {
                            "file": TERMINAL_RESULT_FILE,
                            "error": f"status='{term_data.get('status')}', expected 'FAILED'",
                        }
                    )
                if term_data.get("run_label") != run_label:
                    verification_errors.append(
                        {
                            "file": TERMINAL_RESULT_FILE,
                            "error": (
                                f"run_label='{term_data.get('run_label')}', expected '{run_label}'"
                            ),
                        }
                    )
                if term_data.get("candidate_git_sha") != candidate_sha:
                    verification_errors.append(
                        {"file": TERMINAL_RESULT_FILE, "error": "candidate_git_sha mismatch"}
                    )
                if term_data.get("error_phase") != error_phase:
                    verification_errors.append(
                        {
                            "file": TERMINAL_RESULT_FILE,
                            "error": (
                                f"error_phase='{term_data.get('error_phase')}', "
                                f"expected '{error_phase}'"
                            ),
                        }
                    )

        if not man_path.is_file():
            verification_errors.append(
                {"file": "manifest.json", "error": "File does not exist on disk"}
            )
        else:
            man_data = json.loads(man_path.read_text(encoding="utf-8"))
            if not isinstance(man_data, dict):
                verification_errors.append({"file": "manifest.json", "error": "Not a JSON object"})
            else:
                if man_data.get("status") != "FAILED":
                    verification_errors.append(
                        {
                            "file": "manifest.json",
                            "error": f"status='{man_data.get('status')}', expected 'FAILED'",
                        }
                    )
                if man_data.get("run_label") != run_label:
                    verification_errors.append(
                        {
                            "file": "manifest.json",
                            "error": (
                                f"run_label='{man_data.get('run_label')}', expected '{run_label}'"
                            ),
                        }
                    )
                if man_data.get("candidate_git_sha") != candidate_sha:
                    verification_errors.append(
                        {"file": "manifest.json", "error": "candidate_git_sha mismatch"}
                    )

                man_arts = man_data.get("artifacts")
                if not isinstance(man_arts, dict):
                    verification_errors.append(
                        {"file": "manifest.json", "error": "manifest.artifacts is not a dictionary"}
                    )
                else:
                    if TERMINAL_RESULT_FILE not in man_arts:
                        verification_errors.append(
                            {
                                "file": "manifest.json",
                                "error": f"Missing {TERMINAL_RESULT_FILE} in manifest artifacts",
                            }
                        )
                    # Check required artifacts by failure phase
                    if raw_response_content is not None and "raw-response.json" not in man_arts:
                        verification_errors.append(
                            {
                                "file": "manifest.json",
                                "error": "Missing raw-response.json for post-model failure",
                            }
                        )
                    if (
                        metadata is not None or (artifact_dir / "run-metadata.json").is_file()
                    ) and "run-metadata.json" not in man_arts:
                        verification_errors.append(
                            {
                                "file": "manifest.json",
                                "error": "Missing run-metadata.json in manifest artifacts",
                            }
                        )

                    # Verify actual bytes on disk against recorded SHA-256
                    for art_name, expected_sha in man_arts.items():
                        art_file = artifact_dir / art_name
                        if not art_file.is_file():
                            verification_errors.append(
                                {"file": art_name, "error": "Manifested artifact missing from disk"}
                            )
                        else:
                            try:
                                actual_sha = hashlib.sha256(art_file.read_bytes()).hexdigest()
                                if actual_sha != expected_sha:
                                    verification_errors.append(
                                        {
                                            "file": art_name,
                                            "error": (
                                                f"SHA mismatch: actual={actual_sha}, "
                                                f"manifest={expected_sha}"
                                            ),
                                        }
                                    )
                                else:
                                    verified_artifacts[art_name] = actual_sha
                            except Exception as read_err:
                                verification_errors.append(
                                    {
                                        "file": art_name,
                                        "error": f"Failed reading artifact bytes: {read_err}",
                                    }
                                )

        if not verification_errors:
            is_sealed = True
    except Exception as verif_err:
        verification_errors.append({"file": "verification_exception", "error": str(verif_err)})

    # 13. Transition reservation-state.json (H-08 Case A vs Case B)
    reservation_updated = False
    final_status = "FAILED" if is_sealed else "FAILED_UNSEALED"

    if is_sealed:
        # Evidence successfully sealed. Attempt to write FAILED to reservation-state.json.
        res_write_ok = False
        try:
            atomic_write_json(
                reservation_file,
                {
                    "status": "FAILED",
                    "error_phase": error_phase,
                    "error_type": error_type,
                    "error_message": error_message,
                    "run_label": run_label,
                    "gate": 3,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "candidate_git_sha": candidate_sha,
                    "authorization_commit_sha": authorization_commit_sha,
                    "git_commit_sha": authorized_sha,
                    "response_id": response_id,
                    "response_model_id": response_model_id,
                },
            )
            if reservation_file.is_file():
                check_res = json.loads(reservation_file.read_text(encoding="utf-8"))
                if check_res.get("status") == "FAILED":
                    res_write_ok = True
                    reservation_updated = True
        except Exception as res_err:
            failures.append({"file": RESERVATION_STATE_FILE, "error": str(res_err)})

        if not res_write_ok:
            # Case A: Evidence sealed, but writing reservation status FAILED failed!
            final_status = "COORDINATION_FAILURE"
            try:
                atomic_write_json(
                    artifact_dir / "coordination-failure.json",
                    {
                        "status": "SEALED_RESERVATION_UPDATE_FAILED",
                        "error_phase": error_phase,
                        "error_message": error_message,
                        "evidence_sealed": True,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "run_label": run_label,
                        "candidate_git_sha": candidate_sha,
                    },
                )
            except Exception:
                pass
    else:
        # Case B: Evidence failed to seal! Status must be FAILED_UNSEALED.
        final_status = "FAILED_UNSEALED"
        try:
            atomic_write_json(
                reservation_file,
                {
                    "status": "FAILED_UNSEALED",
                    "error_phase": error_phase,
                    "error_type": error_type,
                    "error_message": error_message,
                    "run_label": run_label,
                    "gate": 3,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "candidate_git_sha": candidate_sha,
                    "authorization_commit_sha": authorization_commit_sha,
                    "git_commit_sha": authorized_sha,
                    "verification_errors": verification_errors,
                },
            )
            if reservation_file.is_file():
                check_res = json.loads(reservation_file.read_text(encoding="utf-8"))
                if check_res.get("status") == "FAILED_UNSEALED":
                    reservation_updated = True
        except Exception as res_err:
            failures.append({"file": RESERVATION_STATE_FILE, "error": str(res_err)})

        try:
            atomic_write_json(
                artifact_dir / "coordination-failure.json",
                {
                    "status": "EVIDENCE_SEALING_FAILED",
                    "error_phase": error_phase,
                    "error_message": error_message,
                    "verification_errors": verification_errors,
                    "evidence_sealed": False,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "run_label": run_label,
                    "candidate_git_sha": candidate_sha,
                },
            )
        except Exception:
            pass

    return FailureFinalizationResult(
        sealed=is_sealed,
        reservation_updated=reservation_updated,
        status=final_status,
        error_phase=error_phase,
        verified_artifacts=verified_artifacts,
        failure_details=failures + verification_errors,
    )


def execute_internal_child(args: argparse.Namespace) -> int:
    """Child execution path: self-authorizing trust verification and execution."""
    if not is_isolated_python() or not is_bytecode_writing_disabled():
        print(
            "ERROR: Child execution must be invoked with isolated Python (-I) "
            "and no bytecode (-B).",
            file=sys.stderr,
        )
        return 1

    provenance_repo = Path(args.provenance_repo).resolve()
    snapshot_dir = Path(args.snapshot_dir).resolve()
    artifact_dir = Path(args.artifact_dir).resolve()
    auth_spec_path = Path(args.auth_spec).resolve()
    run_label = args.run_label
    if not run_label and auth_spec_path.is_file():
        try:
            with open(auth_spec_path) as f:
                s = json.load(f)
                run_label = s.get("run_label")
        except Exception:
            pass
    authorized_sha = args.authorized_git_sha
    authorization_commit_sha = getattr(args, "authorization_commit_sha", "") or authorized_sha
    candidate_sha = authorized_sha
    is_live = not (args.synthetic or args.dry_run)
    is_official_live = is_live and not args.allow_dirty
    reservation_file = artifact_dir / RESERVATION_STATE_FILE

    # Irrevocable attempt claim check: presence of claim forbids re-entry unconditionally (H-08)
    claim_file = artifact_dir / ATTEMPT_CLAIM_FILE
    if claim_file.exists():
        print(
            f"ERROR: Irrevocable attempt claim already exists: '{claim_file}'. "
            f"Run label '{run_label}' has already consumed its execution attempt. "
            "Refusing re-entry and prohibiting any model invocation.",
            file=sys.stderr,
        )
        return 1

    if is_official_live:
        canonical_out = (provenance_repo / "artifacts" / "gate-3" / run_label).resolve()
        if artifact_dir != canonical_out:
            print(
                f"ERROR: Official live child artifact directory '{artifact_dir}' does not "
                f"equal canonical destination '{canonical_out}'",
                file=sys.stderr,
            )
            return 1

        if not reservation_file.is_file():
            print(
                f"ERROR: Official live child requires existing reservation state file: "
                f"'{reservation_file}' not found.",
                file=sys.stderr,
            )
            return 1

        try:
            res_data = json.loads(reservation_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(
                f"ERROR: Official live child failed to parse reservation state file: {e}",
                file=sys.stderr,
            )
            return 1

        if not isinstance(res_data, dict):
            print(
                "ERROR: Official live child reservation state must be a JSON object.",
                file=sys.stderr,
            )
            return 1

        required_res_fields = {
            "status",
            "gate",
            "run_label",
            "candidate_git_sha",
            "authorization_commit_sha",
        }
        missing_res_fields = required_res_fields - set(res_data.keys())
        if missing_res_fields:
            print(
                f"ERROR: Official live child reservation state missing required fields: "
                f"{sorted(missing_res_fields)}",
                file=sys.stderr,
            )
            return 1

        if res_data.get("status") != "RESERVED":
            print(
                f"ERROR: Official live child reservation state status must be 'RESERVED', "
                f"got: '{res_data.get('status')}'",
                file=sys.stderr,
            )
            return 1

        if res_data.get("gate") != 3:
            print(
                f"ERROR: Official live child reservation state gate must be 3, "
                f"got: {res_data.get('gate')}",
                file=sys.stderr,
            )
            return 1

        if res_data.get("run_label") != run_label:
            print(
                f"ERROR: Official live child reservation state run_label mismatch: "
                f"reservation='{res_data.get('run_label')}', CLI='{run_label}'",
                file=sys.stderr,
            )
            return 1

        if res_data.get("candidate_git_sha") != authorized_sha:
            print(
                "ERROR: Official live child reservation state candidate_git_sha mismatch: "
                f"reservation='{res_data.get('candidate_git_sha')}', "
                f"CLI authorized='{authorized_sha}'",
                file=sys.stderr,
            )
            return 1

        if res_data.get("authorization_commit_sha") != authorization_commit_sha:
            print(
                "ERROR: Official live child reservation state authorization_commit_sha mismatch: "
                f"reservation='{res_data.get('authorization_commit_sha')}', "
                f"CLI='{authorization_commit_sha}'",
                file=sys.stderr,
            )
            return 1
    else:
        # Offline / backward-compatible test paths
        for state_path in (reservation_file, artifact_dir / "run-state.json"):
            if state_path.exists():
                try:
                    cur_state = json.loads(state_path.read_text(encoding="utf-8"))
                    st = cur_state.get("status")
                    if st in (
                        "MODEL_INVOCATION",
                        "POST_MODEL_RESPONSE",
                        "FINALIZING",
                        "FAILED",
                        "FAILED_UNSEALED",
                        "COORDINATION_FAILURE",
                        "COMPLETED",
                    ):
                        print(
                            f"ERROR: Irrevocable reservation error: Run label '{run_label}' "
                            f"already in state '{st}'. Refusing re-entry.",
                            file=sys.stderr,
                        )
                        return 1
                except Exception:
                    pass

    # Ensure controlled sys.path: snapshot_dir is at sys.path[0] and provenance_repo is excluded
    sys.path = [p for p in sys.path if Path(p).resolve() != provenance_repo.resolve()]
    if not sys.path or sys.path[0] != str(snapshot_dir):
        sys.path.insert(0, str(snapshot_dir))

    # Bootstrap verification of executing runner against committed runner
    try:
        verify_trusted_runner_bootstrap(provenance_repo, authorized_sha, Path(__file__))
    except Exception as e:
        if args.allow_dirty:
            print(
                f"WARNING: Runner bootstrap mismatch ignored under --allow-dirty: {e}",
                file=sys.stderr,
            )
        else:
            print(f"ERROR: Runner bootstrap verification failed: {e}", file=sys.stderr)
            return 1

    # Verify snapshot against Git objects
    try:
        verify_snapshot_against_git_objects(provenance_repo, authorized_sha, snapshot_dir)
    except Exception as e:
        if args.allow_dirty:
            print(
                f"WARNING: Snapshot git object verification ignored under --allow-dirty: {e}",
                file=sys.stderr,
            )
        else:
            print(f"ERROR: Snapshot byte verification failed: {e}", file=sys.stderr)
            return 1

    # Load and verify authorization spec
    try:
        if authorization_commit_sha and not args.allow_dirty:
            try:
                rel_spec_path = (
                    auth_spec_path.resolve().relative_to(provenance_repo.resolve()).as_posix()
                )
            except ValueError:
                rel_spec_path = auth_spec_path.as_posix()
            spec, spec_sha = load_authorization_spec_from_git(
                provenance_repo, authorization_commit_sha, rel_spec_path
            )
        else:
            spec, spec_sha = load_authorization_spec(auth_spec_path)
    except Exception as e:
        print(f"ERROR: Failed to load authorization spec: {e}", file=sys.stderr)
        return 1

    # Child independently verifies binding to committed authorization spec:
    if is_official_live:
        if spec.get("candidate_git_sha") != authorized_sha:
            print(
                f"ERROR: Authorization spec candidate_git_sha '{spec.get('candidate_git_sha')}' "
                f"does not match CLI authorized SHA '{authorized_sha}'",
                file=sys.stderr,
            )
            return 1
        if spec.get("run_label") != run_label:
            print(
                f"ERROR: Authorization spec run_label '{spec.get('run_label')}' "
                f"does not match CLI run_label '{run_label}'",
                file=sys.stderr,
            )
            return 1
        canonical_spec_out = (
            provenance_repo / "artifacts" / "gate-3" / spec["run_label"]
        ).resolve()
        if artifact_dir != canonical_spec_out:
            print(
                "ERROR: Artifact directory does not match spec run_label canonical destination",
                file=sys.stderr,
            )
            return 1
        if res_data["run_label"] != spec["run_label"]:
            print(
                f"ERROR: Reservation run_label '{res_data['run_label']}' does not match "
                f"spec run_label '{spec['run_label']}'",
                file=sys.stderr,
            )
            return 1
        if res_data["candidate_git_sha"] != spec["candidate_git_sha"]:
            print(
                f"ERROR: Reservation candidate_git_sha '{res_data['candidate_git_sha']}' "
                f"does not match spec candidate_git_sha '{spec['candidate_git_sha']}'",
                file=sys.stderr,
            )
            return 1

    # Validate authorization contract in child
    try:
        validate_authorization_contract(
            repo_root=provenance_repo,
            candidate_sha=candidate_sha,
            authorization_commit_sha=authorization_commit_sha,
            auth_spec_path=auth_spec_path,
            allow_dirty=args.allow_dirty,
            is_live=is_live,
        )
    except Exception as e:
        print(f"ERROR: Child authorization contract validation failed: {e}", file=sys.stderr)
        return 1

    golden_file = (
        Path(args.golden_path).resolve()
        if getattr(args, "golden_path", None)
        else (snapshot_dir / DEFAULT_GOLDEN_PATH)
    )
    if not golden_file.is_file():
        print(f"ERROR: Golden dataset file missing: {golden_file}", file=sys.stderr)
        return 1
    actual_golden_sha = hashlib.sha256(golden_file.read_bytes()).hexdigest()
    if actual_golden_sha.lower() != spec["golden_dataset_sha256"].lower():
        print(
            f"ERROR: Golden dataset SHA mismatch: actual={actual_golden_sha}, "
            f"expected={spec['golden_dataset_sha256']}",
            file=sys.stderr,
        )
        return 1

    # Version contract checks
    selected_spec_version = spec.get("spec_version") or spec.get("contract_version")
    if selected_spec_version not in SUPPORTED_CONTRACT_VERSIONS:
        print(
            f"ERROR: Unsupported contract version: '{selected_spec_version}'. "
            f"Must be one of {sorted(SUPPORTED_CONTRACT_VERSIONS)}",
            file=sys.stderr,
        )
        return 1

    golden_json = json.loads(golden_file.read_text(encoding="utf-8"))
    actual_golden_version = golden_json.get("version")
    if actual_golden_version != spec["golden_dataset_version"]:
        print(
            f"ERROR: Golden dataset version mismatch: actual={actual_golden_version}, "
            f"expected={spec['golden_dataset_version']}",
            file=sys.stderr,
        )
        return 1

    from agents.legacy_analyzer.schemas.system_assessment import (
        SCHEMA_VERSION as AGENT_SCHEMA_VERSION,
    )
    from agents.legacy_analyzer.schemas.system_assessment import (
        SystemAssessment,
    )

    if AGENT_SCHEMA_VERSION != spec["schema_version"]:
        print(
            f"ERROR: Schema version mismatch: actual={AGENT_SCHEMA_VERSION}, "
            f"expected={spec['schema_version']}",
            file=sys.stderr,
        )
        return 1

    from src.validation.evaluator_v3 import EVALUATOR_VERSION as RUNTIME_EVAL_VERSION

    if RUNTIME_EVAL_VERSION != spec["evaluator_version"]:
        print(
            f"ERROR: Evaluator version mismatch: actual={RUNTIME_EVAL_VERSION}, "
            f"expected={spec['evaluator_version']}",
            file=sys.stderr,
        )
        return 1

    from agents.legacy_analyzer.system_agent import PROMPT_VERSION as RUNTIME_PROMPT_VERSION

    if RUNTIME_PROMPT_VERSION != spec["prompt_version"]:
        print(
            f"ERROR: Prompt version mismatch: actual={RUNTIME_PROMPT_VERSION}, "
            f"expected={spec['prompt_version']}",
            file=sys.stderr,
        )
        return 1

    # Verify multi-source bundle integrity
    try:
        verify_bundle_integrity(snapshot_dir, spec)
    except Exception as e:
        print(f"ERROR: Bundle integrity verification failed: {e}", file=sys.stderr)
        return 1

    # Verify prompt and wire schema hashes
    try:
        verify_schema_and_prompt_hashes(snapshot_dir, spec)
    except Exception as e:
        print(f"ERROR: Schema / prompt verification failed: {e}", file=sys.stderr)
        return 1

    # Verify runtime environment against lockfile
    lock_file = snapshot_dir / "requirements-lock.txt"
    try:
        runtime_manifest, runtime_manifest_sha = verify_runtime_environment(lock_file, spec=spec)
    except Exception as e:
        print(f"ERROR: Runtime environment verification failed: {e}", file=sys.stderr)
        return 1

    # Check controlled cwd and sys.path
    if Path.cwd().resolve() != snapshot_dir:
        print(
            f"ERROR: Child execution cwd must be snapshot directory. Got: {Path.cwd()}",
            file=sys.stderr,
        )
        return 1

    # Bundle parsing and fail-closed preflight check
    try:
        from src.cobol.multi_source_reader import read_system_bundle
        from src.cobol.system_cobol_parser import SystemCobolParser
    except Exception as e:
        print(f"ERROR: Application parser import failed: {e}", file=sys.stderr)
        return 1

    bundle = read_system_bundle(snapshot_dir)
    parser = SystemCobolParser(bundle)
    coverage_cert = parser.get_parser_coverage_certificate()
    if coverage_cert.unsupported_relevant_count > 0:
        print(
            f"ERROR: Fail-closed parser check failed: {coverage_cert.unsupported_relevant_count} "
            f"unsupported relevant statement(s) detected. Execution strictly aborted.",
            file=sys.stderr,
        )
        atomic_write_json(
            reservation_file,
            {
                "status": "FAILED",
                "error_phase": "FAIL_CLOSED_PARSER_CHECK",
                "error_message": (
                    f"Unsupported relevant statements: {coverage_cert.unsupported_relevant_count}"
                ),
                "timestamp": datetime.now(UTC).isoformat(),
                "candidate_git_sha": candidate_sha,
                "authorization_commit_sha": authorization_commit_sha,
                "git_commit_sha": authorized_sha,
            },
        )
        return 1

    # Host <-> Golden REQUIRED_EXHAUSTIVE preflight parity check
    try:
        from src.cobol.system_support_index import SystemSupportIndex
        from src.validation.evaluator_v3 import SystemEvaluatorV3, load_golden_assessment

        facts = parser.get_supported_facts()
        support_index = SystemSupportIndex(
            facts, bundle, file_status_certificate=parser.file_status_certificate
        )
        evaluator = SystemEvaluatorV3(support_index, golden_dataset_path=golden_file)
        host_exhaustive = evaluator.extract_host_exhaustive_obligations()
        golden_assessment = load_golden_assessment(golden_file)
        golden_exhaustive = evaluator.extract_exhaustive_obligations_from_assessment(
            golden_assessment
        )
        if host_exhaustive != golden_exhaustive:
            diff_missing = host_exhaustive - golden_exhaustive
            diff_extra = golden_exhaustive - host_exhaustive
            err_msg = (
                f"REQUIRED_EXHAUSTIVE preflight parity check failed: "
                f"host_count={len(host_exhaustive)}, golden_count={len(golden_exhaustive)}, "
                f"host_missing_in_golden={len(diff_missing)}, "
                f"golden_missing_in_host={len(diff_extra)}"
            )
            print(f"ERROR: {err_msg}", file=sys.stderr)
            atomic_write_json(
                reservation_file,
                {
                    "status": "FAILED",
                    "error_phase": "REQUIRED_EXHAUSTIVE_PREFLIGHT_DRIFT",
                    "error_message": err_msg,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "candidate_git_sha": candidate_sha,
                    "authorization_commit_sha": authorization_commit_sha,
                    "git_commit_sha": authorized_sha,
                },
            )
            return 1
    except Exception as e:
        print(f"ERROR: REQUIRED_EXHAUSTIVE preflight verification failed: {e}", file=sys.stderr)
        atomic_write_json(
            reservation_file,
            {
                "status": "FAILED",
                "error_phase": "REQUIRED_EXHAUSTIVE_PREFLIGHT_DRIFT",
                "error_message": str(e),
                "timestamp": datetime.now(UTC).isoformat(),
                "candidate_git_sha": candidate_sha,
                "authorization_commit_sha": authorization_commit_sha,
                "git_commit_sha": authorized_sha,
            },
        )
        return 1

    # If dry-run, report success without live call or credentials
    if args.dry_run:
        print("[OK] Dry-run preflight verification complete. All authorization checks PASSED.")
        atomic_write_json(
            reservation_file,
            {
                "status": "DRY_RUN_PASSED",
                "run_label": run_label,
                "gate": 3,
                "timestamp": datetime.now(UTC).isoformat(),
                "git_commit_sha": authorized_sha,
                "bundle_sha256": spec["bundle_sha256"],
                "runtime_manifest_sha256": runtime_manifest_sha,
                "auth_spec_sha256": spec_sha,
            },
        )
        return 0

    # Import application modules strictly from snapshot
    try:
        from agents.legacy_analyzer.system_agent import SystemAnalyzerAgent
        from src.cobol.system_support_index import SystemSupportIndex
        from src.validation.evaluator_v3 import SystemEvaluatorV3, load_golden_assessment
    except Exception as e:
        print(f"ERROR: Application module import failed: {e}", file=sys.stderr)
        return 1

    assessment: SystemAssessment | None = None
    metadata_dict: dict[str, Any] | None = None
    metadata: Any = None

    if args.synthetic:
        if not golden_file.is_file():
            print(f"ERROR: Golden dataset not found: {golden_file}", file=sys.stderr)
            return 1
        assessment = load_golden_assessment(golden_file)

        raw_response_content: Any = {
            "mock": True,
            "source": "synthetic-golden-v3",
            "model": "synthetic-golden-v3",
        }
        metadata_dict = {
            "gate": "3",
            "run_label": run_label,
            "timestamp": datetime.now(UTC).isoformat(),
            "model": "synthetic-golden-v3",
            "requested_model": spec["requested_model"],
            "response_model_id": spec["requested_model"],
            "git_commit_sha": authorized_sha,
            "schema_version": spec["schema_version"],
            "prompt_version": spec["prompt_version"],
            "evaluator_version": spec["evaluator_version"],
            "elapsed_seconds": 0.0,
            "schema_valid": True,
            "foundry_project_fingerprint": spec["foundry_project_fingerprint"],
            "auth_spec_sha256": spec_sha,
            "bundle_sha256": spec["bundle_sha256"],
            "runtime_manifest_sha256": runtime_manifest_sha,
            "candidate_git_sha": candidate_sha,
            "authorization_commit_sha": authorization_commit_sha,
        }
    else:
        # Live path: preflight verification before obtaining client or persisting MODEL_INVOCATION
        from agents.legacy_analyzer.config import (
            compute_foundry_project_fingerprint,
            load_config,
        )

        try:
            cfg = load_config()
        except Exception as e:
            print(f"ERROR: Failed to load config: {e}", file=sys.stderr)
            return 1

        if cfg.foundry_model != spec["requested_model"]:
            print(
                f"ERROR: Model mismatch before invocation: "
                f"config.foundry_model='{cfg.foundry_model}' "
                f"!= spec.requested_model='{spec['requested_model']}'",
                file=sys.stderr,
            )
            return 1

        actual_fp = compute_foundry_project_fingerprint(cfg.foundry_project_endpoint)
        if actual_fp != spec["foundry_project_fingerprint"]:
            print(
                f"ERROR: Project fingerprint mismatch before invocation: actual='{actual_fp}' "
                f"!= spec='{spec['foundry_project_fingerprint']}'",
                file=sys.stderr,
            )
            return 1

        if spec.get("reasoning_effort") != "low":
            print(
                f"ERROR: Unexpected reasoning effort: {spec.get('reasoning_effort')}",
                file=sys.stderr,
            )
            return 1

        if spec.get("openai_client_max_retries") != 0 or spec.get("maximum_model_attempts") != 1:
            print(
                "ERROR: Attempt policy violation: max retries must be 0 and max attempts must be 1",
                file=sys.stderr,
            )
            return 1

        # Attempt claim acquisition: existence-based and irrevocable
        try:
            acquire_atomic_attempt_claim(
                artifact_dir=artifact_dir,
                gate=3,
                run_label=run_label,
                candidate_sha=candidate_sha,
                authorization_commit_sha=authorization_commit_sha,
            )
        except AttemptClaimCollisionError as collision_err:
            print(f"ERROR: Irrevocable attempt claim collision: {collision_err}", file=sys.stderr)
            # Losing child exits before provider access.
            # Losing child MUST NOT transition the shared reservation to FAILED.
            return 1
        except Exception as claim_err:
            print(f"ERROR: Attempt claim acquisition failed: {claim_err}", file=sys.stderr)
            # If creation succeeded but writing failed, attempt claim file exists;
            # attempt remains permanently consumed. Do NOT invoke provider.
            return 1

        # Preflight and claim passed: persist MODEL_INVOCATION state
        try:
            atomic_write_json(
                reservation_file,
                {
                    "status": "MODEL_INVOCATION",
                    "run_label": run_label,
                    "gate": 3,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "candidate_git_sha": candidate_sha,
                    "authorization_commit_sha": authorization_commit_sha,
                    "git_commit_sha": authorized_sha,
                    "requested_model": spec["requested_model"],
                    "foundry_project_fingerprint": spec["foundry_project_fingerprint"],
                },
            )
        except Exception as res_err:
            print(
                f"ERROR: Failed to update reservation to MODEL_INVOCATION after claim: {res_err}",
                file=sys.stderr,
            )
            finalize_post_model_failure(
                artifact_dir=artifact_dir,
                reservation_file=reservation_file,
                error_phase="MODEL_INVOCATION_RESERVATION",
                error=res_err,
                spec=spec,
                candidate_sha=candidate_sha,
                authorization_commit_sha=authorization_commit_sha,
                authorized_sha=authorized_sha,
                run_label=run_label,
                bundle=bundle,
                parser=parser,
                runtime_manifest=runtime_manifest,
                metadata=None,
                assessment=None,
                raw_response_content=None,
                spec_sha=spec_sha,
                runtime_manifest_sha=runtime_manifest_sha,
            )
            return 1

        agent = SystemAnalyzerAgent(config=cfg, reasoning_effort=spec["reasoning_effort"])

        # Call invoke_raw(): returns provider response BEFORE any parsing
        try:
            response, metadata, raw_response_text = agent.invoke_raw(
                bundle=bundle,
                run_label=run_label,
                repo_root=snapshot_dir,
                git_commit_sha=authorized_sha,
            )
        except Exception as e:
            print(f"ERROR: Raw model invocation failed: {e}", file=sys.stderr)
            finalize_post_model_failure(
                artifact_dir=artifact_dir,
                reservation_file=reservation_file,
                error_phase="MODEL_INVOCATION",
                error=e,
                spec=spec,
                candidate_sha=candidate_sha,
                authorization_commit_sha=authorization_commit_sha,
                authorized_sha=authorized_sha,
                run_label=run_label,
                bundle=bundle,
                parser=parser,
                runtime_manifest=runtime_manifest,
                metadata=None,
                assessment=None,
                raw_response_content=None,
                spec_sha=spec_sha,
                runtime_manifest_sha=runtime_manifest_sha,
            )
            return 1

        raw_response_content = raw_response_text
        try:
            # IMMEDIATELY serialize and durably persist raw provider response on disk
            try:
                raw_obj = json.loads(raw_response_text)
                atomic_write_json(artifact_dir / "raw-response.json", raw_obj)
            except Exception:
                (artifact_dir / "raw-response.json").write_text(raw_response_text, encoding="utf-8")

            metadata_dict = metadata.to_dict()
            metadata_dict["auth_spec_sha256"] = spec_sha
            metadata_dict["bundle_sha256"] = spec["bundle_sha256"]
            metadata_dict["runtime_manifest_sha256"] = runtime_manifest_sha
            metadata_dict["candidate_git_sha"] = candidate_sha
            metadata_dict["authorization_commit_sha"] = authorization_commit_sha
            atomic_write_json(artifact_dir / "run-metadata.json", metadata_dict)

            # Transition to POST_MODEL_RESPONSE
            atomic_write_json(
                reservation_file,
                {
                    "status": "POST_MODEL_RESPONSE",
                    "run_label": run_label,
                    "gate": 3,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "candidate_git_sha": candidate_sha,
                    "authorization_commit_sha": authorization_commit_sha,
                    "git_commit_sha": authorized_sha,
                    "response_id": metadata.response_id,
                    "response_model_id": metadata.response_model_id,
                },
            )

            # Post-call validation: status, refusal, exact model equality, Pydantic parsing
            assessment = agent.validate_and_parse_response(
                response=response,
                metadata=metadata,
                requested_model=spec["requested_model"],
            )
            metadata_dict = metadata.to_dict()
            metadata_dict["auth_spec_sha256"] = spec_sha
            metadata_dict["bundle_sha256"] = spec["bundle_sha256"]
            metadata_dict["runtime_manifest_sha256"] = runtime_manifest_sha
            metadata_dict["candidate_git_sha"] = candidate_sha
            metadata_dict["authorization_commit_sha"] = authorization_commit_sha
        except Exception as e:
            print(f"ERROR: Post-invocation response processing failed: {e}", file=sys.stderr)
            err_str = str(e)
            err_phase = "RESPONSE_PROCESSING"
            if "status=" in err_str:
                err_phase = "RESPONSE_STATUS"
            elif (
                "refusal" in err_str.lower()
                or "refused" in err_str.lower()
                or type(e).__name__ == "ResponseRefusedError"
            ):
                err_phase = "RESPONSE_REFUSAL"
            elif "does not match requested model" in err_str:
                err_phase = "RESPONSE_MODEL_MISMATCH"
            elif (
                "validation error" in err_str.lower()
                or "did not contain structured output" in err_str
            ):
                err_phase = "MALFORMED_OUTPUT"

            finalize_post_model_failure(
                artifact_dir=artifact_dir,
                reservation_file=reservation_file,
                error_phase=err_phase,
                error=e,
                spec=spec,
                candidate_sha=candidate_sha,
                authorization_commit_sha=authorization_commit_sha,
                authorized_sha=authorized_sha,
                run_label=run_label,
                bundle=bundle,
                parser=parser,
                runtime_manifest=runtime_manifest,
                metadata=metadata,
                assessment=assessment,
                raw_response_content=raw_response_content,
            )
            return 1

    # Deterministic evaluation using SystemEvaluatorV3
    assert assessment is not None
    eval_result = None
    predictions = None
    try:
        parser = SystemCobolParser(bundle)
        facts = parser.get_supported_facts()
        index = SystemSupportIndex(
            facts, bundle, file_status_certificate=parser.file_status_certificate
        )
        evaluator = SystemEvaluatorV3(index, golden_dataset_path=golden_file)
        eval_result, predictions = evaluator.evaluate_assessment(assessment)

        # Transition to FINALIZING
        atomic_write_json(
            reservation_file,
            {
                "status": "FINALIZING",
                "run_label": run_label,
                "gate": 3,
                "timestamp": datetime.now(UTC).isoformat(),
                "candidate_git_sha": candidate_sha,
                "authorization_commit_sha": authorization_commit_sha,
                "git_commit_sha": authorized_sha,
            },
        )

        # Complete immutable artifact preservation (13 distinct artifacts + manifest.json)
        from agents.legacy_analyzer.schemas.system_export import get_system_openai_wire_schema
        from agents.legacy_analyzer.system_agent import load_system_v3_prompt

        # 1. authorization-spec.json
        atomic_write_json(artifact_dir / "authorization-spec.json", spec)

        # 2. production-prompt.md
        prompt_text = load_system_v3_prompt()
        (artifact_dir / "production-prompt.md").write_text(prompt_text, encoding="utf-8")

        # 3. wire-schema.json
        wire_schema = get_system_openai_wire_schema()
        atomic_write_json(artifact_dir / "wire-schema.json", wire_schema)

        # 4. source-manifest.json
        source_manifest = {
            rel_path: {
                "size": len(f.raw_content.encode("utf-8")),
                "lines": f.line_count,
                "sha256": f.sha256,
            }
            for rel_path, f in bundle.files.items()
        }
        atomic_write_json(artifact_dir / "source-manifest.json", source_manifest)

        # 5. canonical-input-bundle.txt
        (artifact_dir / "canonical-input-bundle.txt").write_text(
            bundle.formatted_prompt_payload, encoding="utf-8"
        )

        # 6. parser-coverage-certificate.json
        coverage_cert = parser.get_parser_coverage_certificate()
        atomic_write_json(
            artifact_dir / "parser-coverage-certificate.json", coverage_cert.to_dict()
        )

        # 7. runtime-manifest.json
        atomic_write_json(artifact_dir / "runtime-manifest.json", runtime_manifest)

        # 8. raw-response.json
        if isinstance(raw_response_content, (dict, list)):
            atomic_write_json(artifact_dir / "raw-response.json", raw_response_content)
        else:
            try:
                parsed_raw = json.loads(raw_response_content)
                atomic_write_json(artifact_dir / "raw-response.json", parsed_raw)
            except Exception:
                (artifact_dir / "raw-response.json").write_text(
                    str(raw_response_content), encoding="utf-8"
                )

        # 9. model-assessment.json
        atomic_write_json(artifact_dir / "model-assessment.json", assessment.model_dump())

        # 10. enriched-assessment.json
        atomic_write_json(artifact_dir / "enriched-assessment.json", assessment.model_dump())

        # 11. evaluation.json
        eval_dict = {
            "metric_summary": eval_result.to_dict(),
            "predictions": [p.to_dict() for p in predictions],
        }
        atomic_write_json(artifact_dir / "evaluation.json", eval_dict)

        # 12. run-metadata.json
        atomic_write_json(artifact_dir / "run-metadata.json", metadata_dict)

        # 13. terminal-result.json (immutable scientific outcome, written before manifest)
        terminal_result = {
            "gate": 3,
            "run_label": run_label,
            "status": "COMPLETED",
            "gate_3_pass": eval_result.gate_3_pass,
            "timestamp": datetime.now(UTC).isoformat(),
            "candidate_git_sha": candidate_sha,
            "authorization_commit_sha": authorization_commit_sha,
            "git_commit_sha": authorized_sha,
            "precision": eval_result.precision,
            "recall": eval_result.recall,
            "matched_expected_count": eval_result.matched_expected_count,
            "expected_fact_count": eval_result.expected_fact_count,
            "duplicate_count": eval_result.duplicate_prediction_count,
            "supported_unique_count": eval_result.supported_predicted_count,
            "unsupported_count": eval_result.unsupported_predicted_count,
        }
        atomic_write_json(artifact_dir / TERMINAL_RESULT_FILE, terminal_result)

        # 14. manifest.json (written LAST; maps filename -> SHA256 of all 13 immutable artifacts)
        excluded_from_manifest = {
            "manifest.json",
            RESERVATION_STATE_FILE,
            "run-state.json",
            ATTEMPT_CLAIM_FILE,
            "coordination-failure.json",
        }
        manifest_shas: dict[str, str] = {}
        for fname in sorted(os.listdir(artifact_dir)):
            if fname in excluded_from_manifest or fname.endswith(".tmp") or ".tmp." in fname:
                continue
            fpath = artifact_dir / fname
            if fpath.is_file():
                manifest_shas[fname] = hashlib.sha256(fpath.read_bytes()).hexdigest()

        manifest = {
            "gate": 3,
            "run_label": run_label,
            "timestamp": datetime.now(UTC).isoformat(),
            "candidate_git_sha": candidate_sha,
            "authorization_commit_sha": authorization_commit_sha,
            "git_commit_sha": authorized_sha,
            "gate_3_pass": eval_result.gate_3_pass,
            "precision": eval_result.precision,
            "recall": eval_result.recall,
            "matched_expected_count": eval_result.matched_expected_count,
            "expected_fact_count": eval_result.expected_fact_count,
            "artifacts": manifest_shas,
        }
        atomic_write_json(artifact_dir / "manifest.json", manifest)
        sealed = True
    except Exception as e:
        err_phase = "EVALUATOR" if eval_result is None else "ARTIFACT_GENERATION"
        print(f"ERROR: Pre-seal execution failed ({err_phase}): {e}", file=sys.stderr)
        finalize_post_model_failure(
            artifact_dir=artifact_dir,
            reservation_file=reservation_file,
            error_phase=err_phase,
            error=e,
            spec=spec,
            candidate_sha=candidate_sha,
            authorization_commit_sha=authorization_commit_sha,
            authorized_sha=authorized_sha,
            run_label=run_label,
            bundle=bundle,
            parser=parser,
            runtime_manifest=runtime_manifest,
            metadata=metadata_dict if metadata_dict is not None else metadata,
            assessment=assessment,
            raw_response_content=raw_response_content,
            evaluation_result=eval_result,
            evaluated_predictions=predictions,
        )
        return 1

    # Post-sealing mutable coordination transition
    # sealed == True: Never call finalize_post_model_failure() after manifest is published.
    assert sealed, "Manifest must be sealed before post-seal coordination."
    try:
        atomic_write_json(
            reservation_file,
            {
                "status": "COMPLETED",
                "gate_3_pass": eval_result.gate_3_pass,
                "run_label": run_label,
                "gate": 3,
                "timestamp": datetime.now(UTC).isoformat(),
                "candidate_git_sha": candidate_sha,
                "authorization_commit_sha": authorization_commit_sha,
                "git_commit_sha": authorized_sha,
            },
        )
    except Exception as coord_err:
        print(
            f"ERROR: Post-seal coordination state update failed: {coord_err}",
            file=sys.stderr,
        )
        try:
            atomic_write_json(
                artifact_dir / "coordination-failure.json",
                {
                    "error": str(coord_err),
                    "timestamp": datetime.now(UTC).isoformat(),
                    "status": "POST_SEAL_COORDINATION_FAILURE",
                },
            )
        except Exception:
            pass
        return 1

    print(
        f"Gate 3 evaluation complete. Pass: {eval_result.gate_3_pass} "
        f"({eval_result.matched_expected_count}/{eval_result.expected_fact_count})"
    )
    return 0 if eval_result.gate_3_pass else 1


def main() -> None:
    """CLI entrypoint for Gate 3 runner."""
    parser = argparse.ArgumentParser(description="Gate 3 Multi-File System Analysis Runner")
    parser.add_argument(
        "--run-label",
        default=None,
        help="Identifier for analysis run (defaults to run_label in authorization spec)",
    )
    parser.add_argument(
        "--auth-spec", default=DEFAULT_AUTH_SPEC_PATH, help="Path to authorization specification"
    )
    parser.add_argument("--output-dir", default=None, help="Custom output directory for artifacts")
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Execute offline synthetic evaluation using golden dataset",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform preflight verification only without execution",
    )
    parser.add_argument(
        "--allow-dirty", action="store_true", help="Allow uncommitted changes (testing only)"
    )
    parser.add_argument("--golden-path", default=None, help="Path to expected golden dataset")

    # Internal child arguments
    parser.add_argument(
        "--internal-child", action="store_true", help="Internal child execution mode"
    )
    parser.add_argument("--provenance-repo", default=None, help="Path to provenance repository")
    parser.add_argument("--snapshot-dir", default=None, help="Path to verified snapshot directory")
    parser.add_argument(
        "--artifact-dir", default=None, help="Path to destination artifact directory"
    )
    parser.add_argument("--authorized-git-sha", default=None, help="Authorized Git commit SHA")
    parser.add_argument(
        "--authorization-commit-sha", default=None, help="Authorization commit Git SHA"
    )

    args = parser.parse_args()

    if args.internal_child:
        if (
            not args.provenance_repo
            or not args.snapshot_dir
            or not args.artifact_dir
            or not args.authorized_git_sha
        ):
            print("ERROR: Missing required internal-child arguments.", file=sys.stderr)
            sys.exit(1)
        sys.exit(execute_internal_child(args))
    else:
        auth_spec = Path(args.auth_spec)
        if not auth_spec.is_absolute():
            auth_spec = REPO_ROOT / auth_spec
        out_dir = Path(args.output_dir) if args.output_dir else None
        golden = Path(args.golden_path) if args.golden_path else None

        exit_code = execute_gate_3(
            repo_root=REPO_ROOT,
            auth_spec_path=auth_spec,
            output_dir=out_dir,
            run_label=args.run_label,
            synthetic=args.synthetic,
            dry_run=args.dry_run,
            allow_dirty=args.allow_dirty,
            golden_path=golden,
        )
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
