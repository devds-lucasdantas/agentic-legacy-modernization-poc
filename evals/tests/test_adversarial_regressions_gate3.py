"""Adversarial regressions, weak controls, and real source-mutating counterfactual suite for Gate 3.

Adheres strictly to:
- Blocker 6: Real temporary source mutations (copy fixture to temp bundle -> mutate source bytes
  -> rerun parser -> rebuild host facts -> evaluate invariant against mutated source).
- Blocker 7: Independent positive oracle test; deletion of every required proposition fails;
  semantically false proposition fails; wrong occurrence fails; incomplete evidence roles fail;
  supplementary proposition handling; source counterfactuals cause oracle truth to change.
- Blocker 8: Categorical completeness semantics (REQUIRED COMPLETE vs SUPPLEMENTARY).
- Blocker 9: Role-bound multi-evidence coordinates for relational assertions.
"""

from copy import deepcopy
from pathlib import Path
from typing import Any

from agents.legacy_analyzer.schemas.system_assessment import (
    CallEdge,
    InternalCallResolution,
    ProgramDeclaration,
    SourceEvidence,
    SystemAssessment,
)
from src.cobol.multi_source_reader import (
    ALLOWED_SYSTEM_FILES,
    MultiSourceBundle,
    read_system_bundle,
)
from src.cobol.system_atomic_facts import (
    CallEdgeFact,
    CallerContinuationConstraintFact,
    CallOccurrenceFact,
    CommandInvocationFact,
    FileBindingFact,
    InternalCallResolutionFact,
    RecordLayoutFact,
    RecordLayoutRelationFact,
    TerminationSiteFact,
)
from src.cobol.system_cobol_parser import SystemCobolParser
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


def _create_mutated_source_bundle(mutations: dict[str, str], tmp_path: Path) -> MultiSourceBundle:
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
# BLOCKER 7: Independent Positive Oracle Test
# ===========================================================================


def test_independent_golden_positive_oracle_pass():
    """Verify independently authored frozen golden dataset achieves 100% precision, recall, PASS."""
    _, _, evaluator = _build_oracle()
    golden_assessment = load_golden_assessment()

    metrics, predictions = evaluator.evaluate_assessment(golden_assessment)

    assert metrics.gate_3_pass is True
    assert metrics.expected_fact_count == 60
    assert metrics.matched_expected_count == 60
    assert metrics.missing_expected_count == 0
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.unsupported_predicted_count == 0
    assert metrics.invalid_evidence_count == 0
    assert metrics.duplicate_prediction_count == 0
    assert metrics.contradiction_count == 0
    assert len(predictions) == 60
    assert all(p.is_supported for p in predictions)


# ===========================================================================
# BLOCKER 7: Deletion of Every Required Proposition Causes FAIL
# ===========================================================================


def test_deletion_of_each_required_proposition_causes_fail():
    """Verify that omitting ANY single required proposition causes recall < 1.0 and FAIL."""
    _, _, evaluator = _build_oracle()
    base_assessment = load_golden_assessment()

    # Test deleting one item from each collection
    collections: list[tuple[str, list[Any]]] = [
        ("program_declarations", base_assessment.program_declarations),
        ("call_occurrences", base_assessment.call_occurrences),
        ("call_edges", base_assessment.call_edges),
        ("internal_call_resolutions", base_assessment.internal_call_resolutions),
        ("file_bindings", base_assessment.file_bindings),
        ("record_layouts", base_assessment.record_layouts),
        ("record_layout_relations", base_assessment.record_layout_relations),
        ("termination_sites", base_assessment.termination_sites),
        ("caller_continuation_constraints", base_assessment.caller_continuation_constraints),
        ("command_invocations", base_assessment.command_invocations),
        ("data_transfer_relations", base_assessment.data_transfer_relations),
        ("resource_lifecycles", base_assessment.resource_lifecycles),
        ("operation_sequences", base_assessment.operation_sequences),
        ("computation_dataflows", base_assessment.computation_dataflows),
        ("platform_dependencies", base_assessment.platform_dependencies),
        ("behavioral_risks", base_assessment.behavioral_risks),
        ("data_state_comparisons", base_assessment.data_state_comparisons),
    ]

    for name, coll in collections:
        for idx in range(len(coll)):
            assessment_copy = deepcopy(base_assessment)
            target_list = getattr(assessment_copy, name)
            removed = target_list.pop(idx)

            metrics, _ = evaluator.evaluate_assessment(assessment_copy)
            assert metrics.gate_3_pass is False, (
                f"Deleting item {idx} from {name} ({removed}) must cause FAIL!"
            )
            assert metrics.missing_expected_count >= 1
            assert metrics.recall < 1.0


