"""Adversarial Regression Suite V3 for Gate 2 (Candidate V2.2).

Verifies the 26 required regressions from the Third Independent Adversarial Review
and the Six Approved Amendments:
1-7:   A3-01 Strict literal parsing, menu key separation, PIC grammar, DISPLAY evidence.
8-9:   A3-02 OpenAI wire schema plain unions without oneOf, discriminator, or defaults.
10-13: A3-03 Comprehensive refusal inspection across ResponseOutputRefusal structures.
14:    A3-04 Requirement for isolated Python (sys.flags.isolated == 1) for baseline runs.
15:    Amendment 6 Frozen expected model/deployment identity check.
16-19: A3-05 / Amendment 5 Canonical runtime/lock attestation.
20:    A3-04 Full tracked tree comparison against git HEAD blobs.
21-23: A3-04 Overlay detection probes (root openai.py, loose pyc, sitecustomize.py).
24:    A3-04 Post-import origin verification rejecting repo overlays.
25:    Amendment 3 Preservation of historical V2.1 rescore artifact.
26:    Amendment 3 Exact reproducibility of fresh V2.2 rescore against committed artifact.
"""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agents.legacy_analyzer.agent import (
    ResponseRefusedError,
    inspect_response_for_refusal,
)
from agents.legacy_analyzer.schemas.export import (
    get_openai_wire_schema,
)
from src.cobol.atomic_facts import (
    AtomicFact,
    PredictedFact,
    SupportedFactOccurrence,
    normalize_menu_key,
    normalize_pic,
    normalize_semantic_literal,
    parse_cobol_literal_token,
    parse_source_menu_key_token,
)
from src.cobol.support_index import SourceSupportIndex
from src.validation.evaluator_v2 import load_source_lines
from src.validation.evidence_validator import validate_claim_evidence
from src.validation.v1_rescore import rescore_v1_assessment

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def get_runner_module():
    spec = importlib.util.spec_from_file_location(
        "run_gate_2_module_v3", REPO_ROOT / "scripts" / "run-gate-2.py"
    )
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    raise ImportError("Failed to load scripts/run-gate-2.py")


# ==============================================================================
# 1-7: A3-01 Strict Literal Parsing, Menu Separation, PIC Grammar, Evidence
# ==============================================================================


def test_01_parse_cobol_literal_token_matching_quotes():
    """1. parse_cobol_literal_token requires matching quotes and strips outer quotes once."""
    assert parse_cobol_literal_token("'HELLO'") == "HELLO"
    assert parse_cobol_literal_token('"WORLD"') == "WORLD"
    assert parse_cobol_literal_token("' WS-CHOICE '") == " WS-CHOICE "
    assert parse_cobol_literal_token("''") == ""
    assert parse_cobol_literal_token('""') == ""

    with pytest.raises(ValueError, match="missing matching outer quotes"):
        parse_cobol_literal_token("'MISMATCH\"")

    with pytest.raises(ValueError, match="missing matching outer quotes"):
        parse_cobol_literal_token("NO_QUOTES")

    with pytest.raises(ValueError, match="too short"):
        parse_cobol_literal_token("'")


def test_02_parse_cobol_literal_token_preserves_interior_characters_and_spaces():
    """2. parse_cobol_literal_token preserves interior spaces and characters verbatim."""
    val = "   1. Deposit Funds   "
    token = f"'{val}'"
    assert parse_cobol_literal_token(token) == val

    val_internal = "Option   1 :  Check   Balance"
    assert parse_cobol_literal_token(f"'{val_internal}'") == val_internal


def test_03_parse_source_menu_key_token_source_parsing():
    """3. parse_source_menu_key_token parses source quoted tokens and OTHER."""
    assert parse_source_menu_key_token("'1'") == "1"
    assert parse_source_menu_key_token('"2"') == "2"
    assert parse_source_menu_key_token("OTHER") == "OTHER"
    assert parse_source_menu_key_token("other") == "OTHER"

    with pytest.raises(ValueError, match="Invalid source menu key token"):
        parse_source_menu_key_token("'1")

    with pytest.raises(ValueError, match="Invalid source menu key token"):
        parse_source_menu_key_token("1'")

    with pytest.raises(ValueError, match="Malformed source menu key token"):
        parse_source_menu_key_token("'1''")


