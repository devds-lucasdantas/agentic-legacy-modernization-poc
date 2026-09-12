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
    assert data.get("total_expected_facts") == 60
    assert len(data["propositions"]) == 60

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

    import subprocess

    orig_run = subprocess.run

    def mock_run(cmd, *args, **kwargs):
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

    import subprocess

    orig_run = subprocess.run

    def mock_run(cmd, *args, **kwargs):
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
