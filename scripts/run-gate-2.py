#!/usr/bin/env python3
"""Gate 2 — COBOL Reader Runner (Version 2.3.1)

Executes single-file COBOL analysis on BANK-MAIN.CBL using Azure AI Foundry
Responses API with native Structured Outputs.

Enforces Candidate V2.3.1 Architecture:
1. Commit-bound baseline authorization specification (evals/baselines/gate-2-baseline-v2.json).
2. Self-Authorizing Child Trust Model: every execution path reaching model invocation,
   including direct internal child execution, must independently establish and satisfy
   the complete baseline authorization contract.
3. Provenance Git repository supplied explicitly by the parent.
4. Runner bootstrap self-verification against committed runner blob in authorized Git SHA.
5. Snapshot byte identity verified against Git object blobs (git cat-file blob <object-id>).
6. Child-derived source identity recomputed from verified snapshot bytes (BANK-MAIN.CBL).
7. Deterministic artifact destination binding (provenance_repo/artifacts/gate-2/run_label).
8. Canonical runtime/lock attestation strictly before model invocation.
9. Strict 18-step child verification ordering guaranteeing zero model calls on preflight failure.
10. Host-owned Python runtime provenance persistence in run-metadata.json.
11. Baseline authorization spec SHA256 persisted in run-metadata.json.
12. Zero serialization of raw Foundry endpoint, subscription IDs, or credential tokens.
13. Deterministic evaluation using Evaluator V2.3 and Golden Dataset V2.2.

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

EXPECTED_BANK_MAIN_SHA = "b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028"
BASELINE_SPEC_REL_PATH = "evals/baselines/gate-2-baseline-v2.json"


def get_sanitized_git_env() -> dict[str, str]:
    """Sanitize environment for Git subprocesses to bypass object replacement and redirection.

    Enforces:
    - GIT_NO_REPLACE_OBJECTS=1
    - Purges GIT_DIR, GIT_WORK_TREE, GIT_OBJECT_DIRECTORY, GIT_ALTERNATE_OBJECT_DIRECTORIES,
      GIT_INDEX_FILE, GIT_REPLACE_REF_BASE.
    """
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
            "Must be exactly 64 lowercase hexadecimal SHA256 characters."
        )


def load_baseline_authorization_spec(root: Path) -> tuple[dict[str, Any], str]:
    """Load and validate commit-bound baseline authorization specification.

    Returns:
        Tuple of (spec_dict, spec_sha256).
    """
    spec_path = root / BASELINE_SPEC_REL_PATH
    if not spec_path.is_file():
        raise FileNotFoundError(f"Baseline authorization spec not found at: {spec_path}")
    raw_bytes = spec_path.read_bytes()
    spec_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    spec = json.loads(raw_bytes.decode("utf-8"))

    required_keys = {
        "spec_version",
        "run_label",
        "source_path",
        "source_sha256",
        "requested_model",
        "foundry_project_fingerprint",
        "schema_version",
        "prompt_version",
        "evaluator_version",
        "golden_dataset_version",
    }
    missing = required_keys - set(spec.keys())
    if missing:
        raise ValueError(f"Baseline authorization spec missing required keys: {sorted(missing)}")
    return spec, spec_sha256


def validate_internal_child_args(args: argparse.Namespace) -> None:
    """Validate internal child execution argument contract strictly.

    Required internal arguments:
    - run_label
    - authorized_git_sha
    - provenance_repo
    - snapshot_dir
    - artifact_dir
    - expected_model
    - expected_project_fingerprint
    """
    required_attrs = [
        "run_label",
        "authorized_git_sha",
        "provenance_repo",
        "snapshot_dir",
        "artifact_dir",
        "expected_model",
        "expected_project_fingerprint",
    ]
    for attr in required_attrs:
        val = getattr(args, attr, None)
        if not val or not str(val).strip():
            raise ValueError(
                f"Missing mandatory internal child execution argument: --{attr.replace('_', '-')}"
            )

    validate_run_label(args.run_label)
    if not HEX_40_PATTERN.fullmatch(args.authorized_git_sha.lower()):
        raise ValueError(
            f"Invalid authorized git commit SHA '{args.authorized_git_sha}'. "
            "Must be exactly 40 lowercase hexadecimal characters."
        )
    validate_project_fingerprint_format(args.expected_project_fingerprint)

    prov_path = Path(args.provenance_repo).resolve()
    if not prov_path.is_dir():
        raise ValueError(f"Provenance repository directory not found: {prov_path}")

    snap_path = Path(args.snapshot_dir).resolve()
    if not snap_path.is_dir():
        raise ValueError(f"Snapshot directory not found: {snap_path}")

    art_path = Path(args.artifact_dir).resolve()
    if not art_path.is_dir():
        raise ValueError(f"Artifact directory not found: {art_path}")


def check_git_branch() -> str:
    """Verify current git branch is feat/gate-2-cobol-reader."""
    res = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=REPO_ROOT,
        env=get_sanitized_git_env(),
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
        env=get_sanitized_git_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def is_isolated_python() -> bool:
    """Return True if Python interpreter was invoked in isolated mode (-I)."""
    return sys.flags.isolated == 1


def is_bytecode_writing_disabled() -> bool:
    """Return True if Python interpreter was invoked with -B (dont_write_bytecode)."""
    return sys.flags.dont_write_bytecode == 1


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


def load_env_file_stdlib(env_path: Path) -> dict[str, str]:
    """Read key-value pairs from .env file using standard library only."""
    env_vars: dict[str, str] = {}
    if not env_path.is_file():
        return env_vars
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        env_vars[k] = v
    return env_vars


def normalize_foundry_endpoint(endpoint: str) -> str:
    """Canonical normalization of Azure AI Foundry project endpoint per Amendment 2.

    Enforces:
    - trim external whitespace;
    - require HTTPS;
    - lowercase scheme and hostname;
    - normalize/remove default port if present (443);
    - remove a single insignificant trailing slash;
    - preserve project/path identity and casing (do not lowercase blindly);
    - reject unexpected userinfo;
    - reject unexpected query string;
    - reject fragment.
    """
    s = endpoint.strip()
    if not s:
        raise ValueError("Foundry endpoint string is empty.")

    parsed = urllib.parse.urlsplit(s)

    scheme = parsed.scheme.lower()
    if scheme != "https":
        raise ValueError(
            f"Disallowed endpoint scheme '{parsed.scheme}'. "
            "Only HTTPS is permitted for Foundry endpoints."
        )

    if parsed.username or parsed.password:
        raise ValueError("Foundry endpoint contains disallowed userinfo credentials.")

    if parsed.query:
        raise ValueError("Foundry endpoint contains disallowed query parameters.")

    if parsed.fragment:
        raise ValueError("Foundry endpoint contains disallowed fragment identifier.")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("Foundry endpoint is missing valid hostname.")

    port = parsed.port
    if port is not None and port != 443:
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname

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


def verify_clean_worktree(is_baseline_run: bool = False) -> None:
    """Verify that the git working tree has no uncommitted changes or executable overlays."""
    res = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        env=get_sanitized_git_env(),
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
        env=get_sanitized_git_env(),
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
            env=get_sanitized_git_env(),
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
        env=get_sanitized_git_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    tracked_res = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        env=get_sanitized_git_env(),
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


def verify_trusted_runner_bootstrap(
    provenance_repo: Path, authorized_git_sha: str, executing_file: Path
) -> None:
    """Verify executing runner matches committed runner for authorized Git SHA.

    Enforces:
    - Sanitized Git environment (GIT_NO_REPLACE_OBJECTS=1)
    - Verifies authorized_git_sha resolves to a commit in provenance_repo
    - Fetches committed blob for scripts/run-gate-2.py from authorized_git_sha
    - Compares byte-for-byte / hash-for-hash with executing_file
    - Fails closed if they differ
    """
    sanitized_env = get_sanitized_git_env()

    # 1. Verify authorized_git_sha resolves in provenance repository
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
            f"Authorized Git commit SHA '{authorized_git_sha}' does not resolve "
            f"in provenance repository: {rev_res.stderr.strip()}"
        )
    resolved_sha = rev_res.stdout.strip().lower()
    if resolved_sha != authorized_git_sha.lower():
        raise RuntimeError(
            f"Resolved Git SHA '{resolved_sha}' does not match "
            f"authorized SHA '{authorized_git_sha.lower()}'"
        )

    # 2. Fetch committed blob for scripts/run-gate-2.py
    runner_blob_res = subprocess.run(
        ["git", "show", f"{authorized_git_sha}:scripts/run-gate-2.py"],
        cwd=provenance_repo,
        env=sanitized_env,
        capture_output=True,
        check=False,
    )
    if runner_blob_res.returncode != 0:
        raise RuntimeError(
            f"Failed to retrieve committed runner blob for "
            f"'{authorized_git_sha}:scripts/run-gate-2.py': "
            f"{runner_blob_res.stderr.decode('utf-8', errors='replace').strip()}"
        )
    committed_runner_bytes = runner_blob_res.stdout

    # 3. Read executing runner bytes
    executing_path = executing_file.resolve()
    if not executing_path.is_file():
        raise RuntimeError(f"Executing runner file not found: {executing_path}")
    executing_bytes = executing_path.read_bytes()

    if executing_bytes != committed_runner_bytes:
        executing_sha = hashlib.sha256(executing_bytes).hexdigest()
        committed_sha = hashlib.sha256(committed_runner_bytes).hexdigest()
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
    """Verify snapshot regular-file bytes against Git object blobs byte-for-byte.

    Enforces:
    - GIT_NO_REPLACE_OBJECTS=1 and sanitized Git environment
    - git ls-tree -r -z <authorized_git_sha>
    - Fail closed on unsupported tree entry modes/types (symlinks, submodules)
    - Regular-file bytes must equal committed blob bytes via git cat-file blob <object-id>
    - Exact expected regular-file set equality
    - Zero bytecode (__pycache__, *.pyc, *.pyo, *.pyd)
    """
    sanitized_env = get_sanitized_git_env()

    # 1. Fetch tree listing from authorized Git commit
    ls_tree_res = subprocess.run(
        ["git", "ls-tree", "-r", "-z", authorized_git_sha],
        cwd=provenance_repo,
        env=sanitized_env,
        capture_output=True,
        check=False,
    )
    if ls_tree_res.returncode != 0:
        raise RuntimeError(
            f"git ls-tree failed for commit '{authorized_git_sha}': "
            f"{ls_tree_res.stderr.decode('utf-8', errors='replace').strip()}"
        )

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

        # Fail closed on unsupported tree entry modes/types
        if mode not in ("100644", "100755"):
            raise RuntimeError(
                f"Unsupported tree entry mode '{mode}' for path '{rel_path}'. "
                "Only regular files (100644, 100755) are permitted."
            )
        if typ != "blob":
            raise RuntimeError(
                f"Unsupported tree entry type '{typ}' for path '{rel_path}'. "
                "Only blob entries are permitted."
            )

        expected_files.add(rel_path)

        file_path = snapshot_dir / rel_path
        if not file_path.is_file() or file_path.is_symlink():
            raise RuntimeError(f"Committed file missing or is symlink in snapshot: {rel_path}")

        disk_bytes = file_path.read_bytes()

        # Retrieve committed blob bytes via git cat-file blob <object-id>
        blob_proc = subprocess.run(
            ["git", "cat-file", "blob", obj_id],
            cwd=provenance_repo,
            env=sanitized_env,
            capture_output=True,
            check=False,
        )
        if blob_proc.returncode != 0:
            raise RuntimeError(
                f"Failed to retrieve committed blob for '{rel_path}' ({obj_id}): "
                f"{blob_proc.stderr.decode('utf-8', errors='replace').strip()}"
            )
        committed_bytes = blob_proc.stdout

        if disk_bytes != committed_bytes:
            disk_sha = hashlib.sha256(disk_bytes).hexdigest()
            blob_sha = hashlib.sha256(committed_bytes).hexdigest()
            raise RuntimeError(
                f"Snapshot file '{rel_path}' does not match committed Git object bytes!\n"
                f"Snapshot SHA256: {disk_sha}\n"
                f"Git blob SHA256: {blob_sha}"
            )

    # 2. Verify exact regular-file set equality & zero bytecode/cache
    for root, dirs, files in os.walk(snapshot_dir):
        if "__pycache__" in dirs:
            raise RuntimeError(
                f"Illegal __pycache__ directory detected in snapshot: {root}/__pycache__"
            )
        for f in files:
            if f.endswith((".pyc", ".pyo", ".pyd")):
                raise RuntimeError(f"Illegal bytecode cache detected in snapshot: {root}/{f}")
            disk_file = Path(root) / f
            if disk_file.is_symlink():
                raise RuntimeError(f"Illegal symlink detected in snapshot: {disk_file}")
            actual_rel = disk_file.relative_to(snapshot_dir).as_posix()
            if actual_rel not in expected_files:
                raise RuntimeError(
                    f"Unexpected uncommitted file detected in snapshot: {actual_rel}"
                )

    return expected_files


def create_and_verify_git_snapshot(
    expected_git_sha: str, temp_dir: Path, repo_root: Path = REPO_ROOT
) -> Path:
    """Extract immutable application snapshot from authorized Git commit object tree.

    Uses sanitized Git environment to defeat object redirection / replacement.
    Extracts strictly committed bytes from expected_git_sha via git archive into temp_dir.
    Verifies that snapshot matches Git tree objects and contains zero bytecode/cache files.
    """
    sanitized_env = get_sanitized_git_env()

    # 1. Stream git archive <expected_git_sha> into temp_dir
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

    stderr_out = (
        archive_proc.stderr.read().decode("utf-8", errors="replace") if archive_proc.stderr else ""
    )
    returncode = archive_proc.wait()
    if returncode != 0:
        raise RuntimeError(f"git archive failed (exit {returncode}): {stderr_out}")

    # 2. Verify snapshot files against Git object tree byte-for-byte
    verify_snapshot_against_git_objects(repo_root, expected_git_sha, temp_dir)

    return temp_dir


def atomic_write_json(file_path: Path, data: dict[str, Any]) -> None:
    """Atomically write JSON data to file using NamedTemporaryFile.

    Ensures the temporary file is removed on ANY exception path, guaranteeing
    zero orphaned temporary files on write failure.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tf = tempfile.NamedTemporaryFile(
        dir=file_path.parent,
        prefix=f"{file_path.stem}-",
        suffix=".tmp",
        mode="w",
        encoding="utf-8",
        delete=False,
    )
    tmp_name = tf.name
    try:
        json.dump(data, tf, indent=2)
        tf.write("\n")
        tf.flush()
        tf.close()
        os.replace(tmp_name, file_path)
    except BaseException:
        try:
            tf.close()
        except Exception:
            pass
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except Exception:
                pass
        raise


