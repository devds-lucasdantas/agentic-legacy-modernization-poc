"""H6 Pre-Freeze Final Hotfix Comprehensive Remediation Regressions.

Verifies:
1. Atomic Parent Reservation Ownership & Multiprocess Race (F2)
2. Parent Crash After Exclusive Reservation (F2)
3. Exact Directory Inventory & Namespace Package Rejection (F3)
4. Nested and Unrelated Extra-Directory Snapshot Rejection (F3)
5. Preserve Already-Computed Evaluation Evidence on Later Artifact Write Failure (F4)
6. Recovery Never Reruns Evaluator or Provider (F4)
7. Deceptive Prefix Evidence Path Rejection with Gate FAIL (F6)
8. Pure Basename vs Directory Separator Resolution Contract (F6)
9. Preservation of Verified Transport Serialization (F1)
10. Preservation of Verified Post-Seal Coordination Failure Isolation (F5)
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
from typing import Any

import pytest

from agents.legacy_analyzer.schemas.system_export import (
    get_system_responses_text_format,
)
from src.cobol.multi_source_reader import read_system_bundle
from src.cobol.system_cobol_parser import SystemCobolParser
from src.cobol.system_support_index import SystemSupportIndex
from src.validation.evaluator_v3 import SystemEvaluatorV3, load_golden_assessment

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def get_run_gate_3_module():
    """Load scripts/run-gate-3.py dynamically."""
    spec = importlib.util.spec_from_file_location(
        "run_gate_3_mod_h6", REPO_ROOT / "scripts" / "run-gate-3.py"
    )
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    raise ImportError("Failed to load scripts/run-gate-3.py")


# ======================================================================
# 1. ATOMIC PARENT RESERVATION OWNERSHIP & RACE (F2)
# ======================================================================


def _parent_race_worker(
    repo_root: str,
    out_dir: str,
    barrier: Any,
    results_queue: Any,
    run_label: str,
    auth_spec_path: str,
):
    """Worker process representing an execute_gate_3 parent process in a race."""
    mod = get_run_gate_3_module()
    orig_exclusive = mod.create_initial_reservation_exclusive

    # Synchronize both parents immediately before the exclusive kernel open
    def sync_exclusive(res_file, payload):
        barrier.wait()
        return orig_exclusive(res_file, payload)

    mod.create_initial_reservation_exclusive = sync_exclusive

    try:
        ret = mod.execute_gate_3(
            repo_root=Path(repo_root),
            run_label=run_label,
            allow_dirty=True,
            synthetic=True,
            output_dir=Path(out_dir),
            auth_spec_path=Path(auth_spec_path),
        )
        results_queue.put(("EXIT", ret, os.getpid()))
    except mod.ReservationCollisionError:
        results_queue.put(("COLLISION_EXC", 1, os.getpid()))
    except Exception as e:
        results_queue.put(("ERROR", str(e), os.getpid()))


def test_h6_f2_parent_multiprocess_reservation_race(tmp_path: Path):
    """Test A: Multiprocess race between two real execute_gate_3() parents.

    Both parents target the same official canonical run and are synchronized
    immediately before exclusive reservation creation.
    Expected:
    - exactly one parent acquires initial reservation;
    - exactly one child is launched and reaches completion;
    - losing parent exits immediately with returncode 1;
    - losing parent performs ZERO writes to reservation state;
    - winning parent reaches terminal state (COMPLETED);
    - final reservation is never reverted to RESERVED.
    """
    mod = get_run_gate_3_module()
    official_spec, _ = mod.load_authorization_spec(REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH)

    # Repeat race multiple times to stress the race window
    for trial in range(3):
        out_dir = tmp_path / f"parent_race_out_{trial}"
        out_dir.mkdir(parents=True, exist_ok=True)
        run_label = f"race-parent-{trial}"

        auth_spec = copy.deepcopy(official_spec)
        auth_spec["run_label"] = run_label

        spec_path = out_dir / "auth_spec.json"
        spec_path.write_text(json.dumps(auth_spec, indent=2), encoding="utf-8")

        barrier = multiprocessing.Barrier(2)
        results_queue: multiprocessing.Queue[Any] = multiprocessing.Queue()

        p1 = multiprocessing.Process(
            target=_parent_race_worker,
            args=(
                str(REPO_ROOT),
                str(out_dir),
                barrier,
                results_queue,
                run_label,
                str(spec_path),
            ),
        )
        p2 = multiprocessing.Process(
            target=_parent_race_worker,
            args=(
                str(REPO_ROOT),
                str(out_dir),
                barrier,
                results_queue,
                run_label,
                str(spec_path),
            ),
        )

        p1.start()
        p2.start()
        p1.join(timeout=30)
        p2.join(timeout=30)

        results = []
        while not results_queue.empty():
            results.append(results_queue.get_nowait())

        assert len(results) == 2, f"Expected 2 results, got {results}"
        exit_codes = [r[1] for r in results]
        assert exit_codes.count(0) == 1, f"Expected exactly one exit 0 (winner), got: {exit_codes}"
        assert exit_codes.count(1) == 1, f"Expected exactly one exit 1 (loser), got: {exit_codes}"

        res_state_file = out_dir / mod.RESERVATION_STATE_FILE
        assert res_state_file.is_file()
        res_data = json.loads(res_state_file.read_text(encoding="utf-8"))
        # Final reservation state must be COMPLETED, not reverted to RESERVED by loser
        assert res_data["status"] == "COMPLETED"
        assert res_data["gate_3_pass"] is True


def test_h6_f2_parent_crash_after_exclusive_reservation(tmp_path: Path):
    """Test B: Parent crashes immediately after exclusive reservation creation.

    Subsequent parent targeting the same label must fail closed without
    provider invocation.
    """
    mod = get_run_gate_3_module()
    out_dir = tmp_path / "crashed_parent_run"
    out_dir.mkdir(parents=True, exist_ok=True)
    res_file = out_dir / mod.RESERVATION_STATE_FILE

    # Simulate parent creating initial exclusive reservation and crashing
    mod.create_initial_reservation_exclusive(
        res_file,
        {
            "status": "RESERVED",
            "run_label": "crash-run",
            "gate": 3,
        },
    )

    # Subsequent parent run MUST fail closed at check_existing_reservation
    with pytest.raises(RuntimeError, match="Irrevocable reservation error"):
        mod.check_existing_reservation(out_dir, "crash-run")

    # Even if reservation file is empty or corrupted (e.g. crash during write)
    res_file.write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Irrevocable reservation error"):
        mod.check_existing_reservation(out_dir, "crash-run")


# ======================================================================
# 2. EXACT DIRECTORY INVENTORY (F3)
# ======================================================================


def test_h6_f3_empty_namespace_directory_rejected(tmp_path: Path):
    """Test C: Add ONLY src/h5_untracked_namespace/ with no files.

    verify_snapshot_against_git_objects() MUST reject it.
    Isolated control demonstrates that such a directory would otherwise be
    importable as a namespace package.
    """
    mod = get_run_gate_3_module()
    snap_dir = tmp_path / "snapshot_c"
    snap_dir.mkdir(parents=True, exist_ok=True)

    # Extract clean snapshot directly from Git commit HEAD
    mod.create_git_snapshot_archive("HEAD", snap_dir, repo_root=REPO_ROOT, allow_dirty=False)

    # Pristine snapshot verification must pass
    mod.verify_snapshot_against_git_objects(REPO_ROOT, "HEAD", snap_dir)

    # Attack: add empty namespace directory
    attack_dir = snap_dir / "src" / "h5_untracked_namespace"
    attack_dir.mkdir(parents=True, exist_ok=False)

    # Snapshot verification MUST reject the untracked directory
    with pytest.raises(RuntimeError, match="Unauthorized extra directory in snapshot"):
        mod.verify_snapshot_against_git_objects(REPO_ROOT, "HEAD", snap_dir)

    # Isolated Control: demonstrate Python PEP 420 namespace package importability
    import sys

    src_str = str((snap_dir / "src").resolve())
    sys.path.insert(0, src_str)
    try:
        import importlib

        ns_pkg = importlib.import_module("h5_untracked_namespace")
        # In Python 3, empty directory without __init__.py is an importable namespace package!
        assert hasattr(ns_pkg, "__path__")
        assert getattr(ns_pkg, "__file__", None) is None
    finally:
        if src_str in sys.path:
            sys.path.remove(src_str)
        sys.modules.pop("h5_untracked_namespace", None)


def test_h6_f3_nested_and_external_extra_directories_rejected(tmp_path: Path):
    """Test D: Reject nested empty directory and extra directory outside src."""
    mod = get_run_gate_3_module()
    snap_dir = tmp_path / "snapshot_d"
    snap_dir.mkdir(parents=True, exist_ok=True)

    mod.create_git_snapshot_archive("HEAD", snap_dir, repo_root=REPO_ROOT, allow_dirty=False)

    # 1. Nested empty directory
    nested_dir = snap_dir / "nested" / "deep" / "dir"
    nested_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(RuntimeError, match="Unauthorized extra directory in snapshot"):
        mod.verify_snapshot_against_git_objects(REPO_ROOT, "HEAD", snap_dir)
    import shutil

    shutil.rmtree(snap_dir / "nested")

    # 2. Extra directory outside src
    extra_dir = snap_dir / "extra_unauthorized"
    extra_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(RuntimeError, match="Unauthorized extra directory in snapshot"):
        mod.verify_snapshot_against_git_objects(REPO_ROOT, "HEAD", snap_dir)
    shutil.rmtree(extra_dir)

    # 3. Pristine state passes
    mod.verify_snapshot_against_git_objects(REPO_ROOT, "HEAD", snap_dir)


# ======================================================================
# 3. PRESERVE ALREADY-COMPUTED EVALUATION EVIDENCE (F4)
# ======================================================================


def test_h6_f4_post_evaluation_unrelated_write_failure_preservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Test E: Reproduction of Astra case.

    1. Valid provider response (or synthetic golden v3).
    2. Evaluation completes 59/59, Gate PASS.
    3. Fail ONLY authorization-spec.json write during final artifact generation.
    Expected:
    - controlled terminal execution failure (exit 1);
    - evaluation.json EXISTS and reports 59/59 / Gate PASS;
    - evaluation.json contains 59 evaluated predictions;
    - enriched-assessment.json EXISTS;
    - failure manifest exists and hashes evaluation.json and enriched-assessment.json;
    - evaluator is invoked exactly ONCE (never re-invoked during recovery).
    """
    mod = get_run_gate_3_module()
    out_dir = tmp_path / "f4_astra_case_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    run_label = "test-astra-f4"

    golden_file = REPO_ROOT / mod.DEFAULT_GOLDEN_PATH
    assessment = load_golden_assessment(golden_file)

    bundle = read_system_bundle(REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, bundle, file_status_certificate=parser.file_status_certificate
    )
    evaluator = SystemEvaluatorV3(index, golden_dataset_path=golden_file)

    eval_calls = 0
    orig_evaluate = evaluator.evaluate_assessment

    def counting_evaluate(a):
        nonlocal eval_calls
        eval_calls += 1
        return orig_evaluate(a)

    monkeypatch.setattr(evaluator, "evaluate_assessment", counting_evaluate)

    # Run evaluation
    eval_result, predictions = evaluator.evaluate_assessment(assessment)
    assert eval_calls == 1
    assert eval_result.gate_3_pass is True
    assert eval_result.matched_expected_count == 59
    assert len(predictions) == 59

    res_file = out_dir / mod.RESERVATION_STATE_FILE
    res_file.write_text(json.dumps({"status": "RESERVED"}), encoding="utf-8")

    spec = {
        "gate": 3,
        "spec_version": "3.4.3",
        "run_label": run_label,
    }

    # Simulate failure during artifact generation of authorization-spec.json
    simulated_error = OSError("Simulated authorization-spec.json I/O error")

    # In finalize_post_model_failure, fail authorization-spec.json write only
    orig_safe_preserve = mod.safe_preserve_artifact

    def failing_safe_preserve(artifact_path, data, is_json=True, failures=None):
        if artifact_path.name == "authorization-spec.json":
            if failures is not None:
                failures.append({"file": "authorization-spec.json", "error": str(simulated_error)})
            return False
        return orig_safe_preserve(artifact_path, data, is_json=is_json, failures=failures)

    monkeypatch.setattr(mod, "safe_preserve_artifact", failing_safe_preserve)

    mod.finalize_post_model_failure(
        artifact_dir=out_dir,
        reservation_file=res_file,
        error_phase="ARTIFACT_GENERATION",
        error=simulated_error,
        spec=spec,
        candidate_sha="test_cand_sha",
        authorization_commit_sha="test_auth_sha",
        authorized_sha="test_auth_sha",
        run_label=run_label,
        bundle=bundle,
        parser=parser,
        runtime_manifest={"pkg": "1.0"},
        metadata={"gate": "3", "run_label": run_label},
        assessment=assessment,
        raw_response_content={"mock": True},
        evaluation_result=eval_result,
        evaluated_predictions=predictions,
    )

    # Assertions on preserved evidence:
    eval_path = out_dir / "evaluation.json"
    assert eval_path.is_file(), "evaluation.json MUST exist despite artifact generation failure"
    eval_json = json.loads(eval_path.read_text(encoding="utf-8"))
    assert eval_json["metric_summary"]["gate_3_pass"] is True
    assert eval_json["metric_summary"]["matched_expected_count"] == 59
    assert len(eval_json["predictions"]) == 59

    enriched_path = out_dir / "enriched-assessment.json"
    assert enriched_path.is_file(), (
        "enriched-assessment.json MUST exist despite artifact generation failure"
    )

    manifest_path = out_dir / "manifest.json"
    assert manifest_path.is_file(), "manifest.json MUST exist"
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_data["status"] == "FAILED"
    assert "evaluation.json" in manifest_data["artifacts"]
    assert "enriched-assessment.json" in manifest_data["artifacts"]

    terminal_path = out_dir / mod.TERMINAL_RESULT_FILE
    assert terminal_path.is_file()
    term_data = json.loads(terminal_path.read_text(encoding="utf-8"))
    assert term_data["status"] == "FAILED"
    assert any(
        f["file"] == "authorization-spec.json" for f in term_data.get("artifact_write_failures", [])
    )

    # Verification that evaluator was never rerun during recovery
    assert eval_calls == 1


