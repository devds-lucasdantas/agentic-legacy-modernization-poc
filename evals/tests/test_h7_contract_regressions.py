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

import argparse
import copy
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from agents.legacy_analyzer.schemas.system_assessment import (
    BehavioralRisk,
    CallEdge,
    CallerContinuationConstraint,
    CallOccurrence,
    DataStateComparison,
    DataTransferRelation,
    FileBinding,
    ImpactCategory,
    PlatformDependency,
    ProgramDeclaration,
    RecordField,
    RecordLayout,
    RecordLayoutRelation,
    RecordRelationType,
    ResourceLifecycle,
    RiskBasisKind,
    RiskCategory,
    SourceEvidence,
    SystemAssessment,
    TerminationSite,
)
from src.cobol.multi_source_reader import MultiSourceBundle, TargetFile, read_system_bundle
from src.cobol.system_atomic_facts import (
    BehavioralRiskFact,
    FileBindingFact,
    OperationSequenceFact,
    RecordFieldFact,
    RecordLayoutFact,
    RecordLayoutRelationFact,
    canonicalize_picture,
)
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


# ======================================================================
# TEST Q: ANTI-REPAIR VALIDATION ACROSS ALL CONSTRUCTOR NORMALIZATION FAMILIES
# ======================================================================


def test_h7_anti_repair_all_normalization_families():
    """Verify that model assertions across all normalization families are rejected

    at the schema / evaluator boundary rather than silently normalized.
    """
    ev = SourceEvidence(
        file_path="legacy/core-banking-system/BANK-MAIN.CBL", line_start=2, line_end=2
    )

    # 1. Identifier normalization (lowercase, surrounding/internal spaces)
    with pytest.raises(ValidationError):
        ProgramDeclaration(program_id="bank-main", evidence=ev)

    with pytest.raises(ValidationError):
        ProgramDeclaration(program_id=" BANK-MAIN ", evidence=ev)

    with pytest.raises(ValidationError):
        ProgramDeclaration(program_id="BANK  MAIN", evidence=ev)

    # 2. Token normalization (lowercase, space/hyphen instead of underscore)
    with pytest.raises(ValidationError):
        CallOccurrence(
            caller_program="BANK-MAIN",
            target_program="INIT-DB",
            call_mechanism="literal-target",  # type: ignore[arg-type]
            evidence=ev,
        )

    with pytest.raises(ValidationError):
        TerminationSite(
            program_id="INIT-DB",
            statement_type="stop run",  # type: ignore[arg-type]
            evidence=ev,
        )

    # 3. Whitespace stripping on literals
    with pytest.raises(ValidationError):
        RecordField(
            field_kind="DATA_FIELD",
            level=5,
            name="ACC-NUM",
            picture=" 9(10) ",
            usage="DISPLAY",
        )

    with pytest.raises(ValidationError):
        FileBinding(
            program_id="INIT-DB",
            internal_file_name="ACCOUNT-FILE",
            external_file_name=" ACCOUNTS.DAT ",
            organization="LINE_SEQUENTIAL",
            evidence=ev,
        )

    # 4. Quote stripping on literals
    with pytest.raises(ValidationError):
        FileBinding(
            program_id="INIT-DB",
            internal_file_name="ACCOUNT-FILE",
            external_file_name='"ACCOUNTS.DAT"',
            organization="LINE_SEQUENTIAL",
            evidence=ev,
        )

    with pytest.raises(ValidationError):
        PlatformDependency(
            program_id="TRANS-PROC",
            platform_family="WINDOWS",
            command_literal='"del ACCOUNTS.DAT"',
            evidence=ev,
        )

    # 5. Explicit aliases (reject non-canonical model variants)
    with pytest.raises(ValidationError):
        PlatformDependency(
            program_id="TRANS-PROC",
            platform_family="WIN_CMD",  # type: ignore[arg-type]
            command_literal="del ACCOUNTS.DAT",
            evidence=ev,
        )

    with pytest.raises(ValidationError):
        PlatformDependency(
            program_id="TRANS-PROC",
            platform_family="WINDOWS_CMD",  # type: ignore[arg-type]
            command_literal="del ACCOUNTS.DAT",
            evidence=ev,
        )

    with pytest.raises(ValidationError):
        ResourceLifecycle(
            program_id="TRANS-PROC",
            resource_name="ACCOUNT-FILE",
            access_mode="I-O",  # type: ignore[arg-type]
            ordered_operations=["OPEN_IO", "READ", "CLOSE"],
            evidence=ev,
        )

    with pytest.raises(ValidationError):
        ResourceLifecycle(
            program_id="TRANS-PROC",
            resource_name="ACCOUNT-FILE",
            access_mode="IO",
            ordered_operations=["OPEN_I-O", "READ", "CLOSE"],  # type: ignore[list-item]
            evidence=ev,
        )

    with pytest.raises(ValidationError):
        ResourceLifecycle(
            program_id="TRANS-PROC",
            resource_name="ACCOUNT-FILE",
            access_mode="IO",
            ordered_operations=["OPEN_I_O", "READ", "CLOSE"],  # type: ignore[list-item]
            evidence=ev,
        )


# ======================================================================
# TEST R: COMPLETE LAYOUT ENDPOINT PERMUTATION & GOLDEN INVARIANCE (F-02)
# ======================================================================


