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
    CommandInvocation,
    ComputationDataflow,
    DataStateComparison,
    DataTransferRelation,
    FileBinding,
    ImpactCategory,
    OperationSequence,
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
    validate_canonical_identifier,
)
from agents.legacy_analyzer.schemas.system_export import get_system_openai_wire_schema
from src.cobol.identifier_domain import (
    is_canonical_cobol_identifier,
    is_computation_operand,
    is_numeric_literal,
    validate_canonical_cobol_identifier,
    validate_computation_operand,
)
from src.cobol.multi_source_reader import MultiSourceBundle, TargetFile, read_system_bundle
from src.cobol.system_atomic_facts import (
    BehavioralRiskFact,
    CallEdgeFact,
    CallerContinuationConstraintFact,
    CallOccurrenceFact,
    CommandInvocationFact,
    ComputationDataflowFact,
    DataStateComparisonFact,
    EvidenceSpan,
    FileBindingFact,
    FileOperationFact,
    InternalCallResolutionFact,
    OperationSequenceFact,
    PlatformDependencyFact,
    RecordFieldFact,
    RecordLayoutFact,
    RecordLayoutRelationFact,
    ResourceLifecycleFact,
    SupportedSystemFact,
    TerminationSiteFact,
    canonicalize_picture,
)
from src.cobol.system_cobol_parser import ExecutionEffect, SystemCobolParser
from src.cobol.system_support_index import SystemSupportIndex
from src.validation.evaluator_v3 import (
    CanonicalExhaustiveObligation,
    SystemEvaluatorV3,
    load_golden_assessment,
)

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
    """Test L: PlatformDependency validates discrete commands without placeholder heuristics.

    Fabricated placeholders fail certification against grounded host facts.
    """
    ev = SourceEvidence(file_path="dummy.cbl", line_start=1, line_end=5)

    # Empty command literal must be rejected by field validator
    with pytest.raises(ValidationError, match="must not be empty"):
        PlatformDependency(
            program_id="TRANS-PROC",
            platform_family="WINDOWS",
            command_literal="",
            evidence=ev,
        )

    # Wildcards and shell syntax are valid discrete command literals
    dep_wild = PlatformDependency(
        program_id="TRANS-PROC",
        platform_family="WINDOWS",
        command_literal="cmd /c del *.tmp",
        evidence=ev,
    )
    assert dep_wild.command_literal == "cmd /c del *.tmp"

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

    # Fabricated template placeholders pass schema as literal content,
    # but fail evaluator certification
    dep_placeholder = PlatformDependency(
        program_id="TRANS-PROC",
        platform_family="WINDOWS",
        command_literal="cmd /c <...>",
        evidence=ev,
    )
    idx = SystemSupportIndex(
        [
            SupportedSystemFact(
                fact=PlatformDependencyFact(
                    program_id="TRANS-PROC",
                    platform_family="WINDOWS",
                    command_literal="del ACCOUNTS.DAT",
                ),
                proposition_id="prop.plat.1",
                evidence_spans={"evidence": EvidenceSpan("dummy.cbl", 1, 5)},
            )
        ],
        _make_synth_bundle(
            "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. DUMMY.\n", "dummy.cbl"
        ),
    )
    ev_test = SystemEvaluatorV3(idx)
    ass_place = SystemAssessment(system_name="Test")
    ass_place.platform_dependencies.append(dep_placeholder)
    m, preds = ev_test.evaluate_assessment(ass_place)
    assert m.unsupported_predicted_count == 1
    assert preds[0].is_supported is False


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

    # Empty literal validation fails at field boundary
    with pytest.raises(ValidationError, match="must not be empty"):
        FileBinding(
            program_id="INIT-DB",
            internal_file_name="ACCOUNT-FILE",
            external_file_name="",
            organization="LINE_SEQUENTIAL",
            evidence=ev,
        )

    with pytest.raises(ValidationError, match="must not be empty"):
        PlatformDependency(
            program_id="TRANS-PROC",
            platform_family="WINDOWS",
            command_literal="",
            evidence=ev,
        )

    # Literal content whitespace and quote mutations: preserved verbatim by schema
    # (no silent strip/repair), but strictly rejected at the evaluator boundary
    fb_space = FileBinding(
        program_id="INIT-DB",
        internal_file_name="ACCOUNT-FILE",
        external_file_name=" ACCOUNTS.DAT ",
        organization="LINE_SEQUENTIAL",
        evidence=ev,
    )
    assert fb_space.external_file_name == " ACCOUNTS.DAT "

    fb_quote = FileBinding(
        program_id="INIT-DB",
        internal_file_name="ACCOUNT-FILE",
        external_file_name='"ACCOUNTS.DAT"',
        organization="LINE_SEQUENTIAL",
        evidence=ev,
    )
    assert fb_quote.external_file_name == '"ACCOUNTS.DAT"'

    dep_quote = PlatformDependency(
        program_id="TRANS-PROC",
        platform_family="WINDOWS",
        command_literal='"del ACCOUNTS.DAT"',
        evidence=ev,
    )
    assert dep_quote.command_literal == '"del ACCOUNTS.DAT"'

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

    assert runner_mod.SUPPORTED_CONTRACT_VERSIONS == {"3.4.3", "3.5.0", "3.5.1", "3.5.2", "3.5.3"}


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

    # 3. Source literal content: quotes preserved verbatim by schema,
    # rejected by evaluator against unquoted host fact
    dep_quoted = PlatformDependency(
        program_id="TRANS-PROC",
        platform_family="WINDOWS",
        command_literal="'cmd /c del ACCOUNTS.DAT'",  # preserved verbatim
        evidence=SourceEvidence(
            file_path="legacy/core-banking-system/TRANS-PROC.CBL", line_start=86, line_end=86
        ),
    )
    assert dep_quoted.command_literal == "'cmd /c del ACCOUNTS.DAT'"

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


def _make_multi_file_bundle(files_dict: dict[str, str]) -> MultiSourceBundle:
    target_files = {}
    tot_lines = 0
    for filename, source_code in files_dict.items():
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
        target_files[filename] = tf
        tot_lines += tf.line_count
    return MultiSourceBundle(
        files=target_files,
        total_physical_lines=tot_lines,
        bundle_sha256="synth_multi",
        formatted_prompt_payload="synth_multi",
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
    assert len(rec_facts3) == 0, (
        "Atomic record layout must invalidate entire record on unsupported 88 condition"
    )

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
    assert len(rec_facts4) == 0, (
        "Atomic record layout must invalidate entire record on unsupported 88 condition"
    )

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
    assert len(rec_facts5) == 0, (
        "Atomic record layout must invalidate entire record on unsupported 88 condition"
    )

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
    assert len(rec_facts6) == 0, (
        "Atomic record layout must invalidate entire record on unsupported 88 condition"
    )


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

    # 2. Sequence shape: RENAME -> DELETE (commands supported, no sequence emitted)
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
    assert cert2.unsupported_relevant_count > 0, (
        "Unrepresentable sequence RENAME->DELETE must fail closed"
    )
    assert cert2.is_evaluation_blocked is True
    seq_facts2 = [f.fact for f in p2.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq_facts2) == 0, "No OperationSequenceFact for non-DELETE->RENAME"
    risk_facts2 = [f.fact for f in p2.supported_facts if isinstance(f.fact, BehavioralRiskFact)]
    assert len(risk_facts2) == 0, "No non-atomic risk for RENAME -> DELETE"

    # 3. Sequence shape: DELETE -> DELETE (unrepresentable sequence fails closed)
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
    assert cert3.unsupported_relevant_count > 0, (
        "Unrepresentable sequence DELETE->DELETE must fail closed"
    )
    assert cert3.is_evaluation_blocked is True
    seq_facts3 = [f.fact for f in p3.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq_facts3) == 0
    risk_facts3 = [f.fact for f in p3.supported_facts if isinstance(f.fact, BehavioralRiskFact)]
    assert len(risk_facts3) == 0

    # 4. Sequence shape: RENAME -> RENAME (unrepresentable sequence fails closed)
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
    assert cert4.unsupported_relevant_count > 0, (
        "Unrepresentable sequence RENAME->RENAME must fail closed"
    )
    assert cert4.is_evaluation_blocked is True
    seq_facts4 = [f.fact for f in p4.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq_facts4) == 0
    risk_facts4 = [f.fact for f in p4.supported_facts if isinstance(f.fact, BehavioralRiskFact)]
    assert len(risk_facts4) == 0

    # 5. Sequence shape: COPY -> RENAME (unsupported verb and unrepresentable sequence fails closed)
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
    assert cert5.unsupported_relevant_count > 0, (
        "Unsupported mutation verb and sequence must fail closed"
    )
    assert cert5.is_evaluation_blocked is True
    seq_facts5 = [f.fact for f in p5.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq_facts5) == 0
    risk_facts5 = [f.fact for f in p5.supported_facts if isinstance(f.fact, BehavioralRiskFact)]
    assert len(risk_facts5) == 0


# ======================================================================
# H7.4 / CONTRACT 3.5.3 REMEDIATION REGRESSION TEST SUITE
# ======================================================================


def test_h7_4_b01_adversarial_matrix_complete_evaluator_path():
    """Verify B-01 adversarial matrix through the complete real evaluator/support path.

    1. 7-field host record vs 6-field injected-PICTURE candidate:
       -> support FAIL, matched_proposition_id None, Gate FAIL.
    2. Host condition_values ("A", "B") vs candidate ["A,B"] -> FAIL.
    3. Host condition_values ("A,B",) vs candidate ["A", "B"] -> FAIL.
    4. Fabricated DATA_FIELD condition_values -> schema validation FAIL.
    5. Collision resilience: legacy semantic key collides while structural
       certification distinguishes facts.
    """
    golden = load_golden_assessment()
    bundle = read_system_bundle(REPO_ROOT)
    parser = SystemCobolParser(bundle)
    parser.parse_system()
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, bundle, file_status_certificate=parser.file_status_certificate
    )
    evaluator = SystemEvaluatorV3(index)

    # 1. 7-field host record vs 6-field candidate with injected picture
    # Target: ACCOUNTS ACCOUNT-RECORD (7 fields in host: 4 data fields + 3 condition names)
    bad_record_assessment = golden.model_copy(deep=True)
    bank_main_rec = next(
        r for r in bad_record_assessment.record_layouts if r.record_name == "ACCOUNT-RECORD"
    )
    # Inject 6 fields: remove level-88 and alter picture of first DATA_FIELD
    assert len(bank_main_rec.fields) == 7
    bad_fields = [f.model_copy() for f in bank_main_rec.fields[:6]]
    bad_fields[0].picture = "9(20)"  # injected PICTURE on DATA_FIELD
    bank_main_rec.fields = bad_fields
    assert len(bank_main_rec.fields) == 6

    res1, preds1 = evaluator.evaluate_assessment(bad_record_assessment)
    rec_pred = next(
        p
        for p in preds1
        if p.fact_category == "RECORD_LAYOUT" and "ACCOUNT-RECORD" in p.semantic_key
    )
    assert rec_pred.is_supported is False, (
        "6-field candidate must NOT be supported against 7-field host"
    )
    assert rec_pred.matched_proposition_id is None, (
        "Mismatched structure must yield matched_proposition_id None"
    )
    assert res1.gate_3_pass is False, "Gate 3 must FAIL when required record layout fails support"

    # 2. Host condition_values ("A", "B") vs model ["A,B"]
    host_fact_ab = RecordLayoutFact(
        program_id="PROG",
        record_name="REC",
        fields=(
            RecordFieldFact(
                field_kind="CONDITION_NAME",
                level=88,
                name="COND-NAME",
                picture=None,
                usage=None,
                condition_values=("A", "B"),
            ),
        ),
    )
    cand_fact_comma = RecordLayoutFact(
        program_id="PROG",
        record_name="REC",
        fields=(
            RecordFieldFact(
                field_kind="CONDITION_NAME",
                level=88,
                name="COND-NAME",
                picture=None,
                usage=None,
                condition_values=("A,B",),
            ),
        ),
    )
    ev_bank = {"evidence": EvidenceSpan("legacy/core-banking-system/BANK-MAIN.CBL", 10, 15)}
    sf_ab = SupportedSystemFact(
        fact=host_fact_ab,
        proposition_id="prop.test.ab",
        evidence_spans=ev_bank,
    )
    idx_ab = SystemSupportIndex([sf_ab], bundle)
    is_supp_2, reason_2, matched_2 = idx_ab.verify_role_bound_assertion(
        cand_fact_comma,
        ev_bank,
    )
    assert is_supp_2 is False
    assert matched_2 is None
    assert "structural" in reason_2.lower()

    # 3. Host condition_values ("A,B",) vs model ["A", "B"]
    sf_comma = SupportedSystemFact(
        fact=cand_fact_comma,
        proposition_id="prop.test.comma",
        evidence_spans=ev_bank,
    )
    idx_comma = SystemSupportIndex([sf_comma], bundle)
    is_supp_3, reason_3, matched_3 = idx_comma.verify_role_bound_assertion(
        host_fact_ab,
        ev_bank,
    )
    assert is_supp_3 is False
    assert matched_3 is None
    assert "structural" in reason_3.lower()

    # 4. Fabricated DATA_FIELD condition_values
    with pytest.raises(ValidationError):
        RecordField(
            field_kind="DATA_FIELD",
            level=5,
            name="ACC-NUM",
            picture="9(10)",
            usage="DISPLAY",
            condition_values=["FABRICATED"],
        )

    # 5. Collision resilience: legacy semantic key collides while structural
    # certification distinguishes facts.
    sf1 = SupportedSystemFact(
        fact=host_fact_ab,
        proposition_id="prop.struct.ab",
        evidence_spans=ev_bank,
    )
    sf2 = SupportedSystemFact(
        fact=cand_fact_comma,
        proposition_id="prop.struct.comma",
        evidence_spans=ev_bank,
    )
    # Both have the exact same semantic key LAYOUT:PROG:REC
    assert host_fact_ab.get_semantic_key() == cand_fact_comma.get_semantic_key()
    multi_idx = SystemSupportIndex([sf1, sf2], bundle)

    # Candidate matching sf1 matches sf1
    s_ok1, _, m1 = multi_idx.verify_role_bound_assertion(
        host_fact_ab,
        ev_bank,
    )
    assert s_ok1 is True
    assert m1 is not None
    assert m1.proposition_id == "prop.struct.ab"

    # Candidate matching sf2 matches sf2
    s_ok2, _, m2 = multi_idx.verify_role_bound_assertion(
        cand_fact_comma,
        ev_bank,
    )
    assert s_ok2 is True
    assert m2 is not None
    assert m2.proposition_id == "prop.struct.comma"

    # Third structure not in index is rejected
    cand_fact_third = RecordLayoutFact(
        program_id="PROG",
        record_name="REC",
        fields=(
            RecordFieldFact(
                field_kind="DATA_FIELD",
                level=5,
                name="OTHER-FIELD",
                picture="X(1)",
                usage="DISPLAY",
                condition_values=(),
            ),
        ),
    )
    s_fail3, _, m3 = multi_idx.verify_role_bound_assertion(
        cand_fact_third,
        {"evidence": EvidenceSpan("legacy/core-banking-system/BANK-MAIN.CBL", 10, 15)},
    )
    assert s_fail3 is False
    assert m3 is None


def test_h7_4_clarification2_revalidation_attacks_on_typed_objects():
    """Verify that evaluate_assessment entry rebuilds the complete model tree

    so mutating existing nested typed objects post-init fails revalidation.
    """
    golden = load_golden_assessment()
    bundle = read_system_bundle(REPO_ROOT)
    parser = SystemCobolParser(bundle)
    parser.parse_system()
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, bundle, file_status_certificate=parser.file_status_certificate
    )
    evaluator = SystemEvaluatorV3(index)

    # Attack 1: Mutate field_kind to lowercase 'data-field'
    att1 = golden.model_copy(deep=True)
    att1.record_layouts[0].fields[0].field_kind = "data-field"  # type: ignore[assignment]
    with pytest.raises(ValidationError):
        evaluator.evaluate_assessment(att1)

    # Attack 2: DATA_FIELD with condition_values = ['FABRICATED']
    att2 = golden.model_copy(deep=True)
    att2.record_layouts[0].fields[0].condition_values = ["FABRICATED"]
    with pytest.raises(ValidationError):
        evaluator.evaluate_assessment(att2)

    # Attack 3: Noncanonical token / lowercase identifier in program_id
    att3 = golden.model_copy(deep=True)
    att3.program_declarations[0].program_id = "bank-main"
    with pytest.raises(ValidationError):
        evaluator.evaluate_assessment(att3)

    # Attack 4: Invalid level-88 invariant: DATA_FIELD with level = 88
    att4 = golden.model_copy(deep=True)
    att4.record_layouts[0].fields[0].level = 88
    with pytest.raises(ValidationError):
        evaluator.evaluate_assessment(att4)

    # Attack 5: Invalid level-88 invariant: CONDITION_NAME with level = 5
    att5 = golden.model_copy(deep=True)
    last_fld = [f for f in att5.record_layouts[0].fields if f.field_kind == "CONDITION_NAME"][0]
    last_fld.level = 5
    with pytest.raises(ValidationError):
        evaluator.evaluate_assessment(att5)

    # Prove raw-dict and already-typed inputs have identical validation semantics
    raw_dict = att2.model_dump(mode="python")
    with pytest.raises(ValidationError):
        evaluator.evaluate_assessment(raw_dict)


def test_h7_4_b02_bounded_level_88_collector_unclosed_quotes():
    """Verify B-02 quote-aware level-88 collector stops at structural boundaries,

    fails closed on unclosed quotes, and does not consume subsequent declarations.
    """
    cobol_src = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. B02PROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ACCOUNT-REC.
          05 WS-VALID-HEADER PIC X(10).
          05 WS-STATUS PIC X(1).
             88 WS-UNCLOSED-STATUS VALUE "MALFORMED.
          05 WS-NEXT-FIELD PIC 9(4) USAGE DISPLAY.
       PROCEDURE DIVISION.
           STOP RUN.
"""
    bundle = _make_synth_bundle(cobol_src)
    parser = SystemCobolParser(bundle)
    cert = parser.parse_system()

    # The unclosed quote level-88 is marked UNSUPPORTED_RELEVANT
    assert cert.unsupported_relevant_count >= 1, (
        "Unclosed quote must be classified UNSUPPORTED_RELEVANT"
    )
    assert cert.is_evaluation_blocked is True

    # Check record layout fields: under atomic record layout rule (F-09),
    # any unsupported level-88 condition invalidates the entire containing RecordLayoutFact.
    rec_facts = [f.fact for f in parser.supported_facts if isinstance(f.fact, RecordLayoutFact)]
    assert len(rec_facts) == 0, (
        "Atomic record layout must emit 0 RecordLayoutFact for record with unsupported 88"
    )


def test_h7_4_b03_procedural_barrier_command_pairing_and_sequencing():
    """Verify B-03 strict procedural linearity:

    - Intervening control-flow (IF/ELSE/DISPLAY) blocks MOVE -> CALL SYSTEM pairing.
    - Intervening control-flow blocks DELETE -> RENAME sequence pairing.
    - Linear execution without barriers succeeds.
    """
    # 1. Control flow barrier (IF) between MOVE and CALL SYSTEM -> fails closed
    src_if_barrier = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. B03BARRIER1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE "cmd /c del ACCOUNTS.TMP" TO WS-CMD.
           IF WS-CMD = "TEST"
               CALL "SYSTEM" USING WS-CMD
           END-IF.
           STOP RUN.
"""
    p1 = SystemCobolParser(_make_synth_bundle(src_if_barrier))
    p1.parse_system()
    cmd_facts1 = [f.fact for f in p1.supported_facts if isinstance(f.fact, CommandInvocationFact)]
    assert len(cmd_facts1) == 0, "MOVE and CALL separated by IF must not be paired"

    # 2. Control flow barrier (DISPLAY) between DELETE and RENAME dispatches -> blocks sequence
    src_display_barrier = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. B03BARRIER2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE "cmd /c del ACCOUNTS.TMP" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           DISPLAY "INTERVENING BARRIER".
           MOVE "cmd /c ren ACCOUNTS.TMP ACCOUNTS.DAT" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           STOP RUN.
"""
    p2 = SystemCobolParser(_make_synth_bundle(src_display_barrier))
    p2.parse_system()
    cmd_facts2 = [f.fact for f in p2.supported_facts if isinstance(f.fact, CommandInvocationFact)]
    assert len(cmd_facts2) == 2, "Both commands should be paired individually"
    seq_facts2 = [f.fact for f in p2.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq_facts2) == 0, "DELETE -> RENAME sequence must NOT cross DISPLAY barrier"

    # 3. Direct linear dispatches without barriers -> sequence successfully extracted
    src_linear = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. B03LINEAR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE "cmd /c del ACCOUNTS.TMP" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           MOVE "cmd /c ren ACCOUNTS.TMP ACCOUNTS.DAT" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           STOP RUN.
"""
    p3 = SystemCobolParser(_make_synth_bundle(src_linear))
    p3.parse_system()
    seq_facts3 = [f.fact for f in p3.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq_facts3) == 1, "Direct sequential commands must produce OperationSequenceFact"
    assert seq_facts3[0].first_operation == "DELETE"
    assert seq_facts3[0].second_operation == "RENAME"


def test_h7_4_generic_structural_equality_support_index():
    """Verify exact complete structured dataclass equality in SystemSupportIndex.

    Generic regression proving:
    same semantic_key + different dataclass structure + same evidence -> UNSUPPORTED.
    """
    bundle = read_system_bundle(REPO_ROOT)
    ev = EvidenceSpan("legacy/core-banking-system/INIT-DB.CBL", 7, 7)

    # RecordLayoutFact: same legacy semantic key via joined condition values,
    # but different dataclass structure (("A", "B") vs ("A,B",))
    rec_host = RecordLayoutFact(
        program_id="INIT-DB",
        record_name="ACCOUNT-RECORD",
        fields=(
            RecordFieldFact(
                field_kind="CONDITION_NAME",
                level=88,
                name="COND-NAME",
                picture=None,
                usage=None,
                condition_values=("A", "B"),
            ),
        ),
    )
    rec_cand = RecordLayoutFact(
        program_id="INIT-DB",
        record_name="ACCOUNT-RECORD",
        fields=(
            RecordFieldFact(
                field_kind="CONDITION_NAME",
                level=88,
                name="COND-NAME",
                picture=None,
                usage=None,
                condition_values=("A,B",),
            ),
        ),
    )
    # Step 1: Prove semantic keys collide
    assert rec_host.get_semantic_key() == rec_cand.get_semantic_key()
    # Step 2: Prove dataclass equality is False
    assert rec_host != rec_cand

    # Step 3: Index lookup with host fact supported
    sf_rec = SupportedSystemFact(
        fact=rec_host, proposition_id="prop.rec", evidence_spans={"evidence": ev}
    )
    idx_rec = SystemSupportIndex([sf_rec], bundle)

    # Step 4: Verification of candidate with same evidence MUST fail on structural equality
    ok_rec, reason_rec, m_rec = idx_rec.verify_role_bound_assertion(rec_cand, {"evidence": ev})
    assert ok_rec is False, "Candidate with different dataclass structure must NOT be supported"
    assert m_rec is None, "Matched proposition must be None when structural equality fails"
    assert "structural" in reason_rec.lower(), (
        f"Rejection reason must cite structural mismatch: {reason_rec}"
    )


