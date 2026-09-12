"""H5 Pre-Freeze Comprehensive Remediation Regressions.

Verifies:
1. Real OpenAI HTTP Transport Request Serialization (F1)
2. Existence-based Atomic Attempt Claim Irrevocability & Concurrency (F2)
3. Snapshot Inventory Walk & Strict File Verification (F3)
4. Contained Post-Provider Path & Safe Failure Preservation (F4)
5. Irreversible Sealing Boundary & Post-Seal Coordination Failure Isolation (F5)
6. Canonical Evidence Identity Propagation End-to-End & Basename Duplicate Catch (F6)
7. Real Preflight Identity Checks with Zero Sentinels (F7)
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
from typing import Any

import httpx2
import pytest
from openai import OpenAI

from agents.legacy_analyzer.config import FoundryConfig
from agents.legacy_analyzer.schemas.system_assessment import (
    ProgramDeclaration,
    SourceEvidence,
    SystemAssessment,
)
from agents.legacy_analyzer.schemas.system_export import (
    get_system_responses_text_format,
)
from agents.legacy_analyzer.system_agent import SystemAnalyzerAgent
from src.cobol.multi_source_reader import read_system_bundle
from src.cobol.system_cobol_parser import SystemCobolParser
from src.cobol.system_support_index import SystemSupportIndex
from src.validation.evaluator_v3 import SystemEvaluatorV3, load_golden_assessment

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def get_run_gate_3_module():
    """Load scripts/run-gate-3.py dynamically."""
    spec = importlib.util.spec_from_file_location(
        "run_gate_3_mod_h5", REPO_ROOT / "scripts" / "run-gate-3.py"
    )
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    raise ImportError("Failed to load scripts/run-gate-3.py")


# ======================================================================
# 1. REAL OPENAI HTTP TRANSPORT REGRESSION (F1)
# ======================================================================


def test_h5_transport_serialized_http_body(monkeypatch: pytest.MonkeyPatch):
    """Test real OpenAI SDK request serialization by calling real agent.invoke_raw().

    Validates that the outgoing serialized HTTP request body sent to the Responses API
    contains text.format matching get_system_responses_text_format() directly,
    without any outer json_schema envelope bug.
    """
    captured_requests: list[httpx2.Request] = []

    def mock_handler(request: httpx2.Request) -> httpx2.Response:
        captured_requests.append(request)
        # Return a valid minimal Responses API completed mock response
        mock_body = {
            "id": "resp_test_mock_transport",
            "model": "gpt-5-mini",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "text",
                            "text": SystemAssessment(
                                system_name="Core Banking System"
                            ).model_dump_json(),
                        }
                    ],
                }
            ],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
            },
        }
        return httpx2.Response(200, json=mock_body, request=request)

    mock_transport = httpx2.MockTransport(mock_handler)
    mock_http_client = httpx2.Client(transport=mock_transport)

    real_client = OpenAI(
        api_key="mock-test-key-offline",
        base_url="https://mock.azure.openai.com/v1",
        http_client=mock_http_client,
        max_retries=0,
    )

    cfg = FoundryConfig(
        foundry_project_endpoint="https://mock.azure.openai.com",
        foundry_model="gpt-5-mini",
    )
    agent = SystemAnalyzerAgent(config=cfg, reasoning_effort="low")
    monkeypatch.setattr(agent, "_get_openai_client", lambda: real_client)

    bundle = read_system_bundle(REPO_ROOT)
    resp, meta, raw_json = agent.invoke_raw(
        bundle=bundle,
        run_label="test-transport",
        repo_root=REPO_ROOT,
        git_commit_sha="test_sha",
    )

    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.method == "POST"
    assert "/responses" in str(req.url)

    req_body = json.loads(req.content.decode("utf-8"))
    assert req_body["model"] == "gpt-5-mini"
    assert "text" in req_body
    assert "format" in req_body["text"]

    text_format = req_body["text"]["format"]
    expected_format = get_system_responses_text_format()

    # The serialized format must exactly match get_system_responses_text_format()
    assert text_format == expected_format
    assert text_format["type"] == "json_schema"
    assert text_format["name"] == "SystemAssessment"
    assert text_format["strict"] is True
    assert "schema" in text_format
    assert "properties" in text_format["schema"]
    # Verify no double wrapping: text_format must NOT contain a nested "json_schema" key
    assert "json_schema" not in text_format


# ======================================================================
# 2. ATTEMPT CLAIM CONCURRENCY & IRREVOCABILITY (F2)
# ======================================================================


def _claim_worker(
    artifact_dir: str,
    barrier: Any,
    results_queue: Any,
    run_label: str,
):
    """Worker process attempting to acquire attempt claim."""
    mod = get_run_gate_3_module()
    barrier.wait()
    try:
        mod.acquire_atomic_attempt_claim(
            artifact_dir=Path(artifact_dir),
            gate=3,
            run_label=run_label,
            candidate_sha="test_cand_sha",
            authorization_commit_sha="test_auth_sha",
        )
        results_queue.put(("SUCCESS", os.getpid()))
    except mod.AttemptClaimCollisionError:
        results_queue.put(("COLLISION", os.getpid()))
    except Exception as e:
        results_queue.put(("ERROR", str(e)))


def test_h5_atomic_attempt_claim_multiprocess_race(tmp_path: Path):
    """Verify that under multiprocess race, exactly ONE process acquires the claim file."""
    mod = get_run_gate_3_module()
    out_dir = tmp_path / "claim_race_dir"
    out_dir.mkdir(parents=True, exist_ok=True)

    barrier = multiprocessing.Barrier(2)
    results_queue: multiprocessing.Queue[Any] = multiprocessing.Queue()

    p1 = multiprocessing.Process(
        target=_claim_worker,
        args=(str(out_dir), barrier, results_queue, "race-run"),
    )
    p2 = multiprocessing.Process(
        target=_claim_worker,
        args=(str(out_dir), barrier, results_queue, "race-run"),
    )

    p1.start()
    p2.start()
    p1.join(timeout=10)
    p2.join(timeout=10)

    results = []
    while not results_queue.empty():
        results.append(results_queue.get_nowait())

    assert len(results) == 2
    statuses = [r[0] for r in results]
    assert statuses.count("SUCCESS") == 1, f"Expected exactly 1 SUCCESS, got: {statuses}"
    assert statuses.count("COLLISION") == 1, f"Expected exactly 1 COLLISION, got: {statuses}"

    claim_path = out_dir / mod.ATTEMPT_CLAIM_FILE
    assert claim_path.is_file()
    claim_data = json.loads(claim_path.read_text(encoding="utf-8"))
    assert claim_data["gate"] == 3
    assert claim_data["run_label"] == "race-run"

    # Existing claim blocks any subsequent check_existing_reservation
    with pytest.raises(RuntimeError, match="Irrevocable reservation error"):
        mod.check_existing_reservation(out_dir, "race-run")


def test_h5_corrupted_attempt_claim_remains_consumed(tmp_path: Path):
    """Empty or malformed claim file still consumes the attempt irrevocably."""
    mod = get_run_gate_3_module()
    out_dir = tmp_path / "corrupt_claim_dir"
    out_dir.mkdir(parents=True, exist_ok=True)
    claim_path = out_dir / mod.ATTEMPT_CLAIM_FILE

    # Touch empty file
    claim_path.write_bytes(b"")

    with pytest.raises(RuntimeError, match="Irrevocable reservation error"):
        mod.check_existing_reservation(out_dir, "corrupt-run")

    with pytest.raises(mod.AttemptClaimCollisionError):
        mod.acquire_atomic_attempt_claim(
            artifact_dir=out_dir,
            gate=3,
            run_label="corrupt-run",
            candidate_sha="test_cand",
            authorization_commit_sha="test_auth",
        )


# ======================================================================
# 3. SNAPSHOT INVENTORY REJECTS UNAUTHORIZED / EXTRA FILES (F3)
# ======================================================================


def test_h5_snapshot_inventory_walk_rejects_unauthorized_files(tmp_path: Path):
    """Verify verify_snapshot_against_git_objects strictly rejects unauthorized files."""
    mod = get_run_gate_3_module()
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    # Get current commit HEAD
    env = mod.get_sanitized_git_env()
    import subprocess

    rev_res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    head_sha = rev_res.stdout.strip()

    # Extract clean archive
    mod.create_git_snapshot_archive(head_sha, snapshot_dir, repo_root=REPO_ROOT)

    # 1. Clean archive passes verification
    expected = mod.verify_snapshot_against_git_objects(REPO_ROOT, head_sha, snapshot_dir)
    assert len(expected) > 0

    # 2. Injected extra __init__.py in src/
    init_file = snapshot_dir / "src" / "__init__.py"
    init_file.write_text("# malicious init\n", encoding="utf-8")
    with pytest.raises(
        RuntimeError, match="Unauthorized extra Python package initializer in snapshot"
    ):
        mod.verify_snapshot_against_git_objects(REPO_ROOT, head_sha, snapshot_dir)
    init_file.unlink()

    # 3. Injected sitecustomize.py
    site_cust = snapshot_dir / "sitecustomize.py"
    site_cust.write_text("# sitecustomize\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Unauthorized Python customization module in snapshot"):
        mod.verify_snapshot_against_git_objects(REPO_ROOT, head_sha, snapshot_dir)
    site_cust.unlink()

    # 4. Injected .pth file
    pth_file = snapshot_dir / "evil.pth"
    pth_file.write_text("/tmp\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Unauthorized Python .pth file in snapshot"):
        mod.verify_snapshot_against_git_objects(REPO_ROOT, head_sha, snapshot_dir)
    pth_file.unlink()

    # 5. Injected symlink
    symlink_file = snapshot_dir / "symlink_file"
    try:
        symlink_file.symlink_to(snapshot_dir / "README.md")
        with pytest.raises(RuntimeError, match="Unauthorized symlink in snapshot"):
            mod.verify_snapshot_against_git_objects(REPO_ROOT, head_sha, snapshot_dir)
    except OSError:
        pass  # Windows unprivileged symlink permission fallback


# ======================================================================
# 4. POST-PROVIDER CONTAINMENT & SAFE PRESERVATION (F4)
# ======================================================================


def test_h5_safe_preserve_artifact_records_failures(tmp_path: Path):
    """Verify safe_preserve_artifact records I/O failures instead of crashing."""
    mod = get_run_gate_3_module()
    failures: list[dict[str, str]] = []

    # Writing to a directory path as file will fail with IsADirectoryError or PermissionError
    dir_path = tmp_path / "a_directory"
    dir_path.mkdir(parents=True, exist_ok=True)

    success = mod.safe_preserve_artifact(dir_path, {"data": 123}, is_json=True, failures=failures)
    assert success is False
    assert len(failures) == 1
    assert failures[0]["file"] == "a_directory"
    assert "error" in failures[0]


def test_h5_finalize_post_model_failure_never_crashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Verify finalize_post_model_failure absorbs write failures and writes terminal-result."""
    mod = get_run_gate_3_module()
    out_dir = tmp_path / "failure_test_dir"
    out_dir.mkdir(parents=True, exist_ok=True)
    res_file = out_dir / mod.RESERVATION_STATE_FILE

    orig_atomic = mod.atomic_write_json

    def failing_atomic(path, data):
        if Path(path).name == "authorization-spec.json":
            raise OSError("Injected disk write failure for authorization-spec.json")
        return orig_atomic(path, data)

    monkeypatch.setattr(mod, "atomic_write_json", failing_atomic)

    spec = {
        "gate": 3,
        "spec_version": "3.4.2",
        "run_label": "test-failure-absorption",
    }

    # Must complete without throwing any exception!
    mod.finalize_post_model_failure(
        artifact_dir=out_dir,
        reservation_file=res_file,
        error_phase="TEST_INJECTION",
        error=RuntimeError("Simulated primary error"),
        spec=spec,
        candidate_sha="cand_sha",
        authorization_commit_sha="auth_sha",
        authorized_sha="auth_sha",
        run_label="test-failure-absorption",
        raw_response_content='{"mock": 1}',
    )

    term_path = out_dir / mod.TERMINAL_RESULT_FILE
    assert term_path.is_file()
    term_data = json.loads(term_path.read_text(encoding="utf-8"))
    assert term_data["status"] == "FAILED"
    assert term_data["error_phase"] == "TEST_INJECTION"
    assert "artifact_write_failures" in term_data
    failed_files = [f["file"] for f in term_data["artifact_write_failures"]]
    assert "authorization-spec.json" in failed_files

    manifest_path = out_dir / "manifest.json"
    assert manifest_path.is_file()
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_data["status"] == "FAILED"
    assert "raw-response.json" in manifest_data["artifacts"]