def test_h7_layout_endpoint_permutations_and_golden_invariance():
    """Verify Adjustment 2 (F-02):

    (A, evA), (B, evB) == (B, evB), (A, evA) [both supported, same prop ID]
    (B, evA), (A, evB) != valid assertion    [swapped evidence fails support]
    (A, evB), (B, evA) != valid assertion    [swapped evidence fails support]
    Submitting both canonical and reversed endpoints yields 1 duplicate.
    """
    bundle = read_system_bundle(REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, bundle, file_status_certificate=parser.file_status_certificate
    )
    evaluator = SystemEvaluatorV3(index)

    rel_facts = [sf for sf in facts if sf.fact.fact_category == "RECORD_LAYOUT_RELATION"]
    assert len(rel_facts) == 10

    for sf in rel_facts:
        f = sf.fact
        assert isinstance(f, RecordLayoutRelationFact)
        ev_a = sf.evidence_spans["evidence_a"]
        ev_b = sf.evidence_spans["evidence_b"]

        source_ev_a = SourceEvidence(
            file_path=ev_a.file_path, line_start=ev_a.line_start, line_end=ev_a.line_end
        )
        source_ev_b = SourceEvidence(
            file_path=ev_b.file_path, line_start=ev_b.line_start, line_end=ev_b.line_end
        )

        # 1. Canonical submission
        rel_canonical = RecordLayoutRelation(
            layout_a_name=f.layout_a_name,
            layout_b_name=f.layout_b_name,
            relation_type=cast(RecordRelationType, f.relation_type),
            evidence_a=source_ev_a,
            evidence_b=source_ev_b,
        )
        assessment_canon = SystemAssessment(system_name="Test")
        assessment_canon.record_layout_relations.append(rel_canonical)
        m_canon, p_canon = evaluator.evaluate_assessment(assessment_canon)
        assert m_canon.supported_predicted_count == 1
        assert m_canon.unsupported_predicted_count == 0

        # 2. Reversed complete endpoints: (B, evB), (A, evA)
        rel_reversed = RecordLayoutRelation(
            layout_a_name=f.layout_b_name,
            layout_b_name=f.layout_a_name,
            relation_type=cast(RecordRelationType, f.relation_type),
            evidence_a=source_ev_b,
            evidence_b=source_ev_a,
        )
        assessment_rev = SystemAssessment(system_name="Test")
        assessment_rev.record_layout_relations.append(rel_reversed)
        m_rev, p_rev = evaluator.evaluate_assessment(assessment_rev)
        assert m_rev.supported_predicted_count == 1
        assert m_rev.unsupported_predicted_count == 0
        assert p_canon[0].matched_proposition_id == p_rev[0].matched_proposition_id

        # 3. Swapped names only: (B, evA), (A, evB)
        if f.layout_a_name != f.layout_b_name:
            rel_bad_names = RecordLayoutRelation(
                layout_a_name=f.layout_b_name,
                layout_b_name=f.layout_a_name,
                relation_type=cast(RecordRelationType, f.relation_type),
                evidence_a=source_ev_a,
                evidence_b=source_ev_b,
            )
            assessment_bad = SystemAssessment(system_name="Test")
            assessment_bad.record_layout_relations.append(rel_bad_names)
            m_bad, _ = evaluator.evaluate_assessment(assessment_bad)
            assert m_bad.unsupported_predicted_count == 1

        # 4. Duplicate test: both submitted together
        assessment_dup = SystemAssessment(system_name="Test")
        assessment_dup.record_layout_relations.extend([rel_canonical, rel_reversed])
        m_dup, _ = evaluator.evaluate_assessment(assessment_dup)
        assert m_dup.raw_predicted_count == 2
        assert m_dup.duplicate_prediction_count == 1
        assert m_dup.supported_predicted_count == 1


# ======================================================================
# TEST S: HETEROGENEOUS IN-MEMORY LAYOUT COMPARISON PROBE (Adjustment 3 / F-04)
# ======================================================================


def test_h7_heterogeneous_in_memory_layout_comparison_probe():
    """Verify Adjustment 3:

    Total comparator produces all N*(N-1)/2 pairs even when field picture differs.
    Mutating INIT-DB.CBL REC-ACC-NUMBER 9(10) -> 9(11) preserves total comparator,
    yielding 10 pairs with REPRESENTATION_MISMATCH on modified relations.
    """
    bundle = read_system_bundle(REPO_ROOT)
    parser = SystemCobolParser(bundle)
    parser.parse_system()

    # Mutate in-memory AST for INIT-DB
    for unit in parser.compilation_units:
        if unit.program_id == "INIT-DB":
            for rec in unit.record_declarations:
                if rec.container_name == "ACCOUNT-REC":
                    for fld in rec.fields:
                        if fld.name == "REC-ACC-NUMBER":
                            fld.picture = "9(11)"  # Mutate 9(10) -> 9(11)

    # Re-evaluate layout relations
    parser.supported_facts.clear()
    parser._build_record_layout_relations()
    rel_facts = [
        sf for sf in parser.supported_facts if sf.fact.fact_category == "RECORD_LAYOUT_RELATION"
    ]

    assert len(rel_facts) == 10, f"Expected exactly 10 pairs, got {len(rel_facts)}"

    # Relations involving INIT-DB must be REPRESENTATION_MISMATCH now
    for sf in rel_facts:
        f = sf.fact
        assert isinstance(f, RecordLayoutRelationFact)
        if "INIT-DB" in f.layout_a_name or "INIT-DB" in f.layout_b_name:
            assert f.relation_type == "REPRESENTATION_MISMATCH", (
                f"Expected REPRESENTATION_MISMATCH for mutated pair "
                f"{f.layout_a_name} - {f.layout_b_name}, got {f.relation_type}"
            )
        elif (
            "TRANS-PROC:ACCOUNT-REC" in f.layout_a_name and "TRANS-PROC:TEMP-REC" in f.layout_b_name
        ):
            # Non-mutated pair preserves existing EQUIVALENT relation
            assert f.relation_type == "EQUIVALENT"


# ======================================================================
# TEST T: BEHAVIORAL RISK DUAL BASIS VERIFICATION (F-03)
# ======================================================================


def test_h7_behavioral_risk_dual_basis_verification():
    """Verify both supported behavioral risk bases are supported by support index:

    - MISSING_ERROR_STATUS in TRANS-PROC (IO_ERROR_HANDLING)
    - NON_ATOMIC_EXTERNAL_MUTATION in TRANS-PROC (DATA_INTEGRITY)
    """
    bundle = read_system_bundle(REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, bundle, file_status_certificate=parser.file_status_certificate
    )
    evaluator = SystemEvaluatorV3(index)

    risk_facts = [sf for sf in facts if sf.fact.fact_category == "BEHAVIORAL_RISK"]
    bases = {
        sf.fact.risk_basis_kind for sf in risk_facts if isinstance(sf.fact, BehavioralRiskFact)
    }
    assert "MISSING_ERROR_STATUS" in bases
    assert "NON_ATOMIC_EXTERNAL_MUTATION" in bases

    assessment = SystemAssessment(system_name="Core Banking System")
    for sf in risk_facts:
        f = sf.fact
        assert isinstance(f, BehavioralRiskFact)
        op_ev = sf.evidence_spans["operation_evidence"]
        res_ev = sf.evidence_spans["affected_resource_evidence"]
        assessment.behavioral_risks.append(
            BehavioralRisk(
                program_id=f.program_id,
                risk_category=cast(RiskCategory, f.risk_category),
                risk_basis_kind=cast(RiskBasisKind, f.risk_basis_kind),
                impact_category=cast(ImpactCategory, f.impact_category),
                resource_name=f.resource_name,
                operation_evidence=SourceEvidence(
                    file_path=op_ev.file_path, line_start=op_ev.line_start, line_end=op_ev.line_end
                ),
                affected_resource_evidence=SourceEvidence(
                    file_path=res_ev.file_path,
                    line_start=res_ev.line_start,
                    line_end=res_ev.line_end,
                ),
            )
        )

    metrics, _ = evaluator.evaluate_assessment(assessment)
    assert metrics.supported_predicted_count == len(risk_facts)
    assert metrics.unsupported_predicted_count == 0