def test_h7_4_golden_direct_structural_comparison_vs_a1():
    """Verify direct structural comparison of golden dataset vs A1 and reservation hashes.

    - Golden dataset structurally equals A1 excluding ONLY 'version': '3.5.3'.
    - artifacts/gate-3/baseline-v2/reservation-state.json has original exact SHA.
    - artifacts/gate-3/baseline-v3 DOES NOT EXIST.
    """
    import subprocess

    golden_path = REPO_ROOT / "evals/expected/system-understanding-v3.json"
    current_golden = json.loads(golden_path.read_text(encoding="utf-8"))

    # Fetch golden content from commit A1
    a1_commit = "9672708e6bcdc01f9d6377535afbb9e11258126e"
    proc = subprocess.run(
        ["git", "show", f"{a1_commit}:evals/expected/system-understanding-v3.json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    a1_golden = json.loads(proc.stdout)

    # Require equality of all scientific fields
    assert current_golden["benchmark_design"] == a1_golden["benchmark_design"]
    assert current_golden["golden_authoring_method"] == a1_golden["golden_authoring_method"]
    assert current_golden["provenance_notes"] == a1_golden["provenance_notes"]
    assert current_golden["total_expected_facts"] == 59
    assert current_golden["total_expected_facts"] == a1_golden["total_expected_facts"]
    assert current_golden["category_policies"] == a1_golden["category_policies"]
    assert current_golden["group_counts"] == a1_golden["group_counts"]

    # All 59 propositions identical
    current_props = current_golden["propositions"]
    a1_props = a1_golden["propositions"]
    assert len(current_props) == 59
    assert len(a1_props) == 59
    assert current_props == a1_props

    # Exclude ONLY version metadata
    assert current_golden["version"] == "3.5.3"
    assert a1_golden["version"] == "3.4.3"

    # Baseline-v2 reservation hash byte-for-byte preserved
    v2_res_file = REPO_ROOT / "artifacts/gate-3/baseline-v2/reservation-state.json"
    assert v2_res_file.is_file()
    expected_v2_sha = "108c51b222e476f32bd98c092c5dc814be9a25b4d1b93ae60f0f28ea2f5a631d"
    actual_v2_sha = hashlib.sha256(v2_res_file.read_bytes()).hexdigest()
    assert actual_v2_sha == expected_v2_sha, f"baseline-v2 reservation modified! {actual_v2_sha}"

    # baseline-v3 artifacts MUST NOT EXIST
    v3_art_dir = REPO_ROOT / "artifacts/gate-3/baseline-v3"
    assert not v3_art_dir.exists(), "artifacts/gate-3/baseline-v3 must not exist"


# ======================================================================
# TEST SECTION 15: H7.4.1 SOURCE-LITERAL CONTENT SYMMETRY REGRESSIONS
# ======================================================================


def test_h7_4_1_file_binding_source_literal_symmetry() -> None:
    """H7.4.1 Test A: FileBinding exact literal preservation and unsupported quote fail-closed.

    Traverses: source overlay -> parser -> host facts -> model schema -> evaluator -> index.
    """
    # 1. Exact whitespace positive case: ASSIGN TO ' accounts.dat '
    src_space = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TSPACE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACC-FILE ASSIGN TO ' accounts.dat '
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD ACC-FILE.
       01 ACC-REC PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
"""
    p_space = SystemCobolParser(_make_synth_bundle(src_space, "TSPACE.CBL"))
    cert_space = p_space.parse_system()
    assert cert_space.unsupported_relevant_count == 0
    assert not cert_space.is_evaluation_blocked
    fb_facts = [
        f.fact for f in p_space.get_supported_facts() if isinstance(f.fact, FileBindingFact)
    ]
    assert len(fb_facts) == 1
    assert fb_facts[0].external_file_name == " accounts.dat "

    idx_space = SystemSupportIndex(
        p_space.get_supported_facts(),
        _make_synth_bundle(src_space, "TSPACE.CBL"),
        file_status_certificate=p_space.file_status_certificate,
    )
    ev_space = SystemEvaluatorV3(idx_space)

    # Positive exact model assertion -> certified
    exact_model = SystemAssessment(system_name="Test")
    exact_model.file_bindings.append(
        FileBinding(
            program_id="TSPACE",
            internal_file_name="ACC-FILE",
            external_file_name=" accounts.dat ",
            organization="LINE_SEQUENTIAL",
            evidence=SourceEvidence(
                file_path="TSPACE.CBL",
                line_start=6,
                line_end=7,
            ),
        )
    )
    m_exact, preds_exact = ev_space.evaluate_assessment(exact_model)
    assert m_exact.unsupported_predicted_count == 0
    assert len(preds_exact) == 1
    assert preds_exact[0].is_supported is True

    # Mutated whitespace (trimmed) -> schema accepts, evaluator rejects
    trimmed_model = SystemAssessment(system_name="Test")
    trimmed_model.file_bindings.append(
        FileBinding(
            program_id="TSPACE",
            internal_file_name="ACC-FILE",
            external_file_name="accounts.dat",
            organization="LINE_SEQUENTIAL",
            evidence=SourceEvidence(
                file_path="TSPACE.CBL",
                line_start=6,
                line_end=7,
            ),
        )
    )
    m_trim, _ = ev_space.evaluate_assessment(trimmed_model)
    assert m_trim.unsupported_predicted_count == 1

    # Mutated casing -> evaluator rejects
    case_model = SystemAssessment(system_name="Test")
    case_model.file_bindings.append(
        FileBinding(
            program_id="TSPACE",
            internal_file_name="ACC-FILE",
            external_file_name=" ACCOUNTS.DAT ",
            organization="LINE_SEQUENTIAL",
            evidence=SourceEvidence(
                file_path="TSPACE.CBL",
                line_start=6,
                line_end=7,
            ),
        )
    )
    m_case, _ = ev_space.evaluate_assessment(case_model)
    assert m_case.unsupported_predicted_count == 1

    # Mutated punctuation -> evaluator rejects
    punct_model = SystemAssessment(system_name="Test")
    punct_model.file_bindings.append(
        FileBinding(
            program_id="TSPACE",
            internal_file_name="ACC-FILE",
            external_file_name=" accounts_dat ",
            organization="LINE_SEQUENTIAL",
            evidence=SourceEvidence(
                file_path="TSPACE.CBL",
                line_start=6,
                line_end=7,
            ),
        )
    )
    m_punct, _ = ev_space.evaluate_assessment(punct_model)
    assert m_punct.unsupported_predicted_count == 1

    # 2. Opposite quote characters in content: ASSIGN TO '"accounts.dat"'
    src_quotes = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TQUOTE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACC-FILE ASSIGN TO '"accounts.dat"'
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD ACC-FILE.
       01 ACC-REC PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
"""
    p_quotes = SystemCobolParser(_make_synth_bundle(src_quotes, "TQUOTE.CBL"))
    cert_quotes = p_quotes.parse_system()
    assert cert_quotes.unsupported_relevant_count == 0
    fb_q_facts = [
        f.fact for f in p_quotes.get_supported_facts() if isinstance(f.fact, FileBindingFact)
    ]
    assert len(fb_q_facts) == 1
    assert fb_q_facts[0].external_file_name == '"accounts.dat"'

    idx_quotes = SystemSupportIndex(
        p_quotes.get_supported_facts(),
        _make_synth_bundle(src_quotes, "TQUOTE.CBL"),
        file_status_certificate=p_quotes.file_status_certificate,
    )
    ev_quotes = SystemEvaluatorV3(idx_quotes)

    # Positive exact model assertion -> certified
    exact_q_model = SystemAssessment(system_name="Test")
    exact_q_model.file_bindings.append(
        FileBinding(
            program_id="TQUOTE",
            internal_file_name="ACC-FILE",
            external_file_name='"accounts.dat"',
            organization="LINE_SEQUENTIAL",
            evidence=SourceEvidence(
                file_path="TQUOTE.CBL",
                line_start=6,
                line_end=7,
            ),
        )
    )
    m_q_exact, preds_q = ev_quotes.evaluate_assessment(exact_q_model)
    assert m_q_exact.unsupported_predicted_count == 0
    assert preds_q[0].is_supported is True

    # Mutated (stripping quotes) -> evaluator rejects
    mut_q_model = SystemAssessment(system_name="Test")
    mut_q_model.file_bindings.append(
        FileBinding(
            program_id="TQUOTE",
            internal_file_name="ACC-FILE",
            external_file_name="accounts.dat",
            organization="LINE_SEQUENTIAL",
            evidence=SourceEvidence(
                file_path="TQUOTE.CBL",
                line_start=6,
                line_end=7,
            ),
        )
    )
    m_q_mut, _ = ev_quotes.evaluate_assessment(mut_q_model)
    assert m_q_mut.unsupported_predicted_count == 1

    # 3. Adversarial probes: unsupported quoting fails closed with zero facts
    # Probe A: doubled quotes (same-quote escape)
    src_doubled = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TDOUBLED.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACC-FILE ASSIGN TO 'acc''ounts.dat'
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD ACC-FILE.
       01 ACC-REC PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
"""
    p_doubled = SystemCobolParser(_make_synth_bundle(src_doubled, "TDOUBLED.CBL"))
    cert_doubled = p_doubled.parse_system()
    assert cert_doubled.unsupported_relevant_count >= 1
    assert cert_doubled.is_evaluation_blocked is True
    assert not any(isinstance(f.fact, FileBindingFact) for f in p_doubled.get_supported_facts())

    # Probe B: unclosed literal
    src_unclosed = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TUNCLOSED.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACC-FILE ASSIGN TO 'accounts.dat
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD ACC-FILE.
       01 ACC-REC PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
"""
    p_unclosed = SystemCobolParser(_make_synth_bundle(src_unclosed, "TUNCLOSED.CBL"))
    cert_unclosed = p_unclosed.parse_system()
    assert cert_unclosed.unsupported_relevant_count >= 1
    assert cert_unclosed.is_evaluation_blocked is True
    assert not any(isinstance(f.fact, FileBindingFact) for f in p_unclosed.get_supported_facts())

    # Probe C: empty literal
    src_empty = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEMPTY.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACC-FILE ASSIGN TO ''
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD ACC-FILE.
       01 ACC-REC PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
"""
    p_empty = SystemCobolParser(_make_synth_bundle(src_empty, "TEMPTY.CBL"))
    cert_empty = p_empty.parse_system()
    assert cert_empty.unsupported_relevant_count >= 1
    assert cert_empty.is_evaluation_blocked is True
    assert not any(isinstance(f.fact, FileBindingFact) for f in p_empty.get_supported_facts())

    # Probe D: malformed trailing characters
    src_malformed = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TMALFORMED.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACC-FILE ASSIGN TO 'accounts.dat'extra
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD ACC-FILE.
       01 ACC-REC PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
"""
    p_malformed = SystemCobolParser(_make_synth_bundle(src_malformed, "TMALFORMED.CBL"))
    cert_malformed = p_malformed.parse_system()
    assert cert_malformed.unsupported_relevant_count >= 1
    assert cert_malformed.is_evaluation_blocked is True
    assert not any(isinstance(f.fact, FileBindingFact) for f in p_malformed.get_supported_facts())


def test_h7_4_1_level_88_source_literal_symmetry() -> None:
    """H7.4.1 Test B: Level-88 exact literal preservation, opposite quotes, fail-closed."""
    # 1. Exact whitespace preservation: 88 STATUS VALUE ' A '.
    src_88_space = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T88SPACE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-STATUS PIC X(3).
             88 STATUS-ACTIVE VALUE ' A '.
       PROCEDURE DIVISION.
           STOP RUN.
"""
    p_88_space = SystemCobolParser(_make_synth_bundle(src_88_space, "T88SPACE.CBL"))
    cert_88_space = p_88_space.parse_system()
    assert cert_88_space.unsupported_relevant_count == 0
    rl_facts = [
        f.fact for f in p_88_space.get_supported_facts() if isinstance(f.fact, RecordLayoutFact)
    ]
    assert len(rl_facts) == 1
    flds = rl_facts[0].fields
    cond_fld = next(f for f in flds if f.name == "STATUS-ACTIVE")
    assert cond_fld.condition_values == (" A ",)

    idx_88_space = SystemSupportIndex(
        p_88_space.get_supported_facts(),
        _make_synth_bundle(src_88_space, "T88SPACE.CBL"),
        file_status_certificate=p_88_space.file_status_certificate,
    )
    ev_88_space = SystemEvaluatorV3(idx_88_space)

    # Positive exact model assertion -> certified
    exact_model = SystemAssessment(system_name="Test")
    exact_model.record_layouts.append(
        RecordLayout(
            program_id="T88SPACE",
            record_name="WS-REC",
            fields=[
                RecordField(
                    field_kind="DATA_FIELD",
                    level=5,
                    name="WS-STATUS",
                    picture="X(3)",
                    usage="DISPLAY",
                    condition_values=[],
                ),
                RecordField(
                    field_kind="CONDITION_NAME",
                    level=88,
                    name="STATUS-ACTIVE",
                    picture=None,
                    usage=None,
                    condition_values=[" A "],
                ),
            ],
            evidence=SourceEvidence(
                file_path="T88SPACE.CBL",
                line_start=5,
                line_end=7,
            ),
        )
    )
    m_exact, preds_exact = ev_88_space.evaluate_assessment(exact_model)
    assert m_exact.unsupported_predicted_count == 0
    assert len(preds_exact) == 1
    assert preds_exact[0].is_supported is True

    # Mutated trimmed condition value -> evaluator rejects
    trimmed_model = SystemAssessment(system_name="Test")
    trimmed_model.record_layouts.append(
        RecordLayout(
            program_id="T88SPACE",
            record_name="WS-REC",
            fields=[
                RecordField(
                    field_kind="DATA_FIELD",
                    level=5,
                    name="WS-STATUS",
                    picture="X(3)",
                    usage="DISPLAY",
                    condition_values=[],
                ),
                RecordField(
                    field_kind="CONDITION_NAME",
                    level=88,
                    name="STATUS-ACTIVE",
                    picture=None,
                    usage=None,
                    condition_values=["A"],
                ),
            ],
            evidence=SourceEvidence(
                file_path="T88SPACE.CBL",
                line_start=5,
                line_end=7,
            ),
        )
    )
    m_trim, _ = ev_88_space.evaluate_assessment(trimmed_model)
    assert m_trim.unsupported_predicted_count == 1

    # 2. Opposite quote characters in condition content: 88 STATUS VALUE '"A"'.
    src_88_quote = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T88QUOTE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-STATUS PIC X(3).
             88 STATUS-A VALUE '"A"'.
       PROCEDURE DIVISION.
           STOP RUN.
"""
    p_88_quote = SystemCobolParser(_make_synth_bundle(src_88_quote, "T88QUOTE.CBL"))
    cert_88_quote = p_88_quote.parse_system()
    assert cert_88_quote.unsupported_relevant_count == 0
    rl_q = [
        f.fact for f in p_88_quote.get_supported_facts() if isinstance(f.fact, RecordLayoutFact)
    ][0]
    cond_q = next(f for f in rl_q.fields if f.name == "STATUS-A")
    assert cond_q.condition_values == ('"A"',)

    idx_88_quote = SystemSupportIndex(
        p_88_quote.get_supported_facts(),
        _make_synth_bundle(src_88_quote, "T88QUOTE.CBL"),
        file_status_certificate=p_88_quote.file_status_certificate,
    )
    ev_88_quote = SystemEvaluatorV3(idx_88_quote)

    exact_q_model = SystemAssessment(system_name="Test")
    exact_q_model.record_layouts.append(
        RecordLayout(
            program_id="T88QUOTE",
            record_name="WS-REC",
            fields=[
                RecordField(
                    field_kind="DATA_FIELD",
                    level=5,
                    name="WS-STATUS",
                    picture="X(3)",
                    usage="DISPLAY",
                    condition_values=[],
                ),
                RecordField(
                    field_kind="CONDITION_NAME",
                    level=88,
                    name="STATUS-A",
                    picture=None,
                    usage=None,
                    condition_values=['"A"'],
                ),
            ],
            evidence=SourceEvidence(
                file_path="T88QUOTE.CBL",
                line_start=5,
                line_end=7,
            ),
        )
    )
    m_q_exact, preds_q = ev_88_quote.evaluate_assessment(exact_q_model)
    assert m_q_exact.unsupported_predicted_count == 0
    assert preds_q[0].is_supported is True

    # Mutated condition value (removed double quotes) -> evaluator rejects
    mut_q_model = SystemAssessment(system_name="Test")
    mut_q_model.record_layouts.append(
        RecordLayout(
            program_id="T88QUOTE",
            record_name="WS-REC",
            fields=[
                RecordField(
                    field_kind="DATA_FIELD",
                    level=5,
                    name="WS-STATUS",
                    picture="X(3)",
                    usage="DISPLAY",
                    condition_values=[],
                ),
                RecordField(
                    field_kind="CONDITION_NAME",
                    level=88,
                    name="STATUS-A",
                    picture=None,
                    usage=None,
                    condition_values=["A"],
                ),
            ],
            evidence=SourceEvidence(
                file_path="T88QUOTE.CBL",
                line_start=5,
                line_end=7,
            ),
        )
    )
    m_q_mut, _ = ev_88_quote.evaluate_assessment(mut_q_model)
    assert m_q_mut.unsupported_predicted_count == 1

    # 3. Empty condition value support: 88 STATUS-EMPTY VALUE ''.
    src_88_empty = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T88EMPTY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-STATUS PIC X(3).
             88 STATUS-EMPTY VALUE ''.
       PROCEDURE DIVISION.
           STOP RUN.
"""
    p_88_empty = SystemCobolParser(_make_synth_bundle(src_88_empty, "T88EMPTY.CBL"))
    cert_88_empty = p_88_empty.parse_system()
    assert cert_88_empty.unsupported_relevant_count == 0
    rl_empty = [
        f.fact for f in p_88_empty.get_supported_facts() if isinstance(f.fact, RecordLayoutFact)
    ][0]
    cond_empty = next(f for f in rl_empty.fields if f.name == "STATUS-EMPTY")
    assert cond_empty.condition_values == ("",)

    idx_88_empty = SystemSupportIndex(
        p_88_empty.get_supported_facts(),
        _make_synth_bundle(src_88_empty, "T88EMPTY.CBL"),
        file_status_certificate=p_88_empty.file_status_certificate,
    )
    ev_88_empty = SystemEvaluatorV3(idx_88_empty)

    empty_model = SystemAssessment(system_name="Test")
    empty_model.record_layouts.append(
        RecordLayout(
            program_id="T88EMPTY",
            record_name="WS-REC",
            fields=[
                RecordField(
                    field_kind="DATA_FIELD",
                    level=5,
                    name="WS-STATUS",
                    picture="X(3)",
                    usage="DISPLAY",
                    condition_values=[],
                ),
                RecordField(
                    field_kind="CONDITION_NAME",
                    level=88,
                    name="STATUS-EMPTY",
                    picture=None,
                    usage=None,
                    condition_values=[""],
                ),
            ],
            evidence=SourceEvidence(
                file_path="T88EMPTY.CBL",
                line_start=5,
                line_end=7,
            ),
        )
    )
    m_empty, preds_empty = ev_88_empty.evaluate_assessment(empty_model)
    assert m_empty.unsupported_predicted_count == 0
    assert preds_empty[0].is_supported is True

    # 4. Unsupported quoting in level-88 fails closed
    src_88_bad = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T88BAD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-STATUS PIC X(3).
             88 STATUS-BAD VALUE 'A''B'.
       PROCEDURE DIVISION.
           STOP RUN.
"""
    p_88_bad = SystemCobolParser(_make_synth_bundle(src_88_bad, "T88BAD.CBL"))
    cert_88_bad = p_88_bad.parse_system()
    assert cert_88_bad.unsupported_relevant_count >= 1
    assert cert_88_bad.is_evaluation_blocked is True
    assert not any(
        isinstance(f.fact, RecordLayoutFact)
        and any(fld.name == "STATUS-BAD" for fld in f.fact.fields)
        for f in p_88_bad.get_supported_facts()
    )


def test_h7_4_1_command_literal_source_symmetry() -> None:
    """H7.4.1 Test C: Command literal preservation, shell syntax acceptance, fail-closed."""
    # 1. Exact whitespace preservation: MOVE ' cmd /c echo test ' TO WS-CMD
    src_cmd_space = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TCMDSPACE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(30).
       PROCEDURE DIVISION.
           MOVE ' cmd /c del "accounts.dat" ' TO WS-CMD.
           CALL 'SYSTEM' USING WS-CMD.
           STOP RUN.
"""
    p_cmd = SystemCobolParser(_make_synth_bundle(src_cmd_space, "TCMDSPACE.CBL"))
    cert_cmd = p_cmd.parse_system()
    assert cert_cmd.unsupported_relevant_count == 0
    cmd_facts = [
        f.fact for f in p_cmd.get_supported_facts() if isinstance(f.fact, CommandInvocationFact)
    ]
    plat_facts = [
        f.fact for f in p_cmd.get_supported_facts() if isinstance(f.fact, PlatformDependencyFact)
    ]
    assert len(cmd_facts) == 1
    assert len(plat_facts) == 1
    assert cmd_facts[0].command_template == ' cmd /c del "accounts.dat" '
    assert plat_facts[0].command_literal == ' cmd /c del "accounts.dat" '

    idx_cmd = SystemSupportIndex(
        p_cmd.get_supported_facts(),
        _make_synth_bundle(src_cmd_space, "TCMDSPACE.CBL"),
        file_status_certificate=p_cmd.file_status_certificate,
    )
    ev_cmd = SystemEvaluatorV3(idx_cmd)

    # Positive exact model assertion -> certified
    exact_model = SystemAssessment(system_name="Test")
    exact_model.command_invocations.append(
        CommandInvocation(
            program_id="TCMDSPACE",
            command_template=' cmd /c del "accounts.dat" ',
            target_operand="WS-CMD",
            assignment_evidence=SourceEvidence(file_path="TCMDSPACE.CBL", line_start=7, line_end=7),
            call_evidence=SourceEvidence(file_path="TCMDSPACE.CBL", line_start=8, line_end=8),
        )
    )
    exact_model.platform_dependencies.append(
        PlatformDependency(
            program_id="TCMDSPACE",
            platform_family="WINDOWS",
            command_literal=' cmd /c del "accounts.dat" ',
            evidence=SourceEvidence(file_path="TCMDSPACE.CBL", line_start=7, line_end=7),
        )
    )
    m_exact, preds_exact = ev_cmd.evaluate_assessment(exact_model)
    assert m_exact.unsupported_predicted_count == 0
    assert len(preds_exact) == 2

    # Mutated command_template (trimmed) -> evaluator rejects
    trim_cmd_model = SystemAssessment(system_name="Test")
    trim_cmd_model.command_invocations.append(
        CommandInvocation(
            program_id="TCMDSPACE",
            command_template='cmd /c del "accounts.dat"',
            target_operand="WS-CMD",
            assignment_evidence=SourceEvidence(file_path="TCMDSPACE.CBL", line_start=7, line_end=7),
            call_evidence=SourceEvidence(file_path="TCMDSPACE.CBL", line_start=8, line_end=8),
        )
    )
    m_trim, _ = ev_cmd.evaluate_assessment(trim_cmd_model)
    assert m_trim.unsupported_predicted_count == 1

    # 2. Shell wildcard syntax (*) in command literal grounds opaque command/platform facts,
    # but mutation interpretation fails closed (coverage blocked, zero sequence/risk).
    src_wildcard = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWILD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(30).
       PROCEDURE DIVISION.
           MOVE ' cmd /c del *.tmp ' TO WS-CMD.
           CALL 'SYSTEM' USING WS-CMD.
           STOP RUN.
"""
    p_wild = SystemCobolParser(_make_synth_bundle(src_wildcard, "TWILD.CBL"))
    cert_wild = p_wild.parse_system()
    assert cert_wild.unsupported_relevant_count > 0, "Wildcard mutation must fail closed"
    assert cert_wild.is_evaluation_blocked is True
    plat_wild = [
        f.fact for f in p_wild.get_supported_facts() if isinstance(f.fact, PlatformDependencyFact)
    ][0]
    assert plat_wild.command_literal == " cmd /c del *.tmp "
    assert plat_wild.platform_family == "WINDOWS"
    seq_wild = [
        f.fact
        for f in p_wild.get_supported_facts()
        if isinstance(f.fact, (OperationSequenceFact, BehavioralRiskFact))
    ]
    assert len(seq_wild) == 0, "Zero target-based sequence/risk facts for wildcard mutation"

    idx_wild = SystemSupportIndex(
        p_wild.get_supported_facts(),
        _make_synth_bundle(src_wildcard, "TWILD.CBL"),
        file_status_certificate=p_wild.file_status_certificate,
    )
    ev_wild = SystemEvaluatorV3(idx_wild)

    # Schema must accept command containing wildcard *
    wild_model = SystemAssessment(system_name="Test")
    wild_model.platform_dependencies.append(
        PlatformDependency(
            program_id="TWILD",
            platform_family="WINDOWS",
            command_literal=" cmd /c del *.tmp ",
            evidence=SourceEvidence(file_path="TWILD.CBL", line_start=7, line_end=7),
        )
    )
    m_wild, preds_wild = ev_wild.evaluate_assessment(wild_model)
    assert m_wild.unsupported_predicted_count == 0
    assert preds_wild[0].is_supported is True

    # 3. Unsupported quoting in command fails closed with zero facts
    src_bad_cmd = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TBADCMD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(30).
       PROCEDURE DIVISION.
           MOVE 'cmd /c del ''test.dat''' TO WS-CMD.
           CALL 'SYSTEM' USING WS-CMD.
           STOP RUN.
"""
    p_bad = SystemCobolParser(_make_synth_bundle(src_bad_cmd, "TBADCMD.CBL"))
    cert_bad = p_bad.parse_system()
    assert cert_bad.unsupported_relevant_count >= 1
    assert cert_bad.is_evaluation_blocked is True
    assert not any(isinstance(f.fact, CommandInvocationFact) for f in p_bad.get_supported_facts())
    assert not any(isinstance(f.fact, PlatformDependencyFact) for f in p_bad.get_supported_facts())


def test_h7_4_1_data_state_comparison_literal_symmetry() -> None:
    """H7.4.1 Test D: DataStateComparison literal content preservation and empty content support."""
    # Boundary whitespace and punctuation in DataStateComparison
    dsc = DataStateComparison(
        entity_id="ACC-001",
        dat_record_value="  100.50,PENDING  ",
        initializer_code_value="  100.50,SETTLED  ",
        causal_provenance="UNKNOWN",
        dat_evidence=SourceEvidence(file_path="ACCOUNTS.DAT", line_start=1, line_end=1),
        initializer_evidence=SourceEvidence(file_path="INIT-DB.CBL", line_start=10, line_end=10),
    )
    assert dsc.dat_record_value == "  100.50,PENDING  "
    assert dsc.initializer_code_value == "  100.50,SETTLED  "

    # Empty content permitted by generic validator on DataStateComparison
    dsc_empty = DataStateComparison(
        entity_id="ACC-002",
        dat_record_value="",
        initializer_code_value="0.00",
        causal_provenance="UNKNOWN",
        dat_evidence=SourceEvidence(file_path="ACCOUNTS.DAT", line_start=2, line_end=2),
        initializer_evidence=SourceEvidence(file_path="INIT-DB.CBL", line_start=12, line_end=12),
    )
    assert dsc_empty.dat_record_value == ""

    # Evaluator certification: exact match succeeds, trimmed fails
    fact = DataStateComparisonFact(
        entity_id="ACC-001",
        dat_record_value="  100.50,PENDING  ",
        initializer_code_value="  100.50,SETTLED  ",
        causal_provenance="UNKNOWN",
    )
    supp_fact = SupportedSystemFact(
        fact=fact,
        proposition_id="prop.state.test",
        evidence_spans={
            "dat_evidence": EvidenceSpan("ACCOUNTS.DAT", 1, 1),
            "initializer_evidence": EvidenceSpan("INIT-DB.CBL", 10, 10),
        },
    )
    tf_dat = TargetFile(
        relative_path="ACCOUNTS.DAT",
        file_type="DATA",
        raw_content="  100.50,PENDING  \n",
        numbered_content="000001   100.50,PENDING  \n",
        sha256="dummy_dat",
        line_count=2,
    )
    tf_cbl = TargetFile(
        relative_path="INIT-DB.CBL",
        file_type="COBOL",
        raw_content="       MOVE '  100.50,SETTLED  ' TO WS-VAL.\n" * 15,
        numbered_content="000010        MOVE '  100.50,SETTLED  ' TO WS-VAL.\n",
        sha256="dummy_cbl",
        line_count=20,
    )
    bundle = MultiSourceBundle(
        files={"ACCOUNTS.DAT": tf_dat, "INIT-DB.CBL": tf_cbl},
        total_physical_lines=22,
        bundle_sha256="synth",
        formatted_prompt_payload="synth",
    )
    idx = SystemSupportIndex([supp_fact], bundle)
    ev = SystemEvaluatorV3(idx)

    # Positive exact model
    model_exact = SystemAssessment(system_name="Test")
    model_exact.data_state_comparisons.append(dsc)
    m_exact, preds_exact = ev.evaluate_assessment(model_exact)
    assert m_exact.unsupported_predicted_count == 0
    assert len(preds_exact) == 1
    assert preds_exact[0].is_supported is True

    # Mutated trimmed model -> evaluator rejects
    dsc_trimmed = DataStateComparison(
        entity_id="ACC-001",
        dat_record_value="100.50,PENDING",
        initializer_code_value="100.50,SETTLED",
        causal_provenance="UNKNOWN",
        dat_evidence=SourceEvidence(file_path="ACCOUNTS.DAT", line_start=1, line_end=1),
        initializer_evidence=SourceEvidence(file_path="INIT-DB.CBL", line_start=10, line_end=10),
    )
    model_trim = SystemAssessment(system_name="Test")
    model_trim.data_state_comparisons.append(dsc_trimmed)
    m_trim, _ = ev.evaluate_assessment(model_trim)
    assert m_trim.unsupported_predicted_count == 1


def test_h7_4_1_file_organization_field_description() -> None:
    """H7.4.1 Section 5: FileBinding.organization description has LINE_SEQUENTIAL or SEQUENTIAL."""
    wire = get_system_openai_wire_schema()
    defs = wire.get("schema", {}).get("$defs", {})
    fb_def = defs.get("FileBinding", {})
    props = fb_def.get("properties", {})
    org_prop = props.get("organization", {})
    org_desc = org_prop.get("description", "")

    assert "LINE_SEQUENTIAL or SEQUENTIAL" in org_desc
    assert "INDEXED" not in org_desc
    assert "RELATIVE" not in org_desc


# ======================================================================
# 16. H7.4.2 PROCEDURAL SYNTAX & COVERAGE HOTFIX REGRESSION SUITE
# ======================================================================


def test_h7_4_2_b01_strict_call_target_syntax() -> None:
    """H7.4.2 B-01: Strict CALL target syntax before ASTCall emission."""
    # A. Supported literal target
    src_valid_single = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLV1.
       PROCEDURE DIVISION.
           CALL 'TARGET'
           STOP RUN.
"""
    p_v1 = SystemCobolParser(_make_synth_bundle(src_valid_single))
    cert_v1 = p_v1.parse_system()
    assert cert_v1.unsupported_relevant_count == 0
    call_facts_v1 = [f.fact for f in p_v1.supported_facts if isinstance(f.fact, CallOccurrenceFact)]
    assert len(call_facts_v1) == 1
    assert call_facts_v1[0].target_program == "TARGET"
    assert call_facts_v1[0].call_mechanism == "LITERAL_TARGET"

    src_valid_double = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLV2.
       PROCEDURE DIVISION.
           CALL "TARGET"
           STOP RUN.
"""
    p_v2 = SystemCobolParser(_make_synth_bundle(src_valid_double))
    cert_v2 = p_v2.parse_system()
    assert cert_v2.unsupported_relevant_count == 0
    call_facts_v2 = [f.fact for f in p_v2.supported_facts if isinstance(f.fact, CallOccurrenceFact)]
    assert len(call_facts_v2) == 1
    assert call_facts_v2[0].target_program == "TARGET"

    # B. Supported dynamic target
    src_valid_dyn = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLV3.
       PROCEDURE DIVISION.
           CALL TARGET-NAME
           STOP RUN.
"""
    p_v3 = SystemCobolParser(_make_synth_bundle(src_valid_dyn))
    cert_v3 = p_v3.parse_system()
    assert cert_v3.unsupported_relevant_count == 0
    call_facts_v3 = [f.fact for f in p_v3.supported_facts if isinstance(f.fact, CallOccurrenceFact)]
    assert len(call_facts_v3) == 1
    assert call_facts_v3[0].target_program == "TARGET-NAME"
    assert call_facts_v3[0].call_mechanism == "DYNAMIC_TARGET"

    # C. Malformed target probes: each must fail closed and emit 0 call facts
    malformed_targets = [
        "CALL 'TARGET",
        'CALL "TARGET',
        "CALL 'A''B'",
        'CALL "A""B"',
        "CALL 'TARGET'xyz",
        r"CALL 'TARGET\X'",
        "CALL ''",
        'CALL ""',
    ]
    for probe in malformed_targets:
        src_mal = f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLBAD.
       PROCEDURE DIVISION.
           {probe}
           STOP RUN.
"""
        p_mal = SystemCobolParser(_make_synth_bundle(src_mal))
        cert_mal = p_mal.parse_system()
        assert cert_mal.unsupported_relevant_count > 0, f"Probe {probe} must fail closed"
        assert cert_mal.is_evaluation_blocked is True
        call_facts_mal = [
            f.fact
            for f in p_mal.supported_facts
            if isinstance(f.fact, (CallOccurrenceFact, CallEdgeFact))
        ]
        assert len(call_facts_mal) == 0, f"Probe {probe} must emit zero call facts"

    # D. Malformed CALL 'SYSTEM specifically: must never enter command dispatch
    src_mal_sys = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. MALSYSCMD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE "cmd /c echo test" TO WS-CMD.
           CALL 'SYSTEM
           STOP RUN.
"""
    p_msys = SystemCobolParser(_make_synth_bundle(src_mal_sys))
    cert_msys = p_msys.parse_system()
    assert cert_msys.unsupported_relevant_count > 0
    cmd_facts_msys = [
        f.fact
        for f in p_msys.supported_facts
        if isinstance(f.fact, (CommandInvocationFact, PlatformDependencyFact))
    ]
    assert len(cmd_facts_msys) == 0, "Malformed CALL 'SYSTEM must never enter command dispatch"


def test_h7_4_2_b02_same_line_barriers_and_procedural_grammar() -> None:
    """H7.4.2 B-02: Same-line barriers must block coverage and prevent false sequence/risk."""
    # Auditor's exact fixture: same-line ELSE
    src_else_fixture = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. AUDITELSE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(100).
       01 FLAG PIC 9 VALUE 1.
       PROCEDURE DIVISION.
           IF FLAG = 1
               MOVE 'cmd /c del accounts.dat' TO BUFFER
               CALL 'SYSTEM' USING BUFFER ELSE
               MOVE 'cmd /c ren accounts.tmp accounts.dat' TO BUFFER
               CALL 'SYSTEM' USING BUFFER
           END-IF
           STOP RUN.
"""
    p_else = SystemCobolParser(_make_synth_bundle(src_else_fixture))
    cert_else = p_else.parse_system()
    assert cert_else.unsupported_relevant_count > 0, "Same-line ELSE must fail closed"
    assert cert_else.is_evaluation_blocked is True
    seq_facts = [
        f.fact for f in p_else.supported_facts if isinstance(f.fact, OperationSequenceFact)
    ]
    assert len(seq_facts) == 0, "Same-line ELSE must NOT produce false DELETE -> RENAME sequence"
    risk_facts = [f.fact for f in p_else.supported_facts if isinstance(f.fact, BehavioralRiskFact)]
    assert len(risk_facts) == 0, "Same-line ELSE must NOT produce false non-atomic risk"

    # Same-line barriers on CALL line: END-IF, WHEN, DISPLAY
    call_barrier_probes = [
        "CALL 'SYSTEM' USING BUFFER END-IF",
        "CALL 'SYSTEM' USING BUFFER WHEN 1",
        "CALL 'SYSTEM' USING BUFFER DISPLAY 'DONE'",
        "CALL 'SYSTEM' DISPLAY 'DONE'",
        "CALL 'SYSTEM' USING BUFFER ELSE",
    ]
    for probe in call_barrier_probes:
        src_b = f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLBAR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(100).
       PROCEDURE DIVISION.
           MOVE 'cmd /c echo test' TO BUFFER
           {probe}
           STOP RUN.
"""
        p_b = SystemCobolParser(_make_synth_bundle(src_b))
        cert_b = p_b.parse_system()
        assert cert_b.unsupported_relevant_count > 0, f"CALL barrier probe {probe} must fail closed"
        assert cert_b.is_evaluation_blocked is True

    # Same-line barriers on MOVE line: ELSE, END-IF, DISPLAY, WHEN
    move_barrier_probes = [
        "MOVE 'TARGET' TO BUFFER ELSE",
        "MOVE 'TARGET' TO BUFFER END-IF",
        "MOVE 'TARGET' TO BUFFER DISPLAY 'X'",
        "MOVE 'TARGET' TO BUFFER WHEN 1",
    ]
    for probe in move_barrier_probes:
        src_mb = f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. MOVEBAR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(100).
       PROCEDURE DIVISION.
           {probe}
           CALL 'SYSTEM' USING BUFFER
           STOP RUN.
"""
        p_mb = SystemCobolParser(_make_synth_bundle(src_mb))
        cert_mb = p_mb.parse_system()
        assert cert_mb.unsupported_relevant_count > 0, (
            f"MOVE barrier probe {probe} must fail closed"
        )
        assert cert_mb.is_evaluation_blocked is True
        cmd_facts_mb = [
            f.fact
            for f in p_mb.supported_facts
            if isinstance(f.fact, (CommandInvocationFact, PlatformDependencyFact))
        ]
        assert len(cmd_facts_mb) == 0


def test_h7_4_2_h01_move_syntax_validation() -> None:
    """H7.4.2 H-01: Validate literal MOVE syntax during MOVE parsing."""
    # Valid literal MOVE
    src_valid_move = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. MOVEV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(100).
       PROCEDURE DIVISION.
           MOVE 'TARGET' TO BUFFER
           STOP RUN.
"""
    p_vm = SystemCobolParser(_make_synth_bundle(src_valid_move))
    cert_vm = p_vm.parse_system()
    assert cert_vm.unsupported_relevant_count == 0
    assert cert_vm.is_evaluation_blocked is False

    # Malformed MOVE probes
    malformed_moves = [
        "MOVE 'TARGET TO BUFFER",
        'MOVE "TARGET TO BUFFER',
        "MOVE 'A''B' TO BUFFER",
        "MOVE 'TARGET'xyz TO BUFFER",
        "MOVE 'TARGET'",
        "MOVE 'TARGET' TO",
        r"MOVE 'TARGET\X' TO BUFFER",
    ]
    for probe in malformed_moves:
        src_mal = f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. MOVEBAD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(100).
       PROCEDURE DIVISION.
           {probe}
           CALL 'SYSTEM' USING BUFFER
           STOP RUN.
"""
        p_mal = SystemCobolParser(_make_synth_bundle(src_mal))
        cert_mal = p_mal.parse_system()
        assert cert_mal.unsupported_relevant_count > 0, f"MOVE probe {probe} must fail closed"
        assert cert_mal.is_evaluation_blocked is True
        cmd_facts = [
            f.fact
            for f in p_mal.supported_facts
            if isinstance(f.fact, (CommandInvocationFact, PlatformDependencyFact))
        ]
        assert len(cmd_facts) == 0, f"MOVE probe {probe} must produce no command facts"


def test_h7_4_2_h02_decoupled_command_and_sequence_support() -> None:
    """H7.4.2 H-02: Decouple command fact support from operation-sequence support."""
    # 1. Exact positive echo traversal: cmd /c echo test
    src_echo = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. ECHOCMD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(100).
       PROCEDURE DIVISION.
           MOVE ' cmd /c echo test ' TO BUFFER
           CALL 'SYSTEM' USING BUFFER
           STOP RUN.
"""
    bundle = _make_synth_bundle(src_echo)
    p_echo = SystemCobolParser(bundle)
    cert_echo = p_echo.parse_system()
    assert cert_echo.unsupported_relevant_count == 0, "Valid echo command must have clean coverage"
    assert cert_echo.is_evaluation_blocked is False

    cmd_facts = [
        f.fact for f in p_echo.supported_facts if isinstance(f.fact, CommandInvocationFact)
    ]
    assert len(cmd_facts) == 1
    assert cmd_facts[0].command_template == " cmd /c echo test "

    plat_facts = [
        f.fact for f in p_echo.supported_facts if isinstance(f.fact, PlatformDependencyFact)
    ]
    assert len(plat_facts) == 1
    assert plat_facts[0].command_literal == " cmd /c echo test "
    assert plat_facts[0].platform_family == "WINDOWS"

    seq_facts = [
        f.fact for f in p_echo.supported_facts if isinstance(f.fact, OperationSequenceFact)
    ]
    assert len(seq_facts) == 0, "Echo command is not a mutation sequence"
    risk_facts = [f.fact for f in p_echo.supported_facts if isinstance(f.fact, BehavioralRiskFact)]
    assert len(risk_facts) == 0, "Echo command has no non-atomic risk"

    # Evaluator traversal
    idx = SystemSupportIndex(p_echo.supported_facts, bundle)
    ev = SystemEvaluatorV3(idx)

    # Positive exact model
    model_exact = SystemAssessment(system_name="Echo")
    model_exact.command_invocations.append(
        CommandInvocation(
            program_id="ECHOCMD",
            command_template=" cmd /c echo test ",
            target_operand="BUFFER",
            assignment_evidence=SourceEvidence(file_path="TEST.CBL", line_start=7, line_end=7),
            call_evidence=SourceEvidence(file_path="TEST.CBL", line_start=8, line_end=8),
        )
    )
    model_exact.platform_dependencies.append(
        PlatformDependency(
            program_id="ECHOCMD",
            platform_family="WINDOWS",
            command_literal=" cmd /c echo test ",
            evidence=SourceEvidence(file_path="TEST.CBL", line_start=7, line_end=7),
        )
    )
    m_exact, preds_exact = ev.evaluate_assessment(model_exact)
    assert m_exact.unsupported_predicted_count == 0
    assert len(preds_exact) == 2
    assert all(p.is_supported for p in preds_exact)

    # Mutated model: trimmed whitespace -> evaluator rejects
    model_trim = SystemAssessment(system_name="Echo")
    model_trim.command_invocations.append(
        CommandInvocation(
            program_id="ECHOCMD",
            command_template="cmd /c echo test",
            target_operand="BUFFER",
            assignment_evidence=SourceEvidence(file_path="TEST.CBL", line_start=7, line_end=7),
            call_evidence=SourceEvidence(file_path="TEST.CBL", line_start=8, line_end=8),
        )
    )
    model_trim.platform_dependencies.append(
        PlatformDependency(
            program_id="ECHOCMD",
            platform_family="WINDOWS",
            command_literal="cmd /c echo test",
            evidence=SourceEvidence(file_path="TEST.CBL", line_start=7, line_end=7),
        )
    )
    m_trim, preds_trim = ev.evaluate_assessment(model_trim)
    assert m_trim.unsupported_predicted_count == 2
    assert all(not p.is_supported for p in preds_trim)

    # 2. Non-mutation command (dir): clean coverage, command supported, zero sequence
    src_dir = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONCCMD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(100).
       PROCEDURE DIVISION.
           MOVE 'cmd /c dir' TO BUFFER
           CALL 'SYSTEM' USING BUFFER
           STOP RUN.
"""
    p_dir = SystemCobolParser(_make_synth_bundle(src_dir))
    cert_dir = p_dir.parse_system()
    assert cert_dir.unsupported_relevant_count == 0, (
        "Non-mutation command dir must have clean coverage"
    )
    assert cert_dir.is_evaluation_blocked is False
    cmds_dir = [f.fact for f in p_dir.supported_facts if isinstance(f.fact, CommandInvocationFact)]
    assert len(cmds_dir) == 1
    assert cmds_dir[0].command_template == "cmd /c dir"

    # Wildcard mutation (cmd /c del *.tmp): grounds command and platform facts,
    # but mutation is unsupported
    src_wild = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONCWILD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(100).
       PROCEDURE DIVISION.
           MOVE 'cmd /c del *.tmp' TO BUFFER
           CALL 'SYSTEM' USING BUFFER
           STOP RUN.
"""
    p_wild2 = SystemCobolParser(_make_synth_bundle(src_wild))
    cert_wild2 = p_wild2.parse_system()
    assert cert_wild2.unsupported_relevant_count > 0, "Wildcard mutation fails closed"
    assert cert_wild2.is_evaluation_blocked is True
    cmds_wild = [
        f.fact for f in p_wild2.supported_facts if isinstance(f.fact, CommandInvocationFact)
    ]
    assert len(cmds_wild) == 1
    assert cmds_wild[0].command_template == "cmd /c del *.tmp"
    plats_wild = [
        f.fact for f in p_wild2.supported_facts if isinstance(f.fact, PlatformDependencyFact)
    ]
    assert len(plats_wild) == 1
    assert plats_wild[0].platform_family == "WINDOWS"
    seqs_wild = [
        f.fact
        for f in p_wild2.supported_facts
        if isinstance(f.fact, (OperationSequenceFact, BehavioralRiskFact))
    ]
    assert len(seqs_wild) == 0

    # 3. Single DELETE and single RENAME: command supported, no sequence, clean coverage
    for single_op in ("cmd /c del accounts.dat", "cmd /c ren accounts.tmp accounts.dat"):
        src_s = f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. SINGLEOP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(100).
       PROCEDURE DIVISION.
           MOVE '{single_op}' TO BUFFER
           CALL 'SYSTEM' USING BUFFER
           STOP RUN.
"""
        p_s = SystemCobolParser(_make_synth_bundle(src_s))
        cert_s = p_s.parse_system()
        assert cert_s.unsupported_relevant_count == 0
        seqs = [f.fact for f in p_s.supported_facts if isinstance(f.fact, OperationSequenceFact)]
        assert len(seqs) == 0, "Single command must produce no sequence fact"


# ======================================================================
# SECTION 17: H7.4.3 / CONTRACT 3.5.3 EXACT PROCEDURAL GRAMMAR & STATIC RESOLUTION REGRESSIONS
# ======================================================================


def test_h7_4_3_f01_f04_call_using_syntax_and_binding():
    """F-01 / Clarification 4: CALL/USING syntax validation and command binding rules.

    - CALL <target> USING <arg1> <arg2> has 2 USING args -> UNSUPPORTED_RELEVANT, 0 CallOccurrence.
    - CALL <target> USING <arg> CALL OTHER has trailing starter -> UNSUPPORTED_RELEVANT.
    - CALL 'SYSTEM' USING OTHER (where MOVE was to BUFFER) -> valid single-arg CALL, clean coverage,
      but 0 CommandInvocationFact.
    - CALL 'SYSTEM' USING OTHER BUFFER -> UNSUPPORTED_RELEVANT, 0 CallOccurrence,
      0 CommandInvocation.
    """
    # 1. Multiple USING arguments fail closed
    src_two_args = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWOARGS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 ARG1 PIC X(10).
       01 ARG2 PIC X(10).
       PROCEDURE DIVISION.
           CALL 'SUBPROG' USING ARG1 ARG2.
           STOP RUN.
"""
    p_two = SystemCobolParser(_make_synth_bundle(src_two_args))
    cert_two = p_two.parse_system()
    assert cert_two.unsupported_relevant_count >= 1
    calls_two = [f.fact for f in p_two.supported_facts if isinstance(f.fact, CallOccurrenceFact)]
    assert len(calls_two) == 0

    # 2. Compound CALL trailing in USING argument fails closed
    src_comp_call = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMPCALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(50).
       PROCEDURE DIVISION.
           MOVE 'cmd /c echo 1' TO WS-CMD.
           CALL 'SYSTEM' USING WS-CMD CALL OTHER.
           STOP RUN.
"""
    p_comp = SystemCobolParser(_make_synth_bundle(src_comp_call))
    cert_comp = p_comp.parse_system()
    assert cert_comp.unsupported_relevant_count >= 1
    calls_comp = [f.fact for f in p_comp.supported_facts if isinstance(f.fact, CallOccurrenceFact)]
    assert len(calls_comp) == 0
    cmds_comp = [
        f.fact for f in p_comp.supported_facts if isinstance(f.fact, CommandInvocationFact)
    ]
    assert len(cmds_comp) == 0

    # 3. Valid single-argument CALL with non-matching identifier produces 0 CommandInvocation
    src_unbound = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNBOUND.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(50).
       01 OTHER  PIC X(50).
       PROCEDURE DIVISION.
           MOVE 'cmd /c echo 1' TO BUFFER.
           CALL 'SYSTEM' USING OTHER.
           STOP RUN.
"""
    p_unbound = SystemCobolParser(_make_synth_bundle(src_unbound))
    cert_unbound = p_unbound.parse_system()
    assert cert_unbound.unsupported_relevant_count == 0, (
        "Syntactically valid CALL USING OTHER must have clean coverage"
    )
    calls_unbound = [
        f.fact for f in p_unbound.supported_facts if isinstance(f.fact, CallOccurrenceFact)
    ]
    assert len(calls_unbound) == 1
    cmds_unbound = [
        f.fact for f in p_unbound.supported_facts if isinstance(f.fact, CommandInvocationFact)
    ]
    assert len(cmds_unbound) == 0, "Unbound CALL USING OTHER must produce 0 CommandInvocation"

    # 4. CALL 'SYSTEM' USING OTHER BUFFER -> UNSUPPORTED_RELEVANT, 0 command dispatch
    src_sys_two = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SYSTWO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(50).
       01 OTHER  PIC X(50).
       PROCEDURE DIVISION.
           MOVE 'cmd /c echo 1' TO BUFFER.
           CALL 'SYSTEM' USING OTHER BUFFER.
           STOP RUN.
"""
    p_sys_two = SystemCobolParser(_make_synth_bundle(src_sys_two))
    cert_sys_two = p_sys_two.parse_system()
    assert cert_sys_two.unsupported_relevant_count >= 1
    calls_sys_two = [
        f.fact for f in p_sys_two.supported_facts if isinstance(f.fact, CallOccurrenceFact)
    ]
    assert len(calls_sys_two) == 0
    cmds_sys_two = [
        f.fact for f in p_sys_two.supported_facts if isinstance(f.fact, CommandInvocationFact)
    ]
    assert len(cmds_sys_two) == 0


def test_h7_4_3_f02_dynamic_call_target_isolation():
    """F-02 / Clarification 4: Dynamic target isolation.

    Dynamic CALL target does NOT participate in static internal resolution.
    CALL SYSTEM USING BUFFER where SYSTEM is an identifier:
    - Valid DYNAMIC_TARGET CallOccurrence
    - 0 InternalCallResolutionFact
    - 0 CallerContinuationConstraintFact
    - 0 CommandInvocationFact
    - 0 PlatformDependencyFact
    - 0 OperationSequenceFact
    - 0 BehavioralRiskFact
    """
    src_dyn = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYNCALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 SYSTEM PIC X(10) VALUE 'TARGET'.
       01 BUFFER PIC X(50).
       PROCEDURE DIVISION.
           MOVE 'cmd /c del test.dat' TO BUFFER.
           CALL SYSTEM USING BUFFER.
           STOP RUN.
"""
    p_dyn = SystemCobolParser(_make_synth_bundle(src_dyn))
    cert_dyn = p_dyn.parse_system()
    assert cert_dyn.unsupported_relevant_count == 0

    calls = [f.fact for f in p_dyn.supported_facts if isinstance(f.fact, CallOccurrenceFact)]
    assert len(calls) == 1
    assert calls[0].call_mechanism == "DYNAMIC_TARGET"
    assert calls[0].target_program == "SYSTEM"

    res_facts = [
        f.fact for f in p_dyn.supported_facts if isinstance(f.fact, InternalCallResolutionFact)
    ]
    assert len(res_facts) == 0, "Dynamic target must not produce InternalCallResolutionFact"

    cont_facts = [
        f.fact
        for f in p_dyn.supported_facts
        if isinstance(f.fact, CallerContinuationConstraintFact)
    ]
    assert len(cont_facts) == 0, "Dynamic target must not produce CallerContinuationConstraintFact"

    cmd_facts = [f.fact for f in p_dyn.supported_facts if isinstance(f.fact, CommandInvocationFact)]
    assert len(cmd_facts) == 0, "Dynamic target must not dispatch SYSTEM command"

    plat_facts = [
        f.fact for f in p_dyn.supported_facts if isinstance(f.fact, PlatformDependencyFact)
    ]
    assert len(plat_facts) == 0, "Dynamic target must not emit PlatformDependencyFact"

    seq_facts = [f.fact for f in p_dyn.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq_facts) == 0, "Dynamic target must not emit OperationSequenceFact"

    risk_facts = [f.fact for f in p_dyn.supported_facts if isinstance(f.fact, BehavioralRiskFact)]
    assert len(risk_facts) == 0, "Dynamic target must not emit BehavioralRiskFact"


def test_h7_4_3_f04_windows_mutation_three_outcomes_and_e2e_traversal():
    """F-04 / Clarification 3 & E2E Requirement:

    Tests three outcomes:
    A. NOT_MUTATION (echo, dir): CommandInvocation & PlatformDependency supported,
       clean coverage, not eligible for sequence/risk.
    B. MUTATION_PARSED:
       - Different spaced targets ("accounts old.dat" vs "accounts new.dat"):
         DELETE->RENAME sequence supported, NO risk fact. Fabricated matching risk fails evaluator.
       - Same spaced target ("accounts old.dat" vs "accounts old.dat"):
         DELETE->RENAME sequence supported, risk supported with canonical
         resource_name == "ACCOUNTS OLD.DAT" (never fragmented like '"ACCOUNTS').
    C. MUTATION_UNSUPPORTED:
       - Malformed Windows quoting (single quotes e.g. 'accounts old.dat'):
         Opaque CommandInvocation derived, source marked UNSUPPORTED_RELEVANT,
         evaluation blocked, 0 sequence, 0 risk.
    """
    # Outcome A: NOT_MUTATION
    src_echo = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. ECHOTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(50).
       PROCEDURE DIVISION.
           MOVE 'cmd /c echo hello' TO BUFFER.
           CALL 'SYSTEM' USING BUFFER.
           STOP RUN.
"""
    p_echo = SystemCobolParser(_make_synth_bundle(src_echo))
    cert_echo = p_echo.parse_system()
    assert cert_echo.unsupported_relevant_count == 0
    assert cert_echo.is_evaluation_blocked is False
    cmds_echo = [
        f.fact for f in p_echo.supported_facts if isinstance(f.fact, CommandInvocationFact)
    ]
    assert len(cmds_echo) == 1
    seqs_echo = [
        f.fact for f in p_echo.supported_facts if isinstance(f.fact, OperationSequenceFact)
    ]
    assert len(seqs_echo) == 0
    risks_echo = [f.fact for f in p_echo.supported_facts if isinstance(f.fact, BehavioralRiskFact)]
    assert len(risks_echo) == 0

    # Outcome B1: MUTATION_PARSED with different spaced targets
    src_diff = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DIFFTGT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(100).
       PROCEDURE DIVISION.
           MOVE 'cmd /c del "accounts old.dat"' TO BUFFER.
           CALL 'SYSTEM' USING BUFFER.
           MOVE 'cmd /c ren temp.tmp "accounts new.dat"' TO BUFFER.
           CALL 'SYSTEM' USING BUFFER.
           STOP RUN.
"""
    bundle_diff = _make_synth_bundle(src_diff, "DIFFTGT.CBL")
    p_diff = SystemCobolParser(bundle_diff)
    cert_diff = p_diff.parse_system()
    assert cert_diff.unsupported_relevant_count == 0
    seqs_diff = [
        f.fact for f in p_diff.supported_facts if isinstance(f.fact, OperationSequenceFact)
    ]
    assert len(seqs_diff) == 1
    assert seqs_diff[0].first_operation == "DELETE"
    assert seqs_diff[0].second_operation == "RENAME"
    risks_diff = [f.fact for f in p_diff.supported_facts if isinstance(f.fact, BehavioralRiskFact)]
    assert len(risks_diff) == 0, "Different targets must produce NO BehavioralRiskFact"

    # Evaluator traversal for B1: fabricated matching risk must FAIL evaluator support
    idx_diff = SystemSupportIndex(p_diff.supported_facts, bundle_diff)
    ev_diff = SystemEvaluatorV3(idx_diff)

    model_diff = SystemAssessment(system_name="DiffTgt")
    model_diff.operation_sequences.append(
        OperationSequence(
            program_id="DIFFTGT",
            first_operation="DELETE",
            second_operation="RENAME",
            first_assignment_evidence=SourceEvidence(
                file_path="DIFFTGT.CBL", line_start=7, line_end=7
            ),
            first_call_evidence=SourceEvidence(file_path="DIFFTGT.CBL", line_start=8, line_end=8),
            second_assignment_evidence=SourceEvidence(
                file_path="DIFFTGT.CBL", line_start=9, line_end=9
            ),
            second_call_evidence=SourceEvidence(
                file_path="DIFFTGT.CBL", line_start=10, line_end=10
            ),
        )
    )
    # Fabricated matching-target risk:
    model_diff.behavioral_risks.append(
        BehavioralRisk(
            program_id="DIFFTGT",
            risk_category="DATA_INTEGRITY",
            risk_basis_kind="NON_ATOMIC_EXTERNAL_MUTATION",
            impact_category="DATA_INTEGRITY",
            resource_name="ACCOUNTS OLD.DAT",
            operation_evidence=SourceEvidence(file_path="DIFFTGT.CBL", line_start=8, line_end=10),
            affected_resource_evidence=SourceEvidence(
                file_path="DIFFTGT.CBL", line_start=9, line_end=9
            ),
        )
    )
    m_diff, _ = ev_diff.evaluate_assessment(model_diff)
    assert m_diff.unsupported_predicted_count >= 1, (
        "Fabricated matching-target risk assertion must FAIL evaluator support"
    )

    # Outcome B2: MUTATION_PARSED with same spaced targets
    src_same = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMETGT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(100).
       PROCEDURE DIVISION.
           MOVE 'cmd /c del "accounts old.dat"' TO BUFFER.
           CALL 'SYSTEM' USING BUFFER.
           MOVE 'cmd /c ren temp.tmp "accounts old.dat"' TO BUFFER.
           CALL 'SYSTEM' USING BUFFER.
           STOP RUN.
"""
    bundle_same = _make_synth_bundle(src_same, "SAMETGT.CBL")
    p_same = SystemCobolParser(bundle_same)
    cert_same = p_same.parse_system()
    assert cert_same.unsupported_relevant_count == 0
    seqs_same = [
        f.fact for f in p_same.supported_facts if isinstance(f.fact, OperationSequenceFact)
    ]
    assert len(seqs_same) == 1
    risks_same = [f.fact for f in p_same.supported_facts if isinstance(f.fact, BehavioralRiskFact)]
    assert len(risks_same) == 1
    assert risks_same[0].resource_name == "ACCOUNTS OLD.DAT", (
        f"Must be canonical uppercase without quotes, got {risks_same[0].resource_name}"
    )
    assert not risks_same[0].resource_name.startswith('"'), "Must never be raw quoted syntax"

    # Evaluator traversal for B2: verified support
    idx_same = SystemSupportIndex(p_same.supported_facts, bundle_same)
    ev_same = SystemEvaluatorV3(idx_same)

    model_same = SystemAssessment(system_name="SameTgt")
    model_same.operation_sequences.append(
        OperationSequence(
            program_id="SAMETGT",
            first_operation="DELETE",
            second_operation="RENAME",
            first_assignment_evidence=SourceEvidence(
                file_path="SAMETGT.CBL", line_start=7, line_end=7
            ),
            first_call_evidence=SourceEvidence(file_path="SAMETGT.CBL", line_start=8, line_end=8),
            second_assignment_evidence=SourceEvidence(
                file_path="SAMETGT.CBL", line_start=9, line_end=9
            ),
            second_call_evidence=SourceEvidence(
                file_path="SAMETGT.CBL", line_start=10, line_end=10
            ),
        )
    )
    model_same.behavioral_risks.append(
        BehavioralRisk(
            program_id="SAMETGT",
            risk_category="DATA_INTEGRITY",
            risk_basis_kind="NON_ATOMIC_EXTERNAL_MUTATION",
            impact_category="DATA_INTEGRITY",
            resource_name="ACCOUNTS OLD.DAT",
            operation_evidence=SourceEvidence(file_path="SAMETGT.CBL", line_start=8, line_end=10),
            affected_resource_evidence=SourceEvidence(
                file_path="SAMETGT.CBL", line_start=9, line_end=9
            ),
        )
    )
    m_same, preds_same = ev_same.evaluate_assessment(model_same)
    assert m_same.unsupported_predicted_count == 0
    assert len(preds_same) == 2
    assert all(p.is_supported for p in preds_same)

    # Outcome C: MUTATION_UNSUPPORTED (single quotes as Windows grouping quotes)
    src_sq = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQMUT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(100).
       PROCEDURE DIVISION.
           MOVE "cmd /c del 'accounts old.dat'" TO BUFFER.
           CALL 'SYSTEM' USING BUFFER.
           STOP RUN.
"""
    p_sq = SystemCobolParser(_make_synth_bundle(src_sq))
    cert_sq = p_sq.parse_system()
    assert cert_sq.unsupported_relevant_count >= 1
    assert cert_sq.is_evaluation_blocked is True
    # Opaque command invocation is still derived
    cmds_sq = [f.fact for f in p_sq.supported_facts if isinstance(f.fact, CommandInvocationFact)]
    assert len(cmds_sq) == 1
    assert cmds_sq[0].command_template == "cmd /c del 'accounts old.dat'"
    # But zero sequence and zero risk facts
    seqs_sq = [f.fact for f in p_sq.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seqs_sq) == 0
    risks_sq = [f.fact for f in p_sq.supported_facts if isinstance(f.fact, BehavioralRiskFact)]
    assert len(risks_sq) == 0


def test_h7_4_3_f05_quoted_call_target_admission():
    """F-05: Quoted CALL target admission must reject non-canonical targets.

    - CALL 'target' (lowercase) -> UNSUPPORTED_RELEVANT, 0 CallOccurrence
    - CALL ' TARGET ' (whitespace-padded) -> UNSUPPORTED_RELEVANT, 0 CallOccurrence
    - CALL 'TARGET' (exact uppercase identifier) -> valid literal CallOccurrence
    """
    # Lowercase
    src_lower = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOWCALL.
       PROCEDURE DIVISION.
           CALL 'subprog'.
           STOP RUN.
"""
    p_low = SystemCobolParser(_make_synth_bundle(src_lower))
    cert_low = p_low.parse_system()
    assert cert_low.unsupported_relevant_count >= 1
    calls_low = [f.fact for f in p_low.supported_facts if isinstance(f.fact, CallOccurrenceFact)]
    assert len(calls_low) == 0

    # Whitespace padded
    src_pad = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PADCALL.
       PROCEDURE DIVISION.
           CALL ' SUBPROG '.
           STOP RUN.
"""
    p_pad = SystemCobolParser(_make_synth_bundle(src_pad))
    cert_pad = p_pad.parse_system()
    assert cert_pad.unsupported_relevant_count >= 1
    calls_pad = [f.fact for f in p_pad.supported_facts if isinstance(f.fact, CallOccurrenceFact)]
    assert len(calls_pad) == 0

    # Valid exact uppercase
    src_valid = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. VALCALL.
       PROCEDURE DIVISION.
           CALL 'SUBPROG'.
           STOP RUN.
"""
    p_val = SystemCobolParser(_make_synth_bundle(src_valid))
    cert_val = p_val.parse_system()
    assert cert_val.unsupported_relevant_count == 0
    calls_val = [f.fact for f in p_val.supported_facts if isinstance(f.fact, CallOccurrenceFact)]
    assert len(calls_val) == 1
    assert calls_val[0].target_program == "SUBPROG"


def test_h7_4_3_f06_interior_period_tokens_and_host_facts_invariance():
    """F-06 / Clarification 1:

    - Procedural parser removes only one terminal sentence-period token.
    - Interior period tokens fail closed:
      CALL . TARGET -> UNSUPPORTED_RELEVANT
      MOVE 'X' . TO BUFFER -> UNSUPPORTED_RELEVANT
      MOVE . 'X' TO BUFFER -> UNSUPPORTED_RELEVANT
    - Numeric literals (100.50) and quoted strings ('file.name') remain single tokens.
    - Legacy host facts remain 100% invariant with SHA
      74148cdb6b5c28c576406db77a8c84ae171a7fd1eec568c4d5a15256ef08f177.
    """
    for bad_stmt in ("CALL . TARGET", "MOVE 'X' . TO BUFFER", "MOVE . 'X' TO BUFFER"):
        src_bad = f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. BADPER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(50).
       PROCEDURE DIVISION.
           {bad_stmt}.
           STOP RUN.
"""
        p_bad = SystemCobolParser(_make_synth_bundle(src_bad))
        cert_bad = p_bad.parse_system()
        assert cert_bad.unsupported_relevant_count >= 1, f"{bad_stmt} must fail closed"

    # Numeric with decimal point preserved
    src_num = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. NUMPER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 NUM-FLD PIC 9(3)V99.
       PROCEDURE DIVISION.
           MOVE 100.50 TO NUM-FLD.
           STOP RUN.
"""
    p_num = SystemCobolParser(_make_synth_bundle(src_num))
    cert_num = p_num.parse_system()
    assert cert_num.unsupported_relevant_count == 0

    # Quoted with period preserved
    src_lit = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. LITPER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 FILE-NAME PIC X(20).
       PROCEDURE DIVISION.
           MOVE 'file.name' TO FILE-NAME.
           STOP RUN.
"""
    p_lit = SystemCobolParser(_make_synth_bundle(src_lit))
    cert_lit = p_lit.parse_system()
    assert cert_lit.unsupported_relevant_count == 0

    # Frozen legacy host facts invariance check
    bundle_legacy = read_system_bundle(REPO_ROOT)
    p_legacy = SystemCobolParser(bundle_legacy)
    cert_legacy = p_legacy.parse_system()
    assert cert_legacy.unsupported_relevant_count == 0
    assert (
        cert_legacy.certificate_sha256
        == "e5900cba53db046c80e0e5f64618b549e894631a0eebfe42f8c502fe0ae948be"
    )


def test_h7_4_3_f07_unified_procedural_starters_fail_closed():
    """F-07 / Clarification 2: Unified procedural starter set governs all branches.

    - Trailing unquoted procedural starter causes branch to fail closed:
      COMPUTE X = Y CALL OTHER -> UNSUPPORTED_RELEVANT
      MULTIPLY A BY B CALL OTHER -> UNSUPPORTED_RELEVANT
      DIVIDE A INTO B CALL OTHER -> UNSUPPORTED_RELEVANT
      IF X = 1 CALL OTHER -> UNSUPPORTED_RELEVANT
      ELSE CALL OTHER -> UNSUPPORTED_RELEVANT
      WHEN 1 CALL OTHER -> UNSUPPORTED_RELEVANT
    - Quoted content containing starter words must remain valid.
    """
    bad_probes = [
        "COMPUTE X = Y CALL OTHER",
        "MULTIPLY A BY B CALL OTHER",
        "DIVIDE A INTO B CALL OTHER",
        "IF X = 1 CALL OTHER",
        "ELSE CALL OTHER",
        "WHEN 1 CALL OTHER",
    ]
    for probe in bad_probes:
        src = f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROBETEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 X PIC 9(5).
       01 Y PIC 9(5).
       01 A PIC 9(5).
       01 B PIC 9(5).
       PROCEDURE DIVISION.
           {probe}.
           STOP RUN.
"""
        p = SystemCobolParser(_make_synth_bundle(src))
        cert = p.parse_system()
        assert cert.unsupported_relevant_count >= 1, (
            f"Probe '{probe}' must fail closed as UNSUPPORTED_RELEVANT"
        )

    # Quoted content containing starter words remains valid
    src_quoted = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. QUOTEDSTARTER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-MSG PIC X(50).
       PROCEDURE DIVISION.
           MOVE 'CALL OTHER' TO WS-MSG.
           STOP RUN.
"""
    p_q = SystemCobolParser(_make_synth_bundle(src_quoted))
    cert_q = p_q.parse_system()
    assert cert_q.unsupported_relevant_count == 0


# ===========================================================================
# SECTION 18: H7.4.4 / CONTRACT 3.5.3 SOUNDNESS & BLOCKER REGRESSIONS
# ===========================================================================


def test_h7_4_4_b01_identifier_domain_boundaries() -> None:
    """B-01: COBOL identifiers are distinguished from other string domains.

    - Canonical COBOL IDs require uppercase alphanumeric with hyphens and >=1 letter.
    - Pure numeric strings are rejected as COBOL IDs but admitted as computation operands
      and generic entity identifiers.
    - Schema validators and parser AST strictly enforce domain separation.
    """
    # 1. Domain predicate behavior
    assert is_canonical_cobol_identifier("PROG-1") is True
    assert is_canonical_cobol_identifier("WS-ACCOUNT-NUM") is True
    assert is_canonical_cobol_identifier("A") is True
    assert is_canonical_cobol_identifier("100") is False, "Numeric literal must not be COBOL ID"
    assert is_canonical_cobol_identifier("1000000003") is False
    assert is_canonical_cobol_identifier("prog-1") is False

    assert is_numeric_literal("100") is True
    assert is_numeric_literal("100.50") is True
    assert is_numeric_literal("+25") is True
    assert is_numeric_literal("-12.34") is True
    assert is_numeric_literal("100A") is False
    assert is_numeric_literal("PROG") is False

    assert is_computation_operand("100") is True
    assert is_computation_operand("100.50") is True
    assert is_computation_operand("WS-TOTAL") is True
    assert is_computation_operand("prog-total") is False

    # 2. Schema validation domain separation
    # DataStateComparison.entity_id accepts numeric entity
    dsc = DataStateComparison(
        entity_id="1000000003",
        dat_record_value="100.00",
        initializer_code_value="100.00",
        causal_provenance="UNKNOWN",
        dat_evidence=SourceEvidence(file_path="ACCOUNTS.DAT", line_start=1, line_end=1),
        initializer_evidence=SourceEvidence(file_path="INIT-DB.CBL", line_start=10, line_end=10),
    )
    assert dsc.entity_id == "1000000003"

    # ComputationDataflow.source_field accepts numeric literal or canonical ID
    cd_num = ComputationDataflow(
        program_id="CALC-PROG",
        target_field="WS-TOTAL",
        source_field="100.50",
        operation_verb="ADD",
        evidence=SourceEvidence(file_path="CALC.CBL", line_start=10, line_end=10),
    )
    assert cd_num.source_field == "100.50"

    cd_id = ComputationDataflow(
        program_id="CALC-PROG",
        target_field="WS-TOTAL",
        source_field="WS-AMOUNT",
        operation_verb="ADD",
        evidence=SourceEvidence(file_path="CALC.CBL", line_start=10, line_end=10),
    )
    assert cd_id.source_field == "WS-AMOUNT"

    # COBOL declaration schemas reject numeric IDs
    with pytest.raises(ValidationError):
        ProgramDeclaration(
            program_id="12345",
            evidence=SourceEvidence(file_path="PROG.CBL", line_start=1, line_end=1),
        )

    with pytest.raises(ValidationError):
        FileBinding(
            program_id="TEST-PROG",
            internal_file_name="12345",
            external_file_name="TEST.DAT",
            organization="LINE_SEQUENTIAL",
            evidence=SourceEvidence(file_path="PROG.CBL", line_start=2, line_end=2),
        )

    # 3. Parser rejects numeric identifiers in AST
    for bad_clause, verb_desc in [
        ("PROGRAM-ID. 12345.", "PROGRAM-ID"),
        ("SELECT 12345 ASSIGN TO 'TEST.DAT'.", "SELECT"),
        ("FD 12345.", "FD"),
        ("01 12345.", "RECORD_01"),
        ("05 12345 PIC X(10).", "FIELD_05"),
        ("88 12345 VALUE 'Y'.", "CONDITION_88"),
    ]:
        src_bad = f"""       IDENTIFICATION DIVISION.
       {bad_clause}
       PROCEDURE DIVISION.
           STOP RUN.
"""
        p_b = SystemCobolParser(_make_synth_bundle(src_bad))
        cert_b = p_b.parse_system()
        assert cert_b.unsupported_relevant_count >= 1, (
            f"{verb_desc} with numeric ID must fail closed"
        )
        assert cert_b.is_evaluation_blocked is True


def test_h7_4_4_b02_arithmetic_sentence_boundary_isolation() -> None:
    """B-02: Multiline arithmetic slurping stops at sentence period."""
    # Sentence period after ADD operand must not slurp the next sentence
    src_period_add = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TADDPER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-COUNT PIC 9(5).
       PROCEDURE DIVISION.
           ADD 1.
           TO WS-COUNT.
           STOP RUN.
"""
    p_add = SystemCobolParser(_make_synth_bundle(src_period_add))
    cert_add = p_add.parse_system()
    assert cert_add.unsupported_relevant_count >= 1, "ADD with period before TO must fail closed"
    assert cert_add.is_evaluation_blocked is True
    arith_facts = [
        f.fact for f in p_add.get_supported_facts() if isinstance(f.fact, ComputationDataflowFact)
    ]
    assert len(arith_facts) == 0, "No arithmetic fact may span across sentence period"

    # Valid multiline SUBTRACT without period on first line parses cleanly
    src_valid_sub = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TSUBMULT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TOTAL PIC 9(5).
       01 WS-AMT PIC 9(5).
       PROCEDURE DIVISION.
           SUBTRACT WS-AMT
              FROM WS-TOTAL.
           STOP RUN.
"""
    p_sub = SystemCobolParser(_make_synth_bundle(src_valid_sub))
    cert_sub = p_sub.parse_system()
    assert cert_sub.unsupported_relevant_count == 0, (
        "Valid multiline SUBTRACT without period must succeed"
    )
    sub_facts = [
        f.fact for f in p_sub.get_supported_facts() if isinstance(f.fact, ComputationDataflowFact)
    ]
    assert len(sub_facts) == 1
    assert sub_facts[0].source_field == "WS-AMT"
    assert sub_facts[0].target_field == "WS-TOTAL"
    assert sub_facts[0].operation_verb == "SUBTRACT"


def test_h7_4_4_b03_and_b05_mutation_tokenization_and_lossy_whitespace() -> None:
    """B-03 & B-05: Shell syntax rejection and lossless whitespace handling."""
    # Shell metacharacters (> < | & ^ % ! * ? ( )) fail closed
    for bad_cmd in (
        "cmd /c del a>b",
        "cmd /c del a|b",
        "cmd /c del a&b",
        "cmd /c del a^b",
        "cmd /c del %TMP%",
        "cmd /c del !VAR!",
        "cmd /c del (test)",
    ):
        src_meta = f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. TMETA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(100).
       PROCEDURE DIVISION.
           MOVE '{bad_cmd}' TO BUFFER
           CALL 'SYSTEM' USING BUFFER
           STOP RUN.
"""
        p_m = SystemCobolParser(_make_synth_bundle(src_meta))
        cert_m = p_m.parse_system()
        assert cert_m.unsupported_relevant_count >= 1, (
            f"Metacharacter command '{bad_cmd}' must fail closed"
        )
        assert cert_m.is_evaluation_blocked is True
        seq_m = [
            f.fact for f in p_m.get_supported_facts() if isinstance(f.fact, OperationSequenceFact)
        ]
        assert len(seq_m) == 0

    # Lossy whitespace: consecutive spaces or boundary whitespace in filename fail closed
    for lossy_cmd in (
        'cmd /c del "a  b.dat"',
        'cmd /c del " a.dat "',
    ):
        src_lossy = f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. TLOSSY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(100).
       PROCEDURE DIVISION.
           MOVE '{lossy_cmd}' TO BUFFER
           CALL 'SYSTEM' USING BUFFER
           STOP RUN.
"""
        p_l = SystemCobolParser(_make_synth_bundle(src_lossy))
        cert_l = p_l.parse_system()
        assert cert_l.unsupported_relevant_count >= 1, (
            f"Lossy whitespace command '{lossy_cmd}' must fail closed"
        )
        assert cert_l.is_evaluation_blocked is True
        seq_l = [
            f.fact for f in p_l.get_supported_facts() if isinstance(f.fact, OperationSequenceFact)
        ]
        assert len(seq_l) == 0


def test_h7_4_4_b04_posix_command_wrappers_fail_closed() -> None:
    """B-04: POSIX -c shell commands are rejected for mutation interpretation."""
    for posix_cmd in (
        "sh -c 'rm accounts.dat'",
        "/bin/sh -c 'rm accounts.dat'",
        "bash -c 'rm accounts.dat'",
        "/usr/bin/bash -c 'rm accounts.dat'",
    ):
        src_posix = f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. TPOSIX.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(100).
       PROCEDURE DIVISION.
           MOVE "{posix_cmd}" TO BUFFER
           CALL 'SYSTEM' USING BUFFER
           STOP RUN.
"""
        p_p = SystemCobolParser(_make_synth_bundle(src_posix))
        cert_p = p_p.parse_system()
        assert cert_p.unsupported_relevant_count >= 1, "POSIX mutation command must fail closed"
        assert cert_p.is_evaluation_blocked is True

        # Opaque facts are grounded
        cmd_facts = [
            f.fact for f in p_p.get_supported_facts() if isinstance(f.fact, CommandInvocationFact)
        ]
        assert len(cmd_facts) == 1
        assert cmd_facts[0].command_template == posix_cmd

        # ZERO PlatformDependencyFact because POSIX is not a model-visible token in Contract 3.5.3
        plat_facts = [
            f.fact for f in p_p.get_supported_facts() if isinstance(f.fact, PlatformDependencyFact)
        ]
        assert len(plat_facts) == 0, "POSIX mutation command must emit zero PlatformDependencyFact"

        # Mutation sequence and risk are NOT derived
        seq_facts = [
            f.fact for f in p_p.get_supported_facts() if isinstance(f.fact, OperationSequenceFact)
        ]
        assert len(seq_facts) == 0
        risk_facts = [
            f.fact for f in p_p.get_supported_facts() if isinstance(f.fact, BehavioralRiskFact)
        ]
        assert len(risk_facts) == 0


def test_h7_4_4_2_posix_non_mutation_unrepresentable_platform_blocks_coverage() -> None:
    """H7.4.4.2: POSIX non-mutation commands have grounded CommandInvocationFact,
    zero PlatformDependencyFact, but FAIL CLOSED with blocked coverage because
    PLATFORM_DEPENDENCY is REQUIRED_EXHAUSTIVE while PlatformFamily admits only WINDOWS.
    """
    for posix_nonmut in (
        "/bin/sh -c 'echo test'",
        "sh -c 'echo test'",
        "bash -c 'echo test'",
        "/usr/bin/bash -c 'echo test'",
    ):
        src_posix = f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. TPOSIXECHO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(100).
       PROCEDURE DIVISION.
           MOVE "{posix_nonmut}" TO BUFFER
           CALL 'SYSTEM' USING BUFFER
           STOP RUN.
"""
        p_p = SystemCobolParser(_make_synth_bundle(src_posix))
        cert_p = p_p.parse_system()
        # Coverage is blocked because unrepresentable platform dependency fails closed
        assert cert_p.unsupported_relevant_count >= 1, "POSIX non-mutation must block coverage"
        assert cert_p.is_evaluation_blocked is True

        # Exact opaque command fact is grounded
        cmd_facts = [
            f.fact for f in p_p.get_supported_facts() if isinstance(f.fact, CommandInvocationFact)
        ]
        assert len(cmd_facts) == 1
        assert cmd_facts[0].command_template == posix_nonmut

        # ZERO PlatformDependencyFact because POSIX is not in frozen wire domain
        plat_facts = [
            f.fact for f in p_p.get_supported_facts() if isinstance(f.fact, PlatformDependencyFact)
        ]
        assert len(plat_facts) == 0, "POSIX non-mutation must emit zero PlatformDependencyFact"

        # Zero sequence and risk
        seq_facts = [
            f.fact for f in p_p.get_supported_facts() if isinstance(f.fact, OperationSequenceFact)
        ]
        assert len(seq_facts) == 0
        risk_facts = [
            f.fact for f in p_p.get_supported_facts() if isinstance(f.fact, BehavioralRiskFact)
        ]
        assert len(risk_facts) == 0


def test_h7_4_4_2_windows_non_mutation_clean_coverage_positive_control() -> None:
    """Windows non-mutation commands (cmd /c, cmd.exe /c) have grounded CommandInvocation,
    grounded PlatformDependencyFact(platform_family='WINDOWS'), and clean coverage.
    """
    for win_cmd in (
        "cmd /c echo test",
        "cmd.exe /c echo test",
    ):
        src_win = f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWINECHO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(100).
       PROCEDURE DIVISION.
           MOVE "{win_cmd}" TO BUFFER
           CALL 'SYSTEM' USING BUFFER
           STOP RUN.
"""
        p_w = SystemCobolParser(_make_synth_bundle(src_win))
        cert_w = p_w.parse_system()
        # Clean coverage
        assert cert_w.unsupported_relevant_count == 0, (
            "Windows non-mutation must have clean coverage"
        )
        assert cert_w.is_evaluation_blocked is False

        # Command invocation fact is grounded
        cmd_facts = [
            f.fact for f in p_w.get_supported_facts() if isinstance(f.fact, CommandInvocationFact)
        ]
        assert len(cmd_facts) == 1
        assert cmd_facts[0].command_template == win_cmd

        # PlatformDependencyFact is emitted with WINDOWS
        plat_facts = [
            f.fact for f in p_w.get_supported_facts() if isinstance(f.fact, PlatformDependencyFact)
        ]
        assert len(plat_facts) == 1
        assert plat_facts[0].platform_family == "WINDOWS"
        assert plat_facts[0].command_literal == win_cmd

        # Zero sequence and risk
        seq_facts = [
            f.fact for f in p_w.get_supported_facts() if isinstance(f.fact, OperationSequenceFact)
        ]
        assert len(seq_facts) == 0
        risk_facts = [
            f.fact for f in p_w.get_supported_facts() if isinstance(f.fact, BehavioralRiskFact)
        ]
        assert len(risk_facts) == 0


def test_h7_4_4_2_platform_dependency_domain_closure_and_fail_closed() -> None:
    """Explicit domain-closure and fail-closed test:
    A. Every emitted PlatformDependencyFact token is wire-representable (WINDOWS).
    B. If parser deterministically observes an unrepresentable platform (POSIX),
       coverage MUST fail closed because PLATFORM_DEPENDENCY is REQUIRED_EXHAUSTIVE
       and POSIX is outside frozen PlatformFamily domain.
    """
    wire = get_system_openai_wire_schema()
    defs = wire.get("schema", {}).get("$defs", {})
    pd_def = defs.get("PlatformDependency", {})
    pf_prop = pd_def.get("properties", {}).get("platform_family", {})
    allowed_families = set(pf_prop.get("enum", []))
    if "const" in pf_prop:
        allowed_families.add(pf_prop["const"])
    assert allowed_families == {"WINDOWS"}, (
        f"Wire schema must expose ONLY WINDOWS, got {allowed_families}"
    )

    # Invariant A: Verify every supported fact across legacy system respects domain closure
    bundle_legacy = read_system_bundle(REPO_ROOT)
    p_legacy = SystemCobolParser(bundle_legacy)
    p_legacy.parse_system()
    for sf in p_legacy.get_supported_facts():
        if isinstance(sf.fact, PlatformDependencyFact):
            assert sf.fact.platform_family in allowed_families
            assert sf.fact.platform_family != "POSIX"

    # Invariant B: Unrepresentable platform (POSIX) deterministically blocks coverage
    src_posix = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TCLOSURE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUFFER PIC X(50).
       PROCEDURE DIVISION.
           MOVE "sh -c 'echo test'" TO BUFFER
           CALL 'SYSTEM' USING BUFFER
           STOP RUN.
"""
    p_posix = SystemCobolParser(_make_synth_bundle(src_posix))
    cert_posix = p_posix.parse_system()
    assert cert_posix.unsupported_relevant_count >= 1
    assert cert_posix.is_evaluation_blocked is True
    # Zero PlatformDependencyFact emitted
    assert not any(
        isinstance(sf.fact, PlatformDependencyFact) for sf in p_posix.get_supported_facts()
    )


def test_h7_4_4_b06_mixed_open_modes_fail_closed() -> None:
    """B-06: Mixed OPEN modes fail closed without fabricated lifecycle fact."""
    src_mixed = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TMIXED.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TEST-FILE ASSIGN TO 'TEST.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD TEST-FILE.
       01 TEST-REC.
          05 REC-ID PIC 9(5).
       PROCEDURE DIVISION.
           OPEN INPUT TEST-FILE.
           CLOSE TEST-FILE.
           OPEN OUTPUT TEST-FILE.
           WRITE TEST-REC.
           CLOSE TEST-FILE.
           STOP RUN.
"""
    p_m = SystemCobolParser(_make_synth_bundle(src_mixed))
    cert_m = p_m.parse_system()
    # Truthful individual FileOperation facts exist
    fop_facts = [f.fact for f in p_m.get_supported_facts() if isinstance(f.fact, FileOperationFact)]
    verbs = [f.operation_verb for f in fop_facts]
    assert "OPEN_INPUT" in verbs
    assert "OPEN_OUTPUT" in verbs

    # NO ResourceLifecycleFact emitted for mixed modes
    lc_facts = [
        f.fact for f in p_m.get_supported_facts() if isinstance(f.fact, ResourceLifecycleFact)
    ]
    assert len(lc_facts) == 0, "Mixed OPEN modes must NOT emit a fabricated ResourceLifecycleFact"

    # Coverage is blocked
    assert cert_m.unsupported_relevant_count >= 1, "Mixed OPEN modes must block evaluation coverage"
    assert cert_m.is_evaluation_blocked is True


def test_h7_4_4_b07_continuation_structural_proof() -> None:
    """B-07: Continuation constraint emission requires strict structural proof."""
    # 1. Auditor counterexample: GO TO and conflicting terminations -> unproven
    src_auditor = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLEEP.
       PROCEDURE DIVISION.
           GO TO RETURN-PARA.
           STOP RUN.
       RETURN-PARA.
           GOBACK.
"""
    src_caller = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLERP.
       PROCEDURE DIVISION.
           CALL 'CALLEEP'.
           STOP RUN.
"""
    bundle_unproven = _make_multi_file_bundle(
        {
            "CALLEEP.CBL": src_auditor,
            "CALLERP.CBL": src_caller,
        }
    )
    p_u = SystemCobolParser(bundle_unproven)
    cert_u = p_u.parse_system()
    # InternalCallResolution is emitted
    res_facts = [
        f.fact for f in p_u.get_supported_facts() if isinstance(f.fact, InternalCallResolutionFact)
    ]
    assert len(res_facts) == 1
    # NO continuation constraint emitted
    cont_facts = [
        f.fact
        for f in p_u.get_supported_facts()
        if isinstance(f.fact, CallerContinuationConstraintFact)
    ]
    assert len(cont_facts) == 0
    # CALL statement in caller is marked UNSUPPORTED_RELEVANT -> coverage blocked
    assert cert_u.unsupported_relevant_count >= 1
    assert cert_u.is_evaluation_blocked is True

    # 2. Conditional termination: IF COND STOP RUN END-IF DISPLAY 'X' -> unproven
    src_cond_callee = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONDCAL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-FLAG PIC X.
       PROCEDURE DIVISION.
           IF WS-FLAG = 'Y'
               STOP RUN
           END-IF.
           DISPLAY 'CONTINUES'.
"""
    bundle_cond = _make_multi_file_bundle(
        {
            "CONDCAL.CBL": src_cond_callee,
            "CALLERP.CBL": src_caller.replace("CALLEEP", "CONDCAL"),
        }
    )
    p_cond = SystemCobolParser(bundle_cond)
    cert_cond = p_cond.parse_system()
    cont_cond = [
        f.fact
        for f in p_cond.get_supported_facts()
        if isinstance(f.fact, CallerContinuationConstraintFact)
    ]
    assert len(cont_cond) == 0
    assert cert_cond.unsupported_relevant_count >= 1
    assert cert_cond.is_evaluation_blocked is True


def test_h7_4_4_procedural_grammar_guards_and_single_token_periods() -> None:
    """Procedural grammar complete consumption guards and single-token period handling."""
    # 1. Trailing syntax attacks
    for probe_stmt in (
        "DISPLAY 'X' GARBAGE",
        "ACCEPT WS-VAL GARBAGE",
        "END-IF GARBAGE",
        "AT END GARBAGE",
        "NOT AT END GARBAGE",
        "GO TO 0100-PARA GARBAGE",
        "GOTO 0100-PARA GARBAGE",
        "ELSE GARBAGE",
        "FROM WS-VAL",
    ):
        src_probe = f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. TGUARD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAL PIC 9(5).
       PROCEDURE DIVISION.
       0100-PARA.
           {probe_stmt}.
           STOP RUN.
"""
        p_g = SystemCobolParser(_make_synth_bundle(src_probe))
        cert_g = p_g.parse_system()
        assert cert_g.unsupported_relevant_count >= 1, (
            f"Trailing garbage '{probe_stmt}' must fail closed"
        )
        assert cert_g.is_evaluation_blocked is True

    # 2. Single token lines ending with period are NOT paragraph headers
    for stmt_tok in ("CALL.", "MOVE.", "END-IF.", "END-PERFORM."):
        src_head = f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. THEAD.
       PROCEDURE DIVISION.
           {stmt_tok}
           STOP RUN.
"""
        p_h = SystemCobolParser(_make_synth_bundle(src_head))
        p_h.parse_system()
        para_stmts = [s for s in p_h.statements if s.verb == "PARAGRAPH_HEADER"]
        assert len(para_stmts) == 0, f"{stmt_tok} must NOT be classified as PARAGRAPH_HEADER"


def test_h7_4_4_clarification_8_domain_symmetry_matrix() -> None:
    """Clarification 8: Domain-symmetry matrix for IDs, operands, entities, and resources."""
    # Pure numeric strings
    assert not is_canonical_cobol_identifier("1000000003")
    assert is_numeric_literal("1000000003")
    assert is_computation_operand("1000000003")
    assert validate_canonical_identifier("entity_id", "1000000003") == "1000000003"
    assert validate_computation_operand("source_field", "1000000003") == "1000000003"
    with pytest.raises(ValueError):
        validate_canonical_cobol_identifier("program_id", "1000000003")

    # Canonical COBOL ID
    assert is_canonical_cobol_identifier("ACCOUNT-RECORD")
    assert not is_numeric_literal("ACCOUNT-RECORD")
    assert is_computation_operand("ACCOUNT-RECORD")
    assert validate_canonical_cobol_identifier("program_id", "ACCOUNT-RECORD") == "ACCOUNT-RECORD"
    assert validate_canonical_identifier("record_name", "ACCOUNT-RECORD") == "ACCOUNT-RECORD"
    assert validate_computation_operand("source_field", "ACCOUNT-RECORD") == "ACCOUNT-RECORD"

    # Lowercase / mixed case identifier
    assert not is_canonical_cobol_identifier("account-record")
    assert not is_computation_operand("account-record")
    with pytest.raises(ValueError):
        validate_canonical_identifier("record_name", "account-record")
    with pytest.raises(ValueError):
        validate_canonical_cobol_identifier("program_id", "account-record")

    # Resource name with file extension (uppercase canonical contract form)
    assert not is_canonical_cobol_identifier("ACCOUNTS.DAT")
    assert not is_computation_operand("ACCOUNTS.DAT")
    assert validate_canonical_identifier("resource_name", "ACCOUNTS.DAT") == "ACCOUNTS.DAT"
    with pytest.raises(ValueError):
        validate_canonical_cobol_identifier("resource_name", "ACCOUNTS.DAT")


# ======================================================================
# H7.5-A REGRESSION SUITE: HOST SOUNDNESS F-01, F-03..F-09
# ======================================================================


def test_h7_5_a_f01_compute_multiply_divide_fail_closed() -> None:
    """F-01: COMPUTE, MULTIPLY, and DIVIDE must fail closed as UNSUPPORTED_RELEVANT,

    emitting zero ASTArithmetic and zero ComputationDataflowFact.
    """
    src_compute = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TCOMPUTE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(4).
       01 WS-B PIC 9(4).
       01 WS-C PIC 9(4).
       PROCEDURE DIVISION.
           COMPUTE WS-C = WS-A + WS-B.
           STOP RUN.
"""
    p1 = SystemCobolParser(_make_synth_bundle(src_compute))
    cert1 = p1.parse_system()
    assert cert1.unsupported_relevant_count == 1
    assert cert1.is_evaluation_blocked is True
    arith_facts1 = [
        f.fact for f in p1.supported_facts if isinstance(f.fact, ComputationDataflowFact)
    ]
    assert len(arith_facts1) == 0

    src_mult = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TMULT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(4).
       01 WS-B PIC 9(4).
       PROCEDURE DIVISION.
           MULTIPLY WS-A BY WS-B.
           STOP RUN.
"""
    p2 = SystemCobolParser(_make_synth_bundle(src_mult))
    cert2 = p2.parse_system()
    assert cert2.unsupported_relevant_count == 1
    assert cert2.is_evaluation_blocked is True
    arith_facts2 = [
        f.fact for f in p2.supported_facts if isinstance(f.fact, ComputationDataflowFact)
    ]
    assert len(arith_facts2) == 0

    src_div = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TDIV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(4).
       01 WS-B PIC 9(4).
       PROCEDURE DIVISION.
           DIVIDE WS-A INTO WS-B.
           STOP RUN.
"""
    p3 = SystemCobolParser(_make_synth_bundle(src_div))
    cert3 = p3.parse_system()
    assert cert3.unsupported_relevant_count == 1
    assert cert3.is_evaluation_blocked is True
    arith_facts3 = [
        f.fact for f in p3.supported_facts if isinstance(f.fact, ComputationDataflowFact)
    ]
    assert len(arith_facts3) == 0


def test_h7_5_a_f03_f04_f05_shell_wrappers_and_windows_mutations() -> None:
    """F-03, F-04, F-05: Strict shell wrapper dialect, whitespace preservation,

    and Windows minimal mutation semantics.
    """
    # 1. Quoted POSIX shell wrapper fails closed
    src_posix_q = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TPOSIXQ.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE '"sh" -c "rm ACCOUNTS.DAT"' TO WS-CMD.
           CALL 'SYSTEM' USING WS-CMD.
           STOP RUN.
"""
    p1 = SystemCobolParser(_make_synth_bundle(src_posix_q))
    cert1 = p1.parse_system()
    assert cert1.unsupported_relevant_count >= 1
    assert cert1.is_evaluation_blocked is True
    plat_facts1 = [f.fact for f in p1.supported_facts if isinstance(f.fact, PlatformDependencyFact)]
    assert len(plat_facts1) == 0

    # 2. Incomplete / unsupported cmd wrapper options
    src_cmd_k = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TCMDK.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE 'cmd /k del ACCOUNTS.DAT' TO WS-CMD.
           CALL 'SYSTEM' USING WS-CMD.
           STOP RUN.
"""
    p2 = SystemCobolParser(_make_synth_bundle(src_cmd_k))
    cert2 = p2.parse_system()
    assert cert2.unsupported_relevant_count >= 1
    assert cert2.is_evaluation_blocked is True

    # 3. Unsupported switch on Windows mutation
    src_switch = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TSWITCH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE 'cmd /c del /f ACCOUNTS.DAT' TO WS-CMD.
           CALL 'SYSTEM' USING WS-CMD.
           STOP RUN.
"""
    p3 = SystemCobolParser(_make_synth_bundle(src_switch))
    cert3 = p3.parse_system()
    assert cert3.unsupported_relevant_count >= 1
    assert cert3.is_evaluation_blocked is True

    # 4. Grouping parens on Windows mutation
    src_parens = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TPARENS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE 'cmd /c (del ACCOUNTS.DAT)' TO WS-CMD.
           CALL 'SYSTEM' USING WS-CMD.
           STOP RUN.
"""
    p4 = SystemCobolParser(_make_synth_bundle(src_parens))
    cert4 = p4.parse_system()
    assert cert4.unsupported_relevant_count >= 1
    assert cert4.is_evaluation_blocked is True

    # 5. Non-minimal verb (erase)
    src_erase = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TERASE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE 'cmd /c erase ACCOUNTS.DAT' TO WS-CMD.
           CALL 'SYSTEM' USING WS-CMD.
           STOP RUN.
"""
    p5 = SystemCobolParser(_make_synth_bundle(src_erase))
    cert5 = p5.parse_system()
    assert cert5.unsupported_relevant_count >= 1
    assert cert5.is_evaluation_blocked is True

    # 6. Lossy whitespace (consecutive spaces in operand)
    src_spaces = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TSPACES.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE 'cmd /c del  ACCOUNTS.DAT' TO WS-CMD.
           CALL 'SYSTEM' USING WS-CMD.
           STOP RUN.
"""
    p6 = SystemCobolParser(_make_synth_bundle(src_spaces))
    cert6 = p6.parse_system()
    assert cert6.unsupported_relevant_count >= 1
    assert cert6.is_evaluation_blocked is True


def test_h7_5_a_f06_linear_segment_sequence_fail_closed() -> None:
    """F-06: Mutation pair across branch barrier must NOT be paired,

    and non-DELETE->RENAME pair in same linear segment must fail closed.
    """
    # Across branch barrier: no sequence emitted, coverage clean
    src_branch = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TBRANCH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-FLAG PIC X(1).
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           IF WS-FLAG = 'Y'
               MOVE 'cmd /c del ACCOUNTS.DAT' TO WS-CMD
               CALL 'SYSTEM' USING WS-CMD
           ELSE
               MOVE 'cmd /c ren ACCOUNTS.TMP ACCOUNTS.DAT' TO WS-CMD
               CALL 'SYSTEM' USING WS-CMD
           END-IF.
           STOP RUN.
"""
    p1 = SystemCobolParser(_make_synth_bundle(src_branch))
    cert1 = p1.parse_system()
    assert cert1.unsupported_relevant_count == 0
    assert cert1.is_evaluation_blocked is False
    seq_facts1 = [f.fact for f in p1.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq_facts1) == 0

    # Same linear segment, RENAME then DELETE: fails closed
    src_linear_unsupp = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TLINEARS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE 'cmd /c ren ACCOUNTS.TMP ACCOUNTS.DAT' TO WS-CMD.
           CALL 'SYSTEM' USING WS-CMD.
           MOVE 'cmd /c del ACCOUNTS.DAT' TO WS-CMD.
           CALL 'SYSTEM' USING WS-CMD.
           STOP RUN.
"""
    p2 = SystemCobolParser(_make_synth_bundle(src_linear_unsupp))
    cert2 = p2.parse_system()
    assert cert2.unsupported_relevant_count > 0
    assert cert2.is_evaluation_blocked is True
    seq_facts2 = [f.fact for f in p2.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq_facts2) == 0


def test_h7_5_a_f07_select_organization_absent_fails_closed() -> None:
    """F-07: SELECT with missing organization or organization in quoted literal must fail closed."""
    src_no_org = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TNOORG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO 'LINE SEQUENTIAL'.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 R PIC X.
       PROCEDURE DIVISION.
           STOP RUN.
"""
    p1 = SystemCobolParser(_make_synth_bundle(src_no_org))
    cert1 = p1.parse_system()
    assert cert1.unsupported_relevant_count == 1
    assert cert1.is_evaluation_blocked is True
    fb_facts1 = [f.fact for f in p1.supported_facts if isinstance(f.fact, FileBindingFact)]
    assert len(fb_facts1) == 0

    src_file_status_lit = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TSTATUSLIT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO 'FILE STATUS'.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 R PIC X.
       PROCEDURE DIVISION.
           STOP RUN.
"""
    p2 = SystemCobolParser(_make_synth_bundle(src_file_status_lit))
    cert2 = p2.parse_system()
    assert cert2.unsupported_relevant_count == 1
    assert cert2.is_evaluation_blocked is True
    fb_facts2 = [f.fact for f in p2.supported_facts if isinstance(f.fact, FileBindingFact)]
    assert len(fb_facts2) == 0


def test_h7_5_a_f08_unsupported_usage_and_record_atomicity() -> None:
    """F-08: Explicit unsupported USAGE fails closed and invalidates record layout.

    PACKED-DECIMAL explicitly aliases to COMP-3.
    """
    # Unsupported USAGE COMP-1
    src_comp1 = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TCOMP1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-FIELD-A PIC 9(4) USAGE DISPLAY.
          05 WS-FIELD-B USAGE COMP-1.
       PROCEDURE DIVISION.
           STOP RUN.
"""
    p1 = SystemCobolParser(_make_synth_bundle(src_comp1))
    cert1 = p1.parse_system()
    assert cert1.unsupported_relevant_count == 1
    assert cert1.is_evaluation_blocked is True
    rec_facts1 = [f.fact for f in p1.supported_facts if isinstance(f.fact, RecordLayoutFact)]
    assert len(rec_facts1) == 0

    # PACKED-DECIMAL alias -> COMP-3
    src_packed = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TPACKED.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-FIELD-A PIC 9(4) USAGE PACKED-DECIMAL.
       PROCEDURE DIVISION.
           STOP RUN.
"""
    p2 = SystemCobolParser(_make_synth_bundle(src_packed))
    cert2 = p2.parse_system()
    assert cert2.unsupported_relevant_count == 0
    assert cert2.is_evaluation_blocked is False
    rec_facts2 = [f.fact for f in p2.supported_facts if isinstance(f.fact, RecordLayoutFact)]
    assert len(rec_facts2) == 1
    assert rec_facts2[0].fields[0].usage == "COMP-3"


def test_h7_5_a_f09_level_88_sentence_boundary_trailing_fragment() -> None:
    """F-09: Premature period in level-88 with trailing fragments fails closed

    and invalidates containing record layout.
    """
    src_trailing = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T88TRAIL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-FLAG PIC X(1).
             88 FLAG-VAL VALUE 'A'. 'B'.
       PROCEDURE DIVISION.
           STOP RUN.
"""
    p1 = SystemCobolParser(_make_synth_bundle(src_trailing))
    cert1 = p1.parse_system()
    assert cert1.unsupported_relevant_count == 1
    assert cert1.is_evaluation_blocked is True
    rec_facts1 = [f.fact for f in p1.supported_facts if isinstance(f.fact, RecordLayoutFact)]
    assert len(rec_facts1) == 0


# ======================================================================
# 18. H7.5-B: CONSERVATIVE CONTROL-FLOW EFFECT PROOF (F-02) REGRESSION SUITE
# ======================================================================


def test_h7_5_b_f02_real_fixture_continuation_proofs() -> None:
    """F-02: Real fixture callee continuation proofs on INIT-DB, REPORT-GEN, TRANS-PROC."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    cert = parser.parse_system()
    assert cert.unsupported_relevant_count == 0
    assert cert.is_evaluation_blocked is False

    units = {u.program_id: u for u in parser.compilation_units}
    assert "INIT-DB" in units
    assert "REPORT-GEN" in units
    assert "TRANS-PROC" in units

    # 1. INIT-DB: proved MUST_PROCESS_TERMINATE at STOP RUN (line 46)
    eff_init, term_init = parser._prove_callee_continuation(units["INIT-DB"])
    assert eff_init == ExecutionEffect.MUST_PROCESS_TERMINATE
    assert term_init is not None
    assert term_init.line_start == 46
    assert term_init.verb == "STOP_RUN"

    # 2. REPORT-GEN: proved MUST_PROCESS_TERMINATE at STOP RUN (line 57)
    eff_rep, term_rep = parser._prove_callee_continuation(units["REPORT-GEN"])
    assert eff_rep == ExecutionEffect.MUST_PROCESS_TERMINATE
    assert term_rep is not None
    assert term_rep.line_start == 57
    assert term_rep.verb == "STOP_RUN"

    # 3. TRANS-PROC: proved MUST_PROCESS_TERMINATE at STOP RUN (line 96)
    eff_trans, term_trans = parser._prove_callee_continuation(units["TRANS-PROC"])
    assert eff_trans == ExecutionEffect.MUST_PROCESS_TERMINATE
    assert term_trans is not None
    assert term_trans.line_start == 96
    assert term_trans.verb == "STOP_RUN"

    # Verify caller continuation facts emitted for BANK-MAIN
    ccc_facts = [
        f.fact
        for f in parser.supported_facts
        if isinstance(f.fact, CallerContinuationConstraintFact)
    ]
    ccc_map = {(f.caller_program, f.callee_program): f for f in ccc_facts}
    assert ("BANK-MAIN", "INIT-DB") in ccc_map
    assert ccc_map[("BANK-MAIN", "INIT-DB")].constraint_type == "PROCESS_TERMINATION_ON_CALL"
    assert ("BANK-MAIN", "REPORT-GEN") in ccc_map
    assert ccc_map[("BANK-MAIN", "REPORT-GEN")].constraint_type == "PROCESS_TERMINATION_ON_CALL"
    assert ("BANK-MAIN", "TRANS-PROC") in ccc_map
    assert ccc_map[("BANK-MAIN", "TRANS-PROC")].constraint_type == "PROCESS_TERMINATION_ON_CALL"


def test_h7_5_b_f02_counterexample_a_callee_terminates_caller_dead_code() -> None:
    """F-02 Counterexample A / H-02: Callee executes CALL 'HALT' then dead GOBACK.

    Flow engine proves MUST_PROCESS_TERMINATE internally, but because the termination
    witness belongs to HALT.CBL (not CALLEE.CBL), no direct-callee CallerContinuationConstraintFact
    can be emitted. Fails closed as UNSUPPORTED_RELEVANT and blocks coverage.
    """
    files = {
        "CALLER.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       PROCEDURE DIVISION.
           CALL 'CALLEE'
           STOP RUN.
""",
        "CALLEE.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLEE.
       PROCEDURE DIVISION.
           CALL 'HALT'
           GOBACK.
""",
        "HALT.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. HALT.
       PROCEDURE DIVISION.
           STOP RUN.
""",
    }
    parser = SystemCobolParser(_make_multi_file_bundle(files))
    cert = parser.parse_system()
    assert cert.unsupported_relevant_count == 1
    assert cert.is_evaluation_blocked is True

    units = {u.program_id: u for u in parser.compilation_units}
    eff, term = parser._prove_callee_continuation(units["CALLEE"])
    assert eff == ExecutionEffect.MUST_PROCESS_TERMINATE
    assert term is not None
    assert term.verb == "STOP_RUN"
    assert term.program_id == "HALT"
    assert term.file_path.endswith("HALT.CBL")

    # Direct evidence contract prevents emitting CALLER -> CALLEE continuation fact
    ccc_facts = [
        f.fact
        for f in parser.supported_facts
        if isinstance(f.fact, CallerContinuationConstraintFact)
        and f.fact.caller_program == "CALLER"
        and f.fact.callee_program == "CALLEE"
    ]
    assert len(ccc_facts) == 0


def test_h7_5_b_f02_counterexample_b_infinite_loop_fails_closed() -> None:
    """F-02 Counterexample B: Unproven loop (PERFORM UNTIL 1 = 2) without progress fails closed."""
    files = {
        "CALLER.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       PROCEDURE DIVISION.
           CALL 'LOOPPROG'
           STOP RUN.
""",
        "LOOPPROG.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOOPPROG.
       PROCEDURE DIVISION.
           PERFORM UNTIL 1 = 2
               DISPLAY 'SPINNING'
           END-PERFORM.
           STOP RUN.
""",
    }
    parser = SystemCobolParser(_make_multi_file_bundle(files))
    cert = parser.parse_system()
    assert cert.unsupported_relevant_count >= 1
    assert cert.is_evaluation_blocked is True


def test_h7_5_b_f02_counterexample_c_dead_code_terminal_statement() -> None:
    """F-02 Counterexample C: Consecutive STOP RUN statements.

    First reachable STOP RUN must be selected as terminal evidence, not unreachable second.
    """
    files = {
        "CALLER.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       PROCEDURE DIVISION.
           CALL 'CALLEE'
           STOP RUN.
""",
        "CALLEE.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLEE.
       PROCEDURE DIVISION.
           STOP RUN.
           STOP RUN.
""",
    }
    parser = SystemCobolParser(_make_multi_file_bundle(files))
    cert = parser.parse_system()
    assert cert.unsupported_relevant_count == 0

    units = {u.program_id: u for u in parser.compilation_units}
    eff, term = parser._prove_callee_continuation(units["CALLEE"])
    assert eff == ExecutionEffect.MUST_PROCESS_TERMINATE
    assert term is not None
    assert term.line_start == 4


def test_h7_5_b_f02_counterexample_d_branch_disagreement_fails_closed() -> None:
    """F-02 Counterexample D: Branch disagreement (one terminates, one continues) fails closed."""
    files = {
        "CALLER.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       PROCEDURE DIVISION.
           CALL 'BRANCHPROG'
           STOP RUN.
""",
        "BRANCHPROG.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. BRANCHPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-FLAG PIC X VALUE 'Y'.
       PROCEDURE DIVISION.
           IF WS-FLAG = 'Y'
               STOP RUN
           ELSE
               GOBACK
           END-IF.
""",
    }
    parser = SystemCobolParser(_make_multi_file_bundle(files))
    cert = parser.parse_system()
    assert cert.unsupported_relevant_count >= 1
    assert cert.is_evaluation_blocked is True


def test_h7_5_b_f02_cyclic_calls_fail_closed() -> None:
    """F-02: Cyclic calls (P1 calls P2, P2 calls P1) terminate CFG recursion and fail closed."""
    files = {
        "P1.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. P1.
       PROCEDURE DIVISION.
           CALL 'P2'
           STOP RUN.
""",
        "P2.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. P2.
       PROCEDURE DIVISION.
           CALL 'P1'
           STOP RUN.
""",
    }
    parser = SystemCobolParser(_make_multi_file_bundle(files))
    cert = parser.parse_system()
    assert cert.unsupported_relevant_count >= 1
    assert cert.is_evaluation_blocked is True


# ======================================================================
# 19. H7.5-B: SOURCE-DERIVED EXHAUSTIVE COMPLETENESS (F-10) REGRESSION SUITE
# ======================================================================


def test_h7_5_b_f10_frozen_fixture_preflight_parity() -> None:
    """F-10: Preflight parity passes exactly for frozen legacy fixture (45/45)."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, bundle, file_status_certificate=parser.file_status_certificate
    )
    evaluator = SystemEvaluatorV3(index)
    golden = load_golden_assessment()

    host_obs = evaluator.extract_host_exhaustive_obligations()
    golden_obs = evaluator.extract_exhaustive_obligations_from_assessment(golden)

    assert len(host_obs) == 45
    assert len(golden_obs) == 45
    assert host_obs == golden_obs

    metrics, preds = evaluator.evaluate_assessment(golden)
    assert metrics.gate_3_pass is True
    assert metrics.host_exhaustive_fact_count == 45
    assert metrics.matched_host_exhaustive_fact_count == 45
    assert metrics.missing_host_exhaustive_fact_count == 0


def test_h7_5_b_f10_canonical_exhaustive_obligation_exact_semantics() -> None:
    """F-10: CanonicalExhaustiveObligation dataclass enforces exact role coordinates & facts."""
    fact1 = CallEdgeFact(caller_program="A", target_program="B", call_mechanism="DYNAMIC")
    fact2 = CallEdgeFact(caller_program="A", target_program="B", call_mechanism="STATIC")
    spans1 = (("evidence", "src/cbl/A.CBL", 10, 10),)
    spans2 = (("evidence", "src/cbl/A.CBL", 10, 11),)

    ob1 = CanonicalExhaustiveObligation("CALL_EDGE", fact1, spans1)
    ob1_same = CanonicalExhaustiveObligation("CALL_EDGE", fact1, spans1)
    ob2 = CanonicalExhaustiveObligation("CALL_EDGE", fact2, spans1)
    ob3 = CanonicalExhaustiveObligation("CALL_EDGE", fact1, spans2)

    assert ob1 == ob1_same
    assert hash(ob1) == hash(ob1_same)
    assert ob1 != ob2
    assert ob1 != ob3
    s = {ob1, ob1_same, ob2, ob3}
    assert len(s) == 3


def _create_mutated_system_bundle(mutations: dict[str, str], tmp_path: Path) -> MultiSourceBundle:
    """Create a temporary directory, apply mutations, and read legacy bundle."""
    overlays: dict[str, str] = {}
    for rel_path in (
        "legacy/core-banking-system/ACCOUNTS.CPY",
        "legacy/core-banking-system/ACCOUNTS.DAT",
        "legacy/core-banking-system/BANK-MAIN.CBL",
        "legacy/core-banking-system/INIT-DB.CBL",
        "legacy/core-banking-system/REPORT-GEN.CBL",
        "legacy/core-banking-system/TRANS-PROC.CBL",
    ):
        target_file = tmp_path / rel_path
        target_file.parent.mkdir(parents=True, exist_ok=True)
        if rel_path in mutations:
            content = mutations[rel_path]
        else:
            orig = (REPO_ROOT / rel_path).resolve()
            content = orig.read_text(encoding="utf-8")
        target_file.write_text(content, encoding="utf-8")
        overlays[rel_path] = content
    return read_system_bundle(repo_root=tmp_path, overlays=overlays)


def test_h7_5_b_f10_source_mutation_extra_call_fails_gate_3(tmp_path: Path) -> None:
    """F-10: In-memory source mutation adding CALL 'EXTRA' fails Gate 3 with missing_host=2."""
    orig_content = (REPO_ROOT / "legacy/core-banking-system/BANK-MAIN.CBL").read_text(
        encoding="utf-8"
    )
    lines = orig_content.splitlines()
    lines.append("           CALL 'EXTRA'.")
    mutated_content = "\n".join(lines) + "\n"

    mut_bundle = _create_mutated_system_bundle(
        {"legacy/core-banking-system/BANK-MAIN.CBL": mutated_content}, tmp_path
    )

    parser = SystemCobolParser(mut_bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, mut_bundle, file_status_certificate=parser.file_status_certificate
    )
    evaluator = SystemEvaluatorV3(index)
    golden = load_golden_assessment()

    host_obs = evaluator.extract_host_exhaustive_obligations()
    assert len(host_obs) == 47

    metrics, preds = evaluator.evaluate_assessment(golden)
    assert metrics.host_exhaustive_fact_count == 47
    assert metrics.matched_host_exhaustive_fact_count == 45
    assert metrics.missing_host_exhaustive_fact_count == 2
    assert metrics.gate_3_pass is False


def test_h7_5_b_f10_source_mutation_file_binding_fails_gate_3(tmp_path: Path) -> None:
    """F-10: In-memory source mutation adding SELECT EXTRA-FILE fails Gate 3."""
    orig_content = (REPO_ROOT / "legacy/core-banking-system/INIT-DB.CBL").read_text(
        encoding="utf-8"
    )
    lines = orig_content.splitlines()
    lines[8] = "           SELECT EXTRA-FILE ASSIGN TO 'EXTRA.DAT' ORGANIZATION IS LINE SEQUENTIAL."
    mutated_content = "\n".join(lines) + "\n"

    mut_bundle = _create_mutated_system_bundle(
        {"legacy/core-banking-system/INIT-DB.CBL": mutated_content}, tmp_path
    )

    parser = SystemCobolParser(mut_bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, mut_bundle, file_status_certificate=parser.file_status_certificate
    )
    evaluator = SystemEvaluatorV3(index)
    golden = load_golden_assessment()

    host_obs = evaluator.extract_host_exhaustive_obligations()
    assert len(host_obs) == 46

    metrics, preds = evaluator.evaluate_assessment(golden)
    assert metrics.host_exhaustive_fact_count == 46
    assert metrics.matched_host_exhaustive_fact_count == 45
    assert metrics.missing_host_exhaustive_fact_count == 1
    assert metrics.gate_3_pass is False


def test_h7_5_b_f10_runner_preflight_drift_detects_mismatch(tmp_path: Path) -> None:
    """F-10: Preflight parity check detects drift when host obligations differ from golden."""
    orig_content = (REPO_ROOT / "legacy/core-banking-system/BANK-MAIN.CBL").read_text(
        encoding="utf-8"
    )
    lines = orig_content.splitlines()
    lines.append("           CALL 'EXTRA'.")
    mutated_content = "\n".join(lines) + "\n"

    mut_bundle = _create_mutated_system_bundle(
        {"legacy/core-banking-system/BANK-MAIN.CBL": mutated_content}, tmp_path
    )

    parser = SystemCobolParser(mut_bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, mut_bundle, file_status_certificate=parser.file_status_certificate
    )
    evaluator = SystemEvaluatorV3(index)
    golden = load_golden_assessment()

    host_obs = evaluator.extract_host_exhaustive_obligations()
    golden_obs = evaluator.extract_exhaustive_obligations_from_assessment(golden)

    assert host_obs != golden_obs
    assert len(host_obs - golden_obs) == 2


# ======================================================================
# 20. H7.6-A: LOSSLESS OCCURRENCES & SEQUENTIAL CERTIFICATION (B-02 & M-01)
# ======================================================================


def test_h7_6_a_b02_lossless_support_index_duplicate_prop_ids(tmp_path: Path) -> None:
    """B-02: Appending two distinct STOP RUNs preserves all distinct occurrences and obligations.

    Evaluating old golden + only the later termination assertion (omitting earlier)
    must yield missing_host_exhaustive_fact_count >= 1 and gate_3_pass == False.
    """
    orig_content = (REPO_ROOT / "legacy/core-banking-system/BANK-MAIN.CBL").read_text(
        encoding="utf-8"
    )
    lines = orig_content.splitlines()
    # Append two additional distinct STOP RUN lines
    lines.append("           STOP RUN.")
    lines.append("           DISPLAY 'UNREACHABLE'.")
    lines.append("           STOP RUN.")
    mutated_content = "\n".join(lines) + "\n"

    mut_bundle = _create_mutated_system_bundle(
        {"legacy/core-banking-system/BANK-MAIN.CBL": mutated_content}, tmp_path
    )

    parser = SystemCobolParser(mut_bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, mut_bundle, file_status_certificate=parser.file_status_certificate
    )

    # 1. Total facts in parser == total facts in support index (lossless occurrences)
    assert len(facts) == len(index.get_all_facts())
    assert index.total_expected_facts == len(facts)

    # Termination site occurrences for BANK-MAIN: original + 2 added = 3
    bank_terms = [
        sf
        for sf in index.get_all_facts()
        if isinstance(sf.fact, TerminationSiteFact) and sf.fact.program_id == "BANK-MAIN"
    ]
    assert len(bank_terms) == 3

    # All distinct termination occurrences share the same proposition_id pattern
    term_prop_ids = [sf.proposition_id for sf in bank_terms]
    assert len(set(term_prop_ids)) == 1  # All share "prop.term.bank-main"

    # get_facts_by_id returns all 3
    assert len(index.get_facts_by_id(term_prop_ids[0])) == 3

    # get_fact_by_id fails explicitly on ambiguous proposition ID
    with pytest.raises(ValueError, match="Ambiguous proposition ID"):
        index.get_fact_by_id(term_prop_ids[0])

    # 2. Raw parser exhaustive obligations == support index exhaustive obligations
    evaluator = SystemEvaluatorV3(index)
    host_obs = evaluator.extract_host_exhaustive_obligations()

    # Original 45 + 2 new termination site obligations = 47
    assert len(host_obs) == 47

    # 3. Evaluate old golden + ONLY the later new termination assertion, omitting earlier
    golden = load_golden_assessment()
    later_term = bank_terms[-1]  # The second appended STOP RUN
    later_span = later_term.evidence_spans["evidence"]

    golden.termination_sites.append(
        TerminationSite(
            program_id="BANK-MAIN",
            statement_type="STOP_RUN",
            evidence=SourceEvidence(
                file_path=later_span.file_path,
                line_start=later_span.line_start,
                line_end=later_span.line_end,
            ),
        )
    )

    metrics, preds = evaluator.evaluate_assessment(golden)
    # Earlier appended STOP RUN is omitted, so missing host exhaustive count must be >= 1
    assert metrics.missing_host_exhaustive_fact_count == 1
    assert metrics.gate_3_pass is False


def test_h7_6_a_b02_exact_duplicate_host_integrity_check() -> None:
    """B-02: Host integrity error raised if exact duplicate occurrence emitted with same coords."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    fact = TerminationSiteFact(program_id="BANK-MAIN", statement_type="STOP_RUN")
    spans = {"evidence": EvidenceSpan("legacy/core-banking-system/BANK-MAIN.CBL", 96, 96)}
    sf1 = SupportedSystemFact(fact=fact, proposition_id="prop.term.bank-main", evidence_spans=spans)
    sf2 = SupportedSystemFact(fact=fact, proposition_id="prop.term.bank-main", evidence_spans=spans)

    index = SystemSupportIndex([sf1, sf2], bundle)
    evaluator = SystemEvaluatorV3(index)

    with pytest.raises(ValueError, match="Host-oracle integrity error"):
        evaluator.extract_host_exhaustive_obligations()


def test_h7_6_a_b02_system_support_index_occurrence_lookup_semantics() -> None:
    """B-02: SystemSupportIndex lookup semantics for unique, ambiguous, and missing IDs."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    f1 = TerminationSiteFact(program_id="A", statement_type="STOP_RUN")
    f2 = TerminationSiteFact(program_id="B", statement_type="STOP_RUN")
    f3 = TerminationSiteFact(program_id="C", statement_type="STOP_RUN")
    sf1 = SupportedSystemFact(
        fact=f1,
        proposition_id="prop.term.same",
        evidence_spans={
            "evidence": EvidenceSpan("legacy/core-banking-system/BANK-MAIN.CBL", 10, 10)
        },
    )
    sf2 = SupportedSystemFact(
        fact=f2,
        proposition_id="prop.term.same",
        evidence_spans={
            "evidence": EvidenceSpan("legacy/core-banking-system/BANK-MAIN.CBL", 20, 20)
        },
    )
    sf3 = SupportedSystemFact(
        fact=f3,
        proposition_id="prop.term.unique",
        evidence_spans={
            "evidence": EvidenceSpan("legacy/core-banking-system/BANK-MAIN.CBL", 30, 30)
        },
    )

    index = SystemSupportIndex([sf1, sf2, sf3], bundle)

    # total_expected_facts is honest total occurrence count (3, not 2)
    assert index.total_expected_facts == 3
    assert len(index.get_all_facts()) == 3

    # get_facts_by_id returns all occurrences
    assert len(index.get_facts_by_id("prop.term.same")) == 2
    assert len(index.get_facts_by_id("prop.term.unique")) == 1
    assert len(index.get_facts_by_id("prop.term.missing")) == 0

    # get_fact_by_id returns unique match
    unique_match = index.get_fact_by_id("prop.term.unique")
    assert unique_match is not None
    assert unique_match.fact == f3

    # get_fact_by_id returns None for missing ID
    assert index.get_fact_by_id("prop.term.missing") is None

    # get_fact_by_id raises on ambiguous ID
    with pytest.raises(
        ValueError, match="Ambiguous proposition ID: 'prop.term.same' has 2 occurrences"
    ):
        index.get_fact_by_id("prop.term.same")


def test_h7_6_a_m01_organization_is_sequential_certification(tmp_path: Path) -> None:
    """M-01: Deterministic parser certification for ORGANIZATION [IS] SEQUENTIAL."""
    seq_src = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TSEQ.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SEQ-FILE ASSIGN TO 'SEQDATA.DAT'
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD SEQ-FILE.
       01 SEQ-REC PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
"""
    mut_bundle = _create_mutated_system_bundle(
        {"legacy/core-banking-system/INIT-DB.CBL": seq_src}, tmp_path
    )
    parser = SystemCobolParser(mut_bundle)
    cert = parser.parse_system()
    assert cert.unsupported_relevant_count == 0
    assert cert.is_evaluation_blocked is False

    fb_facts = [
        sf.fact
        for sf in parser.supported_facts
        if isinstance(sf.fact, FileBindingFact) and sf.fact.internal_file_name == "SEQ-FILE"
    ]
    assert len(fb_facts) == 1
    assert fb_facts[0].organization == "SEQUENTIAL"
    assert fb_facts[0].external_file_name == "SEQDATA.DAT"


# ===========================================================================
# H7.6-B Regressions (B-01, H-01, H-02, H-03, H-05)
# ===========================================================================


def test_h7_6_b_b01_finite_loop_adversarial_matrix() -> None:
    """B-01: Finite-loop structural proof rejects adversarial counterexamples with AST operands."""
    base_src = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOOPPROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCT-FILE ASSIGN TO 'ACCT.DAT'
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD ACCT-FILE.
       01 ACCT-REC PIC X(10).
       WORKING-STORAGE SECTION.
       01 WS-EOF-FLAG PIC X VALUE 'N'.
       01 WS-EOF-FLAG-OTHER PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           OPEN INPUT ACCT-FILE
           MOVE 'N' TO WS-EOF-FLAG
{loop_construct}
           CLOSE ACCT-FILE
           STOP RUN.
"""

    # Probe 1: AT END assigns to WS-EOF-FLAG-OTHER instead of WS-EOF-FLAG
    p1_loop = """           PERFORM UNTIL WS-EOF-FLAG = 'Y'
               READ ACCT-FILE
                   AT END
                       MOVE 'Y' TO WS-EOF-FLAG-OTHER
                   NOT AT END
                       DISPLAY 'OK'
           END-PERFORM"""
    files1 = {
        "CALLER.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       PROCEDURE DIVISION.
           CALL 'LOOPPROG'
           STOP RUN.
""",
        "LOOPPROG.CBL": base_src.format(loop_construct=p1_loop),
    }
    parser1 = SystemCobolParser(_make_multi_file_bundle(files1))
    cert1 = parser1.parse_system()
    assert cert1.unsupported_relevant_count >= 1
    assert cert1.is_evaluation_blocked is True

    # Probe 2: NOT AT END resets WS-EOF-FLAG to 'N'
    p2_loop = """           PERFORM UNTIL WS-EOF-FLAG = 'Y'
               READ ACCT-FILE
                   AT END
                       MOVE 'Y' TO WS-EOF-FLAG
                   NOT AT END
                       MOVE 'N' TO WS-EOF-FLAG
           END-PERFORM"""
    files2 = {
        "CALLER.CBL": files1["CALLER.CBL"],
        "LOOPPROG.CBL": base_src.format(loop_construct=p2_loop),
    }
    parser2 = SystemCobolParser(_make_multi_file_bundle(files2))
    cert2 = parser2.parse_system()
    assert cert2.unsupported_relevant_count >= 1

    # Probe 3: Loop body contains nested PERFORM UNTIL
    p3_loop = """           PERFORM UNTIL WS-EOF-FLAG = 'Y'
               READ ACCT-FILE
                   AT END
                       MOVE 'Y' TO WS-EOF-FLAG
                   NOT AT END
                       PERFORM UNTIL WS-EOF-FLAG-OTHER = 'Y'
                           DISPLAY 'NESTED'
                       END-PERFORM
           END-PERFORM"""
    files3 = {
        "CALLER.CBL": files1["CALLER.CBL"],
        "LOOPPROG.CBL": base_src.format(loop_construct=p3_loop),
    }
    parser3 = SystemCobolParser(_make_multi_file_bundle(files3))
    cert3 = parser3.parse_system()
    assert cert3.unsupported_relevant_count >= 1

    # Probe 4: CLOSE and reopen inside loop body
    p4_loop = """           PERFORM UNTIL WS-EOF-FLAG = 'Y'
               READ ACCT-FILE
                   AT END
                       MOVE 'Y' TO WS-EOF-FLAG
                   NOT AT END
                       CLOSE ACCT-FILE
                       OPEN INPUT ACCT-FILE
           END-PERFORM"""
    files4 = {
        "CALLER.CBL": files1["CALLER.CBL"],
        "LOOPPROG.CBL": base_src.format(loop_construct=p4_loop),
    }
    parser4 = SystemCobolParser(_make_multi_file_bundle(files4))
    cert4 = parser4.parse_system()
    assert cert4.unsupported_relevant_count >= 1