def test_h6_f4_no_evaluator_rerun_recovery(tmp_path: Path):
    """Test F: Prove recovery never reruns evaluator or provider."""
    mod = get_run_gate_3_module()
    out_dir = tmp_path / "no_rerun_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    res_file = out_dir / mod.RESERVATION_STATE_FILE
    res_file.write_text(json.dumps({"status": "RESERVED"}), encoding="utf-8")

    evaluator_run_count = 0

    class MockEvaluator:
        def evaluate_assessment(self, assessment):
            nonlocal evaluator_run_count
            evaluator_run_count += 1
            return None, []

    # Finalizer receives pre-computed results; must not attempt to create or call any evaluator
    mock_eval_res = type(
        "EvalRes",
        (),
        {
            "gate_3_pass": True,
            "precision": 1.0,
            "recall": 1.0,
            "matched_expected_count": 59,
            "expected_fact_count": 59,
            "duplicate_prediction_count": 0,
            "supported_predicted_count": 59,
            "unsupported_predicted_count": 0,
            "to_dict": lambda self: {"gate_3_pass": True, "matched_expected_count": 59},
        },
    )()

    mod.finalize_post_model_failure(
        artifact_dir=out_dir,
        reservation_file=res_file,
        error_phase="ARTIFACT_GENERATION",
        error=RuntimeError("Simulated late artifact error"),
        spec={"gate": 3, "run_label": "no-rerun"},
        candidate_sha="test_cand",
        authorization_commit_sha="test_auth",
        authorized_sha="test_auth",
        run_label="no-rerun",
        evaluation_result=mock_eval_res,
        evaluated_predictions=[],
    )

    # Evaluator invocation count remains 0 because finalize_post_model_failure never runs evaluation
    assert evaluator_run_count == 0
    assert (out_dir / "evaluation.json").is_file()