# ======================================================================
# 5. IRREVERSIBLE SEAL & POST-SEAL COORDINATION FAILURE (F5)
# ======================================================================


def test_h5_post_seal_coordination_failure_preserves_immutable_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """When coordination write fails after manifest publication, immutable bytes remain valid."""
    mod = get_run_gate_3_module()
    out_dir = tmp_path / "sealed_dir"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Mock child environment checks
    monkeypatch.setattr(mod, "is_isolated_python", lambda: True)
    monkeypatch.setattr(mod, "is_bytecode_writing_disabled", lambda: True)
    monkeypatch.setattr(mod, "verify_trusted_runner_bootstrap", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "verify_snapshot_against_git_objects", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "verify_runtime_environment", lambda *a, **kw: ({}, "fake"))
    monkeypatch.setattr(mod, "validate_authorization_contract", lambda *a, **kw: None)

    # Prepare minimal synthetic test
    spec_path = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH
    spec, _ = mod.load_authorization_spec(spec_path)
    spec["run_label"] = "test-post-seal"
    temp_spec_file = tmp_path / "temp-spec.json"
    temp_spec_file.write_text(json.dumps(spec), encoding="utf-8")

    res_file = out_dir / mod.RESERVATION_STATE_FILE
    mod.atomic_write_json(
        res_file,
        {
            "status": "RESERVED",
            "run_label": "test-post-seal",
            "gate": 3,
            "candidate_git_sha": "",
            "authorization_commit_sha": "auth_sha",
        },
    )

    args = argparse.Namespace(
        provenance_repo=str(REPO_ROOT),
        snapshot_dir=str(REPO_ROOT),
        artifact_dir=str(out_dir),
        auth_spec=str(temp_spec_file),
        run_label="test-post-seal",
        authorized_git_sha="",
        authorization_commit_sha="auth_sha",
        golden_path=str(REPO_ROOT / mod.DEFAULT_GOLDEN_PATH),
        synthetic=True,
        dry_run=False,
        allow_dirty=True,
    )

    # Monkeypatch atomic_write_json only when writing reservation_file with status == COMPLETED
    orig_atomic_write = mod.atomic_write_json

    def guarded_atomic_write(dest, data):
        if dest == res_file and isinstance(data, dict) and data.get("status") == "COMPLETED":
            raise PermissionError("Simulated post-seal disk permission failure")
        return orig_atomic_write(dest, data)

    monkeypatch.setattr(mod, "atomic_write_json", guarded_atomic_write)

    ret = mod.execute_internal_child(args)
    # Post-seal coordination failure returns 1
    assert ret == 1

    # But manifest.json and terminal-result.json were already sealed and published!
    manifest_path = out_dir / "manifest.json"
    assert manifest_path.is_file()
    term_path = out_dir / mod.TERMINAL_RESULT_FILE
    assert term_path.is_file()

    term_data = json.loads(term_path.read_text(encoding="utf-8"))
    assert term_data["status"] == "COMPLETED"
    assert term_data["gate_3_pass"] is True

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_data["gate_3_pass"] is True
    assert "terminal-result.json" in manifest_data["artifacts"]

    # Check all manifest hashes remain 100% valid
    for fname, exp_sha in manifest_data["artifacts"].items():
        act_sha = hashlib.sha256((out_dir / fname).read_bytes()).hexdigest()
        assert act_sha == exp_sha

    # coordination-failure.json was written and is NOT in manifest
    assert (out_dir / "coordination-failure.json").is_file()
    assert "coordination-failure.json" not in manifest_data["artifacts"]


