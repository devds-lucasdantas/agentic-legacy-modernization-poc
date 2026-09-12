"""Unit and regression tests for Gate 3 runner, authorization contract, and snapshot isolation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def get_run_gate_3_module():
    """Load scripts/run-gate-3.py dynamically."""
    spec = importlib.util.spec_from_file_location(
        "run_gate_3_module", REPO_ROOT / "scripts" / "run-gate-3.py"
    )
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    raise ImportError("Failed to load scripts/run-gate-3.py")


def test_validate_run_label():
    """Verify run-label validation prevents path traversal."""
    mod = get_run_gate_3_module()
    mod.validate_run_label("baseline-v1")
    mod.validate_run_label("run_2026_09_11")
    mod.validate_run_label("test.run-1")

    with pytest.raises(ValueError):
        mod.validate_run_label("../escaped")
    with pytest.raises(ValueError):
        mod.validate_run_label("/absolute/path")
    with pytest.raises(ValueError):
        mod.validate_run_label(".hidden")
    with pytest.raises(ValueError):
        mod.validate_run_label("invalid/slash")


def test_load_authorization_spec_valid():
    """Verify loading the official Gate 3 authorization spec and all Blocker 10 required fields."""
    mod = get_run_gate_3_module()
    spec_path = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH
    spec, sha256 = mod.load_authorization_spec(spec_path)

    assert spec["gate"] == 3
    assert spec["run_label"] == "baseline-v1"
    assert spec["requested_model"] == "gpt-5-mini"
    assert spec["schema_version"] == "3.4.2"
    assert spec["evaluator_version"] == "3.4.2"
    assert spec["golden_dataset_version"] == "3.4.2"
    assert len(spec["target_bundle"]) == 6
    assert len(sha256) == 64

    # Blocker 10 required fields
    assert "candidate_git_sha" in spec
    assert "expected_git_sha" not in spec
    assert spec["reasoning_effort"] == "low"
    assert len(spec["prompt_sha256"]) == 64
    assert len(spec["wire_schema_sha256"]) == 64
    assert len(spec["source_manifest_sha256"]) == 64
    assert spec["bundle_serialization_version"] == "1.0.0"
    assert len(spec["bundle_sha256"]) == 64
    assert len(spec["dependency_lock_sha256"]) == 64
    assert len(spec["foundry_project_fingerprint"]) == 64
    assert spec["openai_client_max_retries"] == 0
    assert spec["application_model_retries"] == 0
    assert spec["maximum_model_attempts"] == 1
    assert spec["maximum_logical_invocation_count"] == 1


def test_load_authorization_spec_invalid_gate(tmp_path: Path):
    """Verify rejection when gate is not 3."""
    mod = get_run_gate_3_module()
    spec_path = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH
    spec, _ = mod.load_authorization_spec(spec_path)
    spec["gate"] = 2

    bad_spec = tmp_path / "bad-spec.json"
    bad_spec.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(ValueError, match="gate must be 3"):
        mod.load_authorization_spec(bad_spec)


def test_load_authorization_spec_invalid_retries(tmp_path: Path):
    """Verify rejection when retry limits violate zero-retry contract."""
    mod = get_run_gate_3_module()
    spec_path = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH
    spec, _ = mod.load_authorization_spec(spec_path)

    bad_spec1 = tmp_path / "bad-retry1.json"
    spec1 = dict(spec, openai_client_max_retries=2)
    bad_spec1.write_text(json.dumps(spec1), encoding="utf-8")
    with pytest.raises(ValueError, match="openai_client_max_retries must be 0"):
        mod.load_authorization_spec(bad_spec1)

    bad_spec2 = tmp_path / "bad-retry2.json"
    spec2 = dict(spec, maximum_model_attempts=2)
    bad_spec2.write_text(json.dumps(spec2), encoding="utf-8")
    with pytest.raises(ValueError, match="maximum_model_attempts must be 1"):
        mod.load_authorization_spec(bad_spec2)


def test_verify_bundle_integrity_passes():
    """Verify multi-source bundle verification on current repository tree."""
    mod = get_run_gate_3_module()
    spec_path = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH
    spec, _ = mod.load_authorization_spec(spec_path)

    entries, b_sha, m_sha = mod.verify_bundle_integrity(REPO_ROOT, spec)
    assert len(entries) == 6
    assert b_sha == spec["bundle_sha256"]
    assert m_sha == spec["source_manifest_sha256"]


def test_verify_bundle_integrity_tampered_fails(tmp_path: Path):
    """Verify tampering any file in bundle fails bundle verification."""
    mod = get_run_gate_3_module()
    spec_path = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH
    spec, _ = mod.load_authorization_spec(spec_path)

    # Copy files to temp
    for item in spec["target_bundle"]:
        src = REPO_ROOT / item["path"]
        dst = tmp_path / item["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())

    # Tamper one file
    tampered_file = tmp_path / "legacy/core-banking-system/BANK-MAIN.CBL"
    tampered_file.write_text("TAMPERED", encoding="utf-8")

    with pytest.raises(RuntimeError, match="SHA mismatch for bundle file"):
        mod.verify_bundle_integrity(tmp_path, spec)


def test_verify_schema_and_prompt_hashes_passes():
    """Verify prompt and wire schema hashes strictly match authorization spec."""
    mod = get_run_gate_3_module()
    spec_path = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH
    spec, _ = mod.load_authorization_spec(spec_path)

    mod.verify_schema_and_prompt_hashes(REPO_ROOT, spec)


def test_live_execution_refused_when_unfrozen(tmp_path: Path):
    """Verify live execution is strictly refused when candidate_git_sha is empty."""
    mod = get_run_gate_3_module()
    spec_path = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH
    spec, _ = mod.load_authorization_spec(spec_path)
    assert spec["candidate_git_sha"] == ""

    out_dir = tmp_path / "live_refused"
    with pytest.raises(RuntimeError, match="Candidate commit is not frozen"):
        mod.execute_gate_3(
            repo_root=REPO_ROOT,
            auth_spec_path=spec_path,
            output_dir=out_dir,
            run_label="baseline-v1",
            synthetic=False,
            dry_run=False,
            allow_dirty=True,
        )


def test_dry_run_preflight_passes(tmp_path: Path):
    """Verify dry-run preflight completes without requiring live credentials or calling models."""
    mod = get_run_gate_3_module()
    spec_path = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH
    out_dir = tmp_path / "dry_run_out"

    exit_code = mod.execute_gate_3(
        repo_root=REPO_ROOT,
        auth_spec_path=spec_path,
        output_dir=out_dir,
        run_label="baseline-v1",
        synthetic=False,
        dry_run=True,
        allow_dirty=True,
    )
    assert exit_code == 0
    state_file = out_dir / mod.RESERVATION_STATE_FILE
    assert state_file.is_file()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["status"] == "DRY_RUN_PASSED"


def test_synthetic_execution_end_to_end(tmp_path: Path):
    """Verify offline synthetic evaluation runs end-to-end and produces all required artifacts."""
    mod = get_run_gate_3_module()
    spec_path = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH
    out_dir = tmp_path / "synthetic_out"

    exit_code = mod.execute_gate_3(
        repo_root=REPO_ROOT,
        auth_spec_path=spec_path,
        output_dir=out_dir,
        run_label="baseline-v1",
        synthetic=True,
        dry_run=False,
        allow_dirty=True,
    )
    assert exit_code == 0

    # Two-layer state model: mutable coordination file exists
    assert (out_dir / mod.RESERVATION_STATE_FILE).is_file()
    res_state = json.loads((out_dir / mod.RESERVATION_STATE_FILE).read_text(encoding="utf-8"))
    assert res_state["status"] == "COMPLETED"

    # 13 immutable artifacts + manifest.json
    expected_immutable_artifacts = [
        "authorization-spec.json",
        "production-prompt.md",
        "wire-schema.json",
        "source-manifest.json",
        "canonical-input-bundle.txt",
        "parser-coverage-certificate.json",
        "runtime-manifest.json",
        "raw-response.json",
        "model-assessment.json",
        "enriched-assessment.json",
        "evaluation.json",
        "run-metadata.json",
        "terminal-result.json",
    ]
    for art in expected_immutable_artifacts:
        assert (out_dir / art).is_file(), f"Missing artifact: {art}"
    assert (out_dir / "manifest.json").is_file()

    eval_data = json.loads((out_dir / "evaluation.json").read_text(encoding="utf-8"))
    summary = eval_data["metric_summary"]
    assert summary["gate_3_pass"] is True
    assert summary["matched_expected_count"] == 59
    assert summary["expected_fact_count"] == 59
    assert summary["precision"] == 1.0
    assert summary["recall"] == 1.0

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["gate_3_pass"] is True
    assert len(manifest["artifacts"]) == 13
    assert mod.RESERVATION_STATE_FILE not in manifest["artifacts"]
    for art in expected_immutable_artifacts:
        assert art in manifest["artifacts"], f"Missing artifact in manifest: {art}"
        actual_sha = hashlib.sha256((out_dir / art).read_bytes()).hexdigest()
        assert manifest["artifacts"][art] == actual_sha, f"SHA mismatch for {art}"
