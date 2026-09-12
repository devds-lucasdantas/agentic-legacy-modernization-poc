"""Round 3 Pre-ASTRA regression test suite.

Verifies:
1. Level-88 losslessness:
   - condition_values preserved in RecordField(field_kind='CONDITION_NAME')
   - condition name participates in full RecordLayout declaration identity/verification
   - non-storage: zero bytes, excluded from offsets and representation compatibility
   - mutation regression: changing an 88 VALUE changes RecordLayout identity/verification
     while leaving storage size and representation compatibility unchanged
2. FILE STATUS ownership:
   - FILE STATUS belongs to SELECT binding, not FD
   - whole-scope host certificate keyed by (program_id, internal_file_name)
   - BehavioralRisk(risk_basis_kind='MISSING_ERROR_STATUS') receives credit only when
     model explicitly asserted that basis, SELECT binding grounded, operations grounded,
     and host certificate proves absence
3. Parser coverage fail-closed:
   - explicit allowlists for PARSED_AND_SCORED and RECOGNIZED_BUT_UNSCORED
   - unsupported procedural statement triggers UNSUPPORTED_RELEVANT and preflight abort
4. Quote-aware parser:
   - DISPLAY 'STOP RUN' is parsed as DISPLAY, not TERMINATION_SITE
5. Generic WRITE -> FD resolution:
   - WRITE <record> correctly resolves to owning FD
6. FILE_OPERATION category policy:
   - OPTIONAL_SUPPLEMENTARY: 0 recall obligation, strict precision penalty on false predictions
7. OPERATION_SEQUENCE role-bound spans:
   - 4 distinct role-bound evidence spans verified
8. Wire schema leakage prevention:
   - no fixture-specific tokens (WS-CMD, CANONICAL_DATASET_UNAVAILABLE, etc.) in wire schema
"""

import json
from pathlib import Path

import pytest