# ===========================================================================
# BLOCKER 7: Semantically False Proposition with Valid Coordinates Causes FAIL
# ===========================================================================


def test_semantically_false_proposition_causes_fail():
    """Verify that predicting a non-existent unit at valid coordinates causes FAIL."""
    _, _, evaluator = _build_oracle()
    assessment = load_golden_assessment()

    # Inject a false program declaration at valid source coordinates
    false_decl = ProgramDeclaration(
        program_id="FAKE-UNIT",
        evidence=SourceEvidence(
            file_path="legacy/core-banking-system/BANK-MAIN.CBL",
            line_start=1,
            line_end=2,
        ),
    )
    assessment.program_declarations.append(false_decl)

    metrics, _ = evaluator.evaluate_assessment(assessment)
    assert metrics.gate_3_pass is False
    assert metrics.unsupported_predicted_count >= 1
    assert metrics.precision < 1.0


# ===========================================================================
# BLOCKER 7: Correct Relationship with Wrong Occurrence Causes FAIL
# ===========================================================================


def test_correct_relationship_with_wrong_occurrence_causes_fail():
    """Verify that correct call target with wrong line coordinates causes FAIL."""
    _, _, evaluator = _build_oracle()
    assessment = load_golden_assessment()

    # Replace BANK-MAIN -> INIT-DB (line 24) with wrong line 27 (which is TRANS-PROC)
    for c in assessment.call_occurrences:
        if c.caller_program == "BANK-MAIN" and c.target_program == "INIT-DB":
            c.evidence = SourceEvidence(
                file_path="legacy/core-banking-system/BANK-MAIN.CBL",
                line_start=27,
                line_end=27,
            )
            break

    metrics, _ = evaluator.evaluate_assessment(assessment)
    assert metrics.gate_3_pass is False
    assert metrics.unsupported_predicted_count >= 1


# ===========================================================================
# BLOCKER 9: Correct Endpoints with Incomplete / Wrong Evidence Roles
# ===========================================================================


def test_internal_call_resolution_wrong_target_declaration_evidence_causes_fail():
    """Verify InternalCallResolution fails if target_declaration_evidence is wrong."""
    _, _, evaluator = _build_oracle()
    assessment = load_golden_assessment()

    for r in assessment.internal_call_resolutions:
        if r.caller_program == "BANK-MAIN" and r.callee_program == "INIT-DB":
            # Point to line 10 (ENVIRONMENT DIVISION) instead of line 2 (PROGRAM-ID)
            r.target_declaration_evidence = SourceEvidence(
                file_path="legacy/core-banking-system/INIT-DB.CBL",
                line_start=10,
                line_end=10,
            )
            break

    metrics, _ = evaluator.evaluate_assessment(assessment)
    assert metrics.gate_3_pass is False
    assert metrics.unsupported_predicted_count >= 1


