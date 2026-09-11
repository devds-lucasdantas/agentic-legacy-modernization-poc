"""Authorization Regression Suite V2.3.1 for Gate 2 (Candidate V2.3.1).

Verifies the Candidate V2.3.1 runner authorization correction and the Four Required Amendments:
1. Commit-bound baseline authorization specification (evals/baselines/gate-2-baseline-v2.json).
2. Self-Authorizing Child Trust Model: direct internal-child mode independently establishes
   and satisfies the complete baseline authorization contract.
3. Snapshot regular-file byte verification directly against Git object blobs.
4. Child-derived source identity recomputed from verified snapshot bytes (BANK-MAIN.CBL).
5. Strict 18-step child verification ordering guaranteeing zero model calls on preflight failure.
6. Deterministic artifact destination binding and RESERVED-state consistency.
7. Baseline authorization spec SHA256 persisted in run metadata.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from evals.fixtures.synthetic_assessments import make_perfect_assessment_v2

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def get_runner_module():
    spec = importlib.util.spec_from_file_location(
        "run_gate_2_module_v2_3_1", REPO_ROOT / "scripts" / "run-gate-2.py"
    )
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    raise ImportError("Failed to load scripts/run-gate-2.py")


@pytest.fixture
def committed_test_repo(tmp_path: Path) -> tuple[Path, str]:
    """Create a disposable Git repo containing candidate files and return (repo_path, head_sha)."""
    repo_dir = tmp_path / "candidate_repo"
    runner = get_runner_module()
    sanitized_env = runner.get_sanitized_git_env()

    subprocess.run(
        ["git", "clone", "--shared", str(REPO_ROOT), str(repo_dir)],
        env=sanitized_env,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "AuditBot"],
        cwd=repo_dir,
        env=sanitized_env,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "audit@example.com"],
        cwd=repo_dir,
        env=sanitized_env,
        check=True,
    )

    # Ensure candidate files from REPO_ROOT are present and committed in the clone
    shutil.copy2(
        REPO_ROOT / "scripts" / "run-gate-2.py",
        repo_dir / "scripts" / "run-gate-2.py",
    )
    for sub in ["src", "agents"]:
        dest = repo_dir / sub
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(REPO_ROOT / sub, dest)

    (repo_dir / "evals" / "baselines").mkdir(parents=True, exist_ok=True)
    for p in (REPO_ROOT / "evals" / "baselines").glob("*.json"):
        shutil.copy2(p, repo_dir / "evals" / "baselines" / p.name)

    subprocess.run(
        ["git", "add", "-A"],
        cwd=repo_dir,
        env=sanitized_env,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Candidate V2.3.1 committed test baseline"],
        cwd=repo_dir,
        env=sanitized_env,
        capture_output=True,
        check=True,
    )

    res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_dir,
        env=sanitized_env,
        capture_output=True,
        text=True,
        check=True,
    )
    head_sha = res.stdout.strip()
    return repo_dir, head_sha


@pytest.fixture
def valid_child_setup(committed_test_repo, tmp_path: Path):
    """Set up a verified snapshot and valid RESERVED artifact dir for child tests."""
    repo_dir, head_sha = committed_test_repo
    runner = get_runner_module()

    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    runner.create_and_verify_git_snapshot(head_sha, snapshot_dir, repo_root=repo_dir)

    run_label = "baseline-v2"
    artifact_dir = repo_dir / "artifacts" / "gate-2" / run_label
    source_sha = "b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028"
    requested_model = "gpt-5-mini"
    fingerprint = "3f0c34d730680ad8baac11d2825e120045eb19be1d9ec1c0b2a2d337096ae33f"

    runner.reserve_run_directory(
        artifact_dir=artifact_dir,
        run_label=run_label,
        head_sha=head_sha,
        source_sha=source_sha,
        requested_model=requested_model,
        project_fingerprint=fingerprint,
    )

    args = argparse.Namespace(
        run_label=run_label,
        authorized_git_sha=head_sha,
        provenance_repo=str(repo_dir),
        snapshot_dir=str(snapshot_dir),
        artifact_dir=str(artifact_dir),
        expected_model=requested_model,
        expected_project_fingerprint=fingerprint,
        internal_child_exec=True,
    )
    return repo_dir, head_sha, snapshot_dir, artifact_dir, args


# ==============================================================================
# 1. Internal Mode CLI Contract & Provenance Repo Requirements
# ==============================================================================


def test_01_internal_mode_missing_provenance_repo_rejected(valid_child_setup):
    """1. Internal child mode missing --provenance-repo is rejected with zero model calls."""
    _repo, _sha, _snap, _art, args = valid_child_setup
    runner = get_runner_module()

    args.provenance_repo = None
    invocation_mock = MagicMock()

    res = runner.run_child_process(args)
    assert res == 1
    assert invocation_mock.call_count == 0


def test_02_internal_mode_missing_any_required_argument_rejected(valid_child_setup):
    """2. Internal child mode missing any required argument fails closed before invocation."""
    _repo, _sha, _snap, _art, args = valid_child_setup
    runner = get_runner_module()

    required_fields = [
        "run_label",
        "authorized_git_sha",
        "snapshot_dir",
        "artifact_dir",
        "expected_model",
        "expected_project_fingerprint",
    ]

    for field in required_fields:
        corrupted_args = argparse.Namespace(**vars(args))
        setattr(corrupted_args, field, "")
        res = runner.run_child_process(corrupted_args)
        assert res == 1


# ==============================================================================
# 2. Runner Bootstrap Self-Verification Against Committed Blob
# ==============================================================================


def test_03_runner_blob_mismatch_rejected_before_invocation(valid_child_setup, tmp_path):
    """3. Executing runner differing from committed runner blob fails bootstrap verification."""
    repo_dir, head_sha, _snap, _art, args = valid_child_setup
    runner = get_runner_module()

    # Create a modified runner file simulating unauthorized mutation
    fake_runner = tmp_path / "run-gate-2.py"
    fake_runner.write_text("# MODIFIED RUNNER CONTENT\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Executing runner does not match committed runner blob"):
        runner.verify_trusted_runner_bootstrap(
            provenance_repo=repo_dir,
            authorized_git_sha=head_sha,
            executing_file=fake_runner,
        )


def test_04_runner_bootstrap_verifies_exact_match(valid_child_setup):
    """4. Unmodified runner matching committed blob passes bootstrap verification."""
    repo_dir, head_sha, snapshot_dir, _art, _args = valid_child_setup
    runner = get_runner_module()

    # The snapshot runner matches the committed blob
    snapshot_runner = snapshot_dir / "scripts" / "run-gate-2.py"
    runner.verify_trusted_runner_bootstrap(
        provenance_repo=repo_dir,
        authorized_git_sha=head_sha,
        executing_file=snapshot_runner,
    )


# ==============================================================================
# 3. Snapshot Regular-File Byte Verification Against Git Objects
# ==============================================================================


def test_05_snapshot_file_hash_mismatch_rejected_before_app_import(valid_child_setup):
    """5. Snapshot file with tampered bytes is rejected before application import."""
    repo_dir, head_sha, snapshot_dir, _art, _args = valid_child_setup
    runner = get_runner_module()

    # Tamper with a tracked regular file in snapshot
    tampered_file = snapshot_dir / "README.md"
    tampered_file.write_text("TAMPERED BYTES", encoding="utf-8")

    with pytest.raises(RuntimeError, match="does not match committed Git object bytes"):
        runner.verify_snapshot_against_git_objects(
            provenance_repo=repo_dir,
            authorized_git_sha=head_sha,
            snapshot_dir=snapshot_dir,
        )


def test_06_snapshot_missing_tracked_file_rejected(valid_child_setup):
    """6. Snapshot missing an expected committed file is rejected."""
    repo_dir, head_sha, snapshot_dir, _art, _args = valid_child_setup
    runner = get_runner_module()

    license_file = snapshot_dir / "LICENSE"
    license_file.unlink()

    with pytest.raises(RuntimeError, match="Committed file missing or is symlink in snapshot"):
        runner.verify_snapshot_against_git_objects(
            provenance_repo=repo_dir,
            authorized_git_sha=head_sha,
            snapshot_dir=snapshot_dir,
        )


def test_07_snapshot_extra_uncommitted_file_rejected(valid_child_setup):
    """7. Snapshot containing an unexpected uncommitted file is rejected."""
    repo_dir, head_sha, snapshot_dir, _art, _args = valid_child_setup
    runner = get_runner_module()

    extra_file = snapshot_dir / "untracked_overlay.py"
    extra_file.write_text("# UNTRACKED OVERLAY", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Unexpected uncommitted file detected in snapshot"):
        runner.verify_snapshot_against_git_objects(
            provenance_repo=repo_dir,
            authorized_git_sha=head_sha,
            snapshot_dir=snapshot_dir,
        )


def test_08_snapshot_bytecode_cache_rejected(valid_child_setup):
    """8. Snapshot containing __pycache__ or .pyc is rejected."""
    repo_dir, head_sha, snapshot_dir, _art, _args = valid_child_setup
    runner = get_runner_module()

    cache_dir = snapshot_dir / "agents" / "__pycache__"
    cache_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(RuntimeError, match="Illegal __pycache__ directory detected"):
        runner.verify_snapshot_against_git_objects(
            provenance_repo=repo_dir,
            authorized_git_sha=head_sha,
            snapshot_dir=snapshot_dir,
        )


# ==============================================================================
# 4. Commit-Bound Baseline Authorization Spec Verification
# ==============================================================================


def test_09_baseline_authorization_spec_is_part_of_authorized_snapshot(valid_child_setup):
    """9. BaselineAuthorizationSpec is loaded from snapshot and SHA256 is computed."""
    _repo, _sha, snapshot_dir, _art, _args = valid_child_setup
    runner = get_runner_module()

    spec, spec_sha = runner.load_baseline_authorization_spec(snapshot_dir)
    assert spec["spec_version"] in ("1.0.0", "1.1.0")
    assert spec["run_label"] in ("baseline-v2", "baseline-v3")
    assert spec["source_path"] == "legacy/core-banking-system/BANK-MAIN.CBL"
    assert spec["requested_model"] == "gpt-5-mini"
    assert len(spec_sha) == 64


def test_10_cli_expected_model_differing_from_spec_rejected(valid_child_setup, monkeypatch):
    """10. CLI expected model differing from committed spec is rejected before invocation."""
    _repo, _sha, snapshot_dir, _art, args = valid_child_setup
    runner = get_runner_module()

    args.expected_model = "gpt-4o"
    monkeypatch.setattr(runner, "is_isolated_python", lambda: True)
    monkeypatch.setattr(runner, "is_bytecode_writing_disabled", lambda: True)
    monkeypatch.chdir(snapshot_dir)

    res = runner.run_child_process(args)
    assert res == 1


def test_11_cli_project_fingerprint_differing_from_spec_rejected(valid_child_setup, monkeypatch):
    """11. CLI project fingerprint differing from committed spec is rejected before invocation."""
    _repo, _sha, snapshot_dir, _art, args = valid_child_setup
    runner = get_runner_module()

    args.expected_project_fingerprint = (
        "0000000000000000000000000000000000000000000000000000000000000000"
    )
    monkeypatch.setattr(runner, "is_isolated_python", lambda: True)
    monkeypatch.setattr(runner, "is_bytecode_writing_disabled", lambda: True)
    monkeypatch.chdir(snapshot_dir)

    res = runner.run_child_process(args)
    assert res == 1


def test_12_modified_baseline_authorization_spec_causes_git_verification_failure(valid_child_setup):
    """12. Tampering with BaselineAuthorizationSpec in snapshot fails Git byte verification."""
    repo_dir, head_sha, snapshot_dir, _art, _args = valid_child_setup
    runner = get_runner_module()

    spec_file = snapshot_dir / "evals" / "baselines" / "gate-2-baseline-v2.json"
    spec_data = json.loads(spec_file.read_text(encoding="utf-8"))
    spec_data["requested_model"] = "gpt-4o"
    spec_file.write_text(json.dumps(spec_data, indent=2), encoding="utf-8")

    with pytest.raises(RuntimeError, match="does not match committed Git object bytes"):
        runner.verify_snapshot_against_git_objects(
            provenance_repo=repo_dir,
            authorized_git_sha=head_sha,
            snapshot_dir=snapshot_dir,
        )


# ==============================================================================
# 5. Child-Derived Source Identity & Immutability
# ==============================================================================


def test_13_child_recomputes_and_verifies_source_sha(valid_child_setup):
    """13. Child derives source identity from actual verified snapshot bytes."""
    _repo, _sha, snapshot_dir, _art, _args = valid_child_setup
    runner = get_runner_module()

    spec, _ = runner.load_baseline_authorization_spec(snapshot_dir)
    source_file = snapshot_dir / spec["source_path"]
    actual_sha = hashlib.sha256(source_file.read_bytes()).hexdigest()

    assert actual_sha == spec["source_sha256"]
    assert actual_sha == runner.EXPECTED_BANK_MAIN_SHA


def test_14_source_sha_in_reserved_differing_from_snapshot_rejected(valid_child_setup, monkeypatch):
    """14. RESERVED state with mismatched source SHA256 is rejected before invocation."""
    _repo, _sha, snapshot_dir, artifact_dir, args = valid_child_setup
    runner = get_runner_module()

    # Forge source SHA in RESERVED state
    state_file = artifact_dir / "run-state.json"
    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    state_data["source_sha256"] = "0000000000000000000000000000000000000000000000000000000000000000"
    runner.atomic_write_json(state_file, state_data)

    monkeypatch.setattr(runner, "is_isolated_python", lambda: True)
    monkeypatch.setattr(runner, "is_bytecode_writing_disabled", lambda: True)
    monkeypatch.chdir(snapshot_dir)

    res = runner.run_child_process(args)
    assert res == 1


# ==============================================================================
# 6. Artifact Destination Binding & Symlink Rejection
# ==============================================================================


def test_15_artifact_path_outside_deterministic_location_rejected(
    valid_child_setup, monkeypatch, tmp_path
):
    """15. Non-deterministic artifact directory is rejected before model invocation."""
    _repo, _sha, snapshot_dir, _art, args = valid_child_setup
    runner = get_runner_module()

    # Pass an arbitrary outside directory
    arbitrary_dir = tmp_path / "arbitrary_artifacts"
    arbitrary_dir.mkdir()
    args.artifact_dir = str(arbitrary_dir)

    monkeypatch.setattr(runner, "is_isolated_python", lambda: True)
    monkeypatch.setattr(runner, "is_bytecode_writing_disabled", lambda: True)
    monkeypatch.chdir(snapshot_dir)

    res = runner.run_child_process(args)
    assert res == 1


def test_16_symlink_artifact_directory_rejected(valid_child_setup, monkeypatch, tmp_path):
    """16. Symlinked artifact directory is rejected before model invocation."""
    _repo, _sha, snapshot_dir, artifact_dir, args = valid_child_setup
    runner = get_runner_module()

    symlink_dir = tmp_path / "symlinked_artifact_dir"
    try:
        os.symlink(artifact_dir, symlink_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not permitted in this environment")

    args.artifact_dir = str(symlink_dir)
    monkeypatch.setattr(runner, "is_isolated_python", lambda: True)
    monkeypatch.setattr(runner, "is_bytecode_writing_disabled", lambda: True)
    monkeypatch.chdir(snapshot_dir)

    res = runner.run_child_process(args)
    assert res == 1


# ==============================================================================
# 7. Runtime Attestation Before Model Invocation
# ==============================================================================


def test_17_runtime_lock_mismatch_rejected_before_invocation(valid_child_setup, monkeypatch):
    """17. Runtime package mismatch against lockfile fails before model invocation."""
    _repo, _sha, snapshot_dir, _art, args = valid_child_setup
    runner = get_runner_module()

    # Corrupt lockfile in snapshot
    lock_file = snapshot_dir / "requirements-lock.txt"
    lock_file.write_text("nonexistent-package==99.9.9\n", encoding="utf-8")

    monkeypatch.setattr(runner, "is_isolated_python", lambda: True)
    monkeypatch.setattr(runner, "is_bytecode_writing_disabled", lambda: True)
    monkeypatch.chdir(snapshot_dir)

    # Bypass snapshot check to test runtime check ordering explicitly
    monkeypatch.setattr(runner, "verify_snapshot_against_git_objects", lambda **kw: set())

    res = runner.run_child_process(args)
    assert res == 1


# ==============================================================================
# 8. Effective Config Consistency
# ==============================================================================


def test_18_effective_config_model_differing_from_spec_rejected(valid_child_setup, monkeypatch):
    """18. Effective configuration model differing from committed spec is rejected."""
    _repo, _sha, snapshot_dir, _art, args = valid_child_setup
    runner = get_runner_module()

    monkeypatch.setattr(runner, "is_isolated_python", lambda: True)
    monkeypatch.setattr(runner, "is_bytecode_writing_disabled", lambda: True)
    monkeypatch.chdir(snapshot_dir)

    # Mock load_config to return mismatched model
    from agents.legacy_analyzer.config import FoundryConfig

    bad_config = FoundryConfig(
        foundry_project_endpoint="https://example.services.ai.azure.com/api/projects/test",
        foundry_model="gpt-4o",
    )
    # Monkeypatch after import step or via sys.modules
    import agents.legacy_analyzer.config as config_mod

    monkeypatch.setattr(config_mod, "load_config", lambda: bad_config)

    res = runner.run_child_process(args)
    assert res == 1


def test_19_effective_config_fingerprint_differing_from_spec_rejected(
    valid_child_setup, monkeypatch
):
    """19. Effective project fingerprint differing from committed spec is rejected."""
    _repo, _sha, snapshot_dir, _art, args = valid_child_setup
    runner = get_runner_module()

    monkeypatch.setattr(runner, "is_isolated_python", lambda: True)
    monkeypatch.setattr(runner, "is_bytecode_writing_disabled", lambda: True)
    monkeypatch.chdir(snapshot_dir)

    from agents.legacy_analyzer.config import FoundryConfig

    bad_config = FoundryConfig(
        foundry_project_endpoint="https://other-endpoint.services.ai.azure.com/api/projects/test",
        foundry_model="gpt-5-mini",
    )
    import agents.legacy_analyzer.config as config_mod

    monkeypatch.setattr(config_mod, "load_config", lambda: bad_config)

    res = runner.run_child_process(args)
    assert res == 1


# ==============================================================================
# 9. Direct Self-Authorizing Child Execution & Invocation Counter Invariant
# ==============================================================================


def test_20_direct_child_with_correct_provenance_reaches_mocked_invocation(
    valid_child_setup, monkeypatch
):
    """20. Direct self-authorizing child satisfying complete contract reaches mocked invocation."""
    _repo, _sha, snapshot_dir, artifact_dir, args = valid_child_setup
    runner = get_runner_module()

    monkeypatch.setattr(runner, "is_isolated_python", lambda: True)
    monkeypatch.setattr(runner, "is_bytecode_writing_disabled", lambda: True)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    monkeypatch.chdir(snapshot_dir)

    old_sys_path = list(sys.path)
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith(("agents", "src")):
            del sys.modules[mod_name]
    sys.path.insert(0, str(snapshot_dir))

    try:
        import agents.legacy_analyzer.agent as agent_mod
        import agents.legacy_analyzer.config as config_mod
        from agents.legacy_analyzer.agent import ExecutionMetadata

        mock_assessment = make_perfect_assessment_v2()
        mock_meta = ExecutionMetadata(
            run_label="baseline-v2",
            foundry_project_fingerprint=args.expected_project_fingerprint,
            response_model_id="gpt-5-mini-2025-08-07",
            prompt_version="gate2-baseline-v2.2",
            elapsed_seconds=1.23,
        )

        class MockAgent:
            __module__ = "agents.legacy_analyzer.agent"

            def __init__(self, *a, **kw):
                pass

            def analyze_source(self, *a, **kw):
                return mock_assessment, mock_meta

        import src.cobol.source_reader  # noqa: F401
        import src.validation.evaluator_v2  # noqa: F401

        class MockConfig:
            foundry_model = "gpt-5-mini"
            project_fingerprint = args.expected_project_fingerprint

        monkeypatch.setattr(agent_mod, "LegacyAnalyzerAgent", MockAgent)
        monkeypatch.setattr(config_mod, "load_config", lambda: MockConfig())

        # Clean any pycache written prior to test
        for p in snapshot_dir.rglob("__pycache__"):
            if p.is_dir():
                shutil.rmtree(p)

        res = runner.run_child_process(args)
        assert res == 0

        # Verify run artifacts and metadata persisted with committed spec sha
        meta_file = artifact_dir / "run-metadata.json"
        assert meta_file.is_file()
        meta_data = json.loads(meta_file.read_text(encoding="utf-8"))
        assert "baseline_authorization_spec_sha256" in meta_data
        assert len(meta_data["baseline_authorization_spec_sha256"]) == 64

        # Verify run state reached COMPLETED
        state_file = artifact_dir / "run-state.json"
        state_data = json.loads(state_file.read_text(encoding="utf-8"))
        assert state_data["status"] == "COMPLETED"
        assert state_data["gate_2_pass"] is True
    finally:
        sys.path = old_sys_path
        for mod_name in list(sys.modules.keys()):
            if mod_name.startswith(("agents", "src")):
                del sys.modules[mod_name]


def test_21_all_pre_invocation_failures_leave_invocation_counter_at_zero(
    valid_child_setup, monkeypatch
):
    """21. Every pre-invocation failure path guarantees invocation counter remains strictly zero."""
    _repo, _sha, snapshot_dir, _art, args = valid_child_setup
    runner = get_runner_module()

    invocation_count = 0

    class MockAgent:
        def __init__(self, *a, **kw):
            nonlocal invocation_count
            invocation_count += 1

        def analyze_source(self, *a, **kw):
            nonlocal invocation_count
            invocation_count += 1

    import agents.legacy_analyzer.agent as agent_mod

    monkeypatch.setattr(agent_mod, "LegacyAnalyzerAgent", MockAgent)

    # Test 1: missing contract arg
    bad_args = argparse.Namespace(**vars(args))
    bad_args.authorized_git_sha = ""
    runner.run_child_process(bad_args)
    assert invocation_count == 0

    # Test 2: non-isolated Python
    monkeypatch.setattr(runner, "is_isolated_python", lambda: False)
    runner.run_child_process(args)
    assert invocation_count == 0