def reserve_run_directory(
    artifact_dir: Path,
    run_label: str,
    head_sha: str,
    source_sha: str,
    requested_model: str,
    project_fingerprint: str,
) -> None:
    """Atomically reserve run directory and persist initial RESERVED state.

    Guarantees that if initial state persistence fails BEFORE model invocation:
    - all partial files in artifact_dir are unlinked;
    - artifact_dir is removed (rmdir);
    - zero orphan bytes survive;
    - run_label remains reusable.

    If artifact_dir already exists, raises RuntimeError without touching it.
    """
    try:
        artifact_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise RuntimeError(
            f"Run directory already exists: {artifact_dir}. "
            "Refusing to overwrite existing run artifacts. Aborting."
        )

    run_state_file = artifact_dir / "run-state.json"
    try:
        atomic_write_json(
            run_state_file,
            {
                "status": "RESERVED",
                "run_label": run_label,
                "timestamp": datetime.now(UTC).isoformat(),
                "git_commit_sha": head_sha,
                "source_sha256": source_sha,
                "requested_model": requested_model,
                "foundry_project_fingerprint": project_fingerprint,
            },
        )
    except BaseException as exc:
        # Initial reservation write failure BEFORE model invocation: safe rollback!
        try:
            for child in artifact_dir.iterdir():
                try:
                    if child.is_file():
                        child.unlink()
                except Exception:
                    pass
            artifact_dir.rmdir()
        except Exception:
            pass
        raise RuntimeError(
            f"Failed to write initial RESERVED run state before model invocation: {exc}. "
            "Rolled back reserved directory; run label remains reusable."
        ) from exc


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