# ======================================================================
# 6. CANONICAL EVIDENCE IDENTITY END-TO-END (F6)
# ======================================================================


def test_h5_basename_duplicate_caught_by_evaluator():
    """Basename alias predictions are canonicalized BEFORE duplicate detection.

    Proves that emitting one prediction with full path and another with basename alias
    produces a duplicate penalty (duplicate_count == 1), failing Gate 3.
    """
    bundle = read_system_bundle(REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, bundle, file_status_certificate=parser.file_status_certificate
    )

    golden_path = REPO_ROOT / "evals" / "expected" / "system-understanding-v3.json"
    golden_assessment = load_golden_assessment(golden_path)

    evaluator = SystemEvaluatorV3(index, golden_dataset_path=golden_path)

    # Clone golden assessment and inject a duplicate with basename alias
    assessment_dict = golden_assessment.model_dump()
    prog_decls = list(assessment_dict.get("program_declarations", []))
    assert len(prog_decls) > 0

    # First declaration is canonical path
    first_decl = prog_decls[0]
    canonical_path = first_decl["evidence"]["file_path"]
    assert "/" in canonical_path

    # Duplicate prediction with basename alias
    basename_path = Path(canonical_path).name
    dup_decl = dict(first_decl)
    dup_decl["evidence"] = {
        "file_path": basename_path,
        "line_start": first_decl["evidence"]["line_start"],
        "line_end": first_decl["evidence"]["line_end"],
    }
    prog_decls.append(dup_decl)
    assessment_dict["program_declarations"] = prog_decls

    mutated_assessment = SystemAssessment.model_validate(assessment_dict)
    eval_result, predictions = evaluator.evaluate_assessment(mutated_assessment)

    # Duplicate was caught!
    assert eval_result.duplicate_prediction_count == 1
    assert eval_result.supported_predicted_count == 59
    assert eval_result.raw_predicted_count == 60
    assert eval_result.gate_3_pass is False