def test_04_normalize_menu_key_model_values_never_repaired():
    """4. normalize_menu_key preserves model semantic keys without repairing malformed strings."""
    assert normalize_menu_key("1") == "1"
    assert normalize_menu_key("OTHER") == "OTHER"
    assert normalize_menu_key("other") == "OTHER"

    # Malformed model inputs must NEVER be repaired into supported keys
    assert normalize_menu_key("'1'") == "'1'"
    assert normalize_menu_key("1''") == "1''"
    assert normalize_menu_key("'1") == "'1"
    assert normalize_menu_key("1'") == "1'"
    assert normalize_menu_key("O'THER") == "O'THER"

    # Evaluator verification: unrepaired key remains unsupported
    source_lines = load_source_lines(repo_root=REPO_ROOT)
    index = SourceSupportIndex.from_source_lines(source_lines)
    unsupported_fact = AtomicFact(
        kind="MENU_OPTION",
        subject="'1'",  # unrepaired model value
        predicate="CALLS",
        object="INIT-DB",
    )
    assert not index.is_supported(unsupported_fact)


def test_05_normalize_semantic_literal_idempotence():
    """5. normalize_semantic_literal is strictly idempotent and does not alter semantic content."""
    literals = [
        "1",
        "  Leading space",
        "Trailing space  ",
        "Internal   multiple   spaces",
        "'Quoted content inside'",
        'Mixed "quotes" and symbols !@#$%',
    ]
    for lit in literals:
        first = normalize_semantic_literal(lit)
        second = normalize_semantic_literal(first)
        assert first == lit
        assert second == first


def test_06_normalize_pic_narrow_grammar():
    """6. normalize_pic implements narrow grammar without broad punctuation stripping."""
    # Valid supported PIC clauses
    assert normalize_pic("X") == "X(1)"
    assert normalize_pic("X(1)") == "X(1)"
    assert normalize_pic("9") == "9(1)"
    assert normalize_pic("999") == "9(3)"
    assert normalize_pic("XXXXX") == "X(5)"
    assert normalize_pic("9(12)") == "9(12)"
    assert normalize_pic("S9(4)") == "S9(4)"
    assert normalize_pic("PIC X") == "X(1)"
    assert normalize_pic("PIC 9(1)") == "9(1)"
    assert normalize_pic(None) == "NONE"
    assert normalize_pic("") == "NONE"

    # Malformed strings must NOT be stripped or normalized
    assert normalize_pic("X....") == "X...."
    assert normalize_pic("X(") == "X("
    assert normalize_pic("9(abc)") == "9(abc)"


def test_07_display_evidence_binding_non_vacuous():
    """7. DISPLAY evidence binding requires exact source token match; rejects vacuous fragments."""
    # Source line 14: DISPLAY '=== CORE BANKING SYSTEM ==='
    source_lines = load_source_lines(repo_root=REPO_ROOT)
    pred = PredictedFact(
        fact=AtomicFact("IO_OPERATION", "DISPLAY", "WRITES", "=== CORE BANKING SYSTEM ==="),
        line_start=14,
        line_end=14,
        snippet="DISPLAY '=== CORE BANKING SYSTEM ==='",
    )
    occ = SupportedFactOccurrence(
        fact=pred.fact,
        occurrence_id="display-14",
        line_start=14,
        line_end=14,
        required_evidence_fragments=("DISPLAY", "'=== CORE BANKING SYSTEM ==='"),
    )

    # Valid binding with matching token in snippet
    valid_res = validate_claim_evidence(pred, occ, source_lines)
    assert valid_res.is_valid is True

    # Vacuous binding where snippet omits literal token
    pred_bad = PredictedFact(
        fact=pred.fact,
        line_start=14,
        line_end=14,
        snippet="DISPLAY",
    )
    invalid_res = validate_claim_evidence(pred_bad, occ, source_lines)
    assert invalid_res.is_valid is False

    # Vacuous required fragment is rejected as invalid
    occ_vacuous = SupportedFactOccurrence(
        fact=pred.fact,
        occurrence_id="display-vacuous",
        line_start=14,
        line_end=14,
        required_evidence_fragments=("DISPLAY", "   "),
    )
    res_vacuous = validate_claim_evidence(pred, occ_vacuous, source_lines)
    assert res_vacuous.is_valid is False
    assert "vacuous" in (res_vacuous.error_message or "").lower()


# ==============================================================================
# 8-9: A3-02 OpenAI Wire Schema Plain Unions (anyOf, No oneOf, No Defaults)
# ==============================================================================