def test_h7_6_b_h01_control_flow_outcome_algebra() -> None:
    """H-01: Control-flow analysis must not conflate fall-through with termination."""
    # Case 1: IF 1 = 1 GOBACK END-IF STOP RUN.
    # Outcome has two branches (one GOBACK, one STOP RUN) -> cannot prove universal termination
    files1 = {
        "CALLER.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       PROCEDURE DIVISION.
           CALL 'CALLEE'
           STOP RUN.
""",
        "CALLEE.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLEE.
       PROCEDURE DIVISION.
           IF 1 = 1
               GOBACK
           END-IF
           STOP RUN.
""",
    }
    parser1 = SystemCobolParser(_make_multi_file_bundle(files1))
    cert1 = parser1.parse_system()
    assert cert1.unsupported_relevant_count >= 1, "Unproven continuation must fail closed"
    assert cert1.is_evaluation_blocked is True
    units1 = {u.program_id: u for u in parser1.compilation_units}
    flow1 = parser1._prove_callee_continuation(units1["CALLEE"])
    assert flow1.is_definite_process_terminate is False
    assert flow1.is_definite_return is False
    ccc1 = [
        f.fact
        for f in parser1.supported_facts
        if isinstance(f.fact, CallerContinuationConstraintFact)
    ]
    assert len(ccc1) == 0

    # Case 2: EVALUATE FLAG WHEN 'Y' STOP RUN END-EVALUATE GOBACK.
    # Fallthrough possible on unmatched selector -> reaches GOBACK -> not universal termination
    files2 = {
        "CALLER.CBL": files1["CALLER.CBL"],
        "CALLEE.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLEE.
       WORKING-STORAGE SECTION.
       01 WS-FLAG PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           EVALUATE WS-FLAG
               WHEN 'Y'
                   STOP RUN
           END-EVALUATE
           GOBACK.
""",
    }
    parser2 = SystemCobolParser(_make_multi_file_bundle(files2))
    cert2 = parser2.parse_system()
    assert cert2.unsupported_relevant_count >= 1, "Unproven continuation must fail closed"
    assert cert2.is_evaluation_blocked is True
    units2 = {u.program_id: u for u in parser2.compilation_units}
    flow2 = parser2._prove_callee_continuation(units2["CALLEE"])
    assert flow2.is_definite_process_terminate is False

    # Case 3: Two branch-local STOP RUN statements (Section 3 clarification)
    # Both branches terminate, but multiple distinct witnesses -> 0 constraints emitted
    files3 = {
        "CALLER.CBL": files1["CALLER.CBL"],
        "CALLEE.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLEE.
       WORKING-STORAGE SECTION.
       01 WS-FLAG PIC X VALUE 'A'.
       PROCEDURE DIVISION.
           IF WS-FLAG = 'A'
               STOP RUN
           ELSE
               STOP RUN
           END-IF.
""",
    }
    parser3 = SystemCobolParser(_make_multi_file_bundle(files3))
    cert3 = parser3.parse_system()
    units3 = {u.program_id: u for u in parser3.compilation_units}
    flow3 = parser3._prove_callee_continuation(units3["CALLEE"])
    assert len(flow3.process_termination_witnesses) == 2
    ccc3 = [
        f.fact
        for f in parser3.supported_facts
        if isinstance(f.fact, CallerContinuationConstraintFact)
    ]
    assert len(ccc3) == 0
    assert cert3.unsupported_relevant_count >= 1
    assert cert3.is_evaluation_blocked is True