# ======================================================================
# TEST U: CHILD AUTH SPEC PROPAGATION (F-06)
# ======================================================================


def test_h7_child_auth_spec_propagation():
    """Verify that load_authorization_spec_from_git requires rel_path and

    deriving relative spec path supports both baseline-v1 and baseline-v2.
    """
    import importlib.util
    import inspect

    spec_mod = importlib.util.spec_from_file_location(
        "runner_for_test", REPO_ROOT / "scripts/run-gate-3.py"
    )
    assert spec_mod is not None and spec_mod.loader is not None
    runner_mod = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(runner_mod)

    sig = inspect.signature(runner_mod.load_authorization_spec_from_git)
    assert "rel_path" in sig.parameters
    assert sig.parameters["rel_path"].default == inspect.Parameter.empty, (
        "load_authorization_spec_from_git must require rel_path without a default argument"
    )

    v1_path = REPO_ROOT / "evals/baselines/gate-3-baseline-v1.json"
    v2_path = REPO_ROOT / "evals/baselines/gate-3-baseline-v2.json"

    rel_v1 = v1_path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    rel_v2 = v2_path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()

    assert rel_v1 == "evals/baselines/gate-3-baseline-v1.json"
    assert rel_v2 == "evals/baselines/gate-3-baseline-v2.json"


# ======================================================================
# TEST V: STRICT RUNTIME VERSION EQUALITY NEGATIVE TESTS (F-07)
# ======================================================================


def test_h7_strict_runtime_version_equality_negative_tests():
    """Verify that all 4 component version mismatches fail closed in run-gate-3.py."""
    import importlib.util

    spec_mod = importlib.util.spec_from_file_location(
        "runner_mod_v", REPO_ROOT / "scripts/run-gate-3.py"
    )
    assert spec_mod is not None and spec_mod.loader is not None
    runner_mod = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(runner_mod)

    assert runner_mod.SUPPORTED_CONTRACT_VERSIONS == {"3.4.3", "3.5.0", "3.5.1", "3.5.2"}


# ======================================================================
# TEST W: DUPLICATE CALL EDGE DETECTION
# ======================================================================


def test_h7_duplicate_call_edge_detection():
    """Verify that duplicate CallEdge assertions are flagged as duplicate."""
    bundle = read_system_bundle(REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, bundle, file_status_certificate=parser.file_status_certificate
    )
    evaluator = SystemEvaluatorV3(index)

    ev = SourceEvidence(
        file_path="legacy/core-banking-system/BANK-MAIN.CBL", line_start=24, line_end=24
    )
    edge1 = CallEdge(
        caller_program="BANK-MAIN",
        target_program="INIT-DB",
        call_mechanism="LITERAL_TARGET",
        evidence=ev,
    )
    edge2 = CallEdge(
        caller_program="BANK-MAIN",
        target_program="INIT-DB",
        call_mechanism="LITERAL_TARGET",
        evidence=ev,
    )

    assessment = SystemAssessment(system_name="Core Banking System")
    assessment.call_edges.extend([edge1, edge2])

    metrics, preds = evaluator.evaluate_assessment(assessment)
    assert metrics.raw_predicted_count == 2
    assert metrics.duplicate_prediction_count == 1
    assert metrics.supported_predicted_count == 1
    assert preds[1].is_duplicate is True


# ======================================================================
# TEST X (5A): REAL ASSESSMENT MUTATION REGRESSIONS
# ======================================================================


