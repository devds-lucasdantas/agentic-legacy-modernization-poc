"""Pydantic v2 schemas for structured legacy COBOL assessments (Version 2.0.0).

Designed for OpenAI Responses API native Structured Outputs (`responses.parse`).
All field descriptions are completely generic and free of fixture answer hints.
Host-controlled execution metadata (file path, SHA256, callee boundaries) is
managed outside this schema.
"""

from pydantic import BaseModel, ConfigDict, Field


class SourceEvidence(BaseModel):
    """Traceable line and snippet citation in the analyzed source code."""

    model_config = ConfigDict(extra="forbid")

    source_file: str = Field(description="Relative path or filename containing the evidence.")
    line_start: int = Field(description="1-indexed starting line number in the source file.")
    line_end: int = Field(description="1-indexed ending line number in the source file.")
    snippet: str = Field(description="Exact source code line or text snippet evidencing this fact.")


class ProgramIdentity(BaseModel):
    """Identification information for the analyzed COBOL program."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="The PROGRAM-ID identifier declared in the source.")
    evidence: SourceEvidence = Field(description="Source citation for the PROGRAM-ID declaration.")


class CallDependency(BaseModel):
    """External subprogram invocation found in the source code."""

    model_config = ConfigDict(extra="forbid")

    target_program: str = Field(
        description="The name of the external program invoked by the CALL statement."
    )
    evidence: SourceEvidence = Field(description="Source citation for the CALL statement.")


class DataField(BaseModel):
    """Variable or data item declared in the DATA DIVISION."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="The name of the declared data field.")
    level: str = Field(description="COBOL level number, such as '01', '05', or '77'.")
    picture: str | None = Field(
        default=None,
        description="The PICTURE clause string if declared, without the leading PIC keyword.",
    )
    section: str = Field(
        default="WORKING-STORAGE",
        description=(
            "Data division section where the item is declared (e.g. 'WORKING-STORAGE', 'FILE')."
        ),
    )
    evidence: SourceEvidence = Field(description="Source citation for the variable declaration.")


class MenuOption(BaseModel):
    """User-selectable option or evaluation branch discovered in the program."""

    model_config = ConfigDict(extra="forbid")

    option_key: str = Field(
        description="The selection key or branch condition literal (e.g. '1', '2', 'OTHER')."
    )
    description: str = Field(
        description="Menu choice description as displayed to user or handled by branch."
    )
    action_type: str = Field(
        description="Action triggered: 'CALL', 'DISPLAY_EXIT', 'DISPLAY_ERROR', or 'OTHER'."
    )
    action_target: str | None = Field(
        default=None,
        description="Target program called or message displayed when this option is selected.",
    )
    evidence: SourceEvidence = Field(
        description="Source citation for this option's handling in EVALUATE or IF logic."
    )


class ControlFlowConstruct(BaseModel):
    """Control flow mechanism (loops, conditional branches, exits)."""

    model_config = ConfigDict(extra="forbid")

    construct_type: str = Field(
        description="Construct type: 'PERFORM_UNTIL', 'EVALUATE', 'STOP_RUN', or 'IF'."
    )
    condition_or_target: str = Field(description="Condition expression or exit target statement.")
    evidence: SourceEvidence = Field(description="Source citation for the control flow statement.")


class IOOperation(BaseModel):
    """Terminal or file input/output operation directly visible in this source."""

    model_config = ConfigDict(extra="forbid")

    operation_type: str = Field(
        description="Type of operation: 'ACCEPT', 'DISPLAY', 'READ', or 'WRITE'."
    )
    target_or_content: str = Field(description="Field accepted or literal text content displayed.")
    evidence: SourceEvidence = Field(description="Source citation for the I/O statement.")


class LegacyAssessment(BaseModel):
    """Top-level canonical assessment for a single COBOL source module (Version 2.0.0)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="2.0.0",
        description="Version of this assessment schema.",
    )
    program: ProgramIdentity = Field(description="Identity of the analyzed COBOL program.")
    data_fields: list[DataField] = Field(
        description="Key variables declared in Working-Storage or other data sections."
    )
    call_dependencies: list[CallDependency] = Field(
        description="External programs invoked via CALL statements."
    )
    menu_options: list[MenuOption] = Field(
        description="User menu options and branches handled in this program."
    )
    control_flow: list[ControlFlowConstruct] = Field(
        description="Control flow statements including loops, evaluations, and STOP RUN."
    )
    io_operations: list[IOOperation] = Field(
        description="Input and output statements directly visible in source (ACCEPT, DISPLAY)."
    )
    copybook_dependencies: list[str] = Field(
        description=(
            "List of copybook names imported via COPY statements. "
            "Must be explicitly empty if none exist."
        )
    )
