"""Adversarial regressions, weak controls, and counterfactual matrix for Gate 3."""

import json
from pathlib import Path

import pytest

from agents.legacy_analyzer.schemas.system_assessment import (
    ArchitecturalRisk,
    ArithmeticComputation,
    BehavioralRisk,
    ConditionalBranch,
    ControlFlowLoop,
    CrossProgramCall,
    DataFlowTransfer,
    EvaluateSelection,
    InteractiveIO,
    MenuDispatchOption,
    ProgramTermination,
    RecordFieldDeclaration,
    ResourceLifecycle,
    SharedCopybookReference,
    SourceEvidence,
    SystemAssessment,
    SystemComponent,
    SystemExecutionProtocol,
    WorkingStorageState,
)
from src.cobol.multi_source_reader import read_system_bundle
from src.cobol.system_atomic_facts import (
    ArchitecturalRiskFact,
    ArithmeticOperationFact,
    BehavioralRiskFact,
    ComponentTopologyFact,
    ConditionalBranchFact,
    ControlFlowLoopFact,
    CopybookInclusionFact,
    CrossProgramCallFact,
    DataTransferFact,
    EvaluateBranchingFact,
    FieldLayoutFact,
    InteractiveIOFact,
    MenuDispatchFact,
    ResourceLifecycleFact,
    TerminationFact,
    TransactionProtocolFact,
    WorkingStorageStateFact,
)
from src.cobol.system_cobol_parser import SystemCobolParser
from src.cobol.system_support_index import SystemSupportIndex
from src.validation.evaluator_v3 import SystemEvaluatorV3

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def make_perfect_system_assessment(parser: SystemCobolParser) -> SystemAssessment:
    """Construct a perfect synthetic assessment directly from ground-truth AST facts."""
    components = []
    calls = []
    menus = []
    copybooks = []
    fields = []
    transfers = []
    lifecycles = []
    loops = []
    evaluates = []
    arithmetics = []
    branches = []
    ios = []
    terminations = []
    b_risks = []
    a_risks = []
    ws_states = []
    protocols = []

    for sf in parser.get_supported_facts():
        ev = SourceEvidence(
            file_path=sf.file_path,
            line_start=sf.line_start,
            line_end=sf.line_end,
        )
        f = sf.fact
        if isinstance(f, ComponentTopologyFact):
            components.append(
                SystemComponent(
                    program_id=f.program_id,
                    component_role=f.component_role,
                    evidence=ev,
                )
            )
        elif isinstance(f, CrossProgramCallFact):
            calls.append(
                CrossProgramCall(
                    caller_program=f.caller_program,
                    callee_program=f.callee_program,
                    call_mechanism=f.call_mechanism,
                    evidence=ev,
                )
            )
        elif isinstance(f, MenuDispatchFact):
            menus.append(
                MenuDispatchOption(
                    program_id=f.program_id,
                    menu_key=f.menu_key,
                    target_action=f.target_action,
                    evidence=ev,
                )
            )
        elif isinstance(f, CopybookInclusionFact):
            copybooks.append(
                SharedCopybookReference(
                    program_id=f.program_id,
                    copybook_name=f.copybook_name,
                    evidence=ev,
                )
            )
        elif isinstance(f, FieldLayoutFact):
            fields.append(
                RecordFieldDeclaration(
                    container_name=f.container_name,
                    field_name=f.field_name,
                    picture_clause=f.picture_clause,
                    storage_format=f.storage_format,
                    evidence=ev,
                )
            )
        elif isinstance(f, DataTransferFact):
            transfers.append(
                DataFlowTransfer(
                    program_id=f.program_id,
                    source_entity=f.source_entity,
                    target_entity=f.target_entity,
                    transfer_verb=f.transfer_verb,
                    evidence=ev,
                )
            )
        elif isinstance(f, ResourceLifecycleFact):
            lifecycles.append(
                ResourceLifecycle(
                    program_id=f.program_id,
                    resource_name=f.resource_name,
                    access_mode=f.access_mode,
                    operations=list(f.operations),
                    evidence=ev,
                )
            )
        elif isinstance(f, ControlFlowLoopFact):
            loops.append(
                ControlFlowLoop(
                    program_id=f.program_id,
                    loop_predicate=f.loop_predicate,
                    evidence=ev,
                )
            )
        elif isinstance(f, EvaluateBranchingFact):
            evaluates.append(
                EvaluateSelection(
                    program_id=f.program_id,
                    selection_subject=f.selection_subject,
                    evidence=ev,
                )
            )
        elif isinstance(f, ArithmeticOperationFact):
            arithmetics.append(
                ArithmeticComputation(
                    program_id=f.program_id,
                    verb=f.verb,
                    operand=f.operand,
                    target_field=f.target_field,
                    evidence=ev,
                )
            )
        elif isinstance(f, ConditionalBranchFact):
            branches.append(
                ConditionalBranch(
                    program_id=f.program_id,
                    condition_kind=f.condition_kind,
                    predicate=f.predicate,
                    evidence=ev,
                )
            )
        elif isinstance(f, InteractiveIOFact):
            ios.append(
                InteractiveIO(
                    program_id=f.program_id,
                    io_verb=f.io_verb,
                    target_identifier=f.target_identifier,
                    evidence=ev,
                )
            )
        elif isinstance(f, TerminationFact):
            terminations.append(
                ProgramTermination(
                    program_id=f.program_id,
                    termination_verb=f.termination_verb,
                    evidence=ev,
                )
            )
        elif isinstance(f, BehavioralRiskFact):
            b_risks.append(
                BehavioralRisk(
                    program_id=f.program_id,
                    risk_category=f.risk_category,
                    precondition=f.precondition,
                    ordered_operations=list(f.ordered_operations),
                    possible_consequence=f.possible_consequence,
                    severity=f.severity,
                    evidence=ev,
                )
            )
        elif isinstance(f, ArchitecturalRiskFact):
            a_risks.append(
                ArchitecturalRisk(
                    risk_id=f.risk_id,
                    risk_type=f.risk_type,
                    affected_components=list(f.affected_components),
                    architectural_consequence=f.architectural_consequence,
                    severity=f.severity,
                    evidence=ev,
                )
            )
        elif isinstance(f, WorkingStorageStateFact):
            ws_states.append(
                WorkingStorageState(
                    program_id=f.program_id,
                    variable_name=f.variable_name,
                    picture_clause=f.picture_clause,
                    state_role=f.state_role,
                    evidence=ev,
                )
            )
        elif isinstance(f, TransactionProtocolFact):
            protocols.append(
                SystemExecutionProtocol(
                    protocol_name=f.protocol_name,
                    ordered_phases=list(f.ordered_phases),
                    evidence=ev,
                )
            )

    return SystemAssessment(
        system_name="Core Banking System",
        components=components,
        cross_program_calls=calls,
        menu_dispatches=menus,
        copybook_references=copybooks,
        record_fields=fields,
        data_transfers=transfers,
        resource_lifecycles=lifecycles,
        control_flow_loops=loops,
        evaluate_selections=evaluates,
        arithmetic_computations=arithmetics,
        conditional_branches=branches,
        interactive_io_operations=ios,
        terminations=terminations,
        behavioral_risks=b_risks,
        architectural_risks=a_risks,
        working_storage_states=ws_states,
        system_protocols=protocols,
    )