from agents.legacy_analyzer.schemas.system_assessment import (
    FileOperation,
    SourceEvidence,
)
from agents.legacy_analyzer.schemas.system_export import get_system_openai_wire_schema
from src.cobol.multi_source_reader import (
    ALLOWED_SYSTEM_FILES,
    MultiSourceBundle,
    read_system_bundle,
)
from src.cobol.system_atomic_facts import (
    EvidenceSpan,
    FileOperationFact,
    RecordLayoutFact,
    RecordLayoutRelationFact,
    TerminationSiteFact,
)
from src.cobol.system_cobol_parser import (
    FileBindingStatusRecord,
    FileStatusCertificate,
    SystemCobolParser,
    parse_cobol_picture,
)
from src.cobol.system_support_index import SystemSupportIndex
from src.validation.evaluator_v3 import SystemEvaluatorV3, load_golden_assessment

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _build_oracle() -> tuple[SystemCobolParser, SystemSupportIndex, SystemEvaluatorV3]:
    """Construct deterministic AST parser, ground-truth support index, and evaluator."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()
    index = SystemSupportIndex(
        facts, bundle, file_status_certificate=parser.file_status_certificate
    )
    evaluator = SystemEvaluatorV3(index)
    return parser, index, evaluator


def _create_mutated_bundle(mutations: dict[str, str], tmp_path: Path) -> MultiSourceBundle:
    """Create a temporary directory, mutate source bytes, and read bundle."""
    overlays: dict[str, str] = {}
    for rel_path in ALLOWED_SYSTEM_FILES:
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


# ===========================================================================
# 1. LEVEL-88 LOSSLESSNESS AND NON-STORAGE INVARIANCE
# ===========================================================================


def test_level_88_fields_parsed_with_condition_values():
    """Verify level-88 condition names are parsed with condition_values."""
    parser, index, _ = _build_oracle()
    facts = parser.get_supported_facts()

    layout_facts = [f.fact for f in facts if isinstance(f.fact, RecordLayoutFact)]
    acct_rec = next((item for item in layout_facts if item.record_name == "ACCOUNT-RECORD"), None)
    assert acct_rec is not None

    fields = acct_rec.fields
    cond_fields = [f for f in fields if f.field_kind == "CONDITION_NAME"]
    assert len(cond_fields) == 3

    active_status = next((f for f in cond_fields if f.name == "ACC-ACTIVE"), None)
    assert active_status is not None
    assert active_status.level == 88
    assert active_status.condition_values == ("A",)

    closed_status = next((f for f in cond_fields if f.name == "ACC-CLOSED"), None)
    assert closed_status is not None
    assert closed_status.level == 88
    assert closed_status.condition_values == ("C",)

    susp_status = next((f for f in cond_fields if f.name == "ACC-SUSPENDED"), None)
    assert susp_status is not None
    assert susp_status.level == 88
    assert susp_status.condition_values == ("S",)

    # Verify storage size is exactly 56 bytes (sum of data fields, 88 fields have 0 bytes)
    storage_bytes = sum(
        parse_cobol_picture(f.picture)[0] for f in acct_rec.fields if f.field_kind == "DATA_FIELD"
    )
    assert storage_bytes == 56


def test_level_88_value_mutation_changes_layout_identity_leaves_storage_unchanged(tmp_path: Path):
    """REGRESSION REQUIRED:

    Changing an 88 VALUE must change full RecordLayout identity/verification
    while leaving storage size and representation compatibility unchanged.
    """
    orig_cpy = (REPO_ROOT / "legacy/core-banking-system/ACCOUNTS.CPY").read_text(encoding="utf-8")
    # Mutate 88 ACC-ACTIVE VALUE 'A' -> VALUE 'Z'
    mutated_cpy = orig_cpy.replace("VALUE 'A'", "VALUE 'Z'")
    bundle_mut = _create_mutated_bundle(
        {"legacy/core-banking-system/ACCOUNTS.CPY": mutated_cpy}, tmp_path
    )

    parser_orig, index_orig, evaluator_orig = _build_oracle()
    parser_mut = SystemCobolParser(bundle_mut)
    facts_mut = parser_mut.get_supported_facts()
    index_mut = SystemSupportIndex(
        facts_mut, bundle_mut, file_status_certificate=parser_mut.file_status_certificate
    )

    # 1. Full RecordLayout identity must change
    orig_layout = next(
        f.fact
        for f in parser_orig.get_supported_facts()
        if isinstance(f.fact, RecordLayoutFact) and f.fact.record_name == "ACCOUNT-RECORD"
    )
    mut_layout = next(
        f.fact
        for f in facts_mut
        if isinstance(f.fact, RecordLayoutFact) and f.fact.record_name == "ACCOUNT-RECORD"
    )

    assert orig_layout.get_semantic_key() != mut_layout.get_semantic_key()
    assert "COND(88:ACC-ACTIVE:[A])" in orig_layout.get_semantic_key()
    assert "COND(88:ACC-ACTIVE:[Z])" in mut_layout.get_semantic_key()

    # 2. Golden prediction with original 'A' value must FAIL verification against mutated index
    golden = load_golden_assessment()
    evaluator_mut = SystemEvaluatorV3(index_mut)
    res_mut, preds_mut = evaluator_mut.evaluate_assessment(golden)
    acct_pred = next(
        p
        for p in preds_mut
        if p.fact_category == "RECORD_LAYOUT" and "ACCOUNT-RECORD" in p.semantic_key
    )
    assert acct_pred.is_supported is False, (
        "RecordLayout with original 88 value must fail verification against mutated source"
    )

    # 3. Storage size must remain IDENTICAL (56 bytes)
    orig_storage = sum(
        parse_cobol_picture(f.picture)[0]
        for f in orig_layout.fields
        if f.field_kind == "DATA_FIELD"
    )
    mut_storage = sum(
        parse_cobol_picture(f.picture)[0] for f in mut_layout.fields if f.field_kind == "DATA_FIELD"
    )
    assert orig_storage == mut_storage == 56

    # 4. Storage representation compatibility between programs must remain IDENTICAL
    rel_orig = [
        f.fact
        for f in parser_orig.get_supported_facts()
        if isinstance(f.fact, RecordLayoutRelationFact)
    ]
    rel_mut = [f.fact for f in facts_mut if isinstance(f.fact, RecordLayoutRelationFact)]
    assert len(rel_orig) == len(rel_mut)
    for ro, rm in zip(rel_orig, rel_mut):
        assert ro.relation_type == rm.relation_type


# ===========================================================================
# 2. FILE STATUS OWNERSHIP AND BEHAVIORAL RISK
# ===========================================================================


def test_file_status_certificate_ownership_and_binding():
    """Verify FILE STATUS belongs to SELECT binding, not FD."""
    parser, index, _ = _build_oracle()
    cert = parser.file_status_certificate
    assert cert is not None

    # Keyed by (program_id, internal_file_name) for all SELECT declarations in bundle
    assert cert.binding_exists("INIT-DB", "ACCOUNT-FILE") is True
    assert cert.binding_exists("REPORT-GEN", "ACCOUNT-FILE") is True
    assert cert.binding_exists("TRANS-PROC", "ACCOUNT-FILE") is True
    assert cert.binding_exists("TRANS-PROC", "TEMP-FILE") is True

    # All files in this bundle lack FILE STATUS
    assert cert.has_status("INIT-DB", "ACCOUNT-FILE") is False
    assert cert.has_status("REPORT-GEN", "ACCOUNT-FILE") is False
    assert cert.has_status("TRANS-PROC", "ACCOUNT-FILE") is False
    assert cert.has_status("TRANS-PROC", "TEMP-FILE") is False


def test_behavioral_risk_missing_error_status_verification():
    """Verify BehavioralRisk(risk_basis_kind='MISSING_ERROR_STATUS') requires all 4 conditions."""
    _, index, evaluator = _build_oracle()
    golden = load_golden_assessment()

    # 1. Valid prediction passes
    res, preds = evaluator.evaluate_assessment(golden)
    tx_risk_pred = next(
        p
        for p in preds
        if p.fact_category == "BEHAVIORAL_RISK"
        and "TRANS-PROC" in p.semantic_key
        and "MISSING_ERROR_STATUS" in p.semantic_key
    )
    assert tx_risk_pred.is_supported is True

    # 2. Model asserting wrong basis receives NO credit
    bad_basis_assessment = golden.model_copy(deep=True)
    tx_risk = next(
        r
        for r in bad_basis_assessment.behavioral_risks
        if r.program_id == "TRANS-PROC"
        and r.risk_basis_kind == "MISSING_ERROR_STATUS"
        and r.affected_resource_evidence.line_start == 7
    )
    tx_risk.risk_basis_kind = "INVALID_INPUT_HANDLING"
    res_bad_basis, preds_bad_basis = evaluator.evaluate_assessment(bad_basis_assessment)
    bad_pred = next(
        p
        for p in preds_bad_basis
        if p.fact_category == "BEHAVIORAL_RISK"
        and "TRANS-PROC" in p.semantic_key
        and "INVALID_INPUT_HANDLING" in p.semantic_key
    )
    assert bad_pred.is_supported is False

    # 3. Model asserting ungrounded operation evidence receives NO credit
    bad_op_assessment = golden.model_copy(deep=True)
    tx_risk_op = next(
        r
        for r in bad_op_assessment.behavioral_risks
        if r.program_id == "TRANS-PROC"
        and r.risk_basis_kind == "MISSING_ERROR_STATUS"
        and r.affected_resource_evidence.line_start == 7
    )
    tx_risk_op.operation_evidence = SourceEvidence(
        file_path="legacy/core-banking-system/TRANS-PROC.CBL",
        line_start=1,
        line_end=2,
    )
    res_bad_op, preds_bad_op = evaluator.evaluate_assessment(bad_op_assessment)
    bad_op_pred = next(
        p
        for p in preds_bad_op
        if p.fact_category == "BEHAVIORAL_RISK"
        and "TRANS-PROC" in p.semantic_key
        and "MISSING_ERROR_STATUS" in p.semantic_key
    )
    assert bad_op_pred.is_supported is False


def test_behavioral_risk_rejected_if_file_status_present(tmp_path: Path):
    """Verify host certificate proves FILE STATUS presence and rejects MISSING_ERROR_STATUS risk."""
    orig_cbl = (REPO_ROOT / "legacy/core-banking-system/TRANS-PROC.CBL").read_text(encoding="utf-8")
    target = (
        "SELECT ACCOUNT-FILE ASSIGN TO 'ACCOUNTS.DAT'\n"
        "               ORGANIZATION IS LINE SEQUENTIAL."
    )
    assert target in orig_cbl
    replacement = (
        "SELECT ACCOUNT-FILE ASSIGN TO 'ACCOUNTS.DAT'\n"
        "               ORGANIZATION IS LINE SEQUENTIAL\n"
        "               FILE STATUS IS WS-STATUS."
    )
    mutated_cbl = orig_cbl.replace(target, replacement)
    assert mutated_cbl != orig_cbl
    bundle_mut = _create_mutated_bundle(
        {"legacy/core-banking-system/TRANS-PROC.CBL": mutated_cbl}, tmp_path
    )
    parser_mut = SystemCobolParser(bundle_mut)
    facts_mut = parser_mut.get_supported_facts()
    index_mut = SystemSupportIndex(
        facts_mut, bundle_mut, file_status_certificate=parser_mut.file_status_certificate
    )

    # Certificate should now record FILE STATUS present for TRANS-PROC ACCOUNT-FILE
    cert = parser_mut.file_status_certificate
    assert cert.has_status("TRANS-PROC", "ACCOUNT-FILE") is True

    # Golden risk asserting MISSING_ERROR_STATUS for ACCOUNT-FILE must be REJECTED
    golden = load_golden_assessment()
    evaluator_mut = SystemEvaluatorV3(index_mut)
    res_mut, preds_mut = evaluator_mut.evaluate_assessment(golden)
    tx_pred = next(
        p
        for p in preds_mut
        if p.fact_category == "BEHAVIORAL_RISK"
        and "TRANS-PROC" in p.semantic_key
        and "MISSING_ERROR_STATUS" in p.semantic_key
    )
    assert tx_pred.is_supported is False, (
        "MISSING_ERROR_STATUS must be rejected when FILE STATUS is declared"
    )


def test_certificate_contradictory_presence_rejects_missing_error_status():
    """Construct normal source facts with an intentionally contradictory certificate marking
    the relevant binding as FILE STATUS present.
    An otherwise perfectly grounded MISSING_ERROR_STATUS assertion MUST be rejected.
    """
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    normal_facts = parser.get_supported_facts()
    normal_cert = parser.file_status_certificate

    # Build contradictory certificate: duplicate bindings but flip has_file_status to True
    contradictory_bindings = {}
    for key, rec in normal_cert.bindings.items():
        contradictory_bindings[key] = FileBindingStatusRecord(
            program_id=rec.program_id,
            internal_file_name=rec.internal_file_name,
            has_file_status=True,  # Contradictory: claims FILE STATUS is present
            resource_span=rec.resource_span,
            operations_span=rec.operations_span,
        )
    contradictory_cert = FileStatusCertificate(bindings=contradictory_bindings)

    index = SystemSupportIndex(normal_facts, bundle, file_status_certificate=contradictory_cert)
    evaluator = SystemEvaluatorV3(index)
    golden = load_golden_assessment()
    res, preds = evaluator.evaluate_assessment(golden)

    # Every MISSING_ERROR_STATUS prediction must now be REJECTED because the certificate
    # claims FILE STATUS is declared.
    missing_status_preds = [
        p
        for p in preds
        if p.fact_category == "BEHAVIORAL_RISK" and "MISSING_ERROR_STATUS" in p.semantic_key
    ]
    assert len(missing_status_preds) > 0
    for p in missing_status_preds:
        assert p.is_supported is False, (
            f"Expected {p.semantic_key} to be rejected due to "
            "contradictory certificate, but got supported"
        )
        assert "FILE STATUS is declared" in (p.rejection_reason or "")


def test_certificate_missing_in_official_mode_raises_error():
    """SystemSupportIndex with file_status_certificate=None must raise an explicit RuntimeError
    when evaluating any MISSING_ERROR_STATUS assertion."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()

    index_no_cert = SystemSupportIndex(facts, bundle, file_status_certificate=None)
    evaluator = SystemEvaluatorV3(index_no_cert)
    golden = load_golden_assessment()

    with pytest.raises(RuntimeError) as exc_info:
        evaluator.evaluate_assessment(golden)
    assert "FileStatusCertificate is required" in str(exc_info.value)