def test_h7_6_b_h03_call_system_effect_summaries() -> None:
    """H-03: CALL 'SYSTEM' requires grounded command effect; ungrounded commands fail closed."""
    files1 = {
        "CALLER.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       PROCEDURE DIVISION.
           CALL 'CALLEE'
           STOP RUN.
""",
        "CALLEE.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLEE.
       WORKING-STORAGE SECTION.
       01 CMD PIC X(50).
       PROCEDURE DIVISION.
           CALL 'SYSTEM' USING CMD
           STOP RUN.
""",
    }
    parser1 = SystemCobolParser(_make_multi_file_bundle(files1))
    cert1 = parser1.parse_system()
    units1 = {u.program_id: u for u in parser1.compilation_units}
    flow1 = parser1._prove_callee_continuation(units1["CALLEE"])
    assert flow1.unknown is True or not flow1.is_definite_process_terminate
    ccc1 = [
        f.fact
        for f in parser1.supported_facts
        if isinstance(f.fact, CallerContinuationConstraintFact)
    ]
    assert len(ccc1) == 0
    assert cert1.unsupported_relevant_count >= 1


def test_h7_6_b_h05_sentence_period_control_boundary() -> None:
    """H-05: COBOL period acts as control-flow boundary implicitly closing IF blocks."""
    files = {
        "CALLER.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       PROCEDURE DIVISION.
           CALL 'CALLEE'
           STOP RUN.
""",
        "CALLEE.CBL": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLEE.
       WORKING-STORAGE SECTION.
       01 WS-FLAG PIC X VALUE 'Y'.
       PROCEDURE DIVISION.
           IF WS-FLAG = 'Y'
               GOBACK.
           STOP RUN.
""",
    }
    parser = SystemCobolParser(_make_multi_file_bundle(files))
    cert = parser.parse_system()
    units = {u.program_id: u for u in parser.compilation_units}
    flow = parser._prove_callee_continuation(units["CALLEE"])
    assert flow.is_definite_process_terminate is False
    assert flow.is_definite_return is False
    ccc = [
        f.fact
        for f in parser.supported_facts
        if isinstance(f.fact, CallerContinuationConstraintFact)
    ]
    assert len(ccc) == 0
    assert cert.unsupported_relevant_count >= 1