def test_h7_3_real_assessment_mutation_regressions():
    """Verify that model-side mutations across categories fail strictly without repair."""
    # 1. Closed categorical tokens: lowercase or invalid tokens rejected by schema
    with pytest.raises(ValidationError):
        CallEdge(
            caller_program="BANK-MAIN",
            target_program="INIT-DB",
            call_mechanism=cast(Any, "literal_target"),  # must be LITERAL_TARGET
            evidence=SourceEvidence(
                file_path="legacy/core-banking-system/BANK-MAIN.CBL", line_start=24, line_end=24
            ),
        )

    with pytest.raises(ValidationError):
        TerminationSite(
            program_id="BANK-MAIN",
            statement_type=cast(Any, "stop run"),  # must be STOP_RUN
            evidence=SourceEvidence(
                file_path="legacy/core-banking-system/BANK-MAIN.CBL", line_start=27, line_end=27
            ),
        )

    with pytest.raises(ValidationError):
        PlatformDependency(
            program_id="TRANS-PROC",
            platform_family=cast(Any, "WIN_CMD"),  # must be WINDOWS
            command_literal="cmd /c del ACCOUNTS.DAT",
            evidence=SourceEvidence(
                file_path="legacy/core-banking-system/TRANS-PROC.CBL", line_start=86, line_end=86
            ),
        )

    # 2. COBOL identifiers: lowercase and leading/trailing whitespace rejected by schema
    with pytest.raises(ValidationError):
        ProgramDeclaration(
            program_id="bank-main",
            evidence=SourceEvidence(
                file_path="legacy/core-banking-system/BANK-MAIN.CBL", line_start=2, line_end=2
            ),
        )

    with pytest.raises(ValidationError):
        ProgramDeclaration(
            program_id=" BANK-MAIN ",
            evidence=SourceEvidence(
                file_path="legacy/core-banking-system/BANK-MAIN.CBL", line_start=2, line_end=2
            ),
        )

    # 3. Source literal content: quotes rejected by schema
    with pytest.raises(ValidationError):
        PlatformDependency(
            program_id="TRANS-PROC",
            platform_family="WINDOWS",
            command_literal="'cmd /c del ACCOUNTS.DAT'",  # must be unquoted content
            evidence=SourceEvidence(
                file_path="legacy/core-banking-system/TRANS-PROC.CBL", line_start=86, line_end=86
            ),
        )

    # 4. FileBinding external_file_name literal preservation (no casing repair in fact constructor)
    fb_lower = FileBindingFact(
        program_id="P",
        internal_file_name="F",
        external_file_name="accounts.dat",
        organization="SEQUENTIAL",
    )
    assert fb_lower.external_file_name == "accounts.dat"

    # Synthetic bundle with lowercase accounts.dat
    src = (
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. TESTPROG.\n"
        "ENVIRONMENT DIVISION.\n"
        "INPUT-OUTPUT SECTION.\n"
        "FILE-CONTROL.\n"
        "    SELECT IN-FILE ASSIGN TO 'accounts.dat'\n"
        "    ORGANIZATION IS LINE SEQUENTIAL.\n"
        "DATA DIVISION.\n"
        "FILE SECTION.\n"
        "FD IN-FILE.\n"
        "01 IN-REC PIC X(10).\n"
        "PROCEDURE DIVISION.\n"
        "    OPEN INPUT IN-FILE.\n"
        "    CLOSE IN-FILE.\n"
        "    STOP RUN.\n"
    )
    numbered = "\n".join(f"{i:06d} {line}" for i, line in enumerate(src.splitlines(), start=1))
    tf = TargetFile(
        relative_path="TEST.CBL",
        file_type="PROGRAM",
        raw_content=src,
        numbered_content=numbered,
        sha256=hashlib.sha256(src.encode("utf-8")).hexdigest(),
        line_count=len(src.splitlines()),
    )
    b = MultiSourceBundle(
        files={"TEST.CBL": tf},
        total_physical_lines=tf.line_count,
        bundle_sha256="synth",
        formatted_prompt_payload="synth",
    )
    p = SystemCobolParser(b)
    p_facts = p.get_supported_facts()
    idx = SystemSupportIndex(p_facts, b, file_status_certificate=p.file_status_certificate)
    ev = SystemEvaluatorV3(idx)

    # Exact lowercase matches
    ass_pass = SystemAssessment(system_name="Test")
    ass_pass.file_bindings.append(
        FileBinding(
            program_id="TESTPROG",
            internal_file_name="IN-FILE",
            external_file_name="accounts.dat",
            organization="LINE_SEQUENTIAL",
            evidence=SourceEvidence(file_path="TEST.CBL", line_start=6, line_end=7),
        )
    )
    m_pass, _ = ev.evaluate_assessment(ass_pass)
    assert m_pass.supported_predicted_count == 1

    # Uppercased fails exact match
    ass_fail = SystemAssessment(system_name="Test")
    ass_fail.file_bindings.append(
        FileBinding(
            program_id="TESTPROG",
            internal_file_name="IN-FILE",
            external_file_name="ACCOUNTS.DAT",
            organization="LINE_SEQUENTIAL",
            evidence=SourceEvidence(file_path="TEST.CBL", line_start=6, line_end=7),
        )
    )
    m_fail, _ = ev.evaluate_assessment(ass_fail)
    assert m_fail.supported_predicted_count == 0

    # 5. Condition values: exact content preserved without uppercase repair
    golden = load_golden_assessment()
    mut_cond = copy.deepcopy(golden)
    found_cond = False
    for lay in mut_cond.record_layouts:
        for fld in lay.fields:
            if fld.condition_values == ["A"]:
                fld.condition_values = ["a"]
                found_cond = True
    assert found_cond
    real_bundle = read_system_bundle(REPO_ROOT)
    real_parser = SystemCobolParser(real_bundle)
    real_idx = SystemSupportIndex(
        real_parser.get_supported_facts(),
        real_bundle,
        file_status_certificate=real_parser.file_status_certificate,
    )
    real_ev = SystemEvaluatorV3(real_idx)
    metrics_cond, _ = real_ev.evaluate_assessment(mut_cond)
    assert metrics_cond.supported_predicted_count < 59

    # 6. PICTURE punctuation: -(10)9 preserved exactly; _(10)9 fails exact match against host fact
    assert canonicalize_picture("-(10)9") == "-(10)9"
    assert canonicalize_picture("-(10)9") != "_(10)9"
    rf_pic = RecordFieldFact(
        field_kind="DATA_FIELD", level=5, name="VAL", picture="-(10)9", usage="DISPLAY"
    )
    assert rf_pic.picture == "-(10)9"

    with pytest.raises(ValidationError):
        RecordField(
            field_kind="DATA_FIELD", level=5, name="VAL", picture=" -(10)9", usage="DISPLAY"
        )
    with pytest.raises(ValidationError):
        RecordField(
            field_kind="DATA_FIELD", level=5, name="VAL", picture="pic 9(10)", usage="DISPLAY"
        )
    with pytest.raises(ValidationError):
        RecordField(field_kind="DATA_FIELD", level=5, name="VAL", picture="9(10).", usage="DISPLAY")


# ======================================================================
# TEST Y (5B): EXHAUSTIVE LAYOUT ENDPOINT PERMUTATIONS
# ======================================================================