def test_certificate_correct_absence_supported():
    """Verify that with the correct host absence certificate (has_file_status=False),
    all golden MISSING_ERROR_STATUS assertions are supported."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()

    index = SystemSupportIndex(
        facts, bundle, file_status_certificate=parser.file_status_certificate
    )
    evaluator = SystemEvaluatorV3(index)
    golden = load_golden_assessment()
    res, preds = evaluator.evaluate_assessment(golden)

    missing_status_preds = [
        p
        for p in preds
        if p.fact_category == "BEHAVIORAL_RISK" and "MISSING_ERROR_STATUS" in p.semantic_key
    ]
    assert len(missing_status_preds) == 3
    for p in missing_status_preds:
        assert p.is_supported is True, f"Expected {p.semantic_key} to be supported"


def test_certificate_wrong_binding_rejected():
    """Certificate missing the exact binding or with mismatched binding coordinates
    must reject the MISSING_ERROR_STATUS assertion."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()

    wrong_rec = FileBindingStatusRecord(
        program_id="UNRELATED-PROG",
        internal_file_name="UNRELATED-FILE",
        has_file_status=False,
        resource_span=EvidenceSpan(
            file_path="legacy/core-banking-system/TRANS-PROC.CBL",
            line_start=1,
            line_end=2,
        ),
        operations_span=None,
    )
    wrong_cert = FileStatusCertificate(bindings={("UNRELATED-PROG", "UNRELATED-FILE"): wrong_rec})

    index = SystemSupportIndex(facts, bundle, file_status_certificate=wrong_cert)
    evaluator = SystemEvaluatorV3(index)
    golden = load_golden_assessment()
    res, preds = evaluator.evaluate_assessment(golden)

    missing_status_preds = [
        p
        for p in preds
        if p.fact_category == "BEHAVIORAL_RISK" and "MISSING_ERROR_STATUS" in p.semantic_key
    ]
    assert len(missing_status_preds) > 0
    for p in missing_status_preds:
        assert p.is_supported is False, f"Expected {p.semantic_key} to be rejected"
        assert "Affected resource evidence does not match any known file binding" in (
            p.rejection_reason or ""
        )