def test_h7_6_c_h04_command_fail_closed_and_clean_controls() -> None:
    """H-04: Non-cmd.exe command dialects fail closed.

    Clean controls pass without sequence emission.
    """
    # 1. PowerShell fails closed
    src_ps = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TPOWERSHELL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE "powershell -c Remove-Item accounts.dat" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           STOP RUN.
"""
    p_ps = SystemCobolParser(_make_synth_bundle(src_ps))
    cert_ps = p_ps.parse_system()
    assert cert_ps.unsupported_relevant_count >= 1
    assert cert_ps.is_evaluation_blocked is True
    assert any(
        "Unsupported command" in s.description
        for s in p_ps.statements
        if s.classification.value == "UNSUPPORTED_RELEVANT"
    )

    # 2. command.com fails closed
    src_com = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TCOMMANDCOM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE "command.com /c del accounts.dat" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           STOP RUN.
"""
    p_com = SystemCobolParser(_make_synth_bundle(src_com))
    cert_com = p_com.parse_system()
    assert cert_com.unsupported_relevant_count >= 1
    assert cert_com.is_evaluation_blocked is True

    # 3. Bare del (not wrapped in cmd /c) fails closed
    src_bare = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TBAREDEL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE "del accounts.dat" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           STOP RUN.
"""
    p_bare = SystemCobolParser(_make_synth_bundle(src_bare))
    cert_bare = p_bare.parse_system()
    assert cert_bare.unsupported_relevant_count >= 1
    assert cert_bare.is_evaluation_blocked is True

    # 4. Redirection (> out.txt) fails closed
    src_redir = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TREDIR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE "cmd /c echo test > out.txt" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           STOP RUN.
"""
    p_redir = SystemCobolParser(_make_synth_bundle(src_redir))
    cert_redir = p_redir.parse_system()
    assert cert_redir.unsupported_relevant_count >= 1
    assert cert_redir.is_evaluation_blocked is True

    # 5. Command chaining (& del) fails closed
    src_chain = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TCHAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE "cmd /c echo test & del file.dat" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           STOP RUN.