def test_record_layout_relation_wrong_evidence_a_causes_fail():
    """Verify RecordLayoutRelation fails if evidence_a is wrong."""
    _, _, evaluator = _build_oracle()
    assessment = load_golden_assessment()

    # Corrupt evidence_a for the first layout relation
    rel = assessment.record_layout_relations[0]
    rel.evidence_a = SourceEvidence(
        file_path=rel.evidence_a.file_path,
        line_start=1,
        line_end=1,
    )

    metrics, _ = evaluator.evaluate_assessment(assessment)
    assert metrics.gate_3_pass is False
    assert metrics.unsupported_predicted_count >= 1


def test_caller_continuation_wrong_callee_termination_evidence_causes_fail():
    """Verify CallerContinuationConstraint fails if callee_termination_evidence is wrong."""
    _, _, evaluator = _build_oracle()
    assessment = load_golden_assessment()

    con = assessment.caller_continuation_constraints[0]
    con.callee_termination_evidence = SourceEvidence(
        file_path=con.callee_termination_evidence.file_path,
        line_start=1,
        line_end=1,
    )

    metrics, _ = evaluator.evaluate_assessment(assessment)
    assert metrics.gate_3_pass is False
    assert metrics.unsupported_predicted_count >= 1


def test_command_invocation_wrong_assignment_evidence_causes_fail():
    """Verify CommandInvocation fails if assignment_evidence is wrong."""
    _, _, evaluator = _build_oracle()
    assessment = load_golden_assessment()

    cmd = assessment.command_invocations[0]
    cmd.assignment_evidence = SourceEvidence(
        file_path=cmd.assignment_evidence.file_path,
        line_start=1,
        line_end=1,
    )

    metrics, _ = evaluator.evaluate_assessment(assessment)
    assert metrics.gate_3_pass is False
    assert metrics.unsupported_predicted_count >= 1


def test_behavioral_risk_wrong_affected_resource_evidence_causes_fail():
    """Verify BehavioralRisk fails if affected_resource_evidence is wrong."""
    _, _, evaluator = _build_oracle()
    assessment = load_golden_assessment()

    risk = assessment.behavioral_risks[0]
    risk.affected_resource_evidence = SourceEvidence(
        file_path=risk.affected_resource_evidence.file_path,
        line_start=1,
        line_end=1,
    )

    metrics, _ = evaluator.evaluate_assessment(assessment)
    assert metrics.gate_3_pass is False
    assert metrics.unsupported_predicted_count >= 1


def test_data_state_comparison_wrong_initializer_evidence_causes_fail():
    """Verify DataStateComparison fails if initializer_evidence is wrong."""
    _, _, evaluator = _build_oracle()
    assessment = load_golden_assessment()

    cmp_fact = assessment.data_state_comparisons[0]
    cmp_fact.initializer_evidence = SourceEvidence(
        file_path=cmp_fact.initializer_evidence.file_path,
        line_start=1,
        line_end=1,
    )

    metrics, _ = evaluator.evaluate_assessment(assessment)
    assert metrics.gate_3_pass is False
    assert metrics.unsupported_predicted_count >= 1


# ===========================================================================
# BLOCKER 8: Supplementary Proposition Policy
# ===========================================================================


def test_duplicate_propositions_flagged_without_inflating_recall():
    """Verify that duplicate assertions increment duplicate count and do not corrupt recall."""
    _, _, evaluator = _build_oracle()
    assessment = load_golden_assessment()

    # Append an exact duplicate of the first program declaration
    assessment.program_declarations.append(assessment.program_declarations[0])

    metrics, _ = evaluator.evaluate_assessment(assessment)
    assert metrics.duplicate_prediction_count == 1
    assert metrics.raw_predicted_count == 61
    assert metrics.unique_predicted_count == 60
    assert metrics.matched_expected_count == 60
    assert metrics.recall == 1.0
    assert metrics.gate_3_pass is False


# ===========================================================================
# Weak Controls: Source-Blind and Lexical-Only
# ===========================================================================