# ===========================================================================
# 3. PARSER FAIL-CLOSED MUTATION
# ===========================================================================


def test_parser_fail_closed_on_unsupported_statement(tmp_path: Path):
    """Verify an unsupported statement triggers UNSUPPORTED_RELEVANT > 0."""
    orig_cbl = (REPO_ROOT / "legacy/core-banking-system/INIT-DB.CBL").read_text(encoding="utf-8")
    # Insert an unsupported procedural statement (INSPECT ... REPLACING ...)
    inspect_stmt = (
        "INSPECT WS-ACCOUNT-REC REPLACING ALL 'X' BY 'Y'.\n"
        "           DISPLAY 'Database initialized.'."
    )
    mutated_cbl = orig_cbl.replace(
        "DISPLAY 'Database initialized.'.",
        inspect_stmt,
    )
    bundle_mut = _create_mutated_bundle(
        {"legacy/core-banking-system/INIT-DB.CBL": mutated_cbl}, tmp_path
    )
    parser_mut = SystemCobolParser(bundle_mut)
    cert = parser_mut.parse_system()

    assert cert.unsupported_relevant_count > 0
    unsupported_items = [
        s
        for s in cert.per_statement_classifications
        if s["classification"] == "UNSUPPORTED_RELEVANT"
    ]
    assert len(unsupported_items) > 0
    assert unsupported_items[0]["verb"] == "INSPECT"