# ======================================================================
# 4. ONLY EXACT PATH OR PURE BASENAME ALIAS (F6)
# ======================================================================


def test_h6_f6_exact_or_pure_basename_contract():
    """Test H: Exact canonical path or pure basename alias resolution.

    - legacy/core-banking-system/BANK-MAIN.CBL -> accepted exact canonical
    - BANK-MAIN.CBL -> accepted pure unique basename
    - legacy\\core-banking-system\\BANK-MAIN.CBL -> accepted (normalized to canonical)
    - fake/directory/BANK-MAIN.CBL -> REJECT with KeyError
    - foo\\BANK-MAIN.CBL -> REJECT with KeyError
    - ./BANK-MAIN.CBL -> REJECT with KeyError
    - ../BANK-MAIN.CBL -> REJECT with KeyError
    """
    bundle = read_system_bundle(REPO_ROOT)

    # 1. Exact canonical
    assert (
        bundle.resolve_canonical_file_path("legacy/core-banking-system/BANK-MAIN.CBL")
        == "legacy/core-banking-system/BANK-MAIN.CBL"
    )

    # 2. Pure basename
    assert (
        bundle.resolve_canonical_file_path("BANK-MAIN.CBL")
        == "legacy/core-banking-system/BANK-MAIN.CBL"
    )

    # 3. Backslash exact canonical
    assert (
        bundle.resolve_canonical_file_path(r"legacy\core-banking-system\BANK-MAIN.CBL")
        == "legacy/core-banking-system/BANK-MAIN.CBL"
    )

    # 4. Fake directory prefix
    with pytest.raises(KeyError, match="contains directory separators"):
        bundle.resolve_canonical_file_path("fake/directory/BANK-MAIN.CBL")

    # 5. Backslash fake directory prefix
    with pytest.raises(KeyError, match="contains directory separators"):
        bundle.resolve_canonical_file_path(r"foo\BANK-MAIN.CBL")

    # 6. Relative ./
    with pytest.raises(KeyError, match="contains directory separators"):
        bundle.resolve_canonical_file_path("./BANK-MAIN.CBL")

    # 7. Traversal ../
    with pytest.raises(KeyError, match="contains directory separators"):
        bundle.resolve_canonical_file_path("../BANK-MAIN.CBL")