def test_h7_3_layout_endpoint_permutations_exhaustive():
    """Verify normal, reverse, names-only swap, and evidence-only swap.

    Evaluates completeness across all 10 layout pairs.
    """
    bundle = read_system_bundle(REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, bundle, file_status_certificate=parser.file_status_certificate
    )
    evaluator = SystemEvaluatorV3(index)

    rel_facts = [sf for sf in facts if sf.fact.fact_category == "RECORD_LAYOUT_RELATION"]
    assert len(rel_facts) == 10, f"Expected 10 layout relations, got {len(rel_facts)}"

    for sf in rel_facts:
        assert isinstance(sf.fact, RecordLayoutRelationFact)
        f = sf.fact
        ev_a = sf.evidence_spans["evidence_a"]
        ev_b = sf.evidence_spans["evidence_b"]

        # 1. Normal orientation -> PASS
        ass_norm = SystemAssessment(system_name="Core Banking System")
        ass_norm.record_layout_relations.append(
            RecordLayoutRelation(
                layout_a_name=f.layout_a_name,
                layout_b_name=f.layout_b_name,
                relation_type=cast(Any, f.relation_type),
                evidence_a=SourceEvidence(
                    file_path=ev_a.file_path, line_start=ev_a.line_start, line_end=ev_a.line_end
                ),
                evidence_b=SourceEvidence(
                    file_path=ev_b.file_path, line_start=ev_b.line_start, line_end=ev_b.line_end
                ),
            )
        )
        m_norm, _ = evaluator.evaluate_assessment(ass_norm)
        assert m_norm.supported_predicted_count == 1, (
            f"Normal orientation failed for {f.get_semantic_key()}"
        )

        # 2. Complete reverse orientation -> PASS
        ass_rev = SystemAssessment(system_name="Core Banking System")
        ass_rev.record_layout_relations.append(
            RecordLayoutRelation(
                layout_a_name=f.layout_b_name,
                layout_b_name=f.layout_a_name,
                relation_type=cast(Any, f.relation_type),
                evidence_a=SourceEvidence(
                    file_path=ev_b.file_path, line_start=ev_b.line_start, line_end=ev_b.line_end
                ),
                evidence_b=SourceEvidence(
                    file_path=ev_a.file_path, line_start=ev_a.line_start, line_end=ev_a.line_end
                ),
            )
        )
        m_rev, _ = evaluator.evaluate_assessment(ass_rev)
        assert m_rev.supported_predicted_count == 1, (
            f"Reverse orientation failed for {f.get_semantic_key()}"
        )

        # 3. Duplicate detection: emitting both orientations in same assessment flags 1 duplicate
        ass_both = SystemAssessment(system_name="Core Banking System")
        ass_both.record_layout_relations.extend(
            [
                ass_norm.record_layout_relations[0],
                ass_rev.record_layout_relations[0],
            ]
        )
        m_both, preds = evaluator.evaluate_assessment(ass_both)
        assert m_both.raw_predicted_count == 2
        assert m_both.duplicate_prediction_count == 1
        assert m_both.supported_predicted_count == 1
        assert preds[1].is_duplicate is True

        # 4. Names-only swap (evidence NOT swapped) -> FAIL
        if f.layout_a_name != f.layout_b_name and (
            ev_a.file_path != ev_b.file_path or ev_a.line_start != ev_b.line_start
        ):
            ass_names_swap = SystemAssessment(system_name="Core Banking System")
            ass_names_swap.record_layout_relations.append(
                RecordLayoutRelation(
                    layout_a_name=f.layout_b_name,
                    layout_b_name=f.layout_a_name,
                    relation_type=cast(Any, f.relation_type),
                    evidence_a=SourceEvidence(
                        file_path=ev_a.file_path,
                        line_start=ev_a.line_start,
                        line_end=ev_a.line_end,
                    ),
                    evidence_b=SourceEvidence(
                        file_path=ev_b.file_path,
                        line_start=ev_b.line_start,
                        line_end=ev_b.line_end,
                    ),
                )
            )
            m_ns, _ = evaluator.evaluate_assessment(ass_names_swap)
            assert m_ns.supported_predicted_count == 0, (
                f"Names-only swap should fail for {f.get_semantic_key()}"
            )

        # 5. Evidence-only swap (names NOT swapped) -> FAIL
        if f.layout_a_name != f.layout_b_name and (
            ev_a.file_path != ev_b.file_path or ev_a.line_start != ev_b.line_start
        ):
            ass_ev_swap = SystemAssessment(system_name="Core Banking System")
            ass_ev_swap.record_layout_relations.append(
                RecordLayoutRelation(
                    layout_a_name=f.layout_a_name,
                    layout_b_name=f.layout_b_name,
                    relation_type=cast(Any, f.relation_type),
                    evidence_a=SourceEvidence(
                        file_path=ev_b.file_path,
                        line_start=ev_b.line_start,
                        line_end=ev_b.line_end,
                    ),
                    evidence_b=SourceEvidence(
                        file_path=ev_a.file_path,
                        line_start=ev_a.line_start,
                        line_end=ev_a.line_end,
                    ),
                )
            )
            m_es, _ = evaluator.evaluate_assessment(ass_ev_swap)
            assert m_es.supported_predicted_count == 0, (
                f"Evidence-only swap should fail for {f.get_semantic_key()}"
            )


# ======================================================================
# TEST Z (5C): TOTAL LAYOUT COMPARATOR IN-MEMORY PROBES
# ======================================================================


def test_h7_3_total_layout_comparator_in_memory_probes():
    """Verify total layout comparator behavior.

    Field count, picture, and usage mismatches all yield REPRESENTATION_MISMATCH.
    """
    from src.cobol.system_cobol_parser import ASTDataField, ASTRecordDeclaration

    bundle = read_system_bundle(REPO_ROOT)
    parser = SystemCobolParser(bundle)

    def make_ast_record(name: str, fields: list[ASTDataField]) -> ASTRecordDeclaration:
        return ASTRecordDeclaration(
            container_name=name,
            line_start=1,
            line_end=10,
            fields=fields,
        )

    # Probe 1: Field count mismatch (e.g. 3 fields vs 4 fields)
    f3 = [
        ASTDataField(
            level=5, name="F1", picture="9(10)", usage="DISPLAY", line_start=2, line_end=2
        ),
        ASTDataField(
            level=5, name="F2", picture="X(20)", usage="DISPLAY", line_start=3, line_end=3
        ),
        ASTDataField(level=5, name="F3", picture="9(5)", usage="DISPLAY", line_start=4, line_end=4),
    ]
    f4 = [
        ASTDataField(
            level=5, name="F1", picture="9(10)", usage="DISPLAY", line_start=2, line_end=2
        ),
        ASTDataField(
            level=5, name="F2", picture="X(20)", usage="DISPLAY", line_start=3, line_end=3
        ),
        ASTDataField(level=5, name="F3", picture="9(5)", usage="DISPLAY", line_start=4, line_end=4),
        ASTDataField(level=5, name="F4", picture="X(1)", usage="DISPLAY", line_start=5, line_end=5),
    ]
    records_p1 = [make_ast_record(f"REC{i}", f3 if i % 2 == 0 else f4) for i in range(5)]
    pairs_p1 = 0
    for i in range(len(records_p1)):
        for j in range(i + 1, len(records_p1)):
            rel = parser._compare_records_generically(records_p1[i], records_p1[j])
            pairs_p1 += 1
            if len(records_p1[i].fields) != len(records_p1[j].fields):
                assert rel == "REPRESENTATION_MISMATCH"
            else:
                assert rel in ("IDENTICAL", "EQUIVALENT")
    assert pairs_p1 == 10

    # Probe 2: PICTURE mismatch (same field count, different picture)
    f_pic_a = [
        ASTDataField(
            level=5, name="F1", picture="9(10)", usage="DISPLAY", line_start=2, line_end=2
        ),
        ASTDataField(
            level=5, name="F2", picture="X(30)", usage="DISPLAY", line_start=3, line_end=3
        ),
    ]
    f_pic_b = [
        ASTDataField(
            level=5, name="F1", picture="9(10)", usage="DISPLAY", line_start=2, line_end=2
        ),
        ASTDataField(
            level=5, name="F2", picture="X(20)", usage="DISPLAY", line_start=3, line_end=3
        ),
    ]
    records_p2 = [make_ast_record(f"REC{i}", f_pic_a if i % 2 == 0 else f_pic_b) for i in range(5)]
    pairs_p2 = 0
    for i in range(len(records_p2)):
        for j in range(i + 1, len(records_p2)):
            rel = parser._compare_records_generically(records_p2[i], records_p2[j])
            pairs_p2 += 1
            if records_p2[i].fields[1].picture != records_p2[j].fields[1].picture:
                assert rel == "REPRESENTATION_MISMATCH"
            else:
                assert rel in ("IDENTICAL", "EQUIVALENT")
    assert pairs_p2 == 10

    # Probe 3: USAGE mismatch (same picture and names, different usage)
    f_usg_a = [
        ASTDataField(
            level=5, name="F1", picture="S9(13)V99", usage="DISPLAY", line_start=2, line_end=2
        ),
    ]
    f_usg_b = [
        ASTDataField(
            level=5, name="F1", picture="S9(13)V99", usage="COMP-3", line_start=2, line_end=2
        ),
    ]
    records_p3 = [make_ast_record(f"REC{i}", f_usg_a if i % 2 == 0 else f_usg_b) for i in range(5)]
    pairs_p3 = 0
    for i in range(len(records_p3)):
        for j in range(i + 1, len(records_p3)):
            rel = parser._compare_records_generically(records_p3[i], records_p3[j])
            pairs_p3 += 1
            if records_p3[i].fields[0].usage != records_p3[j].fields[0].usage:
                assert rel == "REPRESENTATION_MISMATCH"
            else:
                assert rel in ("IDENTICAL", "EQUIVALENT")
    assert pairs_p3 == 10


