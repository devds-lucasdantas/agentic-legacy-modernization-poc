"""Unit and regression tests for Gate 3 runner, authorization contract, and snapshot isolation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    assert spec["run_label"] == "baseline-v3"
    assert spec["requested_model"] == "gpt-5-mini"
    assert spec["schema_version"] == "3.5.3"
    assert spec["evaluator_version"] == "3.5.3"
    assert spec["golden_dataset_version"] == "3.5.3"
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
            run_label=spec["run_label"],
            synthetic=False,
            dry_run=False,
            allow_dirty=True,
        )


def test_dry_run_preflight_passes(tmp_path: Path):
    """Verify dry-run preflight completes without requiring live credentials or calling models."""
    mod = get_run_gate_3_module()
    spec_path = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH
    spec, _ = mod.load_authorization_spec(spec_path)
    out_dir = tmp_path / "dry_run_out"

    exit_code = mod.execute_gate_3(
        repo_root=REPO_ROOT,
        auth_spec_path=spec_path,
        output_dir=out_dir,
        run_label=spec["run_label"],
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
    spec, _ = mod.load_authorization_spec(spec_path)
    out_dir = tmp_path / "synthetic_out"

    exit_code = mod.execute_gate_3(
        repo_root=REPO_ROOT,
        auth_spec_path=spec_path,
        output_dir=out_dir,
        run_label=spec["run_label"],
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


def test_f1_cli_default_coherence():
    """Verify F1 CLI default coherence and run-label resolution.

    1. Default CLI configuration resolves to baseline-v2 + v2 spec;
    2. Explicit mismatched run-label/spec fails closed;
    3. Explicit v1 spec + baseline-v1 remains supported for offline historical validation.
    """
    mod = get_run_gate_3_module()
    v1_spec = REPO_ROOT / mod.CANONICAL_BASELINE_SPEC_V1
    v2_spec = REPO_ROOT / mod.CANONICAL_BASELINE_SPEC_V2
    v3_spec = REPO_ROOT / mod.CANONICAL_BASELINE_SPEC_V3
    assert v1_spec.is_file()
    assert v2_spec.is_file()
    assert v3_spec.is_file()

    # 1. Default CLI configuration
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-label",
        default=None,
        help="Identifier for analysis run (defaults to run_label in authorization spec)",
    )
    parser.add_argument("--auth-spec", default=mod.DEFAULT_AUTH_SPEC_PATH, help="Path to auth spec")
    args = parser.parse_args([])
    assert args.auth_spec == mod.CANONICAL_BASELINE_SPEC_V3
    assert args.run_label is None

    spec_v3, _ = mod.load_authorization_spec(REPO_ROOT / args.auth_spec)
    effective_run_label = args.run_label or spec_v3["run_label"]
    assert effective_run_label == "baseline-v3"
    assert spec_v3["run_label"] == effective_run_label

    # 2. Explicit mismatched run-label/spec fails closed
    with pytest.raises(ValueError, match="Run label mismatch"):
        mod.execute_gate_3(
            repo_root=REPO_ROOT,
            auth_spec_path=v2_spec,
            run_label="baseline-v1",
            dry_run=True,
            allow_dirty=True,
        )

    with pytest.raises(ValueError, match="Run label mismatch"):
        mod.execute_gate_3(
            repo_root=REPO_ROOT,
            auth_spec_path=v1_spec,
            run_label="baseline-v2",
            dry_run=True,
            allow_dirty=True,
        )

    # 3. Explicit v1 spec + baseline-v1 remains supported for offline historical validation
    spec_v1, _ = mod.load_authorization_spec(v1_spec)
    assert spec_v1["run_label"] == "baseline-v1"
    entries, b_sha, m_sha = mod.verify_bundle_integrity(REPO_ROOT, spec_v1)
    assert len(entries) == 6
    assert b_sha == spec_v1["bundle_sha256"]
    assert m_sha == spec_v1["source_manifest_sha256"]


def test_f2_authorization_diff_bound_to_selected_spec():
    """Verify F2 authorization diff is strictly bound to the selected auth spec.

    - selected v2 / A changes v1 -> REFUSE
    - selected v1 / A changes v2 -> REFUSE
    - selected v2 / A changes v2 only -> PASS trust check
    - selected v2 / A changes v2 + another file -> REFUSE
    """
    mod = get_run_gate_3_module()
    v1_spec = REPO_ROOT / mod.CANONICAL_BASELINE_SPEC_V1
    v2_spec = REPO_ROOT / mod.CANONICAL_BASELINE_SPEC_V2

    # Case 1: selected v2 / A changes v1 -> REFUSE
    with patch("subprocess.run") as mock_run:

        def side_effect_v1(cmd, **kwargs):
            res = MagicMock()
            res.returncode = 0
            if cmd[1:3] == ["rev-parse", "--verify"]:
                res.stdout = "cand123\n"
            elif cmd[1:3] == ["diff", "--name-only"]:
                res.stdout = "evals/baselines/gate-3-baseline-v1.json\n"
            return res

        mock_run.side_effect = side_effect_v1
        with pytest.raises(RuntimeError, match="must modify strictly and only"):
            mod.validate_authorization_contract(
                repo_root=REPO_ROOT,
                candidate_sha="cand123",
                authorization_commit_sha="auth123",
                auth_spec_path=v2_spec,
                allow_dirty=False,
                is_live=False,
            )

    # Case 2: selected v1 / A changes v2 -> REFUSE
    with patch("subprocess.run") as mock_run:

        def side_effect_v2(cmd, **kwargs):
            res = MagicMock()
            res.returncode = 0
            if cmd[1:3] == ["rev-parse", "--verify"]:
                res.stdout = "cand123\n"
            elif cmd[1:3] == ["diff", "--name-only"]:
                res.stdout = "evals/baselines/gate-3-baseline-v2.json\n"
            return res

        mock_run.side_effect = side_effect_v2
        with pytest.raises(RuntimeError, match="must modify strictly and only"):
            mod.validate_authorization_contract(
                repo_root=REPO_ROOT,
                candidate_sha="cand123",
                authorization_commit_sha="auth123",
                auth_spec_path=v1_spec,
                allow_dirty=False,
                is_live=False,
            )

    # Case 3: selected v2 / A changes v2 only -> PASS
    with patch("subprocess.run") as mock_run:

        def side_effect_pass(cmd, **kwargs):
            res = MagicMock()
            res.returncode = 0
            if cmd[1:3] == ["rev-parse", "--verify"]:
                res.stdout = "cand123\n"
            elif cmd[1:3] == ["diff", "--name-only"]:
                res.stdout = "evals/baselines/gate-3-baseline-v2.json\n"
            return res

        mock_run.side_effect = side_effect_pass
        mod.validate_authorization_contract(
            repo_root=REPO_ROOT,
            candidate_sha="cand123",
            authorization_commit_sha="auth123",
            auth_spec_path=v2_spec,
            allow_dirty=False,
            is_live=False,
        )

    # Case 4: selected v2 / A changes v2 + another file -> REFUSE
    with patch("subprocess.run") as mock_run:

        def side_effect_multi(cmd, **kwargs):
            res = MagicMock()
            res.returncode = 0
            if cmd[1:3] == ["rev-parse", "--verify"]:
                res.stdout = "cand123\n"
            elif cmd[1:3] == ["diff", "--name-only"]:
                res.stdout = "evals/baselines/gate-3-baseline-v2.json\nextra_file.txt\n"
            return res

        mock_run.side_effect = side_effect_multi
        with pytest.raises(RuntimeError, match="must modify strictly and only"):
            mod.validate_authorization_contract(
                repo_root=REPO_ROOT,
                candidate_sha="cand123",
                authorization_commit_sha="auth123",
                auth_spec_path=v2_spec,
                allow_dirty=False,
                is_live=False,
            )


def test_f11_raw_invocation_terminal_failure_sealing(tmp_path: Path):
    """Verify F-11: Raw model invocation failures irrevocably claim an attempt,

    route directly through finalize_post_model_failure, persist run-metadata.json,
    write terminal-result.json, seal manifest.json, produce NO fake response files,
    transition reservation-state.json to FAILED (error_phase=MODEL_INVOCATION),
    and exit 1 with zero retries.
    """
    import argparse

    mod = get_run_gate_3_module()
    spec_path = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH
    spec, spec_sha = mod.load_authorization_spec(spec_path)

    test_artifact_dir = tmp_path / "artifacts" / "gate-3" / "f11-test"
    test_artifact_dir.mkdir(parents=True, exist_ok=True)

    child_args = argparse.Namespace(
        provenance_repo=str(REPO_ROOT),
        snapshot_dir=str(REPO_ROOT),
        artifact_dir=str(test_artifact_dir),
        auth_spec=str(spec_path),
        run_label="f11-test",
        authorized_git_sha="test_candidate_sha_12345",
        authorization_commit_sha="test_auth_commit_sha_12345",
        allow_dirty=True,
        synthetic=False,
        dry_run=False,
        golden_path=None,
    )

    mock_cfg = MagicMock()
    mock_cfg.foundry_model = spec["requested_model"]
    mock_cfg.foundry_project_endpoint = "https://mock.foundry.endpoint"

    mock_agent = MagicMock()
    mock_agent.invoke_raw.side_effect = RuntimeError("Simulated provider endpoint timeout")

    with (
        patch.object(mod, "is_isolated_python", return_value=True),
        patch.object(mod, "is_bytecode_writing_disabled", return_value=True),
        patch.object(mod, "validate_authorization_contract"),
        patch("agents.legacy_analyzer.config.load_config", return_value=mock_cfg),
        patch(
            "agents.legacy_analyzer.config.compute_foundry_project_fingerprint",
            return_value=spec["foundry_project_fingerprint"],
        ),
        patch(
            "agents.legacy_analyzer.system_agent.SystemAnalyzerAgent",
            return_value=mock_agent,
        ),
    ):
        exit_code = mod.execute_internal_child(child_args)

    assert exit_code == 1

    # Exactly 1 model attempt was made, zero retries
    mock_agent.invoke_raw.assert_called_once()

    # 1. Attempt claim file was irrevocably written
    claim_file = test_artifact_dir / mod.ATTEMPT_CLAIM_FILE
    assert claim_file.is_file()
    claim_data = json.loads(claim_file.read_text(encoding="utf-8"))
    assert claim_data["gate"] == 3
    assert claim_data["run_label"] == "f11-test"
    assert claim_data["candidate_git_sha"] == "test_candidate_sha_12345"

    # 2. reservation-state.json transitioned to FAILED with error_phase=MODEL_INVOCATION
    res_file = test_artifact_dir / mod.RESERVATION_STATE_FILE
    assert res_file.is_file()
    res_data = json.loads(res_file.read_text(encoding="utf-8"))
    assert res_data["status"] == "FAILED"
    assert res_data["error_phase"] == "MODEL_INVOCATION"
    assert res_data["error_type"] == "RuntimeError"
    assert "Simulated provider endpoint timeout" in res_data["error_message"]
    assert res_data["candidate_git_sha"] == "test_candidate_sha_12345"

    # 3. terminal-result.json is valid terminal failure record
    term_file = test_artifact_dir / mod.TERMINAL_RESULT_FILE
    assert term_file.is_file()
    term_data = json.loads(term_file.read_text(encoding="utf-8"))
    assert term_data["status"] == "FAILED"
    assert term_data["gate"] == 3
    assert term_data["error_phase"] == "MODEL_INVOCATION"
    assert term_data["error_type"] == "RuntimeError"
    assert "Simulated provider endpoint timeout" in term_data["error_message"]
    assert term_data["candidate_git_sha"] == "test_candidate_sha_12345"

    # 4. run-metadata.json documents failure
    meta_file = test_artifact_dir / "run-metadata.json"
    assert meta_file.is_file()
    meta_data = json.loads(meta_file.read_text(encoding="utf-8"))
    assert meta_data["status"] == "FAILED"
    assert meta_data["error_phase"] == "MODEL_INVOCATION"
    assert meta_data["candidate_git_sha"] == "test_candidate_sha_12345"

    # 5. ZERO fake response files created
    assert not (test_artifact_dir / "raw-response.json").exists()
    assert not (test_artifact_dir / "model-assessment.json").exists()
    assert not (test_artifact_dir / "enriched-assessment.json").exists()
    assert not (test_artifact_dir / "evaluation.json").exists()

    # 6. manifest.json is sealed over all preserved artifacts
    manifest_file = test_artifact_dir / "manifest.json"
    assert manifest_file.is_file()
    man_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert man_data["status"] == "FAILED"
    assert man_data["gate_3_pass"] is False
    assert "terminal-result.json" in man_data["artifacts"]
    assert "run-metadata.json" in man_data["artifacts"]
    assert "authorization-spec.json" in man_data["artifacts"]
    assert "production-prompt.md" in man_data["artifacts"]
    assert "wire-schema.json" in man_data["artifacts"]
    assert "source-manifest.json" in man_data["artifacts"]
    assert "parser-coverage-certificate.json" in man_data["artifacts"]

    # Verify SHA256 in manifest matches actual bytes of all preserved artifacts
    for art_name, expected_sha in man_data["artifacts"].items():
        art_path = test_artifact_dir / art_name
        assert art_path.is_file()
        assert hashlib.sha256(art_path.read_bytes()).hexdigest() == expected_sha

    # 7. Re-entry refusal: attempting to run again refuses re-entry and does NOT invoke model
    with (
        patch.object(mod, "is_isolated_python", return_value=True),
        patch.object(mod, "is_bytecode_writing_disabled", return_value=True),
    ):
        reentry_exit = mod.execute_internal_child(child_args)
        assert reentry_exit == 1
        # Call count remains 1, proving no retry occurred
        assert mock_agent.invoke_raw.call_count == 1
