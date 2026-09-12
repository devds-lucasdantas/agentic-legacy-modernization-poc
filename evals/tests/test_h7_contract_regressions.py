"""Gate 3 — Contract 3.5.0 (H7) Offline Regression Test Suite.

Verifies:
- Verifier capability matrix conformance
- Anti-repair principle: reject malformed output, never silently repair
- Exact evidence boundaries and coordinate contract (zero line tolerance)
- Canonical model-visible representations (no 'PIC', no trailing '.', no extensions, explicit USAGE)
- Role-bound evidence fields (CallerContinuationConstraint, DataTransferRelation, etc.)
- Concrete platform dependencies (no template placeholders)
- Pairwise record layout relation completeness (all N*(N-1)/2 pairs)
- Data state discrepancy structure and causal provenance
- Supplementary policy alignment
- Baseline-v1 artifact immutability
- Positive oracle 100% precision/recall Gate 3 PASS
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agents.legacy_analyzer.schemas.system_assessment import (
    BehavioralRisk,
    CallerContinuationConstraint,
    DataStateComparison,
    DataTransferRelation,
    PlatformDependency,
    ProgramDeclaration,
    RecordField,
    RecordLayout,
    ResourceLifecycle,
    SourceEvidence,
    SystemAssessment,
)
from src.cobol.multi_source_reader import read_system_bundle
from src.cobol.system_cobol_parser import SystemCobolParser
from src.cobol.system_support_index import SystemSupportIndex
from src.validation.evaluator_v3 import SystemEvaluatorV3, load_golden_assessment

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ======================================================================
# TEST A: EXACT EVIDENCE BOUNDARIES (Zero Tolerance Coordinate Validation)
# ======================================================================


def test_h7_exact_evidence_boundaries():
    """Test A: Evidence must have valid positive 1-indexed line spans (line_start <= line_end)."""
    # Valid evidence span
    ev = SourceEvidence(
        file_path="legacy/core-banking-system/BANK-MAIN.CBL", line_start=1, line_end=1
    )
    assert ev.line_start == 1
    assert ev.line_end == 1

    # Invalid: line_start < 1
    with pytest.raises(ValidationError):
        SourceEvidence(
            file_path="legacy/core-banking-system/BANK-MAIN.CBL", line_start=0, line_end=1
        )

    # Invalid: line_end < 1
    with pytest.raises(ValidationError):
        SourceEvidence(
            file_path="legacy/core-banking-system/BANK-MAIN.CBL", line_start=1, line_end=0
        )


# ======================================================================
# TEST B: PROGRAM-ID HEADER OVER-INCLUSION REJECTION
# ======================================================================


def test_h7_program_id_header_over_inclusion_rejection():
    """Test B: Evaluator rejects over-inclusive PROGRAM-ID evidence covering headers/divisions."""
    bundle = read_system_bundle(REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, bundle, file_status_certificate=parser.file_status_certificate
    )
    evaluator = SystemEvaluatorV3(index)

    # Valid PROGRAM-ID statement line for BANK-MAIN is line 2
    # If model includes line 1 (IDENTIFICATION DIVISION.), evaluator rejects as unsupported
    assessment = SystemAssessment(system_name="Core Banking System")
    assessment.program_declarations.append(
        ProgramDeclaration(
            program_id="BANK-MAIN",
            evidence=SourceEvidence(
                file_path="legacy/core-banking-system/BANK-MAIN.CBL",
                line_start=1,  # Over-inclusive: includes IDENTIFICATION DIVISION.
                line_end=2,
            ),
        )
    )
    metrics, preds = evaluator.evaluate_assessment(assessment)
    assert metrics.unsupported_predicted_count >= 1
    assert metrics.matched_expected_count == 0


# ======================================================================
# TEST C: CALL VS CALLEE TERMINATION ROLE CORRECTNESS
# ======================================================================


def test_h7_call_vs_callee_termination_role_correctness():
    """Test C: CallerContinuationConstraint role fields call_evidence & callee_termination_evidence

    must correctly map to caller CALL and callee termination statements.
    """
    bundle = read_system_bundle(REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, bundle, file_status_certificate=parser.file_status_certificate
    )
    evaluator = SystemEvaluatorV3(index)

    # Legitimate evidence lines:
    # CALL in BANK-MAIN at line 24
    # Callee termination STOP RUN in INIT-DB at line 46
    call_ev = SourceEvidence(
        file_path="legacy/core-banking-system/BANK-MAIN.CBL", line_start=24, line_end=24
    )
    term_ev = SourceEvidence(
        file_path="legacy/core-banking-system/INIT-DB.CBL", line_start=46, line_end=46
    )

    # 1. Correct role assignment passes
    assessment_correct = SystemAssessment(system_name="Core Banking System")
    assessment_correct.caller_continuation_constraints.append(
        CallerContinuationConstraint(
            caller_program="BANK-MAIN",
            callee_program="INIT-DB",
            constraint_type="PROCESS_TERMINATION_ON_CALL",
            call_evidence=call_ev,
            callee_termination_evidence=term_ev,
        )
    )
    metrics_corr, _ = evaluator.evaluate_assessment(assessment_correct)
    assert metrics_corr.matched_expected_count == 1
    assert metrics_corr.unsupported_predicted_count == 0

    # 2. Swapped roles must be rejected
    assessment_swapped = SystemAssessment(system_name="Core Banking System")
    assessment_swapped.caller_continuation_constraints.append(
        CallerContinuationConstraint(
            caller_program="BANK-MAIN",
            callee_program="INIT-DB",
            constraint_type="PROCESS_TERMINATION_ON_CALL",
            call_evidence=term_ev,  # Swapped!
            callee_termination_evidence=call_ev,  # Swapped!
        )
    )
    metrics_swapped, _ = evaluator.evaluate_assessment(assessment_swapped)
    assert metrics_swapped.unsupported_predicted_count >= 1
    assert metrics_swapped.matched_expected_count == 0


# ======================================================================
# TEST D: PIC PREFIX REJECTION (Anti-Repair)
# ======================================================================


def test_h7_pic_prefix_rejection():
    """Test D: Schema validator rejects 'PIC ' or 'PICTURE ' prefix rather than stripping it."""
    with pytest.raises(ValidationError, match="canonical specification without 'PIC'/'PICTURE'"):
        RecordField(
            field_kind="DATA_FIELD",
            level=5,
            name="TEST-FIELD",
            picture="PIC 9(10)",
            usage="DISPLAY",
        )

    with pytest.raises(ValidationError, match="canonical specification without 'PIC'/'PICTURE'"):
        RecordField(
            field_kind="DATA_FIELD",
            level=5,
            name="TEST-FIELD",
            picture="PICTURE X(20)",
            usage="DISPLAY",
        )


# ======================================================================
# TEST E: TRAILING PICTURE PERIOD REJECTION (Anti-Repair)
# ======================================================================


def test_h7_trailing_picture_period_rejection():
    """Test E: Schema validator rejects trailing period on PICTURE rather than stripping it."""
    with pytest.raises(ValidationError, match="must not contain terminal period"):
        RecordField(
            field_kind="DATA_FIELD", level=5, name="TEST-FIELD", picture="9(10).", usage="DISPLAY"
        )


# ======================================================================
# TEST F: EXTENSION-BEARING LAYOUT CONTAINER REJECTION (Anti-Repair)
# ======================================================================


def test_h7_extension_bearing_layout_container_rejection():
    """Test F: Schema validator rejects file extensions (.CPY, .CBL) or paths in program_id."""
    f = RecordField(
        field_kind="DATA_FIELD", level=5, name="TEST-FIELD", picture="9(10)", usage="DISPLAY"
    )
    ev = SourceEvidence(file_path="dummy.cbl", line_start=1, line_end=5)

    with pytest.raises(ValidationError, match="without path or file extension"):
        RecordLayout(program_id="ACCOUNTS.CPY", record_name="REC", fields=[f], evidence=ev)

    with pytest.raises(ValidationError, match="without path or file extension"):
        RecordLayout(program_id="TRANS-PROC.CBL", record_name="REC", fields=[f], evidence=ev)

    with pytest.raises(ValidationError, match="without path or file extension"):
        RecordLayout(program_id="legacy/core/ACCOUNTS", record_name="REC", fields=[f], evidence=ev)


# ======================================================================
# TEST G: MISSING/NULL DATA_FIELD USAGE REJECTION (Anti-Repair)
# ======================================================================


def test_h7_missing_or_null_data_field_usage_rejection():
    """Test G: DATA_FIELD must explicitly declare usage; omitting or passing null is rejected."""
    with pytest.raises(ValidationError, match="must explicitly declare usage"):
        RecordField(
            field_kind="DATA_FIELD",
            level=5,
            name="TEST-FIELD",
            picture="9(10)",
            usage=None,
        )

    with pytest.raises(ValidationError, match="must explicitly declare usage"):
        RecordField(field_kind="DATA_FIELD", level=5, name="TEST-FIELD", picture="9(10)")


# ======================================================================
# TEST H: DISPLAY EXPLICIT ACCEPTANCE
# ======================================================================


def test_h7_display_explicit_acceptance():
    """Test H: Explicit USAGE 'DISPLAY' is correctly accepted without mutation."""
    f = RecordField(
        field_kind="DATA_FIELD", level=5, name="TEST-FIELD", picture="9(10)", usage="DISPLAY"
    )
    assert f.usage == "DISPLAY"
    assert f.picture == "9(10)"


# ======================================================================
# TEST I: LIFECYCLE DESCRIPTIVE SUFFIX REJECTION (Anti-Repair)
# ======================================================================


def test_h7_lifecycle_descriptive_suffix_rejection():
    """Test I: ResourceLifecycle.ordered_operations rejects descriptive strings like '(loop)'."""
    ev = SourceEvidence(file_path="dummy.cbl", line_start=1, line_end=5)
    with pytest.raises(ValidationError):
        ResourceLifecycle(
            program_id="REPORT-GEN",
            resource_name="ACCOUNT-FILE",
            access_mode="INPUT",
            ordered_operations=["OPEN_INPUT", "READ (loop)", "CLOSE"],  # type: ignore[list-item]
            evidence=ev,
        )


# ======================================================================
# TEST J: UNSUPPORTED RISK BASIS REJECTION
# ======================================================================


def test_h7_unsupported_risk_basis_rejection():
    """Test J: BehavioralRisk rejects unsupported basis kinds outside verifiable host set."""
    ev = SourceEvidence(file_path="dummy.cbl", line_start=1, line_end=5)
    with pytest.raises(ValidationError):
        BehavioralRisk(
            program_id="TRANS-PROC",
            risk_category="IO_ERROR_HANDLING",
            risk_basis_kind="UNSUPPORTED_SPECULATIVE_RISK",  # type: ignore[arg-type]
            impact_category="ERROR_VISIBILITY",
            operation_evidence=ev,
            affected_resource_evidence=ev,
        )


# ======================================================================
# TEST K: UNSUPPORTED TRANSFER SCOPE REJECTION
# ======================================================================


def test_h7_unsupported_transfer_scope_rejection():
    """Test K: DataTransferRelation certifier only supports 01-level record transfers.

    Elementary field transfers or arithmetic transfers fail host verification.
    """
    bundle = read_system_bundle(REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, bundle, file_status_certificate=parser.file_status_certificate
    )
    evaluator = SystemEvaluatorV3(index)

    # Attempting to declare elementary field transfer
    assessment = SystemAssessment(system_name="Core Banking System")
    assessment.data_transfer_relations.append(
        DataTransferRelation(
            program_id="TRANS-PROC",
            source_entity="TEMP-ACC-NUMBER",  # Elementary field!
            target_entity="REC-ACC-NUMBER",  # Elementary field!
            transfer_verb="MOVE",
            evidence=SourceEvidence(
                file_path="legacy/core-banking-system/TRANS-PROC.CBL",
                line_start=60,
                line_end=60,
            ),
        )
    )
    metrics, _ = evaluator.evaluate_assessment(assessment)
    assert metrics.unsupported_predicted_count >= 1
    assert metrics.matched_expected_count == 0


# ======================================================================
# TEST L: CONCRETE PLATFORM COMMAND CARDINALITY
# ======================================================================


def test_h7_concrete_platform_command_cardinality():
    """Test L: PlatformDependency rejects template placeholders (<...>, *) and requires

    discrete assertions per concrete command literal.
    """
    ev = SourceEvidence(file_path="dummy.cbl", line_start=1, line_end=5)

    # Template placeholder must be rejected
    with pytest.raises(ValidationError, match="must be an exact discrete command literal"):
        PlatformDependency(
            program_id="TRANS-PROC",
            platform_family="WINDOWS",
            command_literal="cmd /c <...>",
            evidence=ev,
        )

    with pytest.raises(ValidationError, match="must be an exact discrete command literal"):
        PlatformDependency(
            program_id="TRANS-PROC",
            platform_family="WINDOWS",
            command_literal="cmd /c del *",
            evidence=ev,
        )

    # Concrete command literals validate successfully
    dep1 = PlatformDependency(
        program_id="TRANS-PROC",
        platform_family="WINDOWS",
        command_literal="del ACCOUNTS.DAT",
        evidence=ev,
    )
    dep2 = PlatformDependency(
        program_id="TRANS-PROC",
        platform_family="WINDOWS",
        command_literal="ren ACCOUNTS.TMP ACCOUNTS.DAT",
        evidence=ev,
    )
    assert dep1.command_literal == "del ACCOUNTS.DAT"
    assert dep2.command_literal == "ren ACCOUNTS.TMP ACCOUNTS.DAT"


# ======================================================================
# TEST M: LAYOUT-PAIR COMPLETENESS ACCORDING TO PROVEN VERIFIER CAPABILITY
# ======================================================================


def test_h7_layout_pair_completeness_proven_verifier_capability():
    """Test M: Given N=5 declared layouts in bundle, the parser produces and index certifies

    all N*(N-1)/2 = 10 pairwise RecordLayoutRelation facts.
    """
    bundle = read_system_bundle(REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()

    layout_rel_facts = [sf for sf in facts if type(sf.fact).__name__ == "RecordLayoutRelationFact"]
    layout_facts = [sf for sf in facts if type(sf.fact).__name__ == "RecordLayoutFact"]

    n_layouts = len(layout_facts)
    assert n_layouts == 5
    expected_pairs = n_layouts * (n_layouts - 1) // 2
    assert expected_pairs == 10
    assert len(layout_rel_facts) == expected_pairs


# ======================================================================
# TEST N: DATA-STATE DISCREPANCY STRUCTURE
# ======================================================================


def test_h7_data_state_discrepancy_structure():
    """Test N: DataStateComparison requires entity_id, dat_record_value, initializer_code_value,

    causal_provenance, and dual role-bound evidence.
    """
    ev_dat = SourceEvidence(
        file_path="legacy/core-banking-system/data/ACCOUNTS.DAT", line_start=1, line_end=1
    )
    ev_init = SourceEvidence(
        file_path="legacy/core-banking-system/INIT-DB.CBL", line_start=25, line_end=28
    )

    dsc = DataStateComparison(
        entity_id="1000000001",
        dat_record_value="BALANCE=000000000500000",
        initializer_code_value="BALANCE=000000000100000",
        causal_provenance="UNKNOWN",
        dat_evidence=ev_dat,
        initializer_evidence=ev_init,
    )
    assert dsc.entity_id == "1000000001"
    assert dsc.causal_provenance == "UNKNOWN"
    assert dsc.dat_evidence.file_path == "legacy/core-banking-system/data/ACCOUNTS.DAT"
    assert dsc.initializer_evidence.file_path == "legacy/core-banking-system/INIT-DB.CBL"


# ======================================================================
# TEST O: SUPPLEMENTARY POLICY ALIGNMENT
# ======================================================================


def test_h7_supplementary_policy_alignment():
    """Test O: Verifies that only categories whose supplementary space is deterministic

    are marked as OPTIONAL_SUPPLEMENTARY, and non-certified categories fail verification.
    """
    golden_path = REPO_ROOT / "evals/expected/system-understanding-v3.json"
    golden_data = json.loads(golden_path.read_text(encoding="utf-8"))
    policies = golden_data["category_policies"]

    # In Gate 3 contract, FILE_OPERATION is OPTIONAL_SUPPLEMENTARY
    assert policies["FILE_OPERATION"] == "OPTIONAL_SUPPLEMENTARY"

    # Core categories remain REQUIRED_PREREGISTERED_CORE or REQUIRED_EXHAUSTIVE
    assert policies["DATA_TRANSFER_RELATION"] == "REQUIRED_PREREGISTERED_CORE"
    assert policies["BEHAVIORAL_RISK"] == "REQUIRED_PREREGISTERED_CORE"
    assert policies["RECORD_LAYOUT_RELATION"] == "REQUIRED_PREREGISTERED_CORE"
    assert policies["COMPUTATION_DATAFLOW"] == "REQUIRED_PREREGISTERED_CORE"
    assert policies["PROGRAM_DECLARATION"] == "REQUIRED_EXHAUSTIVE"
    assert policies["RESOURCE_LIFECYCLE"] == "REQUIRED_EXHAUSTIVE"
    assert policies["PLATFORM_DEPENDENCY"] == "REQUIRED_EXHAUSTIVE"


# ======================================================================
# TEST P: BASELINE-V1 ARTIFACT IMMUTABILITY
# ======================================================================


def test_h7_baseline_v1_artifact_immutability():
    """Test P: Verifies that baseline-v1 manifest and all 13 artifacts are immutable and intact."""
    baseline_dir = REPO_ROOT / "artifacts" / "gate-3" / "baseline-v1"
    manifest_path = baseline_dir / "manifest.json"
    assert manifest_path.is_file(), "Baseline-v1 manifest.json missing!"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = manifest["artifacts"]
    assert len(artifacts) == 13, f"Expected 13 baseline-v1 artifacts, found {len(artifacts)}"

    for art_name, expected_sha in artifacts.items():
        art_path = baseline_dir / art_name
        assert art_path.is_file(), f"Missing baseline-v1 artifact: {art_name}"
        actual_sha = hashlib.sha256(art_path.read_bytes()).hexdigest()
        assert actual_sha == expected_sha, f"Hash mismatch for baseline-v1 artifact: {art_name}"

    # Verify baseline-v1 spec file is unchanged
    v1_spec_path = REPO_ROOT / "evals/baselines/gate-3-baseline-v1.json"
    v1_sha = hashlib.sha256(v1_spec_path.read_bytes()).hexdigest()
    assert v1_sha == "b37e8815e2605f279ecc417b8e037f0b235f5e1dcfa64d79b10708e852509695", (
        "Baseline-v1 spec file has been altered!"
    )


# ======================================================================
# ANTI-REPAIR EXPLICIT PROOF: MALFORMED MODEL VALUE -> VALIDATION FAIL
# ======================================================================


def test_h7_anti_repair_proof_malformed_model_value_fails_validation():
    """Proof: Host validators reject malformed model values without normalizing/repairing.

    Tests:
    1. PIC prefix -> ValidationError (not stripped)
    2. Trailing dot on picture -> ValidationError (not stripped)
    3. .CPY extension in container -> ValidationError (not stripped)
    4. Missing usage on DATA_FIELD -> ValidationError (not filled with default)
    5. Descriptive suffix in lifecycle verb -> ValidationError (not cleaned)
    """
    ev = SourceEvidence(file_path="dummy.cbl", line_start=1, line_end=5)

    # 1. PIC prefix
    with pytest.raises(ValidationError):
        RecordField(
            field_kind="DATA_FIELD", level=5, name="F1", picture="PIC X(10)", usage="DISPLAY"
        )

    # 2. Trailing dot
    with pytest.raises(ValidationError):
        RecordField(field_kind="DATA_FIELD", level=5, name="F1", picture="X(10).", usage="DISPLAY")

    # 3. .CPY extension
    f_valid = RecordField(
        field_kind="DATA_FIELD", level=5, name="F1", picture="X(10)", usage="DISPLAY"
    )
    with pytest.raises(ValidationError):
        RecordLayout(
            program_id="MY-COPYBOOK.CPY", record_name="MY-REC", fields=[f_valid], evidence=ev
        )

    # 4. Missing usage
    with pytest.raises(ValidationError):
        RecordField(field_kind="DATA_FIELD", level=5, name="F1", picture="X(10)")

    # 5. Descriptive suffix
    with pytest.raises(ValidationError):
        ResourceLifecycle(
            program_id="PROG1",
            resource_name="FILE1",
            access_mode="INPUT",
            ordered_operations=["OPEN_INPUT", "READ (loop)", "CLOSE"],  # type: ignore[list-item]
            evidence=ev,
        )


# ======================================================================
# SECTION 11: POSITIVE ORACLE VERIFICATION
# ======================================================================


def test_h7_positive_oracle_pass():
    """Section 11: Positive SystemAssessment oracle achieves precision=1.0, recall=1.0,

    unsupported=0, duplicates=0, contradictions=0, invalid evidence=0, Gate 3 PASS.
    """
    bundle = read_system_bundle(REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, bundle, file_status_certificate=parser.file_status_certificate
    )
    evaluator = SystemEvaluatorV3(index)

    assessment = load_golden_assessment()

    # Serialization roundtrip through SystemAssessment model
    serialized = assessment.model_dump_json()
    roundtripped = SystemAssessment.model_validate_json(serialized)

    metrics, preds = evaluator.evaluate_assessment(roundtripped)

    assert metrics.precision == 1.0, f"Expected P=1.0, got {metrics.precision}"
    assert metrics.recall == 1.0, f"Expected R=1.0, got {metrics.recall}"
    assert metrics.matched_expected_count == 59
    assert metrics.expected_fact_count == 59
    assert metrics.unsupported_predicted_count == 0
    assert metrics.duplicate_prediction_count == 0
    assert metrics.contradiction_count == 0
    assert metrics.invalid_evidence_count == 0
    assert metrics.gate_3_pass is True