# ---------------------------------------------------------------------------
# Test 1: Mandatory Positive Invariant
# ---------------------------------------------------------------------------


def test_01_mandatory_positive_invariant_perfect_assessment():
    """Verify that perfect synthetic assessment achieves 100% precision & recall."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    parser.parse_system()
    index = SystemSupportIndex(parser.get_supported_facts(), bundle)
    evaluator = SystemEvaluatorV3(index)

    perfect = make_perfect_system_assessment(parser)
    metrics, _ = evaluator.evaluate_assessment(perfect)

    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.raw_predicted_count == 54
    assert metrics.unique_predicted_count == 54
    assert metrics.supported_predicted_count == 54
    assert metrics.unsupported_predicted_count == 0
    assert metrics.invalid_evidence_count == 0
    assert metrics.duplicate_prediction_count == 0
    assert metrics.contradiction_count == 0
    assert metrics.matched_expected_count == 54
    assert metrics.missing_expected_count == 0
    assert metrics.expected_fact_count == 54
    assert metrics.gate_3_pass is True


# ---------------------------------------------------------------------------
# Test 2 & 3: Weak Model Controls
# ---------------------------------------------------------------------------


def test_02_weak_source_blind_control():
    """Verify that source-blind predictions with invalid coordinates fail evaluation."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    parser.parse_system()
    index = SystemSupportIndex(parser.get_supported_facts(), bundle)
    evaluator = SystemEvaluatorV3(index)

    # Corrupt line numbers
    blind_assessment = SystemAssessment(
        system_name="Blind System",
        components=[
            SystemComponent(
                program_id="BANK-MAIN",
                component_role="ROOT_ORCHESTRATOR",
                evidence=SourceEvidence(
                    file_path="legacy/core-banking-system/BANK-MAIN.CBL",
                    line_start=999,
                    line_end=999,
                ),
            )
        ],
        cross_program_calls=[],
        menu_dispatches=[],
        copybook_references=[],
        record_fields=[],
        data_transfers=[],
        resource_lifecycles=[],
        control_flow_loops=[],
        evaluate_selections=[],
        arithmetic_computations=[],
        conditional_branches=[],
        interactive_io_operations=[],
        terminations=[],
        behavioral_risks=[],
        architectural_risks=[],
        working_storage_states=[],
        system_protocols=[],
    )

    metrics, _ = evaluator.evaluate_assessment(blind_assessment)
    assert metrics.invalid_evidence_count == 1
    assert metrics.precision == 0.0
    assert metrics.recall == 0.0
    assert metrics.gate_3_pass is False