# ===========================================================================
# 4. QUOTE-AWARE PARSER
# ===========================================================================


def test_quote_aware_parser_display_with_stop_run(tmp_path: Path):
    """Verify DISPLAY 'STOP RUN' is classified as DISPLAY, not TERMINATION_SITE."""
    orig_cbl = (REPO_ROOT / "legacy/core-banking-system/INIT-DB.CBL").read_text(encoding="utf-8")
    mutated_cbl = orig_cbl.replace(
        "DISPLAY 'Database initialized.'.",
        "DISPLAY 'STOP RUN IN PROGRESS'.\n           DISPLAY 'Database initialized.'.",
    )
    bundle_mut = _create_mutated_bundle(
        {"legacy/core-banking-system/INIT-DB.CBL": mutated_cbl}, tmp_path
    )
    parser_mut = SystemCobolParser(bundle_mut)
    parser_mut.parse_system()
    facts = parser_mut.get_supported_facts()

    # The statement containing DISPLAY 'STOP RUN...' must NOT be emitted as a TerminationSiteFact
    term_facts = [
        f
        for f in facts
        if isinstance(f.fact, TerminationSiteFact) and f.fact.program_id == "INIT-DB"
    ]
    # In INIT-DB there is only 1 real termination site:
    # STOP RUN at line 46 (now line 47 due to insertion)
    assert len(term_facts) == 1
    assert term_facts[0].line_start == 47


# ===========================================================================
# 5. GENERIC WRITE -> FD RESOLUTION
# ===========================================================================