def test_h5_backslash_path_normalization():
    """Backslashes normalize to canonical repository-relative path."""
    bundle = read_system_bundle(REPO_ROOT)
    resolved = bundle.resolve_canonical_file_path(r"legacy\core-banking-system\BANK-MAIN.CBL")
    assert resolved == "legacy/core-banking-system/BANK-MAIN.CBL"


def test_h5_ambiguous_and_unknown_path_handling():
    """Ambiguous or unknown file aliases raise ValueError/KeyError and become unsupported."""
    bundle = read_system_bundle(REPO_ROOT)

    with pytest.raises(KeyError, match="not found"):
        bundle.resolve_canonical_file_path("UNKNOWN.CBL")

    # In evaluator, unknown path does not crash the evaluation, but marks prediction invalid
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, bundle, file_status_certificate=parser.file_status_certificate
    )
    golden_path = REPO_ROOT / "evals" / "expected" / "system-understanding-v3.json"
    evaluator = SystemEvaluatorV3(index, golden_dataset_path=golden_path)

    assessment = SystemAssessment(
        system_name="Core Banking System",
        program_declarations=[
            ProgramDeclaration(
                program_id="GHOST",
                evidence=SourceEvidence(
                    file_path="NONEXISTENT.CBL",
                    line_start=1,
                    line_end=2,
                ),
            )
        ],
    )

    eval_result, preds = evaluator.evaluate_assessment(assessment)
    assert len(preds) == 1
    assert preds[0].is_supported is False
    assert preds[0].matched_proposition_id is None


