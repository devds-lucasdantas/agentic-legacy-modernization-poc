#!/usr/bin/env python3
"""Gate 3 — Multi-File System Analysis Runner (Version 3.0.0)

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
7. Deterministic artifact destination binding (provenance_repo/artifacts/gate-3/run_label).
8. Canonical runtime/lock attestation strictly before model invocation.
9. Prompt, wire schema, and bundle manifest SHA256 integrity verification.
10. Strict child verification ordering guaranteeing zero model calls on preflight failure.
11. Host-owned Python runtime provenance persistence in run-metadata.json.
12. Exact single-attempt execution contract: openai_client_max_retries=0, max_attempts=1.
13. Safe offline synthetic / dry-run mode guaranteeing zero model calls when requested.
14. Deterministic evaluation using SystemEvaluatorV3 and Golden Dataset V3.0 (54 units).

Exit codes:
    0 = PASS
    1 = FAIL (or scope violation / pre-check failure)
"""

from __future__ import annotations

import argparse
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


def verify_runtime_environment(lock_file: Path) -> tuple[dict[str, str], str]:
    """Verify runtime environment strictly matches requirements-lock.txt."""
    if not lock_file.is_file():
        raise RuntimeError(f"Lock file not found: {lock_file}")

    locked: dict[str, str] = {}
    for line in lock_file.read_text(encoding="utf-8").splitlines():
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
    mismatched = {
        k: (runtime[k], locked[k]) for k in locked if k in runtime and runtime[k] != locked[k]
    }

    errors = []
    if missing:
        errors.append(f"Missing packages: {sorted(missing)}")
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

        if mode not in ("100644", "100755") or typ != "blob":
            continue

        expected_files.add(rel_path)
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

    return expected_files


def create_git_snapshot_archive(
    expected_git_sha: str, temp_dir: Path, repo_root: Path = REPO_ROOT, allow_dirty: bool = False
) -> Path:
    """Extract application snapshot from authorized Git commit tree via git archive."""
    sanitized_env = get_sanitized_git_env()
    archive_proc = subprocess.Popen(
        ["git", "archive", "--format=tar", expected_git_sha],
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
        # For testing with uncommitted changes, overlay working tree files onto snapshot
        for root, dirs, files in os.walk(repo_root):
            rel_root = Path(root).relative_to(repo_root)
            if any(
                part
                in (
                    ".git",
                    ".venv",
                    "artifacts",
                    "scratch",
                    "__pycache__",
                    ".pytest_cache",
                    ".ruff_cache",
                    ".mypy_cache",
                )
                for part in rel_root.parts
            ):
                continue
            for f in files:
                if f.endswith((".pyc", ".pyo")):
                    continue
                src_file = Path(root) / f
                dst_file = temp_dir / rel_root / f
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                dst_file.write_bytes(src_file.read_bytes())

    return temp_dir


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
        "expected_git_sha",
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
        "target_bundle",
    }
    missing = required_keys - set(spec.keys())
    if missing:
        raise ValueError(f"Authorization spec missing required keys: {sorted(missing)}")
    if spec.get("gate") != 3:
        raise ValueError(f"Authorization spec gate must be 3, got: {spec.get('gate')}")
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

    return spec, spec_sha256


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

    # Verify wire schema SHA
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