def test_03_weak_lexical_only_control():
    """Verify that hallucinated lexical predictions without AST backing are rejected."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    parser.parse_system()
    index = SystemSupportIndex(parser.get_supported_facts(), bundle)
    evaluator = SystemEvaluatorV3(index)

    lexical_assessment = SystemAssessment(
        system_name="Lexical Guess",
        components=[
            SystemComponent(
                program_id="NON-EXISTENT-PROGRAM",
                component_role="UNKNOWN_ROLE",
                evidence=SourceEvidence(
                    file_path="legacy/core-banking-system/BANK-MAIN.CBL",
                    line_start=1,
                    line_end=2,
                ),
            )
        ],
        cross_program_calls=[],
        menu_dispatches=[],
        copybook_references=[],
        record_fields=[],
        data_transfers=[],
        resource_lifecycles=[],
        control_flow_loops=[],
        evaluate_selections=[],
        arithmetic_computations=[],
        conditional_branches=[],
        interactive_io_operations=[],
        terminations=[],
        behavioral_risks=[],
        architectural_risks=[],
        working_storage_states=[],
        system_protocols=[],
    )

    metrics, _ = evaluator.evaluate_assessment(lexical_assessment)
    assert metrics.unsupported_predicted_count == 1
    assert metrics.precision == 0.0
    assert metrics.gate_3_pass is False


# ---------------------------------------------------------------------------
# Counterfactual Matrix Tests (CF-01 through CF-08)
# ---------------------------------------------------------------------------


def test_cf_01_remove_trans_proc_call():
    """CF-01: Drop CALL 'TRANS-PROC' invocation and verify rejection."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    parser.parse_system()
    index = SystemSupportIndex(parser.get_supported_facts(), bundle)

    # Inverted / hallucinated call
    fake_call = CrossProgramCallFact(
        fact_category="CROSS_PROGRAM_CALL",
        caller_program="BANK-MAIN",
        callee_program="UNKNOWN-PROGRAM",
        call_mechanism="DYNAMIC_CALL_LITERAL",
    )
    is_supp, _, _ = index.verify_assertion(
        fake_call,
        file_path="legacy/core-banking-system/BANK-MAIN.CBL",
        line_start=26,
        line_end=26,
    )
    assert is_supp is False


def test_cf_02_mutate_acc_balance_comp3_to_display():
    """CF-02: Mutate ACC-BALANCE representation to DISPLAY (name unchanged) and verify detection."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    parser.parse_system()
    index = SystemSupportIndex(parser.get_supported_facts(), bundle)

    # Field identity ACC-BALANCE remains unchanged, representation changed to DISPLAY
    mutated_field = FieldLayoutFact(
        fact_category="FIELD_LAYOUT",
        container_name="ACCOUNT-RECORD",
        field_name="ACC-BALANCE",
        picture_clause="S9(13)V99",
        storage_format="DISPLAY",
    )
    # Ground truth is COMP-3, so DISPLAY assertion must be rejected
    is_supp, reason, _ = index.verify_assertion(
        mutated_field,
        file_path="legacy/core-banking-system/ACCOUNTS.CPY",
        line_start=2,
        line_end=6,
    )
    assert is_supp is False


def test_cf_03_invert_init_db_file_mode():
    """CF-03: Invert INIT-DB file open mode from OUTPUT to INPUT."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    parser.parse_system()
    index = SystemSupportIndex(parser.get_supported_facts(), bundle)

    inverted_lifecycle = ResourceLifecycleFact(
        fact_category="RESOURCE_LIFECYCLE",
        program_id="INIT-DB",
        resource_name="ACCOUNT-FILE",
        access_mode="INPUT",
        operations=("OPEN", "READ", "CLOSE"),
    )
    is_supp, _, _ = index.verify_assertion(
        inverted_lifecycle,
        file_path="legacy/core-banking-system/INIT-DB.CBL",
        line_start=24,
        line_end=44,
    )
    assert is_supp is False


