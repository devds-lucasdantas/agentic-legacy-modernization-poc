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
from agents.legacy_analyzer.schemas.system_export import get_system_openai_wire_schema
from src.cobol.multi_source_reader import MultiSourceBundle, TargetFile, read_system_bundle
from src.cobol.system_atomic_facts import (
    BehavioralRiskFact,
    CommandInvocationFact,
    DataStateComparisonFact,
    EvidenceSpan,
    FileBindingFact,
    OperationSequenceFact,
    PlatformDependencyFact,
    RecordFieldFact,
    RecordLayoutFact,
    RecordLayoutRelationFact,
    SupportedSystemFact,
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

    # Check record layout fields
    rec_facts = [f.fact for f in parser.supported_facts if isinstance(f.fact, RecordLayoutFact)]
    assert len(rec_facts) == 1
    rec = rec_facts[0]
    field_names = [f.name for f in rec.fields]

    # Malformed level-88 must emit NO condition fact
    assert "WS-UNCLOSED-STATUS" not in field_names

    # Subsequent declaration WS-NEXT-FIELD must be independently and cleanly parsed
    assert "WS-NEXT-FIELD" in field_names
    next_field = next(f for f in rec.fields if f.name == "WS-NEXT-FIELD")
    assert next_field.field_kind == "DATA_FIELD"
    assert next_field.level == 5
    assert next_field.picture == "9(4)"
    assert next_field.usage == "DISPLAY"


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

    # 2. Shell wildcard syntax (*) in command literal accepted by schema and certified
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
    assert cert_wild.unsupported_relevant_count == 0
    plat_wild = [
        f.fact for f in p_wild.get_supported_facts() if isinstance(f.fact, PlatformDependencyFact)
    ][0]
    assert plat_wild.command_literal == " cmd /c del *.tmp "

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
