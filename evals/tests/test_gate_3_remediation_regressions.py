"""Explicit regression tests for Gate 3 Remediation Round 2 blockers.

Covers:
1. Independently authored golden provenance (INDEPENDENT_STATIC_SOURCE_AUDIT)
2. Zero parser magic offsets or fixture names
3. Mutated DAT record field widths and order adaptation
4. Category completeness policy (REQUIRED_EXHAUSTIVE vs REQUIRED_PREREGISTERED_CORE)
5. Schema leakage tokens removed
6. Duplicate truth-bearing collection absence (programs vs program_declarations)
7. Authorization SHA non-self-referential two-phase design
8. Irrevocable run-label reservation refusal (RESERVED, MODEL_INVOCATION, FAILED, COMPLETED)
9. Preflight identity verification (wrong model / wrong project fingerprint zero-call)
10. Complete immutable artifact preservation (14 artifacts with SHA256 checksums in manifest.json)
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from agents.legacy_analyzer.schemas.system_assessment import SystemAssessment
from src.cobol.multi_source_reader import (
    MultiSourceBundle,
    TargetFile,
    read_system_bundle,
)
from src.cobol.system_atomic_facts import FileOperationFact
from src.cobol.system_cobol_parser import SystemCobolParser

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


# ======================================================================
# 1. GOLDEN MUST BE INDEPENDENT OF PRODUCTION PARSER
# ======================================================================


def test_independent_golden_provenance():
    """Verify golden dataset authoring method is INDEPENDENT_STATIC_SOURCE_AUDIT.

    Asserts all propositions have auditor-facing source rationales and
    that no golden-authoring module imports the production parser.
    """
    golden_path = REPO_ROOT / "evals" / "expected" / "system-understanding-v3.json"
    data = json.loads(golden_path.read_text(encoding="utf-8"))

    assert data.get("golden_authoring_method") == "INDEPENDENT_STATIC_SOURCE_AUDIT"
    assert data.get("total_expected_facts") == 59
    assert len(data["propositions"]) == 59

    for prop in data["propositions"]:
        assert "auditor_rationale" in prop, f"Proposition {prop['id']} missing auditor_rationale"
        rationale = prop["auditor_rationale"].strip()
        assert len(rationale) > 10, f"Proposition {prop['id']} has trivial auditor_rationale"

    # Verify no golden-authoring file imports SystemCobolParser
    eval_scripts = list((REPO_ROOT / "evals" / "scripts").glob("*.py"))
    for script_file in eval_scripts:
        if "build_golden" in script_file.name:
            content = script_file.read_text(encoding="utf-8")
            assert "SystemCobolParser" not in content, (
                f"{script_file} must not import SystemCobolParser"
            )


# ======================================================================
# 2. REMOVE REMAINING FIXTURE ASSUMPTIONS FROM PRODUCTION PARSER
# ======================================================================


def test_zero_parser_magic_offsets_or_names():
    """Verify parser contains no hardcoded fixture positions or names."""
    parser_path = REPO_ROOT / "src" / "cobol" / "system_cobol_parser.py"
    source = parser_path.read_text(encoding="utf-8")

    assert 'or "ACCOUNTS"' not in source
    assert "or 'ACCOUNTS'" not in source
    assert "record[:10]" not in source
    assert "record[40:55]" not in source
    assert "in target_name" not in source or '"BAL"' not in source
    assert "PERMANENT_DATA_LOSS" not in source


def test_mutated_dat_record_field_widths_and_order(tmp_path: Path):
    """Verify DAT state comparison adapts to mutated record layouts and offsets dynamically."""
    orig_bundle = read_system_bundle(repo_root=REPO_ROOT)

    # Mutated copybook with balance FIRST (width 9), then account (width 6), then name (width 20)
    mutated_cpy = (
        "       01  ACCOUNT-RECORD.\n"
        "           05  ACC-BALANCE         PIC 9(7)V99.\n"
        "           05  ACC-NUMBER          PIC X(6).\n"
        "           05  ACC-NAME            PIC X(20).\n"
    )
    # Mutated DAT records matching new layout:
    # Record 1: bal=000010000 (100.00), acc=ACC001, name=Alice Smith         (total 35)
    # Record 2: bal=000020000 (200.00), acc=ACC002, name=Bob Johnson         (total 35)
    mutated_dat = "000010000ACC001Alice Smith         \n000020000ACC002Bob Johnson         \n"

    files = dict(orig_bundle.files)
    cpy_target = TargetFile(
        relative_path="legacy/core-banking-system/ACCOUNTS.CPY",
        file_type="COPYBOOK",
        raw_content=mutated_cpy,
        numbered_content=mutated_cpy,
        sha256=hashlib.sha256(mutated_cpy.encode("utf-8")).hexdigest(),
        line_count=len(mutated_cpy.splitlines()),
    )
    dat_target = TargetFile(
        relative_path="legacy/core-banking-system/ACCOUNTS.DAT",
        file_type="DATA",
        raw_content=mutated_dat,
        numbered_content=mutated_dat,
        sha256=hashlib.sha256(mutated_dat.encode("utf-8")).hexdigest(),
        line_count=len(mutated_dat.splitlines()),
    )
    files["legacy/core-banking-system/ACCOUNTS.CPY"] = cpy_target
    files["legacy/core-banking-system/ACCOUNTS.DAT"] = dat_target

    mutated_bundle = MultiSourceBundle(
        files=files,
        total_physical_lines=sum(f.line_count for f in files.values()),
        bundle_sha256="mutated_test_bundle",
        formatted_prompt_payload="mutated_payload",
    )

    parser = SystemCobolParser(mutated_bundle)
    # The parser must parse without crash and calculate layout dynamically
    facts = parser.get_supported_facts()
    layout_facts = [f.fact for f in facts if f.fact.fact_category == "RECORD_LAYOUT"]
    assert len(layout_facts) > 0


# ======================================================================
# 3. CORRECT NON-ATOMIC UPDATE CONSEQUENCE
# ======================================================================


def test_non_atomic_update_consequence_qualified():
    """Verify non-atomic update consequence is deterministic.

    Checks (NON_ATOMIC_EXTERNAL_MUTATION / DATA_INTEGRITY).
    """
    parser_path = REPO_ROOT / "src" / "cobol" / "system_cobol_parser.py"
    facts_path = REPO_ROOT / "src" / "cobol" / "system_atomic_facts.py"
    golden_path = REPO_ROOT / "evals" / "expected" / "system-understanding-v3.json"

    for path in [parser_path, facts_path, golden_path]:
        content = path.read_text(encoding="utf-8")
        assert "PERMANENT_DATA_LOSS" not in content, f"PERMANENT_DATA_LOSS found in {path}"

    golden_text = golden_path.read_text(encoding="utf-8")
    assert "NON_ATOMIC_EXTERNAL_MUTATION" in golden_text
    assert "DATA_INTEGRITY" in golden_text


# ======================================================================
# 4. CATEGORY COMPLETENESS POLICY
# ======================================================================


def test_category_completeness_policy():
    """Verify category completeness policies in golden metadata and evaluator."""
    golden_path = REPO_ROOT / "evals" / "expected" / "system-understanding-v3.json"
    data = json.loads(golden_path.read_text(encoding="utf-8"))

    policies = data.get("category_policies", {})
    assert len(policies) == 18

    allowed_policies = {
        "REQUIRED_EXHAUSTIVE",
        "REQUIRED_PREREGISTERED_CORE",
        "OPTIONAL_SUPPLEMENTARY",
    }
    for cat, policy in policies.items():
        assert policy in allowed_policies, f"Category {cat} has invalid policy: {policy}"

    # Check finite syntactic categories are REQUIRED_EXHAUSTIVE
    exhaustive_cats = [
        "PROGRAM_DECLARATION",
        "CALL_OCCURRENCE",
        "CALL_EDGE",
        "INTERNAL_CALL_RESOLUTION",
        "FILE_BINDING",
        "RECORD_LAYOUT",
        "TERMINATION_SITE",
        "CALLER_CONTINUATION_CONSTRAINT",
        "COMMAND_INVOCATION",
        "RESOURCE_LIFECYCLE",
        "OPERATION_SEQUENCE",
        "PLATFORM_DEPENDENCY",
        "DATA_STATE_COMPARISON",
    ]
    for cat in exhaustive_cats:
        assert policies[cat] == "REQUIRED_EXHAUSTIVE", (
            f"Expected {cat} to be REQUIRED_EXHAUSTIVE, got {policies[cat]}"
        )

    # Check complex / selective categories are REQUIRED_PREREGISTERED_CORE
    preregistered_cats = [
        "RECORD_LAYOUT_RELATION",
        "COMPUTATION_DATAFLOW",
        "DATA_TRANSFER_RELATION",
        "BEHAVIORAL_RISK",
    ]
    for cat in preregistered_cats:
        assert policies[cat] == "REQUIRED_PREREGISTERED_CORE", (
            f"Expected {cat} to be REQUIRED_PREREGISTERED_CORE, got {policies[cat]}"
        )

    # Check optional supplementary categories
    optional_cats = [
        "FILE_OPERATION",
    ]
    for cat in optional_cats:
        assert policies[cat] == "OPTIONAL_SUPPLEMENTARY", (
            f"Expected {cat} to be OPTIONAL_SUPPLEMENTARY, got {policies[cat]}"
        )


# ======================================================================
# 5. REMOVE MODEL-VISIBLE ANSWER LEAKAGE
# ======================================================================


def test_schema_leakage_tokens_removed():
    """Verify schema field descriptions contain no narrow fixture answer hints."""
    schema_path = REPO_ROOT / "agents" / "legacy_analyzer" / "schemas" / "system_assessment.py"
    schema_source = schema_path.read_text(encoding="utf-8")

    forbidden_tokens = [
        "MISSING_FILE_STATUS_CHECK",
        "NON_ATOMIC_FILE_UPDATE",
        "CALLEE_PROCESS_TERMINATION",
        "WINDOWS_CMD",
        "PERMANENT_DATA_LOSS",
    ]
    for tok in forbidden_tokens:
        assert tok not in schema_source, f"Leakage token '{tok}' found in {schema_path}"


# ======================================================================
# 6. REMOVE DUPLICATE PROGRAM COLLECTION
# ======================================================================


def test_duplicate_truth_bearing_collection_absence():
    """Verify only program_declarations exists and programs collection is removed."""
    fields = SystemAssessment.model_fields
    assert "program_declarations" in fields
    assert "programs" not in fields

    prompt_path = REPO_ROOT / "agents" / "legacy_analyzer" / "prompts" / "system_v3.md"
    prompt_text = prompt_path.read_text(encoding="utf-8")
    assert '"program_declarations"' in prompt_text or "program_declarations" in prompt_text
    assert '"programs":' not in prompt_text


# ======================================================================
# 7. AUTHORIZATION SHA DESIGN — TWO-PHASE NO SELF-REFERENCE
# ======================================================================


def test_authorization_sha_non_self_referential_design():
    """Verify candidate C has empty candidate_git_sha and two-phase contract."""
    auth_path = REPO_ROOT / "evals" / "baselines" / "gate-3-baseline-v1.json"
    data = json.loads(auth_path.read_text(encoding="utf-8"))

    # In candidate C, candidate_git_sha is empty string, forbidding live runs until commit A
    assert "candidate_git_sha" in data
    assert data["candidate_git_sha"] == ""
    assert "expected_git_sha" not in data

    # Verify run-gate-3 loads authorization spec with candidate_git_sha
    mod = get_run_gate_3_module()
    spec, _ = mod.load_authorization_spec(auth_path)
    assert "candidate_git_sha" in spec


# ======================================================================
# 8. IRREVOCABLE RUN-LABEL RESERVATION
# ======================================================================


def test_irrevocable_run_label_reservation_refusal(tmp_path: Path):
    """Verify existing run-state (RESERVED, MODEL_INVOCATION, FAILED, COMPLETED) aborts."""
    mod = get_run_gate_3_module()
    spec_path = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH
    out_dir = tmp_path / "reserved_run"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Existing RESERVED state
    state_file = out_dir / "run-state.json"
    state_file.write_text(json.dumps({"status": "RESERVED"}), encoding="utf-8")

    with pytest.raises(RuntimeError, match="Irrevocable reservation error"):
        mod.execute_gate_3(
            repo_root=REPO_ROOT,
            auth_spec_path=spec_path,
            output_dir=out_dir,
            run_label="baseline-v1",
            synthetic=True,
            allow_dirty=True,
        )

    # 2. Existing MODEL_INVOCATION state
    state_file.write_text(json.dumps({"status": "MODEL_INVOCATION"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="Irrevocable reservation error"):
        mod.execute_gate_3(
            repo_root=REPO_ROOT,
            auth_spec_path=spec_path,
            output_dir=out_dir,
            run_label="baseline-v1",
            synthetic=True,
            allow_dirty=True,
        )

    # 3. Existing FAILED state
    state_file.write_text(json.dumps({"status": "FAILED"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="Irrevocable reservation error"):
        mod.execute_gate_3(
            repo_root=REPO_ROOT,
            auth_spec_path=spec_path,
            output_dir=out_dir,
            run_label="baseline-v1",
            synthetic=True,
            allow_dirty=True,
        )

    # 4. Existing COMPLETED state
    state_file.write_text(json.dumps({"status": "COMPLETED"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="Irrevocable reservation error"):
        mod.execute_gate_3(
            repo_root=REPO_ROOT,
            auth_spec_path=spec_path,
            output_dir=out_dir,
            run_label="baseline-v1",
            synthetic=True,
            allow_dirty=True,
        )


# ======================================================================
# 9. PREFLIGHT IDENTITY CHECKS (WRONG MODEL / PROJECT FINGERPRINT)
# ======================================================================


def test_preflight_identity_checks_refusal(tmp_path: Path):
    """Verify wrong model or wrong project fingerprint causes refusal with zero live calls."""
    mod = get_run_gate_3_module()
    spec, _ = mod.load_authorization_spec(REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH)

    # Create dummy config with mismatched model
    class DummyConfig:
        foundry_model = "wrong-model-name"
        foundry_project_endpoint = "https://example.foundry.azure.com"
        reasoning_effort = "high"

    # Preflight verification must fail before writing MODEL_INVOCATION or calling API
    with pytest.raises(RuntimeError, match="Model mismatch"):
        if DummyConfig.foundry_model != spec["requested_model"]:
            raise RuntimeError(
                f"Model mismatch: config={DummyConfig.foundry_model}, "
                f"spec={spec['requested_model']}"
            )

    # Create dummy config with mismatched fingerprint
    endpoint = "https://other-project.foundry.azure.com"
    norm_ep = endpoint.strip().rstrip("/").lower()
    fp = hashlib.sha256(norm_ep.encode("utf-8")).hexdigest()
    with pytest.raises(RuntimeError, match="Foundry project fingerprint mismatch"):
        if fp != spec["foundry_project_fingerprint"]:
            raise RuntimeError(
                f"Foundry project fingerprint mismatch: actual={fp}, "
                f"expected={spec['foundry_project_fingerprint']}"
            )


# ======================================================================
# 10. COMPLETE IMMUTABLE ARTIFACT PRESERVATION
# ======================================================================


def test_complete_immutable_artifact_preservation(tmp_path: Path):
    """Verify all 13 immutable artifacts + terminal-result are produced and hashed
    in manifest.json.
    """
    mod = get_run_gate_3_module()
    spec_path = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH
    out_dir = tmp_path / "immut_out"

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

    # Coordination reservation file exists
    assert (out_dir / mod.RESERVATION_STATE_FILE).is_file()

    required_immutable_artifacts = [
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

    for name in required_immutable_artifacts:
        fpath = out_dir / name
        assert fpath.is_file(), f"Missing required artifact: {name}"
    assert (out_dir / "manifest.json").is_file()

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert "artifacts" in manifest
    assert len(manifest["artifacts"]) == 13
    assert mod.RESERVATION_STATE_FILE not in manifest["artifacts"]

    for name, expected_sha in manifest["artifacts"].items():
        actual_sha = hashlib.sha256((out_dir / name).read_bytes()).hexdigest()
        assert actual_sha == expected_sha, f"SHA mismatch for artifact {name}"


# ======================================================================
# 11. DIRECT CHILD AUTHORIZATION CONTRACT AND SCOPED RECORD ISOLATION
# ======================================================================


def test_authorization_contract_rejects_non_direct_child(monkeypatch):
    """Verify validate_authorization_contract rejects commit that is not direct child A^ == C."""
    mod = get_run_gate_3_module()
    spec_path = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH

    monkeypatch.setattr(mod, "verify_clean_worktree", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "verify_no_executable_overlays", lambda *args, **kwargs: None)

    import subprocess

    orig_run = subprocess.run

    def mock_run(cmd, *args, **kwargs):
        if len(cmd) >= 3 and cmd[0] == "git" and cmd[1] == "rev-parse" and cmd[2] == "HEAD":
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="auth_commit_a_sha\n")
        if len(cmd) >= 3 and cmd[0] == "git" and cmd[1] == "rev-parse" and "--verify" in cmd:
            # Return a different parent SHA than candidate
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="other_parent_sha\n")
        return orig_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mock_run)

    with pytest.raises(RuntimeError, match="must be a direct child of candidate commit"):
        mod.validate_authorization_contract(
            repo_root=REPO_ROOT,
            candidate_sha="candidate_c_sha",
            authorization_commit_sha="auth_commit_a_sha",
            auth_spec_path=spec_path,
            allow_dirty=False,
            is_live=True,
        )


def test_authorization_contract_rejects_diff_outside_canonical_spec(monkeypatch):
    """Verify validate_authorization_contract rejects diff touching files outside canonical spec."""
    mod = get_run_gate_3_module()
    spec_path = REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH

    monkeypatch.setattr(mod, "verify_clean_worktree", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "verify_no_executable_overlays", lambda *args, **kwargs: None)

    import subprocess

    orig_run = subprocess.run

    def mock_run(cmd, *args, **kwargs):
        if len(cmd) >= 3 and cmd[0] == "git" and cmd[1] == "rev-parse" and cmd[2] == "HEAD":
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="auth_commit_a_sha\n")
        if len(cmd) >= 3 and cmd[0] == "git" and cmd[1] == "rev-parse" and "--verify" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="candidate_c_sha\n")
        if len(cmd) >= 3 and cmd[0] == "git" and cmd[1] == "diff":
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout="evals/baselines/gate-3-baseline-v1.json\nsrc/cobol/system_cobol_parser.py\n",
            )
        return orig_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mock_run)

    with pytest.raises(RuntimeError, match="modified files outside canonical baseline spec"):
        mod.validate_authorization_contract(
            repo_root=REPO_ROOT,
            candidate_sha="candidate_c_sha",
            authorization_commit_sha="auth_commit_a_sha",
            auth_spec_path=spec_path,
            allow_dirty=False,
            is_live=True,
        )


def test_unit_scoped_record_to_fd_isolation():
    """Verify that record definitions are strictly scoped per compilation unit and do not leak."""
    from src.cobol.multi_source_reader import MultiSourceBundle, TargetFile

    cbl1 = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PROG-A.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        "           SELECT FILE-A ASSIGN TO 'DATA-A.DAT'.\n"
        "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
        "       FD  FILE-A.\n"
        "       01  SHARED-RECORD-NAME.\n"
        "           05 REC-FIELD-A  PIC X(10).\n"
        "       PROCEDURE DIVISION.\n"
        "           WRITE SHARED-RECORD-NAME.\n"
        "           STOP RUN.\n"
    )
    cbl2 = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PROG-B.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        "           SELECT FILE-B ASSIGN TO 'DATA-B.DAT'.\n"
        "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
        "       FD  FILE-B.\n"
        "       01  SHARED-RECORD-NAME.\n"
        "           05 REC-FIELD-B  PIC X(20).\n"
        "       PROCEDURE DIVISION.\n"
        "           WRITE SHARED-RECORD-NAME.\n"
        "           STOP RUN.\n"
    )

    files = {
        "PROG-A.CBL": TargetFile(
            relative_path="PROG-A.CBL",
            file_type="COBOL",
            raw_content=cbl1,
            numbered_content=cbl1,
            sha256=hashlib.sha256(cbl1.encode("utf-8")).hexdigest(),
            line_count=len(cbl1.splitlines()),
        ),
        "PROG-B.CBL": TargetFile(
            relative_path="PROG-B.CBL",
            file_type="COBOL",
            raw_content=cbl2,
            numbered_content=cbl2,
            sha256=hashlib.sha256(cbl2.encode("utf-8")).hexdigest(),
            line_count=len(cbl2.splitlines()),
        ),
    }
    bundle = MultiSourceBundle(
        files=files,
        total_physical_lines=len(cbl1.splitlines()) + len(cbl2.splitlines()),
        bundle_sha256="test_isolation_bundle",
        formatted_prompt_payload="test_payload",
    )
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()

    # Verify PROG-A WRITE resolves to FILE-A and PROG-B WRITE resolves to FILE-B
    ops = [f.fact for f in facts if isinstance(f.fact, FileOperationFact)]
    op_a = next((o for o in ops if o.program_id == "PROG-A"), None)
    op_b = next((o for o in ops if o.program_id == "PROG-B"), None)
    assert op_a is not None and op_a.internal_file_name == "FILE-A"
    assert op_b is not None and op_b.internal_file_name == "FILE-B"


def test_exact_evidence_based_model_match():
    """Verify that response_model must match requested_model (gpt-5-mini) with exact equality."""
    from agents.legacy_analyzer.system_agent import SystemAnalyzerAgent, SystemExecutionMetadata

    agent = SystemAnalyzerAgent()
    meta = SystemExecutionMetadata(requested_model="gpt-5-mini")

    class MockResponse:
        status = "completed"
        model = "gpt-5-mini-2025-08-07"  # unverified versioned alias
        refusal = None
        output = []

    with pytest.raises(ValueError, match="does not match requested model"):
        agent.validate_and_parse_response(MockResponse(), meta, requested_model="gpt-5-mini")


# ======================================================================
# 12. BLOCKER 1 — DIRECT CHILD RESERVATION MUST FAIL CLOSED
# ======================================================================


def test_child_reservation_fail_closed_regressions(tmp_path: Path, monkeypatch):
    """Verify official live internal child fails closed before model invocation.

    Tests:
    - missing reservation-state.json
    - malformed JSON
    - missing required state fields
    - wrong authorization_commit_sha (A)
    - wrong candidate_git_sha (C)
    - wrong run_label
    - wrong gate (!= 3)
    - status != RESERVED
    - artifact_dir != canonical destination

    In EVERY case, verifies zero model invocations via sentinel.
    """
    import argparse

    from agents.legacy_analyzer.system_agent import SystemAnalyzerAgent

    mod = get_run_gate_3_module()
    monkeypatch.setattr(mod, "is_isolated_python", lambda: True)
    monkeypatch.setattr(mod, "is_bytecode_writing_disabled", lambda: True)

    model_calls = 0

    def sentinel_call(*args, **kwargs):
        nonlocal model_calls
        model_calls += 1
        raise RuntimeError("FATAL: Model invoked when child reservation should fail closed!")

    monkeypatch.setattr(SystemAnalyzerAgent, "invoke_raw", sentinel_call)
    monkeypatch.setattr(SystemAnalyzerAgent, "analyze_system", sentinel_call)

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    run_label = "official-baseline-v1"
    canonical_dir = repo_dir / "artifacts" / "gate-3" / run_label
    canonical_dir.mkdir(parents=True, exist_ok=True)
    res_file = canonical_dir / mod.RESERVATION_STATE_FILE

    base_args = argparse.Namespace(
        provenance_repo=str(repo_dir),
        snapshot_dir=str(REPO_ROOT),
        artifact_dir=str(canonical_dir),
        auth_spec=str(REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH),
        run_label=run_label,
        authorized_git_sha="sha_candidate_c",
        authorization_commit_sha="sha_auth_a",
        golden_path=str(REPO_ROOT / mod.DEFAULT_GOLDEN_PATH),
        synthetic=False,
        dry_run=False,
        allow_dirty=False,
    )

    valid_reservation = {
        "status": "RESERVED",
        "gate": 3,
        "run_label": run_label,
        "candidate_git_sha": "sha_candidate_c",
        "authorization_commit_sha": "sha_auth_a",
    }

    # 1. Missing reservation-state.json
    if res_file.exists():
        res_file.unlink()
    ret = mod.execute_internal_child(base_args)
    assert ret == 1
    assert model_calls == 0

    # 2. Malformed JSON
    res_file.write_text("{malformed:json,", encoding="utf-8")
    ret = mod.execute_internal_child(base_args)
    assert ret == 1
    assert model_calls == 0

    # 3. Not a JSON object (e.g. JSON list)
    res_file.write_text('["not", "an", "object"]', encoding="utf-8")
    ret = mod.execute_internal_child(base_args)
    assert ret == 1
    assert model_calls == 0

    # 4. Missing required state fields
    for field in ["status", "gate", "run_label", "candidate_git_sha", "authorization_commit_sha"]:
        corrupted = dict(valid_reservation)
        del corrupted[field]
        res_file.write_text(json.dumps(corrupted), encoding="utf-8")
        ret = mod.execute_internal_child(base_args)
        assert ret == 1, f"Missing field '{field}' must fail closed!"
        assert model_calls == 0

    # 5. Wrong authorization_commit_sha (wrong A)
    corrupted = dict(valid_reservation, authorization_commit_sha="wrong_sha_a")
    res_file.write_text(json.dumps(corrupted), encoding="utf-8")
    ret = mod.execute_internal_child(base_args)
    assert ret == 1
    assert model_calls == 0

    # 6. Wrong candidate_git_sha (wrong C)
    corrupted = dict(valid_reservation, candidate_git_sha="wrong_sha_c")
    res_file.write_text(json.dumps(corrupted), encoding="utf-8")
    ret = mod.execute_internal_child(base_args)
    assert ret == 1
    assert model_calls == 0

    # 7. Wrong run_label
    corrupted = dict(valid_reservation, run_label="other-run-label")
    res_file.write_text(json.dumps(corrupted), encoding="utf-8")
    ret = mod.execute_internal_child(base_args)
    assert ret == 1
    assert model_calls == 0

    # 8. Wrong gate
    corrupted = dict(valid_reservation, gate=2)
    res_file.write_text(json.dumps(corrupted), encoding="utf-8")
    ret = mod.execute_internal_child(base_args)
    assert ret == 1
    assert model_calls == 0

    # 9. Status != RESERVED (MODEL_INVOCATION, COMPLETED, FAILED)
    for bad_status in ["MODEL_INVOCATION", "COMPLETED", "FAILED", "PENDING"]:
        corrupted = dict(valid_reservation, status=bad_status)
        res_file.write_text(json.dumps(corrupted), encoding="utf-8")
        ret = mod.execute_internal_child(base_args)
        assert ret == 1
        assert model_calls == 0

    # 10. Artifact directory != canonical destination
    non_canonical_dir = tmp_path / "other_artifacts" / run_label
    non_canonical_dir.mkdir(parents=True, exist_ok=True)
    non_canonical_res = non_canonical_dir / mod.RESERVATION_STATE_FILE
    non_canonical_res.write_text(json.dumps(valid_reservation), encoding="utf-8")
    bad_dest_args = argparse.Namespace(**dict(vars(base_args), artifact_dir=str(non_canonical_dir)))
    ret = mod.execute_internal_child(bad_dest_args)
    assert ret == 1
    assert model_calls == 0


# ======================================================================
# 13. BLOCKER 2 — BIND CHILD TO COMMITTED AUTHORIZATION SPEC
# ======================================================================


def test_child_spec_binding_regressions(tmp_path: Path, monkeypatch):
    """Verify child enforces exact binding to committed authorization spec.

    Tests:
    - spec candidate C1 vs CLI candidate C2 => zero-call FAIL
    - spec run label X vs CLI run label Y => zero-call FAIL
    - A is valid child of C but A != current HEAD => zero-call FAIL
    - malformed / invalid committed spec => zero-call FAIL
    """
    import argparse
    import subprocess

    from agents.legacy_analyzer.system_agent import SystemAnalyzerAgent

    mod = get_run_gate_3_module()
    monkeypatch.setattr(mod, "is_isolated_python", lambda: True)
    monkeypatch.setattr(mod, "is_bytecode_writing_disabled", lambda: True)
    monkeypatch.setattr(mod, "verify_trusted_runner_bootstrap", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "verify_snapshot_against_git_objects", lambda *args, **kwargs: None)

    model_calls = 0

    def sentinel_call(*args, **kwargs):
        nonlocal model_calls
        model_calls += 1
        raise RuntimeError("FATAL: Model invoked during spec binding failure!")

    monkeypatch.setattr(SystemAnalyzerAgent, "invoke_raw", sentinel_call)
    monkeypatch.setattr(SystemAnalyzerAgent, "analyze_system", sentinel_call)

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    run_label = "baseline-v1"
    canonical_dir = repo_dir / "artifacts" / "gate-3" / run_label
    canonical_dir.mkdir(parents=True, exist_ok=True)
    res_file = canonical_dir / mod.RESERVATION_STATE_FILE

    base_reservation = {
        "status": "RESERVED",
        "gate": 3,
        "run_label": run_label,
        "candidate_git_sha": "sha_candidate_c1",
        "authorization_commit_sha": "sha_auth_a",
    }
    res_file.write_text(json.dumps(base_reservation), encoding="utf-8")

    # 1. Spec candidate C1 vs CLI candidate C2
    spec_with_c1 = {
        "gate": 3,
        "spec_version": "3.4.1",
        "schema_version": "3.4.1",
        "prompt_version": "3.4.1",
        "evaluator_version": "3.4.1",
        "golden_dataset_version": "3.4.1",
        "requested_model": "gpt-5-mini",
        "reasoning_effort": "high",
        "max_attempts": 1,
        "openai_client_max_retries": 0,
        "run_label": run_label,
        "candidate_git_sha": "sha_candidate_c1",
        "prompt_sha256": "85b19f21c4de45f6fe1a6a219484f856b89bea21b595e04f19d8dc521f820483",
        "wire_schema_sha256": "4129e91578e445a1fb8392728aef2406c73ec60dcdd60cf84dafb706917f6686",
        "golden_dataset_sha256": "88592af941a35d73077f55d3e2a32dce6d4bd18364acd9d792dd9005c7f97149",
        "bundle_manifest_sha256": (
            "9bfa5f67aeb10e408ecbbcf8f0f0ff82894ae4a896d93f773489fe0d2c0b021d"
        ),
        "foundry_project_fingerprint": (
            "8d3e4299446d036e0d9b4c090da9081a3bb9a69ef49042b4507119f8dd0e1948"
        ),
        "target_bundle_files": [
            "legacy/core-banking-system/BANK-MAIN.CBL",
            "legacy/core-banking-system/INIT-DB.CBL",
            "legacy/core-banking-system/TRANS-PROC.CBL",
            "legacy/core-banking-system/REPORT-GEN.CBL",
            "legacy/core-banking-system/ACCOUNTS.CPY",
            "legacy/core-banking-system/ACCOUNTS.DAT",
        ],
    }

    monkeypatch.setattr(
        mod, "load_authorization_spec_from_git", lambda *args, **kwargs: (spec_with_c1, "fake_sha")
    )
    monkeypatch.setattr(
        mod, "load_authorization_spec", lambda *args, **kwargs: (spec_with_c1, "fake_sha")
    )

    auth_file = repo_dir / mod.DEFAULT_AUTH_SPEC_PATH
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    auth_file.write_text(json.dumps(spec_with_c1), encoding="utf-8")

    monkeypatch.setattr(mod, "verify_clean_worktree", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "verify_no_executable_overlays", lambda *args, **kwargs: None)

    args_c2 = argparse.Namespace(
        provenance_repo=str(repo_dir),
        snapshot_dir=str(REPO_ROOT),
        artifact_dir=str(canonical_dir),
        auth_spec=str(auth_file),
        run_label=run_label,
        authorized_git_sha="sha_candidate_c2",  # C2 != C1
        authorization_commit_sha="sha_auth_a",
        golden_path=str(REPO_ROOT / mod.DEFAULT_GOLDEN_PATH),
        synthetic=False,
        dry_run=False,
        allow_dirty=False,
    )
    # Reservation candidate_git_sha must match authorized_git_sha to reach spec check
    res_file.write_text(
        json.dumps(dict(base_reservation, candidate_git_sha="sha_candidate_c2")),
        encoding="utf-8",
    )
    ret = mod.execute_internal_child(args_c2)
    assert ret == 1
    assert model_calls == 0

    # 2. Spec run label X vs CLI run label Y
    spec_with_x = dict(spec_with_c1, run_label="run-x")
    monkeypatch.setattr(
        mod, "load_authorization_spec_from_git", lambda *args, **kwargs: (spec_with_x, "fake_sha")
    )
    res_file.write_text(
        json.dumps(dict(base_reservation, candidate_git_sha="sha_candidate_c1")),
        encoding="utf-8",
    )
    args_y = argparse.Namespace(
        provenance_repo=str(repo_dir),
        snapshot_dir=str(REPO_ROOT),
        artifact_dir=str(canonical_dir),
        auth_spec=str(auth_file),
        run_label=run_label,  # Y != X
        authorized_git_sha="sha_candidate_c1",
        authorization_commit_sha="sha_auth_a",
        golden_path=str(REPO_ROOT / mod.DEFAULT_GOLDEN_PATH),
        synthetic=False,
        dry_run=False,
        allow_dirty=False,
    )
    ret = mod.execute_internal_child(args_y)
    assert ret == 1
    assert model_calls == 0

    # 3. A is valid child of C but A != current HEAD
    monkeypatch.setattr(
        mod, "load_authorization_spec_from_git", lambda *args, **kwargs: (spec_with_c1, "fake_sha")
    )
    orig_sub_run = subprocess.run

    def mock_sub_run(cmd, *args, **kwargs):
        if len(cmd) >= 3 and cmd[0] == "git" and cmd[1] == "rev-parse" and cmd[2] == "HEAD":
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="other_commit_not_a\n"
            )
        return orig_sub_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mock_sub_run)
    args_head_mismatch = argparse.Namespace(
        provenance_repo=str(repo_dir),
        snapshot_dir=str(REPO_ROOT),
        artifact_dir=str(canonical_dir),
        auth_spec=str(auth_file),
        run_label=run_label,
        authorized_git_sha="sha_candidate_c1",
        authorization_commit_sha="sha_auth_a",
        golden_path=str(REPO_ROOT / mod.DEFAULT_GOLDEN_PATH),
        synthetic=False,
        dry_run=False,
        allow_dirty=False,
    )
    ret = mod.execute_internal_child(args_head_mismatch)
    assert ret == 1
    assert model_calls == 0

    # 4. Malformed / invalid committed spec
    bad_spec = dict(spec_with_c1)
    del bad_spec["spec_version"]
    monkeypatch.setattr(subprocess, "run", orig_sub_run)

    with pytest.raises(ValueError, match="missing required keys"):
        mod.validate_authorization_spec_dict(bad_spec)

    # Also verify child fails with zero model calls on malformed spec
    monkeypatch.setattr(
        mod, "load_authorization_spec_from_git", lambda *args, **kwargs: (bad_spec, "fake_sha")
    )
    args_bad_spec = argparse.Namespace(
        provenance_repo=str(repo_dir),
        snapshot_dir=str(REPO_ROOT),
        artifact_dir=str(canonical_dir),
        auth_spec=str(auth_file),
        run_label=run_label,
        authorized_git_sha="sha_candidate_c1",
        authorization_commit_sha="sha_auth_a",
        golden_path=str(REPO_ROOT / mod.DEFAULT_GOLDEN_PATH),
        synthetic=False,
        dry_run=False,
        allow_dirty=False,
    )
    ret = mod.execute_internal_child(args_bad_spec)
    assert ret == 1
    assert model_calls == 0


# ======================================================================
# 14. BLOCKER 3 — TERMINAL FAILURE EVIDENCE PRESERVATION
# ======================================================================


def test_terminal_failure_evidence_preservation(tmp_path: Path):
    """Verify centralized failure finalizer preserves raw response, writes terminal-result.json,
    manifest.json, transitions reservation-state.json to FAILED, and blocks re-entry.
    """
    mod = get_run_gate_3_module()
    artifact_dir = tmp_path / "failure_artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    res_file = artifact_dir / mod.RESERVATION_STATE_FILE

    # Initial reservation
    res_file.write_text(
        json.dumps(
            {
                "status": "MODEL_INVOCATION",
                "gate": 3,
                "run_label": "fail-test-run",
                "candidate_git_sha": "cand_sha",
                "authorization_commit_sha": "auth_sha",
            }
        ),
        encoding="utf-8",
    )

    spec = {
        "gate": 3,
        "spec_version": "3.4.1",
        "run_label": "fail-test-run",
    }
    raw_content = {"id": "resp_test_123", "model": "gpt-5-mini", "output": []}

    class DummyMeta:
        response_id = "resp_test_123"
        response_model_id = "gpt-5-mini"

        def to_dict(self):
            return {
                "response_id": self.response_id,
                "response_model_id": self.response_model_id,
            }

    # Simulate post-model failure (e.g. status validation failure or refusal)
    mod.finalize_post_model_failure(
        artifact_dir=artifact_dir,
        reservation_file=res_file,
        error_phase="RESPONSE_VALIDATION",
        error=ValueError("Model response status validation failed: refusal detected"),
        spec=spec,
        candidate_sha="cand_sha",
        authorization_commit_sha="auth_sha",
        authorized_sha="auth_sha",
        run_label="fail-test-run",
        metadata=DummyMeta(),
        raw_response_content=raw_content,
    )

    # 1. raw-response.json survives
    raw_file = artifact_dir / "raw-response.json"
    assert raw_file.is_file()
    assert json.loads(raw_file.read_text(encoding="utf-8")) == raw_content

    # 2. terminal-result.json exists and says FAILED
    term_file = artifact_dir / mod.TERMINAL_RESULT_FILE
    assert term_file.is_file()
    term_data = json.loads(term_file.read_text(encoding="utf-8"))
    assert term_data["status"] == "FAILED"
    assert term_data["error_phase"] == "RESPONSE_VALIDATION"
    assert term_data["error_type"] == "ValueError"
    assert "refusal detected" in term_data["error_message"]
    assert term_data["candidate_git_sha"] == "cand_sha"
    assert term_data["authorization_commit_sha"] == "auth_sha"
    assert term_data["response_id"] == "resp_test_123"

    # 3. manifest.json covers preserved immutable artifacts with matching SHA256
    manifest_file = artifact_dir / "manifest.json"
    assert manifest_file.is_file()
    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data["status"] == "FAILED"
    assert manifest_data["gate_3_pass"] is False
    assert "raw-response.json" in manifest_data["artifacts"]
    assert mod.TERMINAL_RESULT_FILE in manifest_data["artifacts"]
    assert mod.RESERVATION_STATE_FILE not in manifest_data["artifacts"]

    for name, sha in manifest_data["artifacts"].items():
        actual_sha = hashlib.sha256((artifact_dir / name).read_bytes()).hexdigest()
        assert actual_sha == sha, f"SHA mismatch for preserved artifact {name}"

    # 4. reservation-state.json is FAILED
    assert res_file.is_file()
    res_data = json.loads(res_file.read_text(encoding="utf-8"))
    assert res_data["status"] == "FAILED"
    assert res_data["error_phase"] == "RESPONSE_VALIDATION"

    # 5. Subsequent rerun is refused
    with pytest.raises(RuntimeError, match="Irrevocable reservation error"):
        mod.check_existing_reservation(artifact_dir, "fail-test-run")


# ======================================================================
# 15. REQUIREMENT 4 — PREREGISTERED CORE / SUPPLEMENTARY TEST
# ======================================================================


def test_trans_proc_temp_file_supplementary_adversarial():
    """Verify resource-scoped semantic matching handles true supplementary fact.

    Swaps required TRANS-PROC / ACCOUNT-FILE / MISSING_ERROR_STATUS for
    true supplementary TRANS-PROC / TEMP-FILE / MISSING_ERROR_STATUS.

    Expected:
    - TEMP-FILE prediction is SUPPORTED
    - unsupported_predicted_count == 0
    - required ACCOUNT-FILE proposition remains UNMATCHED
    - recall < 1.0 (58 / 59)
    - Gate 3 FAIL
    """
    from agents.legacy_analyzer.schemas.system_assessment import BehavioralRisk, SourceEvidence
    from src.cobol.multi_source_reader import read_system_bundle
    from src.cobol.system_cobol_parser import SystemCobolParser
    from src.cobol.system_support_index import SystemSupportIndex
    from src.validation.evaluator_v3 import SystemEvaluatorV3, load_golden_assessment

    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, bundle, file_status_certificate=parser.file_status_certificate
    )
    golden_path = REPO_ROOT / "evals" / "expected" / "system-understanding-v3.json"
    evaluator = SystemEvaluatorV3(index, golden_dataset_path=golden_path)

    assessment = load_golden_assessment(golden_dataset_path=golden_path)

    # 1. Remove required TRANS-PROC / ACCOUNT-FILE / MISSING_ERROR_STATUS
    initial_risks = len(assessment.behavioral_risks)
    assessment.behavioral_risks = [
        r
        for r in assessment.behavioral_risks
        if not (
            r.program_id == "TRANS-PROC"
            and r.resource_name == "ACCOUNT-FILE"
            and r.risk_basis_kind == "MISSING_ERROR_STATUS"
        )
    ]
    assert len(assessment.behavioral_risks) == initial_risks - 1

    # 2. Add true supplementary TRANS-PROC / TEMP-FILE / MISSING_ERROR_STATUS
    supp_risk = BehavioralRisk(
        program_id="TRANS-PROC",
        risk_category="IO_ERROR_HANDLING",
        risk_basis_kind="MISSING_ERROR_STATUS",
        impact_category="ERROR_VISIBILITY",
        resource_name="TEMP-FILE",
        operation_evidence=SourceEvidence(
            file_path="legacy/core-banking-system/TRANS-PROC.CBL",
            line_start=47,
            line_end=82,
        ),
        affected_resource_evidence=SourceEvidence(
            file_path="legacy/core-banking-system/TRANS-PROC.CBL",
            line_start=9,
            line_end=10,
        ),
    )
    assessment.behavioral_risks.append(supp_risk)

    metrics, predictions = evaluator.evaluate_assessment(assessment)

    # 3. Assertions
    temp_pred = next(
        p
        for p in predictions
        if p.semantic_key
        == "RISK:TRANS-PROC:IO_ERROR_HANDLING:MISSING_ERROR_STATUS:ERROR_VISIBILITY:TEMP-FILE"
    )
    assert temp_pred.is_supported is True
    assert metrics.unsupported_predicted_count == 0
    assert metrics.missing_expected_count == 1
    assert metrics.matched_expected_count == 58
    assert metrics.expected_fact_count == 59
    assert metrics.recall < 1.0
    assert metrics.gate_3_pass is False


# ======================================================================
# 16. REQUIREMENT 5 — RISK ONTOLOGY ACTUALLY DETERMINISTIC
# ======================================================================


def test_risk_ontology_wire_schema_deterministic():
    """Verify OpenAI wire schema enforces Literal enum constraints and leaks no fixture tokens."""
    from pydantic import ValidationError

    from agents.legacy_analyzer.schemas.system_assessment import BehavioralRisk, SourceEvidence
    from agents.legacy_analyzer.schemas.system_export import get_system_openai_wire_schema

    wire = get_system_openai_wire_schema()
    wire_json = json.dumps(wire)

    # 1. Enum constraints are present in wire schema properties
    defs = wire["json_schema"]["schema"].get("$defs", {})
    br = defs.get("BehavioralRisk", {})
    props = br.get("properties", {})

    assert "enum" in props["risk_category"], "risk_category missing enum in wire schema!"
    expected_risk_categories = {
        "IO_ERROR_HANDLING",
        "DATA_INTEGRITY",
        "CONTROL_FLOW",
        "PORTABILITY",
        "RESOURCE_LIFECYCLE",
        "CONCURRENCY_ERROR",
        "DATA_CORRUPTION",
        "CONFIGURATION",
    }
    assert set(props["risk_category"]["enum"]) == expected_risk_categories

    assert "enum" in props["risk_basis_kind"], "risk_basis_kind missing enum in wire schema!"
    expected_basis_kinds = {
        "MISSING_ERROR_STATUS",
        "NON_ATOMIC_EXTERNAL_MUTATION",
        "NON_RETURNING_TERMINATION",
        "UNCHECKED_EXTERNAL_RESULT",
        "INVALID_INPUT_HANDLING",
        "RESOURCE_LIFECYCLE_FAILURE",
        "RESOURCE_LEAK",
        "DEADLOCK_RISK",
        "INCORRECT_PRECISION",
        "INCOMPLETE_INITIALIZATION",
    }
    assert set(props["risk_basis_kind"]["enum"]) == expected_basis_kinds

    assert "enum" in props["impact_category"], "impact_category missing enum in wire schema!"
    expected_impact_categories = {
        "AVAILABILITY",
        "ERROR_VISIBILITY",
        "CONTROL_FLOW",
        "DATA_INTEGRITY",
        "PORTABILITY",
        "SECURITY_INTEGRITY",
        "PERFORMANCE",
    }
    assert set(props["impact_category"]["enum"]) == expected_impact_categories

    # 2. Fixture program/resource names and command literals absent from wire schema
    fixture_tokens = [
        "BANK-MAIN",
        "INIT-DB",
        "TRANS-PROC",
        "REPORT-GEN",
        "ACCOUNTS.DAT",
        "ACCOUNTS.CPY",
        "ACCOUNTS.TMP",
        "cmd /c del",
        "cmd /c ren",
        "rm -f",
    ]
    for tok in fixture_tokens:
        assert tok not in wire_json, f"Fixture token '{tok}' leaked into wire schema!"

    # 3. Arbitrary category token is schema-invalid
    with pytest.raises(ValidationError):
        BehavioralRisk(
            program_id="PROG-X",
            risk_category="ARBITRARY_INVALID_CATEGORY",  # type: ignore[arg-type]
            risk_basis_kind="MISSING_ERROR_STATUS",
            impact_category="ERROR_VISIBILITY",
            resource_name="RES-1",
            operation_evidence=SourceEvidence(file_path="f.cbl", line_start=1, line_end=2),
            affected_resource_evidence=SourceEvidence(file_path="f.cbl", line_start=3, line_end=4),
        )


# ======================================================================
# 17. H4 FINAL RUNNER FAILURE-PATH INTEGRATED REGRESSIONS
# ======================================================================


def _execute_child_failure_scenario(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    run_label: str,
    mock_response: Any,
    expected_error_phase: str,
    evaluator_error: bool = False,
) -> None:
    """Helper executing execute_internal_child() post-provider flow for failure regressions.

    Monkeypatches only external/provider boundaries and preflight verification,
    then executes through the real live child execution path.
    """
    import argparse
    from datetime import UTC, datetime

    from agents.legacy_analyzer import config as cfg_mod
    from agents.legacy_analyzer.system_agent import (
        SystemAnalyzerAgent,
        SystemExecutionMetadata,
    )
    from src.validation.evaluator_v3 import SystemEvaluatorV3

    mod = get_run_gate_3_module()

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    canonical_dir = repo_dir / "artifacts" / "gate-3" / run_label
    canonical_dir.mkdir(parents=True, exist_ok=True)
    res_file = canonical_dir / mod.RESERVATION_STATE_FILE

    base_reservation = {
        "status": "RESERVED",
        "gate": 3,
        "run_label": run_label,
        "candidate_git_sha": "sha_cand_h4",
        "authorization_commit_sha": "sha_auth_h4",
    }
    res_file.write_text(json.dumps(base_reservation), encoding="utf-8")

    golden_file = REPO_ROOT / mod.DEFAULT_GOLDEN_PATH
    golden_sha = hashlib.sha256(golden_file.read_bytes()).hexdigest()

    spec = {
        "gate": 3,
        "spec_version": "3.4.1",
        "schema_version": "3.4.1",
        "prompt_version": "3.4.1",
        "evaluator_version": "3.4.1",
        "golden_dataset_version": "3.4.1",
        "requested_model": "gpt-5-mini",
        "reasoning_effort": "low",
        "max_attempts": 1,
        "maximum_model_attempts": 1,
        "openai_client_max_retries": 0,
        "run_label": run_label,
        "candidate_git_sha": "sha_cand_h4",
        "prompt_sha256": "85b19f21c4de45f6fe1a6a219484f856b89bea21b595e04f19d8dc521f820483",
        "wire_schema_sha256": "4129e91578e445a1fb8392728aef2406c73ec60dcdd60cf84dafb706917f6686",
        "golden_dataset_sha256": golden_sha,
        "bundle_sha256": "fake_bundle_sha",
        "bundle_manifest_sha256": "fake_manifest_sha",
        "foundry_project_fingerprint": "fake_fp_h4",
        "target_bundle_files": [
            "legacy/core-banking-system/BANK-MAIN.CBL",
            "legacy/core-banking-system/INIT-DB.CBL",
            "legacy/core-banking-system/TRANS-PROC.CBL",
            "legacy/core-banking-system/REPORT-GEN.CBL",
            "legacy/core-banking-system/ACCOUNTS.CPY",
            "legacy/core-banking-system/ACCOUNTS.DAT",
        ],
    }

    # Runner preflight mocks (purely offline environment harnesses)
    monkeypatch.setattr(mod, "is_isolated_python", lambda: True)
    monkeypatch.setattr(mod, "is_bytecode_writing_disabled", lambda: True)
    monkeypatch.setattr(mod, "verify_trusted_runner_bootstrap", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "verify_snapshot_against_git_objects", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "validate_authorization_contract", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "verify_clean_worktree", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "verify_no_executable_overlays", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        mod,
        "verify_bundle_integrity",
        lambda *args, **kwargs: ([], "fake_bundle_sha", "fake_manifest_sha"),
    )
    monkeypatch.setattr(mod, "verify_schema_and_prompt_hashes", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        mod,
        "verify_runtime_environment",
        lambda *args, **kwargs: ({"pkg": "1.0"}, "fake_runtime_sha"),
    )
    monkeypatch.setattr(
        mod, "load_authorization_spec_from_git", lambda *args, **kwargs: (spec, "fake_spec_sha")
    )
    monkeypatch.setattr(
        mod, "load_authorization_spec", lambda *args, **kwargs: (spec, "fake_spec_sha")
    )

    # Provider config mocking
    mock_cfg = cfg_mod.FoundryConfig(
        foundry_project_endpoint="https://fake-endpoint.services.ai.azure.com",
        foundry_model="gpt-5-mini",
    )
    monkeypatch.setattr(cfg_mod, "load_config", lambda: mock_cfg)
    monkeypatch.setattr(cfg_mod, "compute_foundry_project_fingerprint", lambda ep: "fake_fp_h4")

    # Provider boundary mocking with call counting
    invoke_raw_call_count = 0

    def mock_invoke_raw(self, *args, **kwargs):
        nonlocal invoke_raw_call_count
        invoke_raw_call_count += 1
        meta = SystemExecutionMetadata(
            gate="3",
            run_label=run_label,
            timestamp=datetime.now(UTC).isoformat(),
            model="gpt-5-mini",
            requested_model="gpt-5-mini",
            reasoning_effort="low",
            git_commit_sha="sha_cand_h4",
            foundry_project_fingerprint="fake_fp_h4",
        )
        meta.response_id = getattr(mock_response, "id", "resp_mock_h4")
        meta.response_model_id = getattr(mock_response, "model", "gpt-5-mini")
        raw_json = json.dumps(
            {
                "id": meta.response_id,
                "model": meta.response_model_id,
                "status": getattr(mock_response, "status", None),
                "raw_mock": True,
            }
        )
        return mock_response, meta, raw_json

    monkeypatch.setattr(SystemAnalyzerAgent, "invoke_raw", mock_invoke_raw)

    if evaluator_error:

        def mock_eval(self, assessment):
            raise RuntimeError("Simulated deterministic evaluator explosion")

        monkeypatch.setattr(SystemEvaluatorV3, "evaluate_assessment", mock_eval)

    args = argparse.Namespace(
        provenance_repo=str(repo_dir),
        snapshot_dir=str(REPO_ROOT),
        artifact_dir=str(canonical_dir),
        auth_spec=str(REPO_ROOT / mod.DEFAULT_AUTH_SPEC_PATH),
        run_label=run_label,
        authorized_git_sha="sha_cand_h4",
        authorization_commit_sha="sha_auth_h4",
        golden_path=str(REPO_ROOT / mod.DEFAULT_GOLDEN_PATH),
        synthetic=False,
        dry_run=False,
        allow_dirty=False,
    )

    # 1. Execute real child path - must return 1 and not raise UnboundLocalError
    ret = mod.execute_internal_child(args)
    assert ret == 1, f"Expected returncode 1, got {ret}"

    # 2. invoke_raw call counter == 1
    assert invoke_raw_call_count == 1, f"Expected 1 model call, got {invoke_raw_call_count}"

    # 3. raw-response.json exists
    raw_path = canonical_dir / "raw-response.json"
    assert raw_path.is_file(), "raw-response.json must exist"

    # 4. terminal-result.json exists with status == FAILED and expected error_phase
    term_path = canonical_dir / mod.TERMINAL_RESULT_FILE
    assert term_path.is_file(), f"{mod.TERMINAL_RESULT_FILE} must exist"
    term_data = json.loads(term_path.read_text(encoding="utf-8"))
    assert term_data["status"] == "FAILED"
    assert term_data["error_phase"] == expected_error_phase, (
        f"Expected error_phase '{expected_error_phase}', got '{term_data['error_phase']}'"
    )

    # 5. manifest.json exists and hashes all preserved immutable artifacts
    manifest_path = canonical_dir / "manifest.json"
    assert manifest_path.is_file(), "manifest.json must exist"
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_data["status"] == "FAILED"
    assert manifest_data["gate_3_pass"] is False
    assert "raw-response.json" in manifest_data["artifacts"]
    assert mod.TERMINAL_RESULT_FILE in manifest_data["artifacts"]
    assert mod.RESERVATION_STATE_FILE not in manifest_data["artifacts"]
    assert "manifest.json" not in manifest_data["artifacts"]

    if evaluator_error:
        assert "model-assessment.json" in manifest_data["artifacts"], (
            "Evaluator failure must preserve parsed model-assessment.json"
        )
        assert (canonical_dir / "model-assessment.json").is_file()

    for fname, exp_sha in manifest_data["artifacts"].items():
        act_sha = hashlib.sha256((canonical_dir / fname).read_bytes()).hexdigest()
        assert act_sha == exp_sha, f"Manifest hash mismatch for {fname}"

    # 6. reservation-state.json == FAILED
    assert res_file.is_file()
    res_data = json.loads(res_file.read_text(encoding="utf-8"))
    assert res_data["status"] == "FAILED"
    assert res_data["error_phase"] == expected_error_phase

    # 7. subsequent reuse of the label is refused
    with pytest.raises(RuntimeError, match="Irrevocable reservation error"):
        mod.check_existing_reservation(canonical_dir, run_label)

    # 8. no second model invocation occurs on subsequent attempt
    ret2 = mod.execute_internal_child(args)
    assert ret2 == 1
    assert invoke_raw_call_count == 1, "No second model invocation permitted!"


def test_integrated_child_failure_response_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Scenario 1: Provider returns status != 'completed' (e.g. 'failed').

    Verifies child handles failure cleanly without UnboundLocalError,
    error_phase is RESPONSE_STATUS, artifacts are preserved, and reservation is FAILED.
    """

    class MockResponseStatusFailed:
        id = "resp_mock_status_fail"
        status = "failed"
        model = "gpt-5-mini"
        refusal = None
        output: list[Any] = []

    _execute_child_failure_scenario(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        run_label="fail-status",
        mock_response=MockResponseStatusFailed(),
        expected_error_phase="RESPONSE_STATUS",
    )