def sanitize_console_message(msg: str) -> str:
    """Strip URLs, secret parameters, bearer tokens, and local paths from console messages."""
    s = re.sub(r"https?://[^\s'\"]+", "[REDACTED_URL]", msg)
    s = re.sub(r"Bearer\s+[A-Za-z0-9._~+/-]+", "Bearer [REDACTED]", s, flags=re.IGNORECASE)
    s = re.sub(r"api[-_]?key=[A-Za-z0-9._~+/-]+", "api-key=[REDACTED]", s, flags=re.IGNORECASE)
    s = re.sub(r"[A-Za-z]:\\[A-Za-z0-9_.\-\\]+", "[REDACTED_PATH]", s)
    s = re.sub(r"/(?:mnt|home|Users|tmp)/[A-Za-z0-9_.\-/]+", "[REDACTED_PATH]", s)
    return s


def get_python_runtime_identity(lock_file_path: Path, manifest_sha256: str) -> dict[str, Any]:
    """Collect host-owned Python runtime provenance without absolute sys.executable path."""
    build_tuple = platform.python_build()
    python_build_str = f"{build_tuple[0]} {build_tuple[1]}"

    lock_sha = ""
    if lock_file_path.is_file():
        lock_sha = hashlib.sha256(lock_file_path.read_bytes()).hexdigest()

    binary_sha = ""
    try:
        binary_sha = hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
    except Exception:
        pass

    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_cache_tag": getattr(sys.implementation, "cache_tag", ""),
        "python_build": python_build_str,
        "isolated_mode": sys.flags.isolated == 1,
        "dont_write_bytecode": sys.flags.dont_write_bytecode == 1,
        "runtime_manifest_sha256": manifest_sha256,
        "dependency_lock_sha256": lock_sha,
        "interpreter_binary_sha256": binary_sha,
    }


