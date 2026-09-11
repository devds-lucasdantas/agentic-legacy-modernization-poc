"""Pydantic v2 schemas for structured legacy COBOL assessments (Version 2.3.0).

Designed for OpenAI Responses API native Structured Outputs (`responses.parse`).
Uses strict variant models combined through standard unions to produce supported
`anyOf` JSON schema constructs without unsupported `oneOf` or `discriminator` properties:
- MenuOption: CallMenuOption | DisplayMenuOption
- ControlFlowConstruct: PerformUntilConstruct | EvaluateConstruct | StopRunConstruct
- IOOperation: AcceptIO | DisplayIO

All field descriptions are completely generic and free of fixture answer hints.
Host-controlled execution metadata (file path, SHA256, schema version, callee boundaries) is
managed outside this schema.
Evidence citations contain exact line coordinates [line_start, line_end] only;
text snippets are derived host-side from verified source code.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceEvidence(BaseModel):
    """Traceable line coordinates in the analyzed source code (Version 2.3.0)."""

    model_config = ConfigDict(extra="forbid")

    line_start: int = Field(description="1-indexed starting line number in the source file.")
    line_end: int = Field(description="1-indexed ending line number in the source file.")


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
        description="PICTURE clause string if declared, without PIC keyword, or null if unpictured."
    )
    section: str = Field(
        description="Data division section where declared (e.g. 'WORKING-STORAGE', 'FILE')."
    )
    evidence: SourceEvidence = Field(description="Source citation for the variable declaration.")


# Strict Menu Option Variant Models
class CallMenuOption(BaseModel):
    """Menu choice or evaluation branch that invokes an external subprogram."""

    model_config = ConfigDict(extra="forbid")

    action_type: Literal["CALL"] = Field(description="Action discriminant type 'CALL'.")
    option_key: str = Field(
        description="The selection key or branch condition literal (e.g. '1', '2')."
    )
    target_program: str = Field(
        description="The name of the external subprogram invoked by this menu branch."
    )
    evidence: SourceEvidence = Field(
        description="Source citation for this option's branch condition and CALL invocation."
    )


class DisplayMenuOption(BaseModel):
    """Menu choice or evaluation branch that displays a message to the user."""

    model_config = ConfigDict(extra="forbid")

    action_type: Literal["DISPLAY"] = Field(description="Action discriminant type 'DISPLAY'.")
    option_key: str = Field(
        description="The selection key or branch condition literal (e.g. '4', 'OTHER')."
    )
    display_literal: str = Field(
        description="Literal message displayed when this menu branch is selected."
    )
    evidence: SourceEvidence = Field(
        description="Source citation for this option's branch condition and DISPLAY statement."
    )


MenuOption = CallMenuOption | DisplayMenuOption


# Strict Control Flow Variant Models
class PerformUntilConstruct(BaseModel):
    """Loop construct executed until a termination condition is met."""

    model_config = ConfigDict(extra="forbid")

    construct_type: Literal["PERFORM_UNTIL"] = Field(
        description="Construct discriminant type 'PERFORM_UNTIL'."
    )
    condition: str = Field(
        description="The loop termination condition expression following the UNTIL keyword."
    )
    evidence: SourceEvidence = Field(
        description="Source citation for the PERFORM UNTIL loop construct."
    )


class EvaluateConstruct(BaseModel):
    """Multi-way branch or decision table construct (EVALUATE)."""

    model_config = ConfigDict(extra="forbid")

    construct_type: Literal["EVALUATE"] = Field(
        description="Construct discriminant type 'EVALUATE'."
    )
    subject: str = Field(
        description="The expression or identifier evaluated in the EVALUATE statement."
    )
    evidence: SourceEvidence = Field(
        description="Source citation for the EVALUATE statement header and subject."
    )


class StopRunConstruct(BaseModel):
    """Program termination statement (STOP RUN)."""

    model_config = ConfigDict(extra="forbid")

    construct_type: Literal["STOP_RUN"] = Field(
        description="Construct discriminant type 'STOP_RUN'."
    )
    evidence: SourceEvidence = Field(description="Source citation for the STOP RUN statement.")


ControlFlowConstruct = PerformUntilConstruct | EvaluateConstruct | StopRunConstruct


# Strict I/O Operation Variant Models
class AcceptIO(BaseModel):
    """Terminal input operation (ACCEPT)."""

    model_config = ConfigDict(extra="forbid")

    operation_type: Literal["ACCEPT"] = Field(
        description="I/O operation discriminant type 'ACCEPT'."
    )
    target_identifier: str = Field(description="Field or identifier into which input is accepted.")
    evidence: SourceEvidence = Field(description="Source citation for the ACCEPT statement.")


class DisplayIO(BaseModel):
    """Terminal output operation (DISPLAY)."""

    model_config = ConfigDict(extra="forbid")

    operation_type: Literal["DISPLAY"] = Field(
        description="I/O operation discriminant type 'DISPLAY'."
    )
    literal: str = Field(description="Literal text or variable content displayed to the terminal.")
    evidence: SourceEvidence = Field(description="Source citation for the DISPLAY statement.")


IOOperation = AcceptIO | DisplayIO


class LegacyAssessment(BaseModel):
    """Top-level canonical assessment for a single COBOL source module (Version 2.1.0).

    Host execution metadata (schema_version, git_commit_sha, prompt_version) is tracked
    externally in ExecutionMetadata.
    """

    model_config = ConfigDict(extra="forbid")

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
            "Must be explicitly empty list if none exist."
        )
    )