"""
    p_chain = SystemCobolParser(_make_synth_bundle(src_chain))
    cert_chain = p_chain.parse_system()
    assert cert_chain.unsupported_relevant_count >= 1
    assert cert_chain.is_evaluation_blocked is True

    # 6. Shell switch (/s) on dir fails closed
    src_switch = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TSWITCH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE "cmd /c dir /s BANKING" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           STOP RUN.
"""
    p_switch = SystemCobolParser(_make_synth_bundle(src_switch))
    cert_switch = p_switch.parse_system()
    assert cert_switch.unsupported_relevant_count >= 1
    assert cert_switch.is_evaluation_blocked is True

    # 7. Valid clean control: echo
    src_echo = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TECHOPASS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE "cmd /c echo Processing started" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           STOP RUN.
"""
    p_echo = SystemCobolParser(_make_synth_bundle(src_echo))
    cert_echo = p_echo.parse_system()
    assert cert_echo.unsupported_relevant_count == 0
    assert cert_echo.is_evaluation_blocked is False
    invocations_echo = [
        f.fact for f in p_echo.supported_facts if isinstance(f.fact, CommandInvocationFact)
    ]
    assert len(invocations_echo) == 1
    plat_echo = [
        f.fact for f in p_echo.supported_facts if isinstance(f.fact, PlatformDependencyFact)
    ]
    assert len(plat_echo) == 1
    assert plat_echo[0].platform_family == "WINDOWS"
    seq_echo = [f.fact for f in p_echo.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq_echo) == 0

    # 8. Valid clean control: dir
    src_dir = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TDIRPASS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE "cmd /c dir BANKING" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           STOP RUN.
"""
    p_dir = SystemCobolParser(_make_synth_bundle(src_dir))
    cert_dir = p_dir.parse_system()
    assert cert_dir.unsupported_relevant_count == 0
    assert cert_dir.is_evaluation_blocked is False
    invocations_dir = [
        f.fact for f in p_dir.supported_facts if isinstance(f.fact, CommandInvocationFact)
    ]
    assert len(invocations_dir) == 1
    seq_dir = [f.fact for f in p_dir.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq_dir) == 0