def test_08_openai_wire_schema_no_oneof_no_discriminator():
    """8. OpenAI wire schema contains no oneOf and no discriminator; uses valid anyOf."""
    wire_schema = get_openai_wire_schema()
    schema_str = json.dumps(wire_schema)

    assert '"oneOf"' not in schema_str
    assert '"discriminator"' not in schema_str
    assert '"anyOf"' in schema_str

    inner_schema = wire_schema.get("json_schema", {}).get("schema", wire_schema)
    props = inner_schema.get("properties", {})
    assert "anyOf" in props["menu_options"]["items"]
    assert "anyOf" in props["control_flow"]["items"]
    assert "anyOf" in props["io_operations"]["items"]


def test_09_openai_wire_schema_no_unnecessary_defaults():
    """9. Variant model properties in wire schema do not contain unnecessary defaults."""
    wire_schema = get_openai_wire_schema()
    inner_schema = wire_schema.get("json_schema", {}).get("schema", wire_schema)
    defs = inner_schema.get("$defs", {})

    variant_types = [
        "CallMenuOption",
        "DisplayMenuOption",
        "PerformUntilConstruct",
        "EvaluateConstruct",
        "StopRunConstruct",
        "AcceptIO",
        "DisplayIO",
    ]

    for v_type in variant_types:
        assert v_type in defs
        props = defs[v_type].get("properties", {})
        for prop_name, prop_def in props.items():
            assert "default" not in prop_def, (
                f"Variant {v_type}.{prop_name} contains unnecessary 'default' in wire schema"
            )


# ==============================================================================
# 10-13: A3-03 Comprehensive Refusal Inspection Across ResponseOutputRefusal
# ==============================================================================


def test_10_inspect_response_for_refusal_top_level():
    """10. inspect_response_for_refusal detects top-level refusal attribute."""
    resp = MagicMock()
    resp.refusal = "Safety policy refusal."
    resp.output = []

    with pytest.raises(
        ResponseRefusedError, match="Model response was refused by provider policy."
    ):
        inspect_response_for_refusal(resp)


def test_11_inspect_response_for_refusal_in_output_item():
    """11. inspect_response_for_refusal detects refusal item directly in output list."""
    from openai.types.responses import ResponseOutputRefusal

    refusal_item = ResponseOutputRefusal(refusal="Content refused.", type="refusal")
    resp = MagicMock()
    resp.refusal = None
    resp.output = [refusal_item]

    with pytest.raises(
        ResponseRefusedError, match="Model response was refused by provider policy."
    ):
        inspect_response_for_refusal(resp)


def test_12_inspect_response_for_refusal_nested_in_content():
    """12. inspect_response_for_refusal detects refusal nested inside output message content."""
    from openai.types.responses import ResponseOutputRefusal

    nested_refusal = ResponseOutputRefusal(refusal="Inner refusal.", type="refusal")
    message = MagicMock()
    message.refusal = None
    message.content = [nested_refusal]

    resp = MagicMock()
    resp.refusal = None
    resp.output = [message]

    with pytest.raises(
        ResponseRefusedError, match="Model response was refused by provider policy."
    ):
        inspect_response_for_refusal(resp)


def test_13_response_refused_error_safe_message():
    """13. ResponseRefusedError produces safe message without leaking raw refusal content."""
    secret_text = "SECRET_PROMPT_INJECTION_TRIGGERED_POLICY"
    resp = MagicMock()
    resp.refusal = secret_text
    resp.output = []

    with pytest.raises(ResponseRefusedError) as exc_info:
        inspect_response_for_refusal(resp)

    err_str = str(exc_info.value)
    assert secret_text not in err_str
    assert err_str == "Model response was refused by provider policy."


# ==============================================================================
# 14-15: Isolated Python and Model Identity Checks
# ==============================================================================


def test_14_baseline_preflight_fails_without_isolated_python(monkeypatch):
    """14. Baseline preflight rejects execution when is_isolated_python() returns False."""
    runner = get_runner_module()

    monkeypatch.setattr(runner, "is_isolated_python", lambda: False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run-gate-2.py",
            "--run-label",
            "baseline-v2",
            "--expected-git-sha",
            "abc1234",
            "--expected-model",
            "gpt-5-mini",
            "--dry-run",
        ],
    )
    ret = runner.main()
    assert ret == 1