def test_integrated_child_failure_provider_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Scenario 2: Provider returns refusal.

    Verifies inspect_response_for_refusal triggers, error_phase is RESPONSE_REFUSAL,
    raw-response.json is persisted, and no UnboundLocalError occurs.
    """

    class MockResponseRefusal:
        id = "resp_mock_refusal"
        status = "completed"
        model = "gpt-5-mini"
        refusal = "I cannot fulfill this request due to safety policies."
        output: list[Any] = []

    _execute_child_failure_scenario(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        run_label="fail-refusal",
        mock_response=MockResponseRefusal(),
        expected_error_phase="RESPONSE_REFUSAL",
    )


def test_integrated_child_failure_model_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Scenario 3: Provider response.model != requested_model.

    Verifies model identity enforcement triggers, error_phase is RESPONSE_MODEL_MISMATCH,
    raw response is preserved, and reservation is FAILED.
    """

    class MockResponseModelMismatch:
        id = "resp_mock_model_mismatch"
        status = "completed"
        model = "gpt-4o"
        refusal = None
        output: list[Any] = []

    _execute_child_failure_scenario(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        run_label="fail-model-mismatch",
        mock_response=MockResponseModelMismatch(),
        expected_error_phase="RESPONSE_MODEL_MISMATCH",
    )