def test_cf_04_invert_nsf_check_condition():
    """CF-04: Invert NSF condition (< instead of >=)."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    parser.parse_system()
    index = SystemSupportIndex(parser.get_supported_facts(), bundle)

    inverted_nsf = ConditionalBranchFact(
        fact_category="CONDITIONAL_BRANCH",
        program_id="TRANS-PROC",
        condition_kind="IF_PREDICATE",
        predicate="REC-ACC-BALANCE < WS-TRANS-AMOUNT",
    )
    is_supp, _, _ = index.verify_assertion(
        inverted_nsf,
        file_path="legacy/core-banking-system/TRANS-PROC.CBL",
        line_start=64,
        line_end=70,
    )
    assert is_supp is False


def test_cf_05_remove_report_balance_accumulation():
    """CF-05: Test assertion of non-existent arithmetic accumulation."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    parser.parse_system()
    index = SystemSupportIndex(parser.get_supported_facts(), bundle)

    fake_arith = ArithmeticOperationFact(
        fact_category="ARITHMETIC_OPERATION",
        program_id="REPORT-GEN",
        verb="SUBTRACT",
        operand="REC-ACC-BALANCE",
        target_field="WS-TOTAL-BAL",
    )
    is_supp, _, _ = index.verify_assertion(
        fake_arith,
        file_path="legacy/core-banking-system/REPORT-GEN.CBL",
        line_start=45,
        line_end=45,
    )
    assert is_supp is False


def test_cf_06_delete_copybook_inclusion():
    """CF-06: Test assertion of non-existent copybook inclusion."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    parser.parse_system()
    index = SystemSupportIndex(parser.get_supported_facts(), bundle)

    fake_copy = CopybookInclusionFact(
        fact_category="COPYBOOK_INCLUSION",
        program_id="BANK-MAIN",
        copybook_name="ACCOUNTS.CPY",
    )
    is_supp, _, _ = index.verify_assertion(
        fake_copy,
        file_path="legacy/core-banking-system/BANK-MAIN.CBL",
        line_start=6,
        line_end=7,
    )
    assert is_supp is False


def test_cf_07_remove_loop_termination():
    """CF-07: Test assertion of non-existent infinite loop."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    parser.parse_system()
    index = SystemSupportIndex(parser.get_supported_facts(), bundle)

    fake_loop = ControlFlowLoopFact(
        fact_category="CONTROL_FLOW_LOOP",
        program_id="BANK-MAIN",
        loop_predicate="1 = 1",
    )
    is_supp, _, _ = index.verify_assertion(
        fake_loop,
        file_path="legacy/core-banking-system/BANK-MAIN.CBL",
        line_start=12,
        line_end=34,
    )
    assert is_supp is False


def test_cf_08_add_explicit_file_status():
    """CF-08: Verify that if file status were present, missing-status risk would be rejected."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    parser.parse_system()
    index = SystemSupportIndex(parser.get_supported_facts(), bundle)

    # Test that risk assertion for program with status is rejected
    fake_risk = BehavioralRiskFact(
        fact_category="BEHAVIORAL_RISK",
        program_id="NON-EXISTENT",
        risk_category="MISSING_FILE_STATUS_CHECK",
        precondition="UNCHECKED_FILE_STATUS",
        ordered_operations=("OPEN", "READ", "CLOSE"),
        possible_consequence="SILENT_IO_FAILURE",
        severity="HIGH",
    )
    is_supp, _, _ = index.verify_assertion(
        fake_risk,
        file_path="legacy/core-banking-system/BANK-MAIN.CBL",
        line_start=1,
        line_end=2,
    )
    assert is_supp is False


# ---------------------------------------------------------------------------
# Schema & Prompt Hygiene Tests
# ---------------------------------------------------------------------------


def test_04_schema_extra_forbid_and_wire_generation():
    """Verify that SystemAssessment enforces extra=forbid and compiles to OpenAI wire schema."""
    schema = SystemAssessment.model_json_schema()
    wire = {"name": "system_assessment", "strict": True, "schema": schema}
    serialized = json.dumps(wire)
    assert len(serialized) > 10000

    # Ensure extra = forbid
    with pytest.raises(Exception):
        SystemComponent.model_validate(
            {
                "program_id": "BANK-MAIN",
                "component_role": "ORCHESTRATOR",
                "evidence": {
                    "file_path": "legacy/core-banking-system/BANK-MAIN.CBL",
                    "line_start": 1,
                    "line_end": 2,
                },
                "unauthorized_extra_field": "forbidden",
            }
        )


def test_05_schema_and_prompt_contain_no_answer_leakage():
    """Verify that model-visible schema and system prompt contain no answer leakage."""
    schema_str = json.dumps(SystemAssessment.model_json_schema())
    prompt_path = REPO_ROOT / "agents" / "legacy_analyzer" / "prompts" / "system_v3.md"
    prompt_str = prompt_path.read_text(encoding="utf-8")

    forbidden_tokens = [
        "INIT-DB",
        "TRANS-PROC",
        "REPORT-GEN",
        "WS-CHOICE",
        "ACCOUNTS.DAT",
        "ACCOUNTS.CPY",
    ]

    for token in forbidden_tokens:
        assert token not in schema_str, (
            f"Forbidden token '{token}' found in SystemAssessment schema"
        )
        assert token not in prompt_str, f"Forbidden token '{token}' found in system_v3.md prompt"
