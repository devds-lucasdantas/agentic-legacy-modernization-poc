"""Unit and regression tests for Gate 3 runner and authorization contract."""

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
    """Verify loading the official Gate 3 authorization spec."""
    mod = get_run_gate_3_module()
    spec_path = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH
    spec, sha256 = mod.load_authorization_spec(spec_path)

    assert spec["gate"] == 3
    assert spec["run_label"] == "baseline-v1"
    assert spec["requested_model"] == "gpt-5-mini"
    assert spec["schema_version"] == "3.0.0"
    assert spec["evaluator_version"] == "3.0.0"
    assert spec["golden_dataset_version"] == "3.0.0"
    assert len(spec["target_bundle"]) == 6
    assert len(sha256) == 64


def test_load_authorization_spec_invalid_gate(tmp_path: Path):
    """Verify rejection when gate is not 3."""
    mod = get_run_gate_3_module()
    bad_spec = tmp_path / "bad-spec.json"
    bad_spec.write_text(
        json.dumps(
            {
                "spec_version": "1.0.0",
                "gate": 2,
                "run_label": "bad",
                "target_bundle": [],
                "requested_model": "gpt-5-mini",
                "foundry_project_fingerprint": "a" * 64,
                "schema_version": "3.0.0",
                "prompt_version": "v1",
                "evaluator_version": "3.0.0",
                "golden_dataset_version": "3.0.0",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="gate must be 3"):
        mod.load_authorization_spec(bad_spec)


def test_runner_synthetic_execution_passes(tmp_path: Path):
    """Verify offline synthetic evaluation runs end-to-end and produces valid manifest."""
    mod = get_run_gate_3_module()
    out_dir = tmp_path / "run_out"
    auth_spec = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH

    exit_code = mod.execute_gate_3(
        repo_root=REPO_ROOT,
        auth_spec_path=auth_spec,
        output_dir=out_dir,
        run_label="test-synthetic-v1",
        synthetic=True,
        allow_dirty=True,
    )
    assert exit_code == 0

    assert (out_dir / "assessment.json").is_file()
    assert (out_dir / "evaluation-result.json").is_file()
    assert (out_dir / "run-metadata.json").is_file()
    assert (out_dir / "manifest.json").is_file()

    eval_data = json.loads((out_dir / "evaluation-result.json").read_text(encoding="utf-8"))
    assert eval_data["gate_3_pass"] is True
    assert eval_data["matched_expected_count"] == 54
    assert eval_data["expected_fact_count"] == 54
    assert eval_data["precision"] == 1.0
    assert eval_data["recall"] == 1.0

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["gate_3_pass"] is True
    assert "assessment.json" in manifest["artifacts"]
    assert "evaluation-result.json" in manifest["artifacts"]
    assert "run-metadata.json" in manifest["artifacts"]


def test_runner_live_fails_without_key(tmp_path: Path, monkeypatch):
    """Verify runner fails closed when live evaluation is requested without credentials."""
    monkeypatch.delenv("AZURE_AI_FOUNDRY_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    mod = get_run_gate_3_module()
    out_dir = tmp_path / "live_fail_out"
    auth_spec = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH

    exit_code = mod.execute_gate_3(
        repo_root=REPO_ROOT,
        auth_spec_path=auth_spec,
        output_dir=out_dir,
        run_label="test-live-fail",
        synthetic=False,
        allow_dirty=True,
    )
    assert exit_code == 1