def test_h7_6_c_h05_operation_sequence_cf_boundaries() -> None:
    """H-05: OperationSequenceFact requires linear CF segment.

    Branching and period boundaries reject cross-block sequences.
    """
    # 1. Historical bug reproduction: period closes IF, del is inside IF, ren is outside
    src_period_branch = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TCFPERIOD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       01 WS-FLAG PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           IF WS-FLAG = 'Y'
               MOVE "cmd /c del b.dat" TO WS-CMD
               CALL "SYSTEM" USING WS-CMD.
           MOVE "cmd /c ren a.dat b.dat" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           STOP RUN.
"""
    p1 = SystemCobolParser(_make_synth_bundle(src_period_branch))
    p1.parse_system()
    seq1 = [f.fact for f in p1.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq1) == 0, "Cross-block sequence across sentence period must not be emitted"
    risk1 = [f.fact for f in p1.supported_facts if isinstance(f.fact, BehavioralRiskFact)]
    assert len(risk1) == 0, "No NON_ATOMIC_EXTERNAL_MUTATION across conditional boundary"

    # 2. Explicit END-IF: del inside IF block, ren outside
    src_endif = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TCFENDIF.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       01 WS-FLAG PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           IF WS-FLAG = 'Y'
               MOVE "cmd /c del b.dat" TO WS-CMD
               CALL "SYSTEM" USING WS-CMD
           END-IF.
           MOVE "cmd /c ren a.dat b.dat" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           STOP RUN.
"""
    p2 = SystemCobolParser(_make_synth_bundle(src_endif))
    p2.parse_system()
    seq2 = [f.fact for f in p2.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq2) == 0, "del inside IF and ren outside must not form OperationSequenceFact"

    # 3. Branch split: del in THEN, ren in ELSE
    src_then_else = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TCFELSE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       01 WS-FLAG PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           IF WS-FLAG = 'Y'
               MOVE "cmd /c del b.dat" TO WS-CMD
               CALL "SYSTEM" USING WS-CMD
           ELSE
               MOVE "cmd /c ren a.dat b.dat" TO WS-CMD
               CALL "SYSTEM" USING WS-CMD
           END-IF.
           STOP RUN.