def verify_import_origins(snapshot_dir: Path | None = None) -> None:
    """Verify that third-party packages come from venv and application code comes from snapshot."""
    import azure.ai.projects
    import azure.identity
    import dotenv
    import openai
    import pydantic

    venv_path = Path(sys.prefix).resolve()
    third_party_modules = [
        ("openai", openai),
        ("pydantic", pydantic),
        ("azure.ai.projects", azure.ai.projects),
        ("azure.identity", azure.identity),
        ("dotenv", dotenv),
    ]
    for name, mod in third_party_modules:
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
        if snapshot_dir is not None:
            try:
                mod_path.relative_to(snapshot_dir.resolve())
                raise RuntimeError(f"Module {name} was imported from snapshot overlay: {mod_path}")
            except ValueError:
                pass
        try:
            rel_to_repo = mod_path.relative_to(REPO_ROOT.resolve())
            parts = rel_to_repo.parts
            if not parts or parts[0] != ".venv":
                raise RuntimeError(
                    f"Module {name} was imported from repository overlay: {mod_path}"
                )
        except ValueError:
            pass

    # Verify application modules resolve from snapshot or repo
    from agents.legacy_analyzer.agent import LegacyAnalyzerAgent
    from src.cobol.source_reader import prepare_source

    agent_mod_file = sys.modules[LegacyAnalyzerAgent.__module__].__file__
    reader_mod_file = sys.modules[prepare_source.__module__].__file__

    if not agent_mod_file or not reader_mod_file:
        raise RuntimeError("Application modules missing __file__.")

    agent_path = Path(agent_mod_file).resolve()
    reader_path = Path(reader_mod_file).resolve()

    if snapshot_dir is not None:
        try:
            agent_path.relative_to(snapshot_dir.resolve())
        except ValueError:
            raise RuntimeError(
                f"agents.* module did not originate from snapshot directory: {agent_path}"
            )

        try:
            reader_path.relative_to(snapshot_dir.resolve())
        except ValueError:
            raise RuntimeError(
                f"src.* module did not originate from snapshot directory: {reader_path}"
            )