# ======================================================================
# 7. REAL PREFLIGHT IDENTITY CHECKS WITH ZERO SENTINELS (F7)
# ======================================================================


def test_h5_preflight_identity_checks_real_child_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Execute execute_internal_child with mismatches, proving sentinels == 0."""
    mod = get_run_gate_3_module()
    out_dir = tmp_path / "preflight_test_dir"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Mock child environment checks
    monkeypatch.setattr(mod, "is_isolated_python", lambda: True)
    monkeypatch.setattr(mod, "is_bytecode_writing_disabled", lambda: True)
    monkeypatch.setattr(mod, "verify_trusted_runner_bootstrap", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "verify_snapshot_against_git_objects", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "verify_runtime_environment", lambda *a, **kw: ({}, "fake"))
    monkeypatch.setattr(mod, "validate_authorization_contract", lambda *a, **kw: None)

    spec_path = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH
    spec, _ = mod.load_authorization_spec(spec_path)
    spec["run_label"] = "test-preflight"
    temp_spec_file = tmp_path / "spec.json"
    temp_spec_file.write_text(json.dumps(spec), encoding="utf-8")

    sentinel_call_count = 0

    def mock_invoke_raw_should_never_run(*args, **kwargs):
        nonlocal sentinel_call_count
        sentinel_call_count += 1
        raise AssertionError("invoke_raw was called on preflight failure!")

    monkeypatch.setattr(SystemAnalyzerAgent, "invoke_raw", mock_invoke_raw_should_never_run)

    # 1. Model mismatch
    from agents.legacy_analyzer import config as cfg_mod

    mismatched_cfg = cfg_mod.FoundryConfig(
        foundry_project_endpoint="https://example.foundry.azure.com",
        foundry_model="gpt-4o",  # Mismatched model (spec expects gpt-5-mini)
    )
    monkeypatch.setattr(cfg_mod, "load_config", lambda: mismatched_cfg)

    args = argparse.Namespace(
        provenance_repo=str(REPO_ROOT),
        snapshot_dir=str(REPO_ROOT),
        artifact_dir=str(out_dir),
        auth_spec=str(temp_spec_file),
        run_label="test-preflight",
        authorized_git_sha="",
        authorization_commit_sha="",
        golden_path=str(REPO_ROOT / mod.DEFAULT_GOLDEN_PATH),
        synthetic=False,
        dry_run=False,
        allow_dirty=True,
    )

    ret = mod.execute_internal_child(args)
    assert ret == 1
    assert sentinel_call_count == 0

    # Claim file must NOT have been created
    assert not (out_dir / mod.ATTEMPT_CLAIM_FILE).exists()

    # 2. Project fingerprint mismatch
    mismatched_fp_cfg = cfg_mod.FoundryConfig(
        foundry_project_endpoint="https://different.foundry.azure.com",
        foundry_model="gpt-5-mini",
    )
    monkeypatch.setattr(cfg_mod, "load_config", lambda: mismatched_fp_cfg)

    ret2 = mod.execute_internal_child(args)
    assert ret2 == 1
    assert sentinel_call_count == 0
    assert not (out_dir / mod.ATTEMPT_CLAIM_FILE).exists()