def test_write_statement_resolves_to_fd():
    """Verify WRITE <record> resolves to owning FD and emits FileOperationFact."""
    parser, index, _ = _build_oracle()
    facts = parser.get_supported_facts()

    file_ops = [f.fact for f in facts if isinstance(f.fact, FileOperationFact)]
    # In INIT-DB: WRITE ACCOUNT-REC -> FD ACCOUNT-FILE
    init_writes = [
        op for op in file_ops if op.program_id == "INIT-DB" and op.operation_verb == "WRITE"
    ]
    assert len(init_writes) == 3
    for w in init_writes:
        assert w.internal_file_name == "ACCOUNT-FILE"


# ===========================================================================
# 6. FILE_OPERATION CATEGORY POLICY (OPTIONAL_SUPPLEMENTARY)
# ===========================================================================


def test_file_operation_zero_recall_obligation_and_precision_penalty():
    """Verify FILE_OPERATION has 0 recall obligation but false predictions penalize precision."""
    _, index, evaluator = _build_oracle()
    golden = load_golden_assessment()

    # 1. Omitting all file_operations from assessment still achieves 100% recall and PASS
    no_file_ops = golden.model_copy(deep=True)
    no_file_ops.file_operations = []
    res_no_ops, _ = evaluator.evaluate_assessment(no_file_ops)
    assert res_no_ops.gate_3_pass is True
    assert res_no_ops.recall == 1.0
    assert res_no_ops.missing_expected_count == 0

    # 2. Adding a false/ungrounded file operation causes precision penalty and FAIL
    false_op = FileOperation(
        program_id="BANK-MAIN",
        internal_file_name="GHOST-FILE",
        operation_verb="READ",
        evidence=SourceEvidence(
            file_path="legacy/core-banking-system/BANK-MAIN.CBL",
            line_start=1,
            line_end=2,
        ),
    )
    with_false_op = golden.model_copy(deep=True)
    with_false_op.file_operations = [false_op]
    res_false, preds = evaluator.evaluate_assessment(with_false_op)
    assert res_false.unsupported_predicted_count >= 1
    assert res_false.precision < 1.0
    assert res_false.gate_3_pass is False, "False supplementary prediction must fail Gate 3"


# ===========================================================================
# 7. OPERATION_SEQUENCE ROLE-BOUND SPANS
# ===========================================================================


def test_operation_sequence_four_role_bound_spans():
    """Verify OperationSequence DELETE->RENAME requires 4 distinct valid role-bound spans."""
    _, index, evaluator = _build_oracle()
    golden = load_golden_assessment()

    seq = golden.operation_sequences[0]
    assert seq.first_operation == "DELETE"
    assert seq.second_operation == "RENAME"

    # All 4 spans must be distinct and valid
    spans = [
        seq.first_assignment_evidence,
        seq.first_call_evidence,
        seq.second_assignment_evidence,
        seq.second_call_evidence,
    ]
    assert len(spans) == 4
    for s in spans:
        assert s is not None
        assert s.line_start > 0
        assert s.line_end >= s.line_start

    # Verify all 4 spans pass evaluation
    res, preds = evaluator.evaluate_assessment(golden)
    seq_pred = next(p for p in preds if p.fact_category == "OPERATION_SEQUENCE")
    assert seq_pred.is_supported is True

    # Corrupting one span fails verification
    bad_assessment = golden.model_copy(deep=True)
    bad_assessment.operation_sequences[0].first_call_evidence = SourceEvidence(
        file_path="legacy/core-banking-system/TRANS-PROC.CBL",
        line_start=1,
        line_end=2,
    )
    res_bad, preds_bad = evaluator.evaluate_assessment(bad_assessment)
    seq_pred_bad = next(p for p in preds_bad if p.fact_category == "OPERATION_SEQUENCE")
    assert seq_pred_bad.is_supported is False


# ===========================================================================
# 8. WIRE SCHEMA LEAKAGE PREVENTION
# ===========================================================================


def test_wire_schema_has_no_fixture_leakage():
    """Assert WS-CMD and other specific tokens are absent from wire schema."""
    wire_schema = get_system_openai_wire_schema()
    wire_json = json.dumps(wire_schema)

    leaked_tokens = [
        "WS-CMD",
        "CANONICAL_DATASET_UNAVAILABLE",
        "UNCHECKED_IO_ERROR",
        "RUN_UNIT_ABORT",
    ]
    for token in leaked_tokens:
        assert token not in wire_json, f"Leaked token '{token}' found in wire schema"