def test_15_baseline_preflight_fails_on_model_mismatch(monkeypatch):
    """15. Baseline preflight rejects execution when --expected-model differs from loaded config."""
    runner = get_runner_module()

    monkeypatch.setattr(runner, "is_isolated_python", lambda: True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run-gate-2.py",
            "--run-label",
            "baseline-v2",
            "--expected-git-sha",
            "abc1234",
            "--expected-model",
            "wrong-model-name",
            "--dry-run",
        ],
    )
    monkeypatch.setattr(runner, "check_git_branch", lambda: "feat/gate-2-cobol-reader")
    monkeypatch.setattr(runner, "get_git_commit_sha", lambda: "abc1234")
    monkeypatch.setattr(runner, "verify_clean_worktree", lambda is_b: None)
    monkeypatch.setattr(runner, "verify_full_tracked_tree_against_head", lambda: {})
    monkeypatch.setattr(runner, "verify_no_executable_overlays", lambda is_b: None)

    ret = runner.main()
    assert ret == 1


# ==============================================================================
# 16-19: Canonical Runtime/Lock Attestation
# ==============================================================================


def test_16_canonical_runtime_manifest_exact_lockfile_match():
    """16. Canonical runtime manifest matches requirements-lock.txt exactly."""
    runner = get_runner_module()
    lock_path = REPO_ROOT / "requirements-lock.txt"
    manifest, manifest_sha = runner.verify_runtime_environment(lock_path)
    assert len(manifest) == 42
    assert len(manifest_sha) == 64


def test_17_runtime_verification_fails_on_missing_package(tmp_path):
    """17. Runtime verification fails if a required package is missing."""
    runner = get_runner_module()
    fake_lock = tmp_path / "fake-lock.txt"
    content = (REPO_ROOT / "requirements-lock.txt").read_text(encoding="utf-8")
    content += "\nmissing-package-xyz==1.0.0\n"
    fake_lock.write_text(content, encoding="utf-8")

    with pytest.raises(RuntimeError, match="Missing expected locked packages"):
        runner.verify_runtime_environment(fake_lock)


def test_18_runtime_verification_fails_on_unexpected_package(tmp_path):
    """18. Runtime verification fails if an unexpected package is present in runtime."""
    runner = get_runner_module()
    fake_lock = tmp_path / "fake-lock.txt"
    lines = (REPO_ROOT / "requirements-lock.txt").read_text(encoding="utf-8").splitlines()
    filtered = [line for line in lines if not line.startswith("openai==")]
    fake_lock.write_text("\n".join(filtered) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Unexpected disallowed packages in runtime"):
        runner.verify_runtime_environment(fake_lock)


def test_19_runtime_verification_fails_on_version_mismatch(tmp_path):
    """19. Runtime verification fails if a package version does not match exact lock."""
    runner = get_runner_module()
    fake_lock = tmp_path / "fake-lock.txt"
    lines = (REPO_ROOT / "requirements-lock.txt").read_text(encoding="utf-8").splitlines()
    mismatched = ["openai==99.99.99" if line.startswith("openai==") else line for line in lines]
    fake_lock.write_text("\n".join(mismatched) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Version mismatches"):
        runner.verify_runtime_environment(fake_lock)


# ==============================================================================
# 20: Full-Tree Git Blob Comparison
# ==============================================================================


def test_20_full_tree_git_blob_comparison_detects_disk_modification(monkeypatch):
    """20. verify_full_tracked_tree_against_head compares disk files directly to git HEAD blobs."""
    runner = get_runner_module()

    # Simulate tracked file list
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda cmd, **kwargs: (
            MagicMock(stdout=b"scripts/run-gate-2.py\x00", returncode=0)
            if cmd[:2] == ["git", "ls-files"]
            else MagicMock(stdout=b"HEAD_CONTENT_DIFFERENT", returncode=0)
        ),
    )
    with pytest.raises(RuntimeError, match="does not match git HEAD blob"):
        runner.verify_full_tracked_tree_against_head()


# ==============================================================================
# 21-24: Overlay Detection and Import Origin Checks
# ==============================================================================


def test_21_overlay_probe_root_openai_py_rejected(monkeypatch):
    """21. verify_no_executable_overlays detects untracked root openai.py."""
    runner = get_runner_module()

    fake_status = "?? openai.py\n"
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda cmd, **kwargs: (
            MagicMock(stdout=fake_status, returncode=0)
            if "status" in cmd
            else MagicMock(stdout="", returncode=0)
        ),
    )
    with pytest.raises(RuntimeError, match="Executable or configuration overlays detected"):
        runner.verify_no_executable_overlays(is_baseline_run=True)