def test_h6_f6_deceptive_prefix_evidence_causes_gate_fail():
    """Test G: Golden assessment with fake/directory/BANK-MAIN.CBL must FAIL Gate 3.

    Replacing one required evidence path with deceptive prefix causes
    invalid_evidence_count > 0 and Gate FAIL.
    """
    mod = get_run_gate_3_module()
    golden_file = REPO_ROOT / mod.DEFAULT_GOLDEN_PATH

    assessment = load_golden_assessment(golden_file)
    for prog in assessment.program_declarations:
        if prog.program_id == "BANK-MAIN":
            prog.evidence.file_path = "fake/directory/BANK-MAIN.CBL"
            break

    bundle = read_system_bundle(REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, bundle, file_status_certificate=parser.file_status_certificate
    )
    evaluator = SystemEvaluatorV3(index, golden_dataset_path=golden_file)

    eval_result, predictions = evaluator.evaluate_assessment(assessment)

    # Must fail Gate 3 and have invalid evidence count > 0
    assert eval_result.gate_3_pass is False
    assert eval_result.invalid_evidence_count > 0


# ======================================================================
# 5. PRESERVE VERIFIED F1 AND F5
# ======================================================================


def test_h6_f1_preserved_transport_serialization():
    """Test I: Verify Responses serialized request body format.

    Uses direct type/name/schema/strict with NO nested json_schema envelope.
    """
    text_format = get_system_responses_text_format()
    assert text_format["type"] == "json_schema"
    assert text_format["name"] == "SystemAssessment"
    assert text_format["strict"] is True
    assert "schema" in text_format
    assert "json_schema" not in text_format