def test_weak_source_blind_control_fails():
    """Verify that a hallucinated source-blind assessment is 100% rejected."""
    _, _, evaluator = _build_oracle()

    blind_assessment = SystemAssessment(
        system_name="Generic System",
        program_declarations=[
            ProgramDeclaration(
                program_id="LEDGER-MAIN",
                evidence=SourceEvidence(
                    file_path="legacy/core-banking-system/BANK-MAIN.CBL",
                    line_start=1,
                    line_end=2,
                ),
            ),
            ProgramDeclaration(
                program_id="PAYROLL-EXEC",
                evidence=SourceEvidence(
                    file_path="legacy/core-banking-system/INIT-DB.CBL",
                    line_start=1,
                    line_end=2,
                ),
            ),
        ],
        call_edges=[
            CallEdge(
                caller_program="LEDGER-MAIN",
                target_program="PAYROLL-EXEC",
                call_mechanism="DYNAMIC_TARGET",
                evidence=SourceEvidence(
                    file_path="legacy/core-banking-system/BANK-MAIN.CBL",
                    line_start=1,
                    line_end=2,
                ),
            )
        ],
    )

    metrics, _ = evaluator.evaluate_assessment(blind_assessment)
    assert metrics.gate_3_pass is False
    assert metrics.precision == 0.0
    assert metrics.supported_predicted_count == 0
    assert metrics.unsupported_predicted_count == 3


def test_weak_lexical_only_control_inverted_relationship_fails():
    """Verify that lexically present identifiers with inverted semantic relationship fail."""
    _, _, evaluator = _build_oracle()
    assessment = load_golden_assessment()

    # Invert caller and callee in InternalCallResolution: INIT-DB -> BANK-MAIN
    assessment.internal_call_resolutions = [
        InternalCallResolution(
            caller_program="INIT-DB",
            callee_program="BANK-MAIN",
            call_evidence=SourceEvidence(
                file_path="legacy/core-banking-system/BANK-MAIN.CBL",
                line_start=24,
                line_end=24,
            ),
            target_declaration_evidence=SourceEvidence(
                file_path="legacy/core-banking-system/BANK-MAIN.CBL",
                line_start=2,
                line_end=2,
            ),
        )
    ]

    metrics, _ = evaluator.evaluate_assessment(assessment)
    assert metrics.gate_3_pass is False
    assert metrics.unsupported_predicted_count >= 1


# ===========================================================================
# BLOCKER 6: Real Source Counterfactual Suite (11 Mutated Source Bundles)
# ===========================================================================


def test_cf1_stop_run_to_goback(tmp_path: Path):
    """CF 1: Mutate INIT-DB.CBL STOP RUN. -> GOBACK.

    Verifies:
    - TerminationSiteFact("INIT-DB", "GOBACK") is generated.
    - TerminationSiteFact("INIT-DB", "STOP_RUN") is eliminated.
    - Caller continuation for BANK-MAIN -> INIT-DB becomes RETURN_TO_CALLER.
    """
    orig = (REPO_ROOT / "legacy/core-banking-system/INIT-DB.CBL").read_text(encoding="utf-8")
    mutated = orig.replace("STOP RUN.", "GOBACK.")

    bundle = _create_mutated_source_bundle(
        {"legacy/core-banking-system/INIT-DB.CBL": mutated}, tmp_path
    )
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()

    term_facts = [f.fact for f in facts if isinstance(f.fact, TerminationSiteFact)]
    goback_fact = next(
        (f for f in term_facts if f.program_id == "INIT-DB" and f.statement_type == "GOBACK"), None
    )
    assert goback_fact is not None

    stop_fact = next(
        (f for f in term_facts if f.program_id == "INIT-DB" and f.statement_type == "STOP_RUN"),
        None,
    )
    assert stop_fact is None

    continuation_facts = [
        f.fact for f in facts if isinstance(f.fact, CallerContinuationConstraintFact)
    ]
    con = next(
        (
            f
            for f in continuation_facts
            if f.caller_program == "BANK-MAIN" and f.callee_program == "INIT-DB"
        ),
        None,
    )
    assert con is not None
    assert con.constraint_type == "RETURN_TO_CALLER"


