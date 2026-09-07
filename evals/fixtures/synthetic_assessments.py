"""Synthetic assessment fixtures for deterministic offline testing of evaluator."""

from agents.legacy_analyzer.schemas.assessment import (
    CallDependency,
    ControlFlowConstruct,
    DataField,
    IOOperation,
    LegacyAssessment,
    MenuOption,
    ModernizationObservation,
    ProgramIdentity,
    ScopeDeclaration,
    SourceEvidence,
)
from src.cobol.source_reader import EXPECTED_BANK_MAIN_SHA256


def make_perfect_assessment() -> LegacyAssessment:
    """Return a synthetic assessment that matches all 15 golden facts with zero violations."""
    return LegacyAssessment(
        schema_version="1.0.0",
        scope=ScopeDeclaration(
            analyzed_file="legacy/core-banking-system/BANK-MAIN.CBL",
            source_sha256=EXPECTED_BANK_MAIN_SHA256,
            has_external_callees_analyzed=False,
            copybook_dependencies_found=[],
        ),
        program=ProgramIdentity(
            program_id="BANK-MAIN",
            evidence=SourceEvidence(
                source_file="BANK-MAIN.CBL",
                line_start=2,
                line_end=2,
                snippet="PROGRAM-ID. BANK-MAIN.",
            ),
        ),
        data_fields=[
            DataField(
                name="WS-CHOICE",
                level="01",
                picture="X",
                section="WORKING-STORAGE",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=8,
                    line_end=8,
                    snippet="01 WS-CHOICE  PIC X.",
                ),
            )
        ],
        call_dependencies=[
            CallDependency(
                target_program="INIT-DB",
                call_type="DYNAMIC",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=24,
                    line_end=24,
                    snippet="CALL 'INIT-DB'",
                ),
            ),
            CallDependency(
                target_program="TRANS-PROC",
                call_type="DYNAMIC",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=26,
                    line_end=26,
                    snippet="CALL 'TRANS-PROC'",
                ),
            ),
            CallDependency(
                target_program="REPORT-GEN",
                call_type="DYNAMIC",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=28,
                    line_end=28,
                    snippet="CALL 'REPORT-GEN'",
                ),
            ),
        ],
        menu_options=[
            MenuOption(
                option_key="1",
                description="Init Database",
                action_type="CALL",
                action_target="INIT-DB",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=23,
                    line_end=24,
                    snippet="WHEN '1'\n     CALL 'INIT-DB'",
                ),
            ),
            MenuOption(
                option_key="2",
                description="Transaction",
                action_type="CALL",
                action_target="TRANS-PROC",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=25,
                    line_end=26,
                    snippet="WHEN '2'\n     CALL 'TRANS-PROC'",
                ),
            ),
            MenuOption(
                option_key="3",
                description="Report",
                action_type="CALL",
                action_target="REPORT-GEN",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=27,
                    line_end=28,
                    snippet="WHEN '3'\n     CALL 'REPORT-GEN'",
                ),
            ),
            MenuOption(
                option_key="4",
                description="Exit",
                action_type="DISPLAY_EXIT",
                action_target="Bye.",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=29,
                    line_end=30,
                    snippet="WHEN '4'\n     DISPLAY 'Bye.'",
                ),
            ),
            MenuOption(
                option_key="OTHER",
                description="Invalid option",
                action_type="DISPLAY_ERROR",
                action_target="Invalid.",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=31,
                    line_end=32,
                    snippet="WHEN OTHER\n     DISPLAY 'Invalid.'",
                ),
            ),
        ],
        control_flow=[
            ControlFlowConstruct(
                construct_type="PERFORM_UNTIL",
                condition_or_target="WS-CHOICE = '4'",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=12,
                    line_end=12,
                    snippet="PERFORM UNTIL WS-CHOICE = '4'",
                ),
            ),
            ControlFlowConstruct(
                construct_type="EVALUATE",
                condition_or_target="WS-CHOICE",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=22,
                    line_end=22,
                    snippet="EVALUATE WS-CHOICE",
                ),
            ),
            ControlFlowConstruct(
                construct_type="STOP_RUN",
                condition_or_target="STOP RUN",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=36,
                    line_end=36,
                    snippet="STOP RUN.",
                ),
            ),
        ],
        io_operations=[
            IOOperation(
                operation_type="ACCEPT",
                target_or_content="WS-CHOICE",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=20,
                    line_end=20,
                    snippet="ACCEPT WS-CHOICE",
                ),
            ),
            IOOperation(
                operation_type="DISPLAY",
                target_or_content="=== CORE BANKING SYSTEM ===",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=14,
                    line_end=14,
                    snippet="DISPLAY '=== CORE BANKING SYSTEM ==='",
                ),
            ),
        ],
        observations=[
            ModernizationObservation(
                category="CONTROL_FLOW",
                observation=(
                    "Main loop relies on PERFORM UNTIL WS-CHOICE = '4' and ends with STOP RUN."
                ),
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=12,
                    line_end=36,
                    snippet="PERFORM UNTIL WS-CHOICE = '4' ... STOP RUN.",
                ),
            )
        ],
        unsupported_assumptions=[
            "Internal implementation of INIT-DB is unknown from this source file alone.",
            "Transaction processing rules in TRANS-PROC cannot be verified without "
            "inspecting TRANS-PROC.CBL.",
        ],
    )


def make_hallucinating_assessment() -> LegacyAssessment:
    """Return a synthetic assessment that contains prohibited out-of-scope claims."""
    assessment = make_perfect_assessment()
    assessment.observations.append(
        ModernizationObservation(
            category="ARCHITECTURE",
            observation=(
                "TRANS-PROC performs deposits and withdrawal logic using Windows cmd /c commands."
            ),
            evidence=SourceEvidence(
                source_file="BANK-MAIN.CBL",
                line_start=26,
                line_end=26,
                snippet="CALL 'TRANS-PROC'",
            ),
        )
    )
    return assessment