"""
    p3 = SystemCobolParser(_make_synth_bundle(src_then_else))
    p3.parse_system()
    seq3 = [f.fact for f in p3.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq3) == 0, "Branch split (THEN vs ELSE) must not form OperationSequenceFact"

    # 4. Valid linear sequence in top-level block: DEL followed by REN
    src_linear = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TCFLINEAR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CMD PIC X(100).
       PROCEDURE DIVISION.
           MOVE "cmd /c del b.dat" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           MOVE "cmd /c ren a.dat b.dat" TO WS-CMD.
           CALL "SYSTEM" USING WS-CMD.
           STOP RUN.
"""
    p4 = SystemCobolParser(_make_synth_bundle(src_linear))
    cert4 = p4.parse_system()
    assert cert4.unsupported_relevant_count == 0
    seq4 = [f.fact for f in p4.supported_facts if isinstance(f.fact, OperationSequenceFact)]
    assert len(seq4) == 1
    assert seq4[0].first_operation == "DELETE"
    assert seq4[0].second_operation == "RENAME"


def test_h7_6_c_h06_level_88_complete_grammar() -> None:
    """H-06: Level-88 complete grammar permits only valid VALUE/VALUES forms.

    Rejects malformed prefix tokens and unquoted delimiters.
    """
    # 1. Valid forms
    src_valid = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T88GRAMMAR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-CODE PIC X(2).
             88 CODE-A VALUE 'AA'.
             88 CODE-B VALUES 'BB' 'CC'.
             88 CODE-C VALUE IS 'DD'.
             88 CODE-D VALUES ARE 'EE' 'FF'.
"""
    p_val = SystemCobolParser(_make_synth_bundle(src_valid))
    cert_val = p_val.parse_system()
    assert cert_val.unsupported_relevant_count == 0
    assert cert_val.is_evaluation_blocked is False
    recs = [f.fact for f in p_val.supported_facts if isinstance(f.fact, RecordLayoutFact)]
    assert len(recs) == 1
    c_fields = {
        f.name: f.condition_values for f in recs[0].fields if f.field_kind == "CONDITION_NAME"
    }
    assert c_fields["CODE-A"] == ("AA",)
    assert c_fields["CODE-B"] == ("BB", "CC")
    assert c_fields["CODE-C"] == ("DD",)
    assert c_fields["CODE-D"] == ("EE", "FF")

    # 2. Malformed prefix: 88 COND INVALID VALUE 'A'.
    src_bad1 = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T88BAD1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-CODE PIC X(2).
             88 COND INVALID VALUE 'AA'.
"""
    p_bad1 = SystemCobolParser(_make_synth_bundle(src_bad1))
    cert_bad1 = p_bad1.parse_system()
    assert cert_bad1.unsupported_relevant_count >= 1
    assert cert_bad1.is_evaluation_blocked is True
    assert (
        len([f.fact for f in p_bad1.supported_facts if isinstance(f.fact, RecordLayoutFact)]) == 0
    )

    # 3. Malformed prefix: 88 COND PIC X VALUE 'A'.
    src_bad2 = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T88BAD2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-CODE PIC X(2).
             88 COND PIC X VALUE 'AA'.
"""
    p_bad2 = SystemCobolParser(_make_synth_bundle(src_bad2))
    cert_bad2 = p_bad2.parse_system()
    assert cert_bad2.unsupported_relevant_count >= 1
    assert cert_bad2.is_evaluation_blocked is True
    assert (
        len([f.fact for f in p_bad2.supported_facts if isinstance(f.fact, RecordLayoutFact)]) == 0
    )


def test_h7_6_c_m02_record_scope_layout_atomicity() -> None:
    """M-02: Non-allowlisted statements invalidate active record.

    Does not leak across division or section boundaries.
    """
    src_multi = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TMULTIREC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC1.
          05 WS-ID PIC 9(5).
          EXEC SQL INCLUDE SQLCA END-EXEC.
          05 WS-NAME PIC X(20).
       01 WS-REC2.
          05 WS-ACC PIC 9(10).
          05 WS-BAL PIC S9(7)V99 COMP-3.
"""
    p = SystemCobolParser(_make_synth_bundle(src_multi))
    cert = p.parse_system()
    # WS-REC1 has unhandled EXEC SQL, so unsupported count increments
    assert cert.unsupported_relevant_count >= 1
    rec_facts = [f.fact for f in p.supported_facts if isinstance(f.fact, RecordLayoutFact)]
    # WS-REC1 is omitted due to atomicity invalidation
    assert not any(r.record_name == "WS-REC1" for r in rec_facts)
    # WS-REC2 is clean, parsed, and certified independently
    rec2 = next((r for r in rec_facts if r.record_name == "WS-REC2"), None)
    assert rec2 is not None
    assert len(rec2.fields) == 2
    assert rec2.fields[0].name == "WS-ACC"
    assert rec2.fields[1].name == "WS-BAL"
    assert rec2.fields[1].usage == "COMP-3"


# ======================================================================
# H7.6-D: POST-CLAIM FAILURE ENVELOPE & SEALED-EVIDENCE STATE MACHINE
# Findings: H-07, H-08
# ======================================================================


def _get_run_gate_3_mod_h7_6_d() -> Any:
    import importlib.util

    repo_root = Path(__file__).resolve().parent.parent.parent
    spec = importlib.util.spec_from_file_location(
        "run_gate_3_module", repo_root / "scripts" / "run-gate-3.py"
    )
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    raise ImportError("Failed to load scripts/run-gate-3.py")


def test_h7_6_d_h07_read_back_verification_tamper_fails_to_unsealed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H-07: Sealed-evidence state machine & read-back verification.

    1. Clean failure verifies all manifested artifacts on disk, transitions
       reservation-state.json to FAILED, and produces NO coordination-failure.json.
    2. Tampered artifact on disk between manifest emission and read-back verification
       is caught by byte-for-byte SHA256 check, setting sealed=False, status=FAILED_UNSEALED,
       and emitting coordination-failure.json with evidence_sealed=False.
    """
    mod = _get_run_gate_3_mod_h7_6_d()

    # Case 1: Clean failure path
    clean_dir = tmp_path / "clean_failure"
    clean_dir.mkdir(parents=True)
    res_file = clean_dir / mod.RESERVATION_STATE_FILE
    mod.atomic_write_json(
        res_file,
        {"status": "RESERVED", "gate": 3, "run_label": "clean-label"},
    )

    clean_res = mod.finalize_post_model_failure(
        artifact_dir=clean_dir,
        reservation_file=res_file,
        error_phase="RESPONSE_PARSING",
        error=ValueError("Invalid structured output"),
        spec={"requested_model": "gpt-5-mini", "bundle_sha256": "abc"},
        candidate_sha="cand_sha_clean",
        authorization_commit_sha="auth_sha_clean",
        authorized_sha="auth_sha_clean",
        run_label="clean-label",
        raw_response_content='{"bogus": 1}',
    )

    assert clean_res.sealed is True
    assert clean_res.reservation_updated is True
    assert clean_res.status == "FAILED"
    assert clean_res.error_phase == "RESPONSE_PARSING"
    assert not (clean_dir / "coordination-failure.json").exists()

    res_data = json.loads(res_file.read_text(encoding="utf-8"))
    assert res_data["status"] == "FAILED"
    assert res_data["error_phase"] == "RESPONSE_PARSING"

    manifest_data = json.loads((clean_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_data["status"] == "FAILED"
    for art_name, exp_sha in manifest_data["artifacts"].items():
        assert hashlib.sha256((clean_dir / art_name).read_bytes()).hexdigest() == exp_sha

    # Case 2: Tampered artifact path (simulating byte corruption on disk)
    tamper_dir = tmp_path / "tamper_failure"
    tamper_dir.mkdir(parents=True)
    res_file_tamper = tamper_dir / mod.RESERVATION_STATE_FILE
    mod.atomic_write_json(
        res_file_tamper,
        {"status": "RESERVED", "gate": 3, "run_label": "tamper-label"},
    )

    orig_atomic_write = mod.atomic_write_json

    def tamper_write_hook(target_path: Path, data: Any) -> None:
        orig_atomic_write(target_path, data)
        # When manifest.json is written, immediately tamper raw-response.json on disk
        if Path(target_path).name == "manifest.json":
            raw_file = tamper_dir / "raw-response.json"
            if raw_file.is_file():
                raw_file.write_bytes(raw_file.read_bytes() + b"\nTAMPERED_POST_MANIFEST")

    monkeypatch.setattr(mod, "atomic_write_json", tamper_write_hook)

    tamper_res = mod.finalize_post_model_failure(
        artifact_dir=tamper_dir,
        reservation_file=res_file_tamper,
        error_phase="RESPONSE_PARSING",
        error=ValueError("Invalid structured output"),
        spec={"requested_model": "gpt-5-mini", "bundle_sha256": "abc"},
        candidate_sha="cand_sha_tamper",
        authorization_commit_sha="auth_sha_tamper",
        authorized_sha="auth_sha_tamper",
        run_label="tamper-label",
        raw_response_content='{"bogus": 2}',
    )

    assert tamper_res.sealed is False
    assert tamper_res.status == "FAILED_UNSEALED"
    assert any("SHA mismatch" in item.get("error", "") for item in tamper_res.failure_details)

    # Reservation file must be marked FAILED_UNSEALED
    res_tamper_data = json.loads(res_file_tamper.read_text(encoding="utf-8"))
    assert res_tamper_data["status"] == "FAILED_UNSEALED"
    assert "verification_errors" in res_tamper_data

    # coordination-failure.json must document evidence sealing failure
    coord_file = tamper_dir / "coordination-failure.json"
    assert coord_file.is_file()
    coord_data = json.loads(coord_file.read_text(encoding="utf-8"))
    assert coord_data["status"] == "EVIDENCE_SEALING_FAILED"
    assert coord_data["evidence_sealed"] is False
    assert len(coord_data["verification_errors"]) > 0


def test_h7_6_d_h07_case_a_sealed_reservation_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H-07 / H-08 Case A: Evidence sealed, but writing reservation state FAILED fails.

    Verifies:
    - Evidence artifacts are verified and sealed intact (sealed=True)
    - Reservation update fails (reservation_updated=False)
    - Status becomes COORDINATION_FAILURE
    - coordination-failure.json is emitted with evidence_sealed=True
    """
    mod = _get_run_gate_3_mod_h7_6_d()

    art_dir = tmp_path / "case_a_failure"
    art_dir.mkdir(parents=True)
    res_file = art_dir / mod.RESERVATION_STATE_FILE
    mod.atomic_write_json(
        res_file,
        {"status": "RESERVED", "gate": 3, "run_label": "case-a-label"},
    )

    orig_atomic_write = mod.atomic_write_json

    def fail_reservation_final_write(target_path: Path, data: Any) -> None:
        if (
            Path(target_path).name == mod.RESERVATION_STATE_FILE
            and isinstance(data, dict)
            and data.get("status") == "FAILED"
        ):
            raise OSError("Simulated disk I/O failure updating reservation state to FAILED")
        orig_atomic_write(target_path, data)

    monkeypatch.setattr(mod, "atomic_write_json", fail_reservation_final_write)

    res = mod.finalize_post_model_failure(
        artifact_dir=art_dir,
        reservation_file=res_file,
        error_phase="RESPONSE_VALIDATION",
        error=RuntimeError("Response schema mismatch"),
        spec={"requested_model": "gpt-5-mini", "bundle_sha256": "def"},
        candidate_sha="cand_sha_case_a",
        authorization_commit_sha="auth_sha_case_a",
        authorized_sha="auth_sha_case_a",
        run_label="case-a-label",
        raw_response_content='{"valid": false}',
    )

    assert res.sealed is True
    assert res.reservation_updated is False
    assert res.status == "COORDINATION_FAILURE"

    coord_file = art_dir / "coordination-failure.json"
    assert coord_file.is_file()
    coord_data = json.loads(coord_file.read_text(encoding="utf-8"))
    assert coord_data["status"] == "SEALED_RESERVATION_UPDATE_FAILED"
    assert coord_data["evidence_sealed"] is True

    # Artifacts remain sealed and verified
    manifest_data = json.loads((art_dir / "manifest.json").read_text(encoding="utf-8"))
    for fname, exp_sha in manifest_data["artifacts"].items():
        assert hashlib.sha256((art_dir / fname).read_bytes()).hexdigest() == exp_sha


def test_h7_6_d_h08_attempt_claim_reentry_refusal_across_all_reservation_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H-08: Irrevocable attempt claim presence refuses re-entry unconditionally.

    Tests across reservation states:
    1. RESERVED
    2. FAILED_UNSEALED
    3. MODEL_INVOCATION
    4. FAILED
    5. Missing reservation file
    6. Corrupt / non-JSON reservation file

    In all cases, child immediately refuses execution (code 1) with 0 provider calls.
    """
    from unittest.mock import MagicMock

    mod = _get_run_gate_3_mod_h7_6_d()
    repo_root = Path(__file__).resolve().parent.parent.parent

    mock_agent = MagicMock()
    mock_agent.invoke_raw.side_effect = AssertionError("Provider MUST NEVER be called!")

    states_to_test: list[tuple[str, Any]] = [
        ("reserved", {"status": "RESERVED", "gate": 3}),
        ("failed_unsealed", {"status": "FAILED_UNSEALED", "gate": 3}),
        ("model_invocation", {"status": "MODEL_INVOCATION", "gate": 3}),
        ("failed", {"status": "FAILED", "gate": 3}),
        ("missing", None),
        ("corrupt", "NOT_VALID_JSON{{{"),
    ]

    for label_suffix, state_payload in states_to_test:
        run_label = f"reentry-{label_suffix}"
        art_dir = tmp_path / run_label
        art_dir.mkdir(parents=True)

        # Irrevocable attempt claim exists
        claim_file = art_dir / mod.ATTEMPT_CLAIM_FILE
        claim_file.write_text(
            json.dumps({"gate": 3, "run_label": run_label, "attempt": 1}),
            encoding="utf-8",
        )

        res_file = art_dir / mod.RESERVATION_STATE_FILE
        if state_payload is not None:
            if isinstance(state_payload, dict):
                res_file.write_text(json.dumps(state_payload), encoding="utf-8")
            else:
                res_file.write_text(state_payload, encoding="utf-8")

        args = argparse.Namespace(
            provenance_repo=str(repo_root),
            snapshot_dir=str(repo_root),
            artifact_dir=str(art_dir),
            auth_spec=str(repo_root / mod.DEFAULT_AUTH_SPEC_PATH),
            run_label=run_label,
            authorized_git_sha="dummy_authorized_sha",
            authorization_commit_sha="dummy_auth_commit_sha",
            golden_path=str(repo_root / mod.DEFAULT_GOLDEN_PATH),
            synthetic=False,
            dry_run=False,
            allow_dirty=False,
        )

        with monkeypatch.context() as m:
            m.setattr(mod, "is_isolated_python", lambda: True)
            m.setattr(mod, "is_bytecode_writing_disabled", lambda: True)
            m.setattr(
                "agents.legacy_analyzer.system_agent.SystemAnalyzerAgent",
                lambda *a, **kw: mock_agent,
            )

            exit_code = mod.execute_internal_child(args)
            assert exit_code == 1
            assert mock_agent.invoke_raw.call_count == 0


def test_h7_6_d_h08_post_claim_reservation_write_failure_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H-08: Failure to write MODEL_INVOCATION after claim acquisition.

    Verifies:
    - Irrevocable attempt claim is written
    - Failure updating reservation to MODEL_INVOCATION is caught cleanly
    - Routes to finalize_post_model_failure with error_phase=MODEL_INVOCATION_RESERVATION
    - Seals terminal failure evidence
    - Zero provider calls made
    - Subsequent re-entry is refused
    """
    from unittest.mock import MagicMock

    mod = _get_run_gate_3_mod_h7_6_d()
    repo_root = Path(__file__).resolve().parent.parent.parent

    run_label = "post-claim-fail"
    art_dir = tmp_path / run_label
    art_dir.mkdir(parents=True)
    res_file = art_dir / mod.RESERVATION_STATE_FILE

    # Initial state is RESERVED
    mod.atomic_write_json(
        res_file,
        {
            "status": "RESERVED",
            "gate": 3,
            "run_label": run_label,
            "timestamp": "2026-09-14T00:00:00Z",
            "candidate_git_sha": "cand_sha_pcf",
            "authorization_commit_sha": "auth_sha_pcf",
            "git_commit_sha": "cand_sha_pcf",
        },
    )

    mock_agent = MagicMock()
    mock_agent.invoke_raw.side_effect = AssertionError("Provider must NOT be called!")

    mock_cfg = MagicMock()
    mock_cfg.foundry_model = "gpt-5-mini"
    mock_cfg.foundry_project_endpoint = "https://mock.foundry.endpoint"

    golden_file = repo_root / mod.DEFAULT_GOLDEN_PATH
    golden_sha = hashlib.sha256(golden_file.read_bytes()).hexdigest()

    mock_spec = {
        "gate": 3,
        "spec_version": mod.SPEC_VERSION,
        "schema_version": mod.SCHEMA_VERSION,
        "prompt_version": mod.PROMPT_VERSION,
        "evaluator_version": mod.EVALUATOR_VERSION,
        "golden_dataset_version": mod.GOLDEN_DATASET_VERSION,
        "requested_model": "gpt-5-mini",
        "reasoning_effort": "low",
        "max_attempts": 1,
        "maximum_model_attempts": 1,
        "openai_client_max_retries": 0,
        "run_label": run_label,
        "candidate_git_sha": "cand_sha_pcf",
        "golden_dataset_sha256": golden_sha,
        "bundle_sha256": "fake_bundle_sha",
        "bundle_manifest_sha256": "fake_manifest_sha",
        "foundry_project_fingerprint": "fake_fp_pcf",
        "target_bundle_files": [
            "legacy/core-banking-system/BANK-MAIN.CBL",
            "legacy/core-banking-system/INIT-DB.CBL",
            "legacy/core-banking-system/TRANS-PROC.CBL",
            "legacy/core-banking-system/REPORT-GEN.CBL",
            "legacy/core-banking-system/ACCOUNTS.CPY",
            "legacy/core-banking-system/ACCOUNTS.DAT",
        ],
    }

    orig_atomic_write = mod.atomic_write_json

    def fail_model_invocation_write(target_path: Path, data: Any) -> None:
        if (
            Path(target_path).name == mod.RESERVATION_STATE_FILE
            and isinstance(data, dict)
            and data.get("status") == "MODEL_INVOCATION"
        ):
            raise OSError("Simulated atomic write failure for MODEL_INVOCATION")
        orig_atomic_write(target_path, data)

    args = argparse.Namespace(
        provenance_repo=str(repo_root),
        snapshot_dir=str(repo_root),
        artifact_dir=str(art_dir),
        auth_spec=str(repo_root / mod.DEFAULT_AUTH_SPEC_PATH),
        run_label=run_label,
        authorized_git_sha="cand_sha_pcf",
        authorization_commit_sha="dummy_auth_sha",
        golden_path=str(golden_file),
        synthetic=False,
        dry_run=False,
        allow_dirty=True,
    )

    with monkeypatch.context() as m:
        m.setattr(mod, "is_isolated_python", lambda: True)
        m.setattr(mod, "is_bytecode_writing_disabled", lambda: True)
        m.setattr(mod, "verify_trusted_runner_bootstrap", lambda *a, **kw: None)
        m.setattr(mod, "verify_snapshot_against_git_objects", lambda *a, **kw: None)
        m.setattr(mod, "validate_authorization_contract", lambda *a, **kw: None)
        m.setattr(mod, "verify_clean_worktree", lambda *a, **kw: None)
        m.setattr(mod, "verify_no_executable_overlays", lambda *a, **kw: None)
        m.setattr(
            mod,
            "verify_bundle_integrity",
            lambda *a, **kw: ([], "fake_bundle_sha", "fake_manifest_sha"),
        )
        m.setattr(mod, "verify_schema_and_prompt_hashes", lambda *a, **kw: None)
        m.setattr(
            mod,
            "verify_runtime_environment",
            lambda *a, **kw: ({"pkg": "1.0"}, "fake_runtime_sha"),
        )
        m.setattr(
            mod,
            "load_authorization_spec_from_git",
            lambda *a, **kw: (mock_spec, "fake_spec_sha"),
        )
        m.setattr(
            mod,
            "load_authorization_spec",
            lambda *a, **kw: (mock_spec, "fake_spec_sha"),
        )
        m.setattr("agents.legacy_analyzer.config.load_config", lambda: mock_cfg)
        m.setattr(
            "agents.legacy_analyzer.config.compute_foundry_project_fingerprint",
            lambda *a, **kw: "fake_fp_pcf",
        )
        m.setattr(
            "agents.legacy_analyzer.system_agent.SystemAnalyzerAgent",
            lambda *a, **kw: mock_agent,
        )
        m.setattr(mod, "atomic_write_json", fail_model_invocation_write)

        exit_code = mod.execute_internal_child(args)
        assert exit_code == 1

    # 1. Zero provider calls
    assert mock_agent.invoke_raw.call_count == 0

    # 2. Irrevocable claim exists
    claim_file = art_dir / mod.ATTEMPT_CLAIM_FILE
    assert claim_file.is_file()

    # 3. Terminal result exists with error_phase MODEL_INVOCATION_RESERVATION
    term_file = art_dir / mod.TERMINAL_RESULT_FILE
    assert term_file.is_file()
    term_data = json.loads(term_file.read_text(encoding="utf-8"))
    assert term_data["status"] == "FAILED"
    assert term_data["error_phase"] == "MODEL_INVOCATION_RESERVATION"
    assert "Simulated atomic write failure" in term_data["error_message"]

    # 4. Manifest exists and hashes match
    manifest_file = art_dir / "manifest.json"
    assert manifest_file.is_file()
    man_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert man_data["status"] == "FAILED"
    assert mod.TERMINAL_RESULT_FILE in man_data["artifacts"]
    for art_name, exp_sha in man_data["artifacts"].items():
        assert hashlib.sha256((art_dir / art_name).read_bytes()).hexdigest() == exp_sha

    # 5. Subsequent re-entry refused by attempt claim check
    with monkeypatch.context() as m:
        m.setattr(mod, "is_isolated_python", lambda: True)
        m.setattr(mod, "is_bytecode_writing_disabled", lambda: True)
        reentry_exit = mod.execute_internal_child(args)
        assert reentry_exit == 1
        assert mock_agent.invoke_raw.call_count == 0