def test_cf2_comp3_to_display_layout_equivalence(tmp_path: Path):
    """CF 2: Mutate ACCOUNTS.CPY COMP-3. -> DISPLAY.

    Verifies:
    - ACCOUNTS:ACCOUNT-RECORD layout changes storage_format to DISPLAY.
    - Layout relation to INIT-DB:ACCOUNT-REC changes from REPRESENTATION_MISMATCH to EQUIVALENT.
    """
    orig = (REPO_ROOT / "legacy/core-banking-system/ACCOUNTS.CPY").read_text(encoding="utf-8")
    mutated = orig.replace("COMP-3.", "DISPLAY.")

    bundle = _create_mutated_source_bundle(
        {"legacy/core-banking-system/ACCOUNTS.CPY": mutated}, tmp_path
    )
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()

    rec_facts = [f.fact for f in facts if isinstance(f.fact, RecordLayoutFact)]
    cpy_rec = next((f for f in rec_facts if f.program_id == "ACCOUNTS"), None)
    assert cpy_rec is not None
    assert any(f.name == "ACC-BALANCE" and f.usage == "DISPLAY" for f in cpy_rec.fields)

    rel_facts = [f.fact for f in facts if isinstance(f.fact, RecordLayoutRelationFact)]
    rel = next(
        (
            f
            for f in rel_facts
            if "ACCOUNTS:ACCOUNT-RECORD" in (f.layout_a_name, f.layout_b_name)
            and "INIT-DB:ACCOUNT-REC" in (f.layout_a_name, f.layout_b_name)
        ),
        None,
    )
    assert rel is not None
    assert rel.relation_type in ("EQUIVALENT", "IDENTICAL")
    assert rel.relation_type != "REPRESENTATION_MISMATCH"


def test_cf3_copy_accounts_insertion(tmp_path: Path):
    """CF 3: Mutate TRANS-PROC.CBL to insert COPY ACCOUNTS.

    Verifies parser successfully classifies and parses the modified file.
    """
    orig = (REPO_ROOT / "legacy/core-banking-system/TRANS-PROC.CBL").read_text(encoding="utf-8")
    mutated = orig.replace(
        "WORKING-STORAGE SECTION.",
        "WORKING-STORAGE SECTION.\n       COPY ACCOUNTS.",
    )

    bundle = _create_mutated_source_bundle(
        {"legacy/core-banking-system/TRANS-PROC.CBL": mutated}, tmp_path
    )
    parser = SystemCobolParser(bundle)
    cert = parser.parse_system()

    assert cert.unsupported_relevant_count == 0
    assert bundle.get_file("legacy/core-banking-system/TRANS-PROC.CBL").line_count == len(
        mutated.splitlines()
    )


def test_cf4_file_status_insertion_eliminates_risk(tmp_path: Path):
    """CF 4: Mutate INIT-DB.CBL to insert FILE STATUS IS WS-STATUS.

    Verifies that missing file status check BehavioralRisk for INIT-DB is eliminated.
    """
    orig = (REPO_ROOT / "legacy/core-banking-system/INIT-DB.CBL").read_text(encoding="utf-8")
    mutated = orig.replace(
        "SELECT ACCOUNT-FILE ASSIGN TO 'ACCOUNTS.DAT'",
        "SELECT ACCOUNT-FILE ASSIGN TO 'ACCOUNTS.DAT'\n           FILE STATUS IS WS-STATUS",
    )

    bundle = _create_mutated_source_bundle(
        {"legacy/core-banking-system/INIT-DB.CBL": mutated}, tmp_path
    )
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()

    risks = [
        f.fact
        for f in facts
        if f.fact.fact_category == "BEHAVIORAL_RISK" and getattr(f.fact, "program_id") == "INIT-DB"
    ]
    assert len(risks) == 0