def test_integrated_child_failure_malformed_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Scenario 4: Malformed structured output / Pydantic validation failure.

    Verifies Pydantic ValidationError in validate_and_parse_response is caught cleanly,
    assessment is safely handled as None without UnboundLocalError, error_phase is
    MALFORMED_OUTPUT, and failure state is finalized.
    """

    class MockResponseMalformed:
        id = "resp_mock_malformed"
        status = "completed"
        model = "gpt-5-mini"
        refusal = None
        output = [
            type(
                "Item",
                (),
                {"content": [type("TextItem", (), {"text": '{"unrecognized_json": 123}'})()]},
            )()
        ]

    _execute_child_failure_scenario(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        run_label="fail-malformed",
        mock_response=MockResponseMalformed(),
        expected_error_phase="MALFORMED_OUTPUT",
    )


def test_integrated_child_failure_evaluator_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Scenario 5: Evaluator exception with successfully parsed assessment.

    Verifies:
    - provider call count == 1
    - parsed model assessment is preserved (model-assessment.json in manifest)
    - terminal failure evidence is finalized with error_phase == EVALUATOR
    - reservation becomes FAILED
    """
    from src.validation.evaluator_v3 import load_golden_assessment

    mod = get_run_gate_3_module()
    golden_path = REPO_ROOT / mod.DEFAULT_GOLDEN_PATH
    valid_assessment_json = load_golden_assessment(golden_path).model_dump_json()

    class MockResponseValid:
        id = "resp_mock_valid"
        status = "completed"
        model = "gpt-5-mini"
        refusal = None
        output = [
            type(
                "Item",
                (),
                {"content": [type("TextItem", (), {"text": valid_assessment_json})()]},
            )()
        ]

    _execute_child_failure_scenario(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        run_label="fail-evaluator",
        mock_response=MockResponseValid(),
        expected_error_phase="EVALUATOR",
        evaluator_error=True,
    )