def test_22_overlay_probe_loose_pyc_rejected(monkeypatch):
    """22. verify_no_executable_overlays detects loose bytecode overlay like src/__init__.pyc."""
    runner = get_runner_module()

    fake_status = "!! src/__init__.pyc\n"
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda cmd, **kwargs: (
            MagicMock(stdout=fake_status, returncode=0)
            if "status" in cmd
            else MagicMock(stdout="", returncode=0)
        ),
    )
    with pytest.raises(RuntimeError, match="Loose bytecode overlay outside __pycache__"):
        runner.verify_no_executable_overlays(is_baseline_run=True)


def test_23_overlay_probe_sitecustomize_rejected(monkeypatch):
    """23. verify_no_executable_overlays detects sitecustomize.py / usercustomize.py."""
    runner = get_runner_module()

    fake_status = "?? sitecustomize.py\n"
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda cmd, **kwargs: (
            MagicMock(stdout=fake_status, returncode=0)
            if "status" in cmd
            else MagicMock(stdout="", returncode=0)
        ),
    )
    with pytest.raises(RuntimeError, match="Disallowed overlay file"):
        runner.verify_no_executable_overlays(is_baseline_run=True)


def test_24_post_import_origin_verification_rejects_repo_overlay(monkeypatch):
    """24. verify_import_origins rejects modules imported from workspace overlay outside .venv."""
    runner = get_runner_module()

    import openai

    monkeypatch.setattr(openai, "__file__", str(REPO_ROOT / "openai.py"))

    expected_match = "imported from outside active virtualenv|imported from repository overlay"
    with pytest.raises(RuntimeError, match=expected_match):
        runner.verify_import_origins()


# ==============================================================================
# 25-26: V2.1 Rescore Preservation and V2.2 Exact Reproducibility
# ==============================================================================


def test_25_historical_v2_1_rescore_preserved_untouched():
    """25. Historical V2.1 rescore artifact exists and is preserved untouched."""
    v2_1_file = REPO_ROOT / "evals" / "results" / "gate-2-v1-rescored-with-v2.1.json"
    assert v2_1_file.exists(), "evals/results/gate-2-v1-rescored-with-v2.1.json must exist"

    data = json.loads(v2_1_file.read_text(encoding="utf-8"))
    assert data["rescore_evaluator_version"] == "2.1.0"
    assert data["evaluation_metrics"]["supported_predicted_count"] == 18
    assert data["evaluation_metrics"]["unsupported_predicted_count"] == 6


def test_26_fresh_v2_2_rescore_matches_committed_artifact():
    """26. Fresh V2.2 rescore output matches committed gate-2-v1-rescored-with-v2.2.json exactly."""
    v2_2_file = REPO_ROOT / "evals" / "results" / "gate-2-v1-rescored-with-v2.2.json"
    assert v2_2_file.exists(), "evals/results/gate-2-v1-rescored-with-v2.2.json must exist"

    committed_data = json.loads(v2_2_file.read_text(encoding="utf-8"))

    # Compute fresh rescore dynamically
    v1_path = REPO_ROOT / "evals" / "observed" / "gate-2-baseline-v1-assessment.json"
    fresh_data = rescore_v1_assessment(v1_path, output_path=None, repo_root=REPO_ROOT)

    # Verify versions and paths
    assert fresh_data["rescore_evaluator_version"] == "2.2.0"
    assert fresh_data["golden_dataset_version"] == "2.2.0"
    assert fresh_data["v1_source_file"] == "evals/observed/gate-2-baseline-v1-assessment.json"

    # Compare exact metrics with committed artifact
    assert fresh_data["claim_accounting"] == committed_data["claim_accounting"]
    f_metrics = fresh_data["evaluation_metrics"]
    c_metrics = committed_data["evaluation_metrics"]
    assert f_metrics["raw_predicted_count"] == c_metrics["raw_predicted_count"]
    assert f_metrics["unique_predicted_count"] == c_metrics["unique_predicted_count"]
    assert f_metrics["supported_predicted_count"] == c_metrics["supported_predicted_count"]
    assert f_metrics["unsupported_predicted_count"] == c_metrics["unsupported_predicted_count"]
    assert f_metrics["invalid_evidence_count"] == c_metrics["invalid_evidence_count"]
    assert f_metrics["matched_expected_count"] == c_metrics["matched_expected_count"]
    assert f_metrics["precision"] == c_metrics["precision"]
    assert f_metrics["recall"] == c_metrics["recall"]
    assert f_metrics["gate_2_pass"] == c_metrics["gate_2_pass"]
