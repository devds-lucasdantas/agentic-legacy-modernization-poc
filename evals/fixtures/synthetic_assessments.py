"""Synthetic assessment fixtures for deterministic offline testing of evaluator."""

from agents.legacy_analyzer.schemas.assessment import (
    CallDependency,
    ControlFlowConstruct,
    DataField,
    IOOperation,
    LegacyAssessment,
    MenuOption,
    ProgramIdentity,
    SourceEvidence,
)
from agents.legacy_analyzer.schemas.assessment_v1 import (
    CallDependency as CallDependencyV1,
)
from agents.legacy_analyzer.schemas.assessment_v1 import (
    ControlFlowConstruct as ControlFlowConstructV1,
)
from agents.legacy_analyzer.schemas.assessment_v1 import (
    DataField as DataFieldV1,
)
from agents.legacy_analyzer.schemas.assessment_v1 import (
    IOOperation as IOOperationV1,
)
from agents.legacy_analyzer.schemas.assessment_v1 import (
    LegacyAssessment as LegacyAssessmentV1,
)
from agents.legacy_analyzer.schemas.assessment_v1 import (
    MenuOption as MenuOptionV1,
)
from agents.legacy_analyzer.schemas.assessment_v1 import (
    ModernizationObservation as ModernizationObservationV1,
)
from agents.legacy_analyzer.schemas.assessment_v1 import (
    ProgramIdentity as ProgramIdentityV1,
)
from agents.legacy_analyzer.schemas.assessment_v1 import (
    ScopeDeclaration as ScopeDeclarationV1,
)
from agents.legacy_analyzer.schemas.assessment_v1 import (
    SourceEvidence as SourceEvidenceV1,
)
from src.cobol.source_reader import EXPECTED_BANK_MAIN_SHA256


def make_perfect_assessment_v2() -> LegacyAssessment:
    """Return a synthetic assessment conforming to Schema V2 matching all expected facts."""
    return LegacyAssessment(
        schema_version="2.0.0",
        program=ProgramIdentity(
            program_id="BANK-MAIN",
            evidence=SourceEvidence(
                source_file="BANK-MAIN.CBL",
                line_start=1,
                line_end=2,
                snippet="IDENTIFICATION DIVISION.\nPROGRAM-ID. BANK-MAIN.",
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
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=24,
                    line_end=24,
                    snippet="CALL 'INIT-DB'",
                ),
            ),
            CallDependency(
                target_program="TRANS-PROC",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=26,
                    line_end=26,
                    snippet="CALL 'TRANS-PROC'",
                ),
            ),
            CallDependency(
                target_program="REPORT-GEN",
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
                description="Invalid choice",
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
                    line_end=34,
                    snippet="PERFORM UNTIL WS-CHOICE = '4'\n...\nEND-PERFORM.",
                ),
            ),
            ControlFlowConstruct(
                construct_type="EVALUATE",
                condition_or_target="WS-CHOICE",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=22,
                    line_end=33,
                    snippet="EVALUATE WS-CHOICE\n...\nEND-EVALUATE",
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
                target_or_content="'Bye.'",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=30,
                    line_end=30,
                    snippet="DISPLAY 'Bye.'",
                ),
            ),
        ],
        copybook_dependencies=[],
    )


def make_perfect_assessment() -> LegacyAssessment:
    """Default alias to make_perfect_assessment_v2."""
    return make_perfect_assessment_v2()


