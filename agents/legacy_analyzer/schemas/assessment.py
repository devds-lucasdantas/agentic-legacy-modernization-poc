"""Pydantic v2 schemas for structured legacy COBOL assessments.

Designed for OpenAI Responses API native Structured Outputs (`responses.parse`).
Every factual observation carries traceable source evidence.
"""

from pydantic import BaseModel, ConfigDict, Field


class SourceEvidence(BaseModel):
    """Traceable line and snippet citation in the analyzed source code."""

    model_config = ConfigDict(extra="forbid")

    source_file: str = Field(
        description="Relative path of the source file containing evidence, e.g. 'BANK-MAIN.CBL'."
    )
    line_start: int = Field(
        description="1-indexed starting line number in the source file."
    )
    line_end: int = Field(
        description="1-indexed ending line number in the source file."
    )
    snippet: str = Field(
        description="Exact source code line or text snippet evidencing this fact."
    )


class ProgramIdentity(BaseModel):
    """Identification information for the analyzed COBOL program."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(
        description="The PROGRAM-ID identifier as defined in the source (e.g. 'BANK-MAIN')."
    )
    evidence: SourceEvidence = Field(
        description="Source citation for the PROGRAM-ID declaration."
    )


class CallDependency(BaseModel):
    """External subprogram invocation found in the source code."""

    model_config = ConfigDict(extra="forbid")

    target_program: str = Field(
        description="Called target program name (e.g. 'INIT-DB', 'TRANS-PROC', 'REPORT-GEN')."
    )
    call_type: str = Field(
        default="DYNAMIC",
        description="Type of invocation, typically 'DYNAMIC' or 'STATIC' CALL.",
    )
    evidence: SourceEvidence = Field(
        description="Source citation for the CALL statement."
    )


class DataField(BaseModel):
    """Variable or data item declared in the DATA DIVISION."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        description="Name of the data field, e.g. 'WS-CHOICE'."
    )
    level: str = Field(
        description="COBOL level number, e.g. '01', '05'."
    )
    picture: str | None = Field(
        default=None,
        description="PICTURE clause if declared, e.g. 'X', '9(4)'."
    )
    section: str = Field(
        default="WORKING-STORAGE",
        description="Data Division section ('WORKING-STORAGE', 'FILE', 'LOCAL-STORAGE')."
    )
    evidence: SourceEvidence = Field(
        description="Source citation for the variable declaration."
    )


class MenuOption(BaseModel):
    """User-selectable option or evaluation branch discovered in the program."""

    model_config = ConfigDict(extra="forbid")

    option_key: str = Field(
        description="The selection key or condition, e.g. '1', '2', '3', '4', 'OTHER'."
    )
    description: str = Field(
        description="Menu choice description as displayed to user or handled by branch."
    )
    action_type: str = Field(
        description="Action triggered: 'CALL', 'DISPLAY_EXIT', 'DISPLAY_ERROR', or 'OTHER'."
    )
    action_target: str | None = Field(
        default=None,
        description="Target program called or message displayed when this option is selected."
    )
    evidence: SourceEvidence = Field(
        description="Source citation for this option's handling in EVALUATE/IF logic."
    )


class ControlFlowConstruct(BaseModel):
    """Control flow mechanism (loops, conditional branches, exits)."""

    model_config = ConfigDict(extra="forbid")

    construct_type: str = Field(
        description="Construct type: 'PERFORM_UNTIL', 'EVALUATE', 'STOP_RUN', 'IF'."
    )
    condition_or_target: str = Field(
        description="Condition expression or exit target, e.g. 'WS-CHOICE = \"4\"', 'STOP RUN'."
    )
    evidence: SourceEvidence = Field(
        description="Source citation for the control flow statement."
    )


class IOOperation(BaseModel):
    """Terminal or file input/output operation directly visible in this source."""

    model_config = ConfigDict(extra="forbid")

    operation_type: str = Field(
        description="Type of operation: 'ACCEPT', 'DISPLAY', 'READ', 'WRITE'."
    )
    target_or_content: str = Field(
        description="Field accepted or literal text / pattern displayed."
    )
    evidence: SourceEvidence = Field(
        description="Source citation for the I/O statement."
    )


class ModernizationObservation(BaseModel):
    """Architecture or modernization risk observation strictly grounded in this file."""

    model_config = ConfigDict(extra="forbid")

    category: str = Field(
        description="Category: 'CONTROL_FLOW', 'COUPLING', 'PORTABILITY', 'ARCHITECTURE'."
    )
    observation: str = Field(
        description="Detailed observation supported by this file's code."
    )
    evidence: SourceEvidence = Field(
        description="Source citation supporting the observation."
    )


class ScopeDeclaration(BaseModel):
    """Scope boundaries confirmed by the analysis."""

    model_config = ConfigDict(extra="forbid")

    analyzed_file: str = Field(
        description="Relative path of the analyzed file (e.g. 'BANK-MAIN.CBL')."
    )
    source_sha256: str = Field(
        description="SHA256 hex digest of the raw source file analyzed."
    )
    has_external_callees_analyzed: bool = Field(
        default=False,
        description="Must be False for single-file analysis; confirms callees were not inspected.",
    )
    copybook_dependencies_found: list[str] = Field(
        default_factory=list,
        description="List of COPY copybook names found in this file (empty if none exist).",
    )


class LegacyAssessment(BaseModel):
    """Top-level canonical assessment for a COBOL source module."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="1.0.0",
        description="Version of this assessment schema.",
    )
    scope: ScopeDeclaration = Field(
        description="Execution scope and boundary verification."
    )
    program: ProgramIdentity = Field(
        description="Identity of the analyzed COBOL program."
    )
    data_fields: list[DataField] = Field(
        default_factory=list,
        description="Variables and fields declared in Working-Storage or other data sections."
    )
    call_dependencies: list[CallDependency] = Field(
        default_factory=list,
        description="External programs invoked via CALL statements."
    )
    menu_options: list[MenuOption] = Field(
        default_factory=list,
        description="User menu options and branches handled in this program."
    )
    control_flow: list[ControlFlowConstruct] = Field(
        default_factory=list,
        description="Control flow statements including loops, evaluations, and STOP RUN."
    )
    io_operations: list[IOOperation] = Field(
        default_factory=list,
        description="Input and output statements (ACCEPT, DISPLAY)."
    )
    observations: list[ModernizationObservation] = Field(
        default_factory=list,
        description="Architectural/modernization observations grounded in the analyzed source."
    )
    unsupported_assumptions: list[str] = Field(
        default_factory=list,
        description="Facts that cannot be determined because external callees are out of scope."
    )