def test_cf5_extra_call_occurrence(tmp_path: Path):
    """CF 5: Mutate BANK-MAIN.CBL to insert CALL 'AUDIT-LOG'.

    Verifies an additional CallOccurrence is extracted and total call count increases.
    """
    orig = (REPO_ROOT / "legacy/core-banking-system/BANK-MAIN.CBL").read_text(encoding="utf-8")
    mutated = orig.replace(
        "CALL 'REPORT-GEN'",
        "CALL 'REPORT-GEN'\n                    CALL 'AUDIT-LOG'",
    )

    bundle = _create_mutated_source_bundle(
        {"legacy/core-banking-system/BANK-MAIN.CBL": mutated}, tmp_path
    )
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()

    calls = [f.fact for f in facts if isinstance(f.fact, CallOccurrenceFact)]
    assert len(calls) == 7

    extra = next((c for c in calls if c.target_program == "AUDIT-LOG"), None)
    assert extra is not None
    assert extra.caller_program == "BANK-MAIN"


def test_cf6_changed_system_command_assignment(tmp_path: Path):
    """CF 6: Mutate TRANS-PROC.CBL to move 'rm -f ACCOUNTS.DAT' TO WS-CMD.

    Verifies CommandInvocation updates command_template to Linux syntax.
    """
    orig = (REPO_ROOT / "legacy/core-banking-system/TRANS-PROC.CBL").read_text(encoding="utf-8")
    mutated = orig.replace(
        "MOVE 'cmd /c del ACCOUNTS.DAT' TO WS-CMD",
        "MOVE 'rm -f ACCOUNTS.DAT' TO WS-CMD",
    )

    bundle = _create_mutated_source_bundle(
        {"legacy/core-banking-system/TRANS-PROC.CBL": mutated}, tmp_path
    )
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()

    cmds = [f.fact for f in facts if isinstance(f.fact, CommandInvocationFact)]
    rm_cmd = next((c for c in cmds if c.command_template == "rm -f ACCOUNTS.DAT"), None)
    assert rm_cmd is not None
    assert rm_cmd.target_operand == "WS-CMD"


def test_cf7_changed_select_assign(tmp_path: Path):
    """CF 7: Mutate REPORT-GEN.CBL to ASSIGN TO 'BANK-ACCTS.DAT'.

    Verifies FileBinding extracts new external file name.
    """
    orig = (REPO_ROOT / "legacy/core-banking-system/REPORT-GEN.CBL").read_text(encoding="utf-8")
    mutated = orig.replace("'ACCOUNTS.DAT'", "'BANK-ACCTS.DAT'")

    bundle = _create_mutated_source_bundle(
        {"legacy/core-banking-system/REPORT-GEN.CBL": mutated}, tmp_path
    )
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()

    bindings = [f.fact for f in facts if isinstance(f.fact, FileBindingFact)]
    b = next((x for x in bindings if x.program_id == "REPORT-GEN"), None)
    assert b is not None
    assert b.external_file_name == "BANK-ACCTS.DAT"


def test_cf8_changed_pic_usage(tmp_path: Path):
    """CF 8: Mutate INIT-DB.CBL line 16 REC-ACC-BALANCE to COMP-3.

    Verifies storage_format changes to COMP-3 for INIT-DB record layout.
    """
    orig = (REPO_ROOT / "legacy/core-banking-system/INIT-DB.CBL").read_text(encoding="utf-8")
    mutated = orig.replace(
        "05 REC-ACC-BALANCE  PIC S9(13)V99.",
        "05 REC-ACC-BALANCE  PIC S9(13)V99 COMP-3.",
    )

    bundle = _create_mutated_source_bundle(
        {"legacy/core-banking-system/INIT-DB.CBL": mutated}, tmp_path
    )
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()

    layouts = [f.fact for f in facts if isinstance(f.fact, RecordLayoutFact)]
    init_rec = next((rec for rec in layouts if rec.program_id == "INIT-DB"), None)
    assert init_rec is not None
    assert any(
        f.name == "REC-ACC-BALANCE" and f.usage in ("COMP_3", "COMP-3") for f in init_rec.fields
    )