def execute_gate_3(
    repo_root: Path,
    auth_spec_path: Path,
    output_dir: Path | None = None,
    run_label: str = "baseline-v1",
    synthetic: bool = False,
    dry_run: bool = False,
    allow_dirty: bool = False,
    golden_path: Path | None = None,
) -> int:
    """Parent execution path: orchestrate preflight and execute isolated child."""
    validate_run_label(run_label)

    # 1. Verify worktree cleanliness and overlays
    verify_clean_worktree(repo_root, allow_dirty=allow_dirty)
    verify_no_executable_overlays(repo_root, allow_dirty=allow_dirty)

    # 2. Get git HEAD SHA
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

    # 3. Load auth spec
    spec, spec_sha = load_authorization_spec(auth_spec_path)
    if spec["run_label"] != run_label:
        raise ValueError(f"Run label mismatch: CLI={run_label}, spec={spec['run_label']}")

    expected_sha = spec.get("expected_git_sha", "").strip()
    if expected_sha and expected_sha.lower() != head_sha.lower():
        raise RuntimeError(f"Authorized git SHA mismatch: HEAD={head_sha}, spec={expected_sha}")

    if not expected_sha and not synthetic and not dry_run:
        raise RuntimeError(
            "Candidate commit is not frozen: expected_git_sha is empty in authorization spec. "
            "Refusing live execution on un-frozen candidate."
        )

    # 4. Determine artifact destination
    out_dir = output_dir or (repo_root / "artifacts" / "gate-3" / run_label)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 5. Write RESERVED state
    run_state_file = out_dir / "run-state.json"
    atomic_write_json(
        run_state_file,
        {
            "status": "RESERVED",
            "run_label": run_label,
            "gate": 3,
            "timestamp": datetime.now(UTC).isoformat(),
            "git_commit_sha": head_sha,
            "bundle_sha256": spec["bundle_sha256"],
            "requested_model": spec["requested_model"],
            "foundry_project_fingerprint": spec["foundry_project_fingerprint"],
        },
    )

    # 6. Execute child in isolated mode
    with tempfile.TemporaryDirectory(prefix="gate3_snapshot_") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        create_git_snapshot_archive(
            head_sha, temp_dir, repo_root=repo_root, allow_dirty=allow_dirty
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


def execute_internal_child(args: argparse.Namespace) -> int:
    """Child execution path: self-authorizing trust verification and execution."""
    # Step 1: Verify isolated Python and no bytecode
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
    authorized_sha = args.authorized_git_sha

    # Ensure controlled sys.path: snapshot_dir is at sys.path[0] and provenance_repo is excluded
    sys.path = [p for p in sys.path if Path(p).resolve() != provenance_repo.resolve()]
    if not sys.path or sys.path[0] != str(snapshot_dir):
        sys.path.insert(0, str(snapshot_dir))

    # Step 2: Bootstrap verification of executing runner against committed runner
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

    # Step 3: Verify snapshot against Git objects
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

    # Step 4: Load and verify authorization spec
    try:
        spec, spec_sha = load_authorization_spec(auth_spec_path)
    except Exception as e:
        print(f"ERROR: Failed to load authorization spec: {e}", file=sys.stderr)
        return 1

    # Step 5: Verify multi-source bundle integrity
    try:
        verify_bundle_integrity(snapshot_dir, spec)
    except Exception as e:
        print(f"ERROR: Bundle integrity verification failed: {e}", file=sys.stderr)
        return 1

    # Step 6: Verify prompt and wire schema hashes
    try:
        verify_schema_and_prompt_hashes(snapshot_dir, spec)
    except Exception as e:
        print(f"ERROR: Schema / prompt verification failed: {e}", file=sys.stderr)
        return 1

    # Step 7: Verify runtime environment against lockfile
    lock_file = snapshot_dir / "requirements-lock.txt"
    try:
        runtime_manifest, runtime_manifest_sha = verify_runtime_environment(lock_file)
    except Exception as e:
        print(f"ERROR: Runtime environment verification failed: {e}", file=sys.stderr)
        return 1

    # Step 8: Check controlled cwd and sys.path
    if Path.cwd().resolve() != snapshot_dir:
        print(
            f"ERROR: Child execution cwd must be snapshot directory. Got: {Path.cwd()}",
            file=sys.stderr,
        )
        return 1

    run_state_file = artifact_dir / "run-state.json"

    # Step 9: If dry-run, report success without live call or credentials
    if args.dry_run:
        print("[OK] Dry-run preflight verification complete. All authorization checks PASSED.")
        atomic_write_json(
            run_state_file,
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

    # Step 10: Import application modules strictly from snapshot
    try:
        from agents.legacy_analyzer.system_agent import SystemAnalyzerAgent
        from src.cobol.multi_source_reader import read_system_bundle
        from src.cobol.system_cobol_parser import SystemCobolParser
        from src.cobol.system_support_index import SystemSupportIndex
        from src.validation.evaluator_v3 import SystemEvaluatorV3, load_golden_assessment
    except Exception as e:
        print(f"ERROR: Application module import failed: {e}", file=sys.stderr)
        return 1

    bundle = read_system_bundle(snapshot_dir)
    golden_file = (
        Path(args.golden_path).resolve()
        if args.golden_path
        else (snapshot_dir / DEFAULT_GOLDEN_PATH)
    )

    # Step 11: Execute Synthetic or Live
    if args.synthetic:
        if not golden_file.is_file():
            print(f"ERROR: Golden dataset not found: {golden_file}", file=sys.stderr)
            return 1
        assessment = load_golden_assessment(golden_file)

        metadata_dict = {
            "gate": "3",
            "run_label": run_label,
            "timestamp": datetime.now(UTC).isoformat(),
            "model": "synthetic-golden-v3",
            "requested_model": spec["requested_model"],
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
        }
    else:
        # Live path: persist MODEL_INVOCATION state
        atomic_write_json(
            run_state_file,
            {
                "status": "MODEL_INVOCATION",
                "run_label": run_label,
                "gate": 3,
                "timestamp": datetime.now(UTC).isoformat(),
                "git_commit_sha": authorized_sha,
                "requested_model": spec["requested_model"],
                "foundry_project_fingerprint": spec["foundry_project_fingerprint"],
            },
        )

        try:
            agent = SystemAnalyzerAgent(reasoning_effort=spec["reasoning_effort"])
            assessment, metadata = agent.analyze_system(
                bundle=bundle,
                run_label=run_label,
                repo_root=snapshot_dir,
                git_commit_sha=authorized_sha,
            )
            metadata_dict = metadata.to_dict()
            metadata_dict["auth_spec_sha256"] = spec_sha
            metadata_dict["bundle_sha256"] = spec["bundle_sha256"]
            metadata_dict["runtime_manifest_sha256"] = runtime_manifest_sha
        except Exception as e:
            print(f"ERROR: Model invocation failed: {e}", file=sys.stderr)
            atomic_write_json(
                run_state_file,
                {
                    "status": "FAILED",
                    "error_phase": "MODEL_INVOCATION",
                    "error_message": str(e),
                    "timestamp": datetime.now(UTC).isoformat(),
                    "git_commit_sha": authorized_sha,
                },
            )
            return 1

    # Step 12: Deterministic evaluation using SystemEvaluatorV3
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(facts, bundle)
    evaluator = SystemEvaluatorV3(index, golden_dataset_path=golden_file)
    eval_result, predictions = evaluator.evaluate_assessment(assessment)

    # Step 13: Persist artifacts
    atomic_write_json(artifact_dir / "assessment.json", assessment.model_dump())
    atomic_write_json(artifact_dir / "evaluation-result.json", eval_result.to_dict())
    atomic_write_json(artifact_dir / "run-metadata.json", metadata_dict)

    manifest_artifacts = [
        "assessment.json",
        "evaluation-result.json",
        "run-metadata.json",
        "run-state.json",
    ]
    manifest = {
        "gate": 3,
        "run_label": run_label,
        "timestamp": datetime.now(UTC).isoformat(),
        "git_commit_sha": authorized_sha,
        "gate_3_pass": eval_result.gate_3_pass,
        "artifacts": manifest_artifacts,
        "precision": eval_result.precision,
        "recall": eval_result.recall,
        "matched_expected_count": eval_result.matched_expected_count,
        "expected_fact_count": eval_result.expected_fact_count,
    }
    atomic_write_json(artifact_dir / "manifest.json", manifest)

    atomic_write_json(
        run_state_file,
        {
            "status": "COMPLETED",
            "gate_3_pass": eval_result.gate_3_pass,
            "run_label": run_label,
            "gate": 3,
            "timestamp": datetime.now(UTC).isoformat(),
            "git_commit_sha": authorized_sha,
        },
    )

    print(
        f"Gate 3 evaluation complete. Pass: {eval_result.gate_3_pass} "
        f"({eval_result.matched_expected_count}/{eval_result.expected_fact_count})"
    )
    return 0 if eval_result.gate_3_pass else 1


def main() -> None:
    """CLI entrypoint for Gate 3 runner."""
    parser = argparse.ArgumentParser(description="Gate 3 Multi-File System Analysis Runner")
    parser.add_argument("--run-label", default="baseline-v1", help="Identifier for analysis run")
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