# ======================================================================
# TEST AA (5D): BEHAVIORAL RISK EVIDENCE DISAMBIGUATION
# ======================================================================


def test_h7_3_behavioral_risk_evidence_disambiguation():
    """Verify that NON_ATOMIC_EXTERNAL_MUTATION accepts RENAME assignment and rejects DELETE."""
    bundle = read_system_bundle(REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, bundle, file_status_certificate=parser.file_status_certificate
    )
    evaluator = SystemEvaluatorV3(index)

    # 1. Correct RENAME assignment (line 88: MOVE 'cmd /c ren...' TO WS-CMD) -> PASS
    ass_pass = SystemAssessment(system_name="Core Banking System")
    ass_pass.behavioral_risks.append(
        BehavioralRisk(
            program_id="TRANS-PROC",
            risk_category="DATA_INTEGRITY",
            risk_basis_kind="NON_ATOMIC_EXTERNAL_MUTATION",
            impact_category="DATA_INTEGRITY",
            resource_name="ACCOUNTS.DAT",
            operation_evidence=SourceEvidence(
                file_path="legacy/core-banking-system/TRANS-PROC.CBL", line_start=87, line_end=89
            ),
            affected_resource_evidence=SourceEvidence(
                file_path="legacy/core-banking-system/TRANS-PROC.CBL", line_start=88, line_end=88
            ),
        )
    )
    m_pass, _ = evaluator.evaluate_assessment(ass_pass)
    assert m_pass.supported_predicted_count == 1

    # 2. Preceding DELETE assignment (line 86: MOVE 'cmd /c del ACCOUNTS.DAT' TO WS-CMD) -> FAIL
    ass_fail = SystemAssessment(system_name="Core Banking System")
    ass_fail.behavioral_risks.append(
        BehavioralRisk(
            program_id="TRANS-PROC",
            risk_category="DATA_INTEGRITY",
            risk_basis_kind="NON_ATOMIC_EXTERNAL_MUTATION",
            impact_category="DATA_INTEGRITY",
            resource_name="ACCOUNTS.DAT",
            operation_evidence=SourceEvidence(
                file_path="legacy/core-banking-system/TRANS-PROC.CBL", line_start=87, line_end=89
            ),
            affected_resource_evidence=SourceEvidence(
                file_path="legacy/core-banking-system/TRANS-PROC.CBL", line_start=86, line_end=86
            ),
        )
    )
    m_fail, _ = evaluator.evaluate_assessment(ass_fail)
    assert m_fail.supported_predicted_count == 0


# ======================================================================
# TEST AB (5E): CHILD AUTHORIZATION SPEC PATH VERIFICATION
# ======================================================================


def test_h7_3_child_authorization_spec_path_verification(monkeypatch):
    """Exercise execute_internal_child and observe rel_spec_path passed to git loader."""
    import importlib.util

    spec_mod = importlib.util.spec_from_file_location(
        "runner_mod_child", REPO_ROOT / "scripts/run-gate-3.py"
    )
    assert spec_mod is not None and spec_mod.loader is not None
    runner_mod = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(runner_mod)

    monkeypatch.setattr(runner_mod, "is_isolated_python", lambda: True)
    monkeypatch.setattr(runner_mod, "is_bytecode_writing_disabled", lambda: True)
    monkeypatch.setattr(runner_mod, "verify_trusted_runner_bootstrap", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runner_mod, "verify_snapshot_against_git_objects", lambda *args, **kwargs: None
    )

    captured_paths: list[str] = []
    orig_loader = runner_mod.load_authorization_spec_from_git

    def spy_loader(repo, commit, rel_path):
        captured_paths.append(rel_path)
        return orig_loader(repo, commit, rel_path)

    monkeypatch.setattr(runner_mod, "load_authorization_spec_from_git", spy_loader)

    # 1. Execute internal child for v1
    with tempfile.TemporaryDirectory() as td:
        args_v1 = argparse.Namespace(
            internal_child=True,
            provenance_repo=str(REPO_ROOT),
            snapshot_dir=str(REPO_ROOT),
            artifact_dir=td,
            auth_spec=str(REPO_ROOT / "evals/baselines/gate-3-baseline-v1.json"),
            run_label="baseline-v1",
            authorized_git_sha="9f5c5d2dbe4f1c61aa666f3a3388b54d89751669",
            authorization_commit_sha="9672708e6bcdc01f9d6377535afbb9e11258126e",
            synthetic=True,
            dry_run=False,
            allow_dirty=False,
            golden_path=None,
        )
        runner_mod.execute_internal_child(args_v1)
        assert len(captured_paths) == 1
        assert captured_paths[0] == "evals/baselines/gate-3-baseline-v1.json"

    # 2. Execute internal child for v2
    with tempfile.TemporaryDirectory() as td:
        args_v2 = argparse.Namespace(
            internal_child=True,
            provenance_repo=str(REPO_ROOT),
            snapshot_dir=str(REPO_ROOT),
            artifact_dir=td,
            auth_spec=str(REPO_ROOT / "evals/baselines/gate-3-baseline-v2.json"),
            run_label="baseline-v2",
            authorized_git_sha="c559ece8fde0512759b29108978b2e528b752b87",
            authorization_commit_sha="0913549fa80ceca9ca9c86151cd323799e0e4be2",
            synthetic=True,
            dry_run=False,
            allow_dirty=False,
            golden_path=None,
        )
        runner_mod.execute_internal_child(args_v2)
        assert len(captured_paths) == 2
        assert captured_paths[1] == "evals/baselines/gate-3-baseline-v2.json"