def make_perfect_assessment_v1() -> LegacyAssessmentV1:
    """Return historical V1 assessment fixture."""
    return LegacyAssessmentV1(
        schema_version="1.0.0",
        scope=ScopeDeclarationV1(
            analyzed_file="legacy/core-banking-system/BANK-MAIN.CBL",
            source_sha256=EXPECTED_BANK_MAIN_SHA256,
            has_external_callees_analyzed=False,
            copybook_dependencies_found=[],
        ),
        program=ProgramIdentityV1(
            program_id="BANK-MAIN",
            evidence=SourceEvidenceV1(
                source_file="BANK-MAIN.CBL",
                line_start=2,
                line_end=2,
                snippet="PROGRAM-ID. BANK-MAIN.",
            ),
        ),
        data_fields=[
            DataFieldV1(
                name="WS-CHOICE",
                level="01",
                picture="X",
                section="WORKING-STORAGE",
                evidence=SourceEvidenceV1(
                    source_file="BANK-MAIN.CBL",
                    line_start=8,
                    line_end=8,
                    snippet="01 WS-CHOICE  PIC X.",
                ),
            )
        ],
        call_dependencies=[
            CallDependencyV1(
                target_program="INIT-DB",
                call_type="DYNAMIC",
                evidence=SourceEvidenceV1(
                    source_file="BANK-MAIN.CBL",
                    line_start=24,
                    line_end=24,
                    snippet="CALL 'INIT-DB'",
                ),
            ),
            CallDependencyV1(
                target_program="TRANS-PROC",
                call_type="DYNAMIC",
                evidence=SourceEvidenceV1(
                    source_file="BANK-MAIN.CBL",
                    line_start=26,
                    line_end=26,
                    snippet="CALL 'TRANS-PROC'",
                ),
            ),
            CallDependencyV1(
                target_program="REPORT-GEN",
                call_type="DYNAMIC",
                evidence=SourceEvidenceV1(
                    source_file="BANK-MAIN.CBL",
                    line_start=28,
                    line_end=28,
                    snippet="CALL 'REPORT-GEN'",
                ),
            ),
        ],
        menu_options=[
            MenuOptionV1(
                option_key="1",
                description="Init Database",
                action_type="CALL",
                action_target="INIT-DB",
                evidence=SourceEvidenceV1(
                    source_file="BANK-MAIN.CBL",
                    line_start=23,
                    line_end=24,
                    snippet="WHEN '1'\n     CALL 'INIT-DB'",
                ),
            ),
            MenuOptionV1(
                option_key="2",
                description="Transaction",
                action_type="CALL",
                action_target="TRANS-PROC",
                evidence=SourceEvidenceV1(
                    source_file="BANK-MAIN.CBL",
                    line_start=25,
                    line_end=26,
                    snippet="WHEN '2'\n     CALL 'TRANS-PROC'",
                ),
            ),
            MenuOptionV1(
                option_key="3",
                description="Report",
                action_type="CALL",
                action_target="REPORT-GEN",
                evidence=SourceEvidenceV1(
                    source_file="BANK-MAIN.CBL",
                    line_start=27,
                    line_end=28,
                    snippet="WHEN '3'\n     CALL 'REPORT-GEN'",
                ),
            ),
            MenuOptionV1(
                option_key="4",
                description="Exit",
                action_type="DISPLAY_EXIT",
                action_target="DISPLAY 'Bye.'",
                evidence=SourceEvidenceV1(
                    source_file="BANK-MAIN.CBL",
                    line_start=29,
                    line_end=30,
                    snippet="WHEN '4'\n     DISPLAY 'Bye.'",
                ),
            ),
            MenuOptionV1(
                option_key="OTHER",
                description="Invalid choice",
                action_type="DISPLAY_ERROR",
                action_target="DISPLAY 'Invalid.'",
                evidence=SourceEvidenceV1(
                    source_file="BANK-MAIN.CBL",
                    line_start=31,
                    line_end=32,
                    snippet="WHEN OTHER\n     DISPLAY 'Invalid.'",
                ),
            ),
        ],
        control_flow=[
            ControlFlowConstructV1(
                construct_type="PERFORM_UNTIL",
                condition_or_target="WS-CHOICE = '4'",
                evidence=SourceEvidenceV1(
                    source_file="BANK-MAIN.CBL",
                    line_start=12,
                    line_end=34,
                    snippet="PERFORM UNTIL WS-CHOICE = '4'\n...\nEND-PERFORM.",
                ),
            ),
            ControlFlowConstructV1(
                construct_type="EVALUATE",
                condition_or_target="EVALUATE WS-CHOICE",
                evidence=SourceEvidenceV1(
                    source_file="BANK-MAIN.CBL",
                    line_start=22,
                    line_end=33,
                    snippet="EVALUATE WS-CHOICE\n...\nEND-EVALUATE",
                ),
            ),
            ControlFlowConstructV1(
                construct_type="STOP_RUN",
                condition_or_target="STOP RUN",
                evidence=SourceEvidenceV1(
                    source_file="BANK-MAIN.CBL",
                    line_start=36,
                    line_end=36,
                    snippet="STOP RUN.",
                ),
            ),
        ],
        io_operations=[
            IOOperationV1(
                operation_type="ACCEPT",
                target_or_content="WS-CHOICE",
                evidence=SourceEvidenceV1(
                    source_file="BANK-MAIN.CBL",
                    line_start=20,
                    line_end=20,
                    snippet="ACCEPT WS-CHOICE",
                ),
            ),
            IOOperationV1(
                operation_type="DISPLAY",
                target_or_content="'Bye.'",
                evidence=SourceEvidenceV1(
                    source_file="BANK-MAIN.CBL",
                    line_start=30,
                    line_end=30,
                    snippet="DISPLAY 'Bye.'",
                ),
            ),
        ],
        observations=[
            ModernizationObservationV1(
                category="CONTROL_FLOW",
                observation="Menu loop controlled by WS-CHOICE.",
                evidence=SourceEvidenceV1(
                    source_file="BANK-MAIN.CBL",
                    line_start=12,
                    line_end=12,
                    snippet="PERFORM UNTIL WS-CHOICE = '4'",
                ),
            )
        ],
        unsupported_assumptions=["Unknown whether INIT-DB seeds accounts or writes database."],
    )


def make_hallucinating_assessment() -> LegacyAssessmentV1:
    """Return historical hallucinating assessment fixture for regression testing."""
    assessment = make_perfect_assessment_v1()
    assessment.observations.append(
        ModernizationObservationV1(
            category="ARCHITECTURE",
            observation="TRANS-PROC performs deposits and executes cmd /c del to manage files.",
            evidence=SourceEvidenceV1(
                source_file="BANK-MAIN.CBL",
                line_start=26,
                line_end=26,
                snippet="CALL 'TRANS-PROC'",
            ),
        )
    )
    return assessment