def run_child_process(args: argparse.Namespace) -> int:
    """Execute Gate 2 application child process with self-authorizing verification.

    Self-Authorizing Child Trust Model:
    ANY execution path capable of reaching MODEL_INVOCATION, including direct internal-child mode,
    must independently satisfy the COMPLETE baseline authorization contract.
    No caller-controlled nonces or paths are trusted; every identity is derived independently
    from the verified provenance Git repository, committed BaselineAuthorizationSpec,
    and verified snapshot bytes.
    """
    # Step 1: Validate internal CLI contract
    try:
        validate_internal_child_args(args)
    except Exception as e:
        print(f"ERROR: Step 1 Internal CLI contract validation failed: {e}")
        return 1

    # Step 2: Require isolated Python (-I) and no bytecode (-B)
    if not is_isolated_python() or not is_bytecode_writing_disabled():
        print(
            "ERROR: Step 2 Child execution must be invoked with isolated Python (-I) "
            "and no bytecode (-B)."
        )
        return 1

    provenance_repo = Path(args.provenance_repo).resolve()
    snapshot_dir = Path(args.snapshot_dir).resolve()
    artifact_dir = Path(args.artifact_dir).resolve()

    # Step 3: Verify provenance Git repository / authorized commit resolves
    # Step 4: Verify executing runner against committed runner blob
    try:
        verify_trusted_runner_bootstrap(
            provenance_repo=provenance_repo,
            authorized_git_sha=args.authorized_git_sha,
            executing_file=Path(__file__),
        )
        print("[OK] Steps 3 & 4: Provenance Git repo and executing runner blob verified")
    except Exception as e:
        print(f"ERROR: Runner bootstrap verification failed: {sanitize_console_message(str(e))}")
        return 1

    # Step 5: Verify EVERY snapshot file against Git object bytes
    try:
        verified_files = verify_snapshot_against_git_objects(
            provenance_repo=provenance_repo,
            authorized_git_sha=args.authorized_git_sha,
            snapshot_dir=snapshot_dir,
        )
        print(
            f"[OK] Step 5: Snapshot verified ({len(verified_files)} files match Git object blobs)"
        )
    except Exception as e:
        print(f"ERROR: Snapshot byte verification failed: {sanitize_console_message(str(e))}")
        return 1

    # Step 6: Load verified committed BaselineAuthorizationSpec
    try:
        spec, spec_sha256 = load_baseline_authorization_spec(snapshot_dir)
        print(
            f"[OK] Step 6: Committed BaselineAuthorizationSpec loaded "
            f"(SHA256: {spec_sha256[:12]}...)"
        )
    except Exception as e:
        print(f"ERROR: Failed to load BaselineAuthorizationSpec: {e}")
        return 1

    # Step 7: Compare CLI assertions against committed spec
    try:
        if args.run_label != spec["run_label"]:
            raise RuntimeError(
                f"CLI run_label '{args.run_label}' does not match "
                f"committed spec run_label '{spec['run_label']}'"
            )
        if args.expected_model != spec["requested_model"]:
            raise RuntimeError(
                f"CLI expected_model '{args.expected_model}' does not match "
                f"committed spec requested_model '{spec['requested_model']}'"
            )
        if args.expected_project_fingerprint != spec["foundry_project_fingerprint"]:
            raise RuntimeError(
                "CLI expected_project_fingerprint does not match "
                "committed spec foundry_project_fingerprint"
            )
        print("[OK] Step 7: CLI assertions match committed BaselineAuthorizationSpec")
    except Exception as e:
        print(f"ERROR: CLI consistency assertion failed: {e}")
        return 1

    # Step 8: Recompute and verify BANK-MAIN source SHA
    try:
        source_rel_path = spec["source_path"]
        source_file = snapshot_dir / source_rel_path
        if not source_file.is_file() or source_file.is_symlink():
            raise RuntimeError(f"Source file missing or is symlink in snapshot: {source_rel_path}")
        actual_source_bytes = source_file.read_bytes()
        actual_source_sha = hashlib.sha256(actual_source_bytes).hexdigest()
        if actual_source_sha.lower() != spec["source_sha256"].lower():
            raise RuntimeError(
                f"Snapshot source SHA256 '{actual_source_sha}' does not match "
                f"committed spec source_sha256 '{spec['source_sha256']}'"
            )
        print("[OK] Step 8: BANK-MAIN source SHA recomputed and verified from snapshot bytes")
    except Exception as e:
        print(f"ERROR: Source SHA verification failed: {e}")
        return 1

    # Step 9: Verify controlled cwd/sys.path
    if Path.cwd().resolve() != snapshot_dir or Path.cwd().is_symlink():
        print(f"ERROR: Step 9 Child execution cwd must be snapshot directory. Got: {Path.cwd()}")
        return 1
    sys.path = [p for p in sys.path if Path(p).resolve() != provenance_repo.resolve()]
    if sys.path[0] != str(snapshot_dir):
        sys.path.insert(0, str(snapshot_dir))
    print("[OK] Step 9: Controlled cwd and sys.path verified")

    # Step 10: Verify deterministic artifact destination and RESERVED-state consistency
    expected_artifact_dir = (provenance_repo / "artifacts" / "gate-2" / args.run_label).resolve()
    resolved_artifact_dir = artifact_dir.resolve()
    if Path(args.artifact_dir).is_symlink() or resolved_artifact_dir.is_symlink():
        print(f"ERROR: Artifact directory must not be a symlink: {args.artifact_dir}")
        return 1
    if resolved_artifact_dir != expected_artifact_dir:
        print(
            "ERROR: Artifact destination mismatch! "
            f"Expected: {expected_artifact_dir}, got: {resolved_artifact_dir}"
        )
        return 1

    run_state_file = resolved_artifact_dir / "run-state.json"
    if run_state_file.is_symlink() or not run_state_file.is_file():
        print(f"ERROR: Prepared run-state.json not found in: {resolved_artifact_dir}")
        return 1

    try:
        initial_state = json.loads(run_state_file.read_text(encoding="utf-8"))
        if initial_state.get("status") != "RESERVED":
            raise RuntimeError(f"Expected RESERVED run state, got: {initial_state.get('status')}")
        if initial_state.get("run_label") != spec["run_label"]:
            raise RuntimeError("Run label mismatch in prepared reservation state.")
        if initial_state.get("git_commit_sha") != args.authorized_git_sha:
            raise RuntimeError("Git commit SHA mismatch in prepared reservation state.")
        if initial_state.get("source_sha256") != actual_source_sha:
            raise RuntimeError(
                f"Source SHA in RESERVED state ({initial_state.get('source_sha256')}) "
                f"does not match actual verified snapshot source SHA ({actual_source_sha})."
            )
        if initial_state.get("requested_model") != spec["requested_model"]:
            raise RuntimeError("Model mismatch in prepared reservation state.")
        if initial_state.get("foundry_project_fingerprint") != spec["foundry_project_fingerprint"]:
            raise RuntimeError("Project fingerprint mismatch in prepared reservation state.")
        print("[OK] Step 10: Deterministic artifact destination and RESERVED state verified")
    except Exception as e:
        print(f"ERROR: Reservation validation failed: {e}")
        return 1

    # Step 11: Verify runtime against verified snapshot requirements-lock.txt
    lock_file = snapshot_dir / "requirements-lock.txt"
    try:
        runtime_manifest, runtime_manifest_sha = verify_runtime_environment(lock_file)
        print(
            f"[OK] Step 11: Runtime environment verified pre-invocation "
            f"({len(runtime_manifest)} packages, SHA256: {runtime_manifest_sha[:12]}...)"
        )
    except Exception as e:
        print(f"ERROR: Runtime environment verification failed: {sanitize_console_message(str(e))}")
        write_failure_run_state(run_state_file, "PRE_INVOCATION", e, args.authorized_git_sha)
        return 1

    # Step 12: Import application modules from snapshot
    try:
        from agents.legacy_analyzer.agent import LegacyAnalyzerAgent
        from agents.legacy_analyzer.config import load_config
        from agents.legacy_analyzer.schemas.export import (
            export_schema_to_file,
            export_wire_schema_to_file,
        )
        from src.cobol.source_reader import prepare_source
        from src.validation.evaluator_v2 import evaluate_assessment_v2, load_golden_dataset_v2

        print("[OK] Step 12: Application modules imported from snapshot")
    except Exception as e:
        print(f"ERROR: Application module import failed: {sanitize_console_message(str(e))}")
        write_failure_run_state(run_state_file, "PRE_INVOCATION", e, args.authorized_git_sha)
        return 1

    # Step 13: Verify application/third-party import origins
    try:
        verify_import_origins(snapshot_dir)
        print("[OK] Step 13: Import origins verified (app from snapshot, deps from attested venv)")
    except Exception as e:
        print(f"ERROR: Import origin verification failed: {sanitize_console_message(str(e))}")
        write_failure_run_state(run_state_file, "PRE_INVOCATION", e, args.authorized_git_sha)
        return 1

    # Step 14: Load effective configuration
    try:
        config = load_config()
        print("[OK] Step 14: Effective configuration loaded")
    except Exception as e:
        print(f"ERROR: Failed to load configuration: {sanitize_console_message(str(e))}")
        write_failure_run_state(run_state_file, "PRE_INVOCATION", e, args.authorized_git_sha)
        return 1

    # Step 15: Verify effective model == committed spec model
    try:
        if config.foundry_model != spec["requested_model"]:
            raise RuntimeError(
                f"Effective model '{config.foundry_model}' does not match "
                f"committed spec model '{spec['requested_model']}'"
            )
        print("[OK] Step 15: Effective model matches committed spec")
    except Exception as e:
        print(f"ERROR: Model verification failed: {sanitize_console_message(str(e))}")
        write_failure_run_state(run_state_file, "PRE_INVOCATION", e, args.authorized_git_sha)
        return 1

    # Step 16: Verify effective Foundry fingerprint == committed spec fingerprint
    try:
        if config.project_fingerprint != spec["foundry_project_fingerprint"]:
            raise RuntimeError(
                "Effective project fingerprint does not match committed spec fingerprint"
            )
        print("[OK] Step 16: Effective Foundry fingerprint matches committed spec")
    except Exception as e:
        print(f"ERROR: Fingerprint verification failed: {sanitize_console_message(str(e))}")
        write_failure_run_state(run_state_file, "PRE_INVOCATION", e, args.authorized_git_sha)
        return 1

    # Step 17: Persist MODEL_INVOCATION state
    current_phase = "MODEL_INVOCATION"
    try:
        atomic_write_json(
            run_state_file,
            {
                "status": "MODEL_INVOCATION",
                "run_label": args.run_label,
                "timestamp": datetime.now(UTC).isoformat(),
                "git_commit_sha": args.authorized_git_sha,
                "requested_model": config.foundry_model,
                "foundry_project_fingerprint": config.project_fingerprint,
            },
        )
        print("[OK] Step 17: MODEL_INVOCATION state persisted")
    except Exception as e:
        print(f"ERROR: Failed to write MODEL_INVOCATION state: {sanitize_console_message(str(e))}")
        write_failure_run_state(run_state_file, "PRE_INVOCATION", e, args.authorized_git_sha)
        return 1

    # Step 18: ONLY NOW construct LegacyAnalyzerAgent and invoke model
    try:
        prep = prepare_source(spec["source_path"], repo_root=snapshot_dir)

        print("--- Executing Responses API Call (Child Process) ---")
        agent = LegacyAnalyzerAgent(config=config, reasoning_effort="low")
        assessment, metadata = agent.analyze_source(
            source_path=spec["source_path"],
            run_label=args.run_label,
            repo_root=snapshot_dir,
            git_commit_sha=args.authorized_git_sha,
        )
        print(f"[OK] Response received in {metadata.elapsed_seconds:.2f}s")

        current_phase = "PERSIST_ASSESSMENT"
        assessment_file = artifact_dir / "bank-main-assessment.json"
        metadata_file = artifact_dir / "run-metadata.json"
        schema_file = artifact_dir / "assessment-schema.json"
        wire_schema_file = artifact_dir / "openai-wire-schema.json"
        runtime_manifest_file = artifact_dir / "runtime-manifest.json"
        eval_file = artifact_dir / "evaluation.json"

        # Persist runtime manifest using pre-attested values
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

        # Compile metadata with host-owned runtime provenance, safe fingerprint, and spec sha
        meta_dict = metadata.to_dict()
        meta_dict.pop("endpoint", None)  # Strictly ensure no raw endpoint
        runtime_id = get_python_runtime_identity(lock_file, runtime_manifest_sha)
        meta_dict["runtime_manifest_sha256"] = runtime_manifest_sha
        meta_dict["baseline_authorization_spec_sha256"] = spec_sha256
        meta_dict["python_runtime"] = runtime_id
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

        current_phase = "COMPLETED"
        atomic_write_json(
            run_state_file,
            {
                "status": "COMPLETED",
                "run_label": args.run_label,
                "timestamp": datetime.now(UTC).isoformat(),
                "git_commit_sha": args.authorized_git_sha,
                "gate_2_pass": report.gate_2_pass,
                "requested_model": config.foundry_model,
                "response_model_id": metadata.response_model_id,
                "foundry_project_fingerprint": metadata.foundry_project_fingerprint,
            },
        )

        # Report Summary
        print("======================================================================")
        print(" GATE 2 EVALUATION SUMMARY (V2.3.1)")
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
        write_failure_run_state(run_state_file, current_phase, e, args.authorized_git_sha)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate 2 COBOL Reader runner with verifiable provenance (V2.3.1)."
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
        "--expected-project-fingerprint",
        help="Expected SHA256 project fingerprint (64 hex characters; baseline mandatory).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run preflight checks only; skip model invocation and artifact creation.",
    )

    # Internal child execution arguments
    parser.add_argument(
        "--internal-child-exec",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--authorized-git-sha",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--provenance-repo",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--snapshot-dir",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--artifact-dir",
        help=argparse.SUPPRESS,
    )

    args = parser.parse_args()

    # Route child process execution
    if args.internal_child_exec:
        return run_child_process(args)

    print("======================================================================")
    print(" GATE 2 — COBOL READER RUNNER (V2.3.1)")
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

    # 2. Isolated Python Flag Check & Mandatory Baseline Arguments
    if is_baseline:
        if not is_isolated_python():
            print(
                "ERROR: Baseline runs require Python executed in isolated mode.\n"
                "Execute with: .venv/bin/python -I scripts/run-gate-2.py ..."
            )
            return 1
        if not args.expected_git_sha:
            print("ERROR: --expected-git-sha is mandatory for baseline runs.")
            return 1
        if not args.expected_model:
            print("ERROR: --expected-model is mandatory for baseline runs.")
            return 1
        if not args.expected_project_fingerprint:
            print("ERROR: --expected-project-fingerprint is mandatory for baseline runs.")
            return 1

        try:
            baseline_spec, baseline_spec_sha = load_baseline_authorization_spec(REPO_ROOT)
            if args.run_label != baseline_spec["run_label"]:
                print(
                    f"ERROR: Baseline run label '{args.run_label}' does not match "
                    f"committed spec '{baseline_spec['run_label']}'."
                )
                return 1
            if args.expected_model != baseline_spec["requested_model"]:
                print(
                    f"ERROR: Expected model '{args.expected_model}' does not match "
                    f"committed spec model '{baseline_spec['requested_model']}'."
                )
                return 1
            if args.expected_project_fingerprint != baseline_spec["foundry_project_fingerprint"]:
                print(
                    "ERROR: Expected project fingerprint does not match committed spec fingerprint."
                )
                return 1
        except Exception as e:
            print(f"ERROR: Baseline authorization spec preflight failed: {e}")
            return 1

    if args.expected_project_fingerprint:
        try:
            validate_project_fingerprint_format(args.expected_project_fingerprint)
        except Exception as e:
            print(f"ERROR: Project fingerprint validation failed: {e}")
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

    if args.expected_git_sha and head_sha.lower() != args.expected_git_sha.lower():
        print(f"ERROR: HEAD SHA mismatch! Expected '{args.expected_git_sha}', but got '{head_sha}'")
        return 1

    print("[OK] Git worktree is clean and commit provenance verified")

    # 6. Full Tracked Tree & Overlay Verification
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

    if source_sha.lower() != EXPECTED_BANK_MAIN_SHA.lower():
        print(f"ERROR: Source SHA256 mismatch! Expected {EXPECTED_BANK_MAIN_SHA}")
        return 1
    print("[OK] Source immutability verified")

    # 8. Foundry Configuration Preflight (Standard Library Only)
    env_vars = load_env_file_stdlib(REPO_ROOT / ".env")
    configured_endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT") or env_vars.get(
        "FOUNDRY_PROJECT_ENDPOINT", ""
    )
    configured_model = os.environ.get("FOUNDRY_MODEL") or env_vars.get("FOUNDRY_MODEL", "")

    if not configured_endpoint:
        print("ERROR: FOUNDRY_PROJECT_ENDPOINT is not configured in environment or .env.")
        return 1
    if not configured_model:
        print("ERROR: FOUNDRY_MODEL is not configured in environment or .env.")
        return 1

    try:
        computed_fingerprint = compute_foundry_project_fingerprint(configured_endpoint)
    except Exception as e:
        print(f"ERROR: Failed to parse and normalize FOUNDRY_PROJECT_ENDPOINT: {e}")
        return 1

    print(f"Configured Model:       {configured_model}")
    print(f"Project Fingerprint:    {computed_fingerprint}")

    if args.expected_model and configured_model != args.expected_model:
        print(
            f"ERROR: Model mismatch! Expected '{args.expected_model}', "
            f"but configured model is '{configured_model}'"
        )
        return 1

    if (
        args.expected_project_fingerprint
        and computed_fingerprint != args.expected_project_fingerprint
    ):
        print(
            f"ERROR: Project fingerprint mismatch! Expected '{args.expected_project_fingerprint}', "
            f"but computed fingerprint is '{computed_fingerprint}'"
        )
        return 1
    print("[OK] Model and project identity fingerprint preflight verified")
    print()

    # Pre-check artifact directory existence
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

    # 9. Create Immutable Git Application Snapshot (Phase B)
    temp_snapshot = tempfile.TemporaryDirectory(prefix="gate2-snapshot-")
    snapshot_path = Path(temp_snapshot.name).resolve()
    print(f"--- Extracting Git Application Snapshot from {head_sha[:12]} ---")
    try:
        create_and_verify_git_snapshot(head_sha, snapshot_path)
        print(f"[OK] Application snapshot verified (clean committed tree at {head_sha[:12]})")
    except Exception as e:
        temp_snapshot.cleanup()
        print(
            f"ERROR: Failed to create and verify Git snapshot: {sanitize_console_message(str(e))}"
        )
        return 1

    # 10. Atomic Run-Directory Reservation (Zero-Stranded State on Write Failure)
    print(f"Reserving run directory: {artifact_dir}")
    try:
        reserve_run_directory(
            artifact_dir=artifact_dir,
            run_label=args.run_label,
            head_sha=head_sha,
            source_sha=source_sha,
            requested_model=configured_model,
            project_fingerprint=computed_fingerprint,
        )
        print("[OK] Run directory reserved and run-state.json initialized to RESERVED")
    except Exception as e:
        temp_snapshot.cleanup()
        print(f"ERROR: Failed to reserve run directory: {sanitize_console_message(str(e))}")
        return 1

    # 11. Spawn Child Execution Process (Isolated Python, No Bytecode, Controlled Cwd)
    child_cmd = [
        sys.executable,
        "-I",
        "-B",
        str(snapshot_path / "scripts" / "run-gate-2.py"),
        "--run-label",
        args.run_label,
        "--internal-child-exec",
        "--authorized-git-sha",
        head_sha,
        "--provenance-repo",
        str(REPO_ROOT.resolve()),
        "--expected-model",
        args.expected_model or configured_model,
        "--expected-project-fingerprint",
        computed_fingerprint,
        "--snapshot-dir",
        str(snapshot_path),
        "--artifact-dir",
        str(artifact_dir.resolve()),
    ]

    child_env = dict(os.environ)
    # Ensure env has credentials from .env if needed
    for k, v in env_vars.items():
        child_env.setdefault(k, v)

    try:
        proc = subprocess.run(
            child_cmd,
            cwd=snapshot_path,
            env=child_env,
            check=False,
        )
        return proc.returncode
    finally:
        # Snapshot cleanup must occur after child terminates without touching durable artifact dir
        temp_snapshot.cleanup()


if __name__ == "__main__":
    sys.exit(main())