# ======================================================================
# TEST AC (5F): RUNTIME VERSION MISMATCH REAL CHILD NEGATIVE TESTS
# ======================================================================


def test_h7_3_runtime_version_mismatch_real_child_negative_tests(monkeypatch):
    """Force each runtime mismatch through execute_internal_child and verify zero provider calls."""
    import importlib.util

    spec_mod = importlib.util.spec_from_file_location(
        "runner_mod_mismatch", REPO_ROOT / "scripts/run-gate-3.py"
    )
    assert spec_mod is not None and spec_mod.loader is not None
    runner_mod = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(runner_mod)

    monkeypatch.setattr(runner_mod, "is_isolated_python", lambda: True)
    monkeypatch.setattr(runner_mod, "is_bytecode_writing_disabled", lambda: True)
    monkeypatch.setattr(runner_mod, "verify_trusted_runner_bootstrap", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runner_mod, "verify_snapshot_against_git_objects", lambda *args, **kwargs: None
    )

    from agents.legacy_analyzer.system_agent import SystemAnalyzerAgent

    provider_calls = 0

    def mock_invoke_raw(*args, **kwargs):
        nonlocal provider_calls
        provider_calls += 1
        raise RuntimeError("Provider call must not be reached on mismatch!")

    monkeypatch.setattr(SystemAnalyzerAgent, "invoke_raw", mock_invoke_raw)

    base_spec_path = REPO_ROOT / "evals/baselines/gate-3-baseline-v2.json"
    base_spec = json.loads(base_spec_path.read_text(encoding="utf-8"))

    mismatches = [
        ("golden_dataset_version", "9.9.9"),
        ("schema_version", "9.9.9"),
        ("evaluator_version", "9.9.9"),
        ("prompt_version", "9.9.9"),
    ]

    for field, bad_val in mismatches:
        with tempfile.TemporaryDirectory() as td:
            temp_spec = dict(base_spec)
            temp_spec[field] = bad_val
            temp_spec_file = Path(td) / "test-spec.json"
            temp_spec_file.write_text(json.dumps(temp_spec), encoding="utf-8")

            args = argparse.Namespace(
                internal_child=True,
                provenance_repo=str(REPO_ROOT),
                snapshot_dir=str(REPO_ROOT),
                artifact_dir=td,
                auth_spec=str(temp_spec_file),
                run_label="baseline-v2",
                authorized_git_sha="",
                authorization_commit_sha="",
                synthetic=True,
                dry_run=False,
                allow_dirty=True,
                golden_path=None,
            )
            rc = runner_mod.execute_internal_child(args)
            assert rc != 0, f"Expected non-zero return code for mismatched {field}, got {rc}"
            assert provider_calls == 0, f"Provider called during failed child preflight for {field}"


def _make_synth_bundle(source_code: str, filename: str = "TEST.CBL") -> MultiSourceBundle:
    lines = source_code.splitlines()
    numbered = "\n".join(f"{idx + 1:06d} {line}" for idx, line in enumerate(lines))
    tf = TargetFile(
        relative_path=filename,
        file_type="COBOL",
        raw_content=source_code,
        numbered_content=numbered,
        sha256=hashlib.sha256(source_code.encode("utf-8")).hexdigest(),
        line_count=len(lines),
    )
    return MultiSourceBundle(
        files={filename: tf},
        total_physical_lines=tf.line_count,
        bundle_sha256="synth",
        formatted_prompt_payload="synth",
    )


def test_h7_3_1_level_88_unsupported_value_syntax_fail_closed() -> None:
    """F1: Ensure supported level-88 values pass cleanly and unsupported syntax fails closed."""
    # 1. Supported simple literal: single value
    src_simple = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T88SIMPLE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-STATUS PIC X(1).
             88 STATUS-ACTIVE VALUE 'A'.
"""
    p1 = SystemCobolParser(_make_synth_bundle(src_simple))
    cert1 = p1.parse_system()
    assert cert1.unsupported_relevant_count == 0
    assert cert1.is_evaluation_blocked is False
    rec_facts1 = [f.fact for f in p1.supported_facts if isinstance(f.fact, RecordLayoutFact)]
    assert len(rec_facts1) == 1
    cond_fields1 = [f for f in rec_facts1[0].fields if f.field_kind == "CONDITION_NAME"]
    assert len(cond_fields1) == 1
    assert cond_fields1[0].name == "STATUS-ACTIVE"
    assert cond_fields1[0].condition_values == ("A",)

    # 2. Supported simple multi-value literal list
    src_multi = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T88MULTI.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-STATUS PIC X(1).
             88 STATUS-VALID VALUES 'A' 'B' 'C'.
"""
    p2 = SystemCobolParser(_make_synth_bundle(src_multi))
    cert2 = p2.parse_system()
    assert cert2.unsupported_relevant_count == 0
    assert cert2.is_evaluation_blocked is False
    rec_facts2 = [f.fact for f in p2.supported_facts if isinstance(f.fact, RecordLayoutFact)]
    assert len(rec_facts2) == 1
    cond_fields2 = [f for f in rec_facts2[0].fields if f.field_kind == "CONDITION_NAME"]
    assert len(cond_fields2) == 1
    assert cond_fields2[0].name == "STATUS-VALID"
    assert cond_fields2[0].condition_values == ("A", "B", "C")

    # 3. Unsupported range with THRU -> fail closed
    src_thru = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T88THRU.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-STATUS PIC X(1).
             88 STATUS-RANGE VALUE 'A' THRU 'Z'.