def test_cf9_changed_caller_callee_target(tmp_path: Path):
    """CF 9: Mutate BANK-MAIN.CBL CALL 'INIT-DB' -> CALL 'SEED-DB'.

    Verifies InternalCallResolution for INIT-DB is eliminated and new external call edge is created.
    """
    orig = (REPO_ROOT / "legacy/core-banking-system/BANK-MAIN.CBL").read_text(encoding="utf-8")
    mutated = orig.replace("CALL 'INIT-DB'", "CALL 'SEED-DB'")

    bundle = _create_mutated_source_bundle(
        {"legacy/core-banking-system/BANK-MAIN.CBL": mutated}, tmp_path
    )
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()

    resolutions = [f.fact for f in facts if isinstance(f.fact, InternalCallResolutionFact)]
    init_res = next((r for r in resolutions if r.callee_program == "INIT-DB"), None)
    assert init_res is None

    edges = [f.fact for f in facts if isinstance(f.fact, CallEdgeFact)]
    seed_edge = next((e for e in edges if e.target_program == "SEED-DB"), None)
    assert seed_edge is not None


def test_cf10_changed_delete_rename_ordering(tmp_path: Path):
    """CF 10: Mutate TRANS-PROC.CBL to swap command ordering.

    Verifies source facts update to reflect the swapped operation.
    """
    orig = (REPO_ROOT / "legacy/core-banking-system/TRANS-PROC.CBL").read_text(encoding="utf-8")
    del_cmd = (
        "              MOVE 'cmd /c del ACCOUNTS.DAT' TO WS-CMD\n"
        "              CALL 'SYSTEM' USING WS-CMD"
    )
    ren_cmd = (
        "              MOVE 'cmd /c ren ACCOUNTS.TMP ACCOUNTS.DAT' TO WS-CMD\n"
        "              CALL 'SYSTEM' USING WS-CMD"
    )
    assert del_cmd in orig
    assert ren_cmd in orig
    mutated = orig.replace(f"{del_cmd}\n{ren_cmd}", f"{ren_cmd}\n{del_cmd}")
    assert mutated != orig

    bundle = _create_mutated_source_bundle(
        {"legacy/core-banking-system/TRANS-PROC.CBL": mutated}, tmp_path
    )
    parser = SystemCobolParser(bundle)
    cert = parser.parse_system()
    assert cert.unsupported_relevant_count == 0
    facts = parser.get_supported_facts()
    non_atomic_risks = [
        f.fact
        for f in facts
        if f.fact.fact_category == "BEHAVIORAL_RISK"
        and "NON_ATOMIC_EXTERNAL_MUTATION" in f.fact.get_semantic_key()
    ]
    assert len(non_atomic_risks) == 0


def test_cf11_bob_state_aligned_with_initializer(tmp_path: Path):
    """CF 11: Mutate ACCOUNTS.DAT to align Bob Johnson balance with 100.00.

    Verifies DataStateComparisonFact discrepancy is eliminated (0.00 discrepancy).
    """
    orig = (REPO_ROOT / "legacy/core-banking-system/ACCOUNTS.DAT").read_text(encoding="utf-8")
    mutated = orig.replace("000000000020000", "000000000010000")

    bundle = _create_mutated_source_bundle(
        {"legacy/core-banking-system/ACCOUNTS.DAT": mutated}, tmp_path
    )
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()

    discrepancies = [f.fact for f in facts if f.fact.fact_category == "DATA_STATE_COMPARISON"]
    assert len(discrepancies) == 0