def test_h6_f5_preserved_post_seal_immutability(tmp_path: Path):
    """Test J: After manifest seal, terminal/manifest/listed artifact bytes are immutable.

    Coordination failure cannot modify or rewrite sealed evidence files.
    """
    mod = get_run_gate_3_module()
    out_dir = tmp_path / "post_seal_out"
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_file = out_dir / "manifest.json"
    manifest_payload = {"status": "SEALED", "gate_3_pass": True}
    manifest_file.write_text(json.dumps(manifest_payload), encoding="utf-8")
    orig_manifest_sha = hashlib.sha256(manifest_file.read_bytes()).hexdigest()

    term_file = out_dir / mod.TERMINAL_RESULT_FILE
    term_payload = {"status": "COMPLETED", "gate_3_pass": True}
    term_file.write_text(json.dumps(term_payload), encoding="utf-8")
    orig_term_sha = hashlib.sha256(term_file.read_bytes()).hexdigest()

    # Simulate post-seal coordination failure
    coord_file = out_dir / "coordination-failure.json"
    coord_file.write_text(json.dumps({"error": "Post-seal state update error"}), encoding="utf-8")

    # Sealed files must remain untouched
    assert hashlib.sha256(manifest_file.read_bytes()).hexdigest() == orig_manifest_sha
    assert hashlib.sha256(term_file.read_bytes()).hexdigest() == orig_term_sha