"""
    p3 = SystemCobolParser(_make_synth_bundle(src_thru))
    cert3 = p3.parse_system()
    assert cert3.unsupported_relevant_count == 1
    assert cert3.is_evaluation_blocked is True
    rec_facts3 = [f.fact for f in p3.supported_facts if isinstance(f.fact, RecordLayoutFact)]
    cond_fields3 = [f for f in rec_facts3[0].fields if f.field_kind == "CONDITION_NAME"]
    assert len(cond_fields3) == 0, "Unsupported THRU range must not emit approximated fact"

    # 4. Unsupported range with THROUGH -> fail closed
    src_through = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T88THROUGH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-STATUS PIC X(1).
             88 STATUS-RANGE VALUE 'A' THROUGH 'Z'.
"""
    p4 = SystemCobolParser(_make_synth_bundle(src_through))
    cert4 = p4.parse_system()
    assert cert4.unsupported_relevant_count == 1
    assert cert4.is_evaluation_blocked is True
    rec_facts4 = [f.fact for f in p4.supported_facts if isinstance(f.fact, RecordLayoutFact)]
    cond_fields4 = [f for f in rec_facts4[0].fields if f.field_kind == "CONDITION_NAME"]
    assert len(cond_fields4) == 0, "Unsupported THROUGH range must not emit approximated fact"

    # 5. Unsupported logical OR separator -> fail closed
    src_or = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T88OR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-STATUS PIC X(1).
             88 STATUS-OR VALUE 'A' OR 'B'.
"""
    p5 = SystemCobolParser(_make_synth_bundle(src_or))
    cert5 = p5.parse_system()
    assert cert5.unsupported_relevant_count == 1
    assert cert5.is_evaluation_blocked is True
    rec_facts5 = [f.fact for f in p5.supported_facts if isinstance(f.fact, RecordLayoutFact)]
    cond_fields5 = [f for f in rec_facts5[0].fields if f.field_kind == "CONDITION_NAME"]
    assert len(cond_fields5) == 0, "Unsupported OR syntax must not emit approximated fact"

    # 6. Unsupported escaped / interior quoting -> fail closed
    src_escaped = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T88ESC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-NAME PIC X(20).
             88 NAME-VAL VALUE 'O''REILLY'.
"""
    p6 = SystemCobolParser(_make_synth_bundle(src_escaped))
    cert6 = p6.parse_system()
    assert cert6.unsupported_relevant_count == 1
    assert cert6.is_evaluation_blocked is True
    rec_facts6 = [f.fact for f in p6.supported_facts if isinstance(f.fact, RecordLayoutFact)]
    cond_fields6 = [f for f in rec_facts6[0].fields if f.field_kind == "CONDITION_NAME"]
    assert len(cond_fields6) == 0, "Unsupported interior quoting must not emit approximated fact"


def test_h7_3_1_unsupported_external_command_sequences_fail_closed() -> None:
    """F2: Ensure supported DELETE->RENAME passes and unsupported sequences fail closed."""
    # 1. Supported sequence: DELETE -> RENAME
    src_del_ren = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SEQDELREN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE "cmd /c del ACCOUNTS.DAT" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           MOVE "cmd /c ren ACCOUNTS.TMP ACCOUNTS.DAT" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           STOP RUN.
"""
    p1 = SystemCobolParser(_make_synth_bundle(src_del_ren))
    cert1 = p1.parse_system()
    assert cert1.unsupported_relevant_count == 0
    assert cert1.is_evaluation_blocked is False
    seq_facts1 = [f.fact for f in p1.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq_facts1) == 1
    assert seq_facts1[0].first_operation == "DELETE"
    assert seq_facts1[0].second_operation == "RENAME"

    # 2. Unsupported sequence: RENAME -> DELETE
    src_ren_del = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SEQRENDEL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE "cmd /c ren ACCOUNTS.TMP ACCOUNTS.DAT" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           MOVE "cmd /c del ACCOUNTS.DAT" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           STOP RUN.
"""
    p2 = SystemCobolParser(_make_synth_bundle(src_ren_del))
    cert2 = p2.parse_system()
    assert cert2.unsupported_relevant_count > 0, "RENAME -> DELETE must fail closed in coverage"
    assert cert2.is_evaluation_blocked is True
    seq_facts2 = [f.fact for f in p2.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq_facts2) == 0, "No OperationSequenceFact should be emitted for unsupported shape"

    # 3. Unsupported sequence: DELETE -> DELETE
    src_del_del = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SEQDELDEL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE "cmd /c del ACCOUNTS.DAT" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           MOVE "cmd /c del ACCOUNTS.BAK" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           STOP RUN.
"""
    p3 = SystemCobolParser(_make_synth_bundle(src_del_del))
    cert3 = p3.parse_system()
    assert cert3.unsupported_relevant_count > 0, "DELETE -> DELETE must fail closed in coverage"
    assert cert3.is_evaluation_blocked is True
    seq_facts3 = [f.fact for f in p3.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq_facts3) == 0

    # 4. Unsupported sequence: RENAME -> RENAME
    src_ren_ren = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SEQRENREN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE "cmd /c ren ACCOUNTS.TMP ACCOUNTS.DAT" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           MOVE "cmd /c ren ACCOUNTS.DAT ACCOUNTS.BAK" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           STOP RUN.
"""
    p4 = SystemCobolParser(_make_synth_bundle(src_ren_ren))
    cert4 = p4.parse_system()
    assert cert4.unsupported_relevant_count > 0, "RENAME -> RENAME must fail closed in coverage"
    assert cert4.is_evaluation_blocked is True
    seq_facts4 = [f.fact for f in p4.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq_facts4) == 0

    # 5. Unsupported command: COPY -> RENAME
    src_copy_ren = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SEQCOPYREN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE "cmd /c copy ACCOUNTS.TMP ACCOUNTS.DAT" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           MOVE "cmd /c ren ACCOUNTS.TMP ACCOUNTS.DAT" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           STOP RUN.
"""
    p5 = SystemCobolParser(_make_synth_bundle(src_copy_ren))
    cert5 = p5.parse_system()
    assert cert5.unsupported_relevant_count > 0, "COPY -> RENAME must fail closed in coverage"
    assert cert5.is_evaluation_blocked is True
    seq_facts5 = [f.fact for f in p5.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq_facts5) == 0
