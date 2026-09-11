"""Pydantic v2 schemas for structured multi-file COBOL system assessments (Version 3.0.0).

Designed for OpenAI Responses API native Structured Outputs (`responses.parse`).
All field descriptions are completely generic and free of fixture answer hints.
Adheres strictly to Guardrail A:
- ZERO fuzzy or LLM semantic evaluation.
- Canonical structured and normalized primitives.
- Exact generic verification against AST ground-truth index.
"""

from pydantic import BaseModel, ConfigDict, Field


class SourceEvidence(BaseModel):
    """Traceable line coordinates and file path in the analyzed multi-file bundle."""

    model_config = ConfigDict(extra="forbid")

    file_path: str = Field(description="Relative repository path of the cited source file.")
    line_start: int = Field(description="1-indexed starting line number in the source file.")
    line_end: int = Field(description="1-indexed ending line number in the source file.")


class SystemComponent(BaseModel):
    """Identified program or component within the system topology."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="COBOL PROGRAM-ID identifier declared in the source.")
    component_role: str = Field(description="Primary architectural role of the component.")
    evidence: SourceEvidence = Field(description="Source citation for the component declaration.")


class CrossProgramCall(BaseModel):
    """Inter-program CALL invocation."""

    model_config = ConfigDict(extra="forbid")

    caller_program: str = Field(description="Program identifier executing the CALL statement.")
    callee_program: str = Field(description="Target program identifier invoked by the CALL.")
    call_mechanism: str = Field(description="Invocation mechanism (e.g. DYNAMIC_CALL_LITERAL).")
    evidence: SourceEvidence = Field(description="Source citation for the CALL statement.")


class MenuDispatchOption(BaseModel):
    """Menu selection or option branch that dispatches to an action or program."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program identifier containing the selection construct.")
    menu_key: str = Field(description="Branch selection literal or key (e.g. '1', '2', '3').")
    target_action: str = Field(description="Target subprogram or action dispatched by this option.")
    evidence: SourceEvidence = Field(description="Source citation for this dispatch branch.")


class SharedCopybookReference(BaseModel):
    """Inclusion of a shared copybook schema within a program."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program including the shared copybook.")
    copybook_name: str = Field(description="Filename or identifier of the shared copybook.")
    evidence: SourceEvidence = Field(description="Source citation for the copybook inclusion.")


class RecordFieldDeclaration(BaseModel):
    """Data field declared within a shared record or copybook."""

    model_config = ConfigDict(extra="forbid")

    container_name: str = Field(description="Parent record or structure containing the field.")
    field_name: str = Field(description="Identifier of the declared data field.")
    picture_clause: str = Field(description="PICTURE clause definition of the field.")
    storage_format: str = Field(description="Storage format representation (e.g. COMP-3, DISPLAY).")
    evidence: SourceEvidence = Field(description="Source citation for the field declaration.")


class DataFlowTransfer(BaseModel):
    """Data transfer operation between structures, records, or files."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program executing the data transfer.")
    source_entity: str = Field(description="Source variable, record, or file entity.")
    target_entity: str = Field(description="Destination variable, record, or file entity.")
    transfer_verb: str = Field(description="Statement verb performing transfer (e.g. MOVE, WRITE).")
    evidence: SourceEvidence = Field(description="Source citation for the transfer operation.")


class ResourceLifecycle(BaseModel):
    """File or resource lifecycle operations within a program."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program managing the resource lifecycle.")
    resource_name: str = Field(description="Identifier of the file or external resource.")
    access_mode: str = Field(
        description="Access mode used to open the resource (e.g. INPUT, OUTPUT, I-O)."
    )
    operations: list[str] = Field(
        description="Ordered sequence of lifecycle operations (e.g. ['OPEN', 'READ', 'CLOSE'])."
    )
    evidence: SourceEvidence = Field(
        description="Source citation spanning the resource operations."
    )


class ControlFlowLoop(BaseModel):
    """Iterative loop construct in procedural logic."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program containing the iterative loop.")
    loop_predicate: str = Field(description="Exit condition predicate (e.g. UNTIL condition).")
    evidence: SourceEvidence = Field(description="Source citation for the loop construct.")


class EvaluateSelection(BaseModel):
    """Multi-way selection construct in procedural logic."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program containing the selection construct.")
    selection_subject: str = Field(description="Variable or expression evaluated across branches.")
    evidence: SourceEvidence = Field(description="Source citation for the EVALUATE construct.")


class ArithmeticComputation(BaseModel):
    """Mathematical computation or counter operation."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program performing the computation.")
    verb: str = Field(description="Arithmetic statement verb (e.g. ADD, SUBTRACT, COMPUTE).")
    operand: str = Field(description="Operand value, field, or literal used in computation.")
    target_field: str = Field(description="Target accumulator or variable receiving result.")
    evidence: SourceEvidence = Field(description="Source citation for the arithmetic statement.")


class ConditionalBranch(BaseModel):
    """Conditional decision predicate or branch handler."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program containing the conditional check.")
    condition_kind: str = Field(
        description="Category of conditional check (e.g. IF_PREDICATE, AT_END, WHEN_OTHER)."
    )
    predicate: str = Field(description="Logical predicate or branch condition expression.")
    evidence: SourceEvidence = Field(description="Source citation for the conditional check.")


class InteractiveIO(BaseModel):
    """Console or terminal interaction."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program performing interactive I/O.")
    io_verb: str = Field(description="Interaction verb (e.g. DISPLAY, ACCEPT).")
    target_identifier: str = Field(
        description="Target variable accepted or message content displayed."
    )
    evidence: SourceEvidence = Field(description="Source citation for the I/O statement.")


class ProgramTermination(BaseModel):
    """Run-unit or program exit point."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program containing the termination statement.")
    termination_verb: str = Field(
        description="Termination verb (e.g. STOP RUN, EXIT PROGRAM, GOBACK)."
    )
    evidence: SourceEvidence = Field(description="Source citation for the termination statement.")


class BehavioralRisk(BaseModel):
    """Behavioral edge case, input risk, or operational vulnerability."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program or component where the risk manifests.")
    risk_category: str = Field(description="Classification of the behavioral risk.")
    precondition: str = Field(description="Grounded state or condition triggering the risk.")
    ordered_operations: list[str] = Field(
        description="Canonical sequence of operations leading to risk."
    )
    possible_consequence: str = Field(description="Potential impact or failure mode of the risk.")
    severity: str = Field(description="Assessed severity level (e.g. HIGH, MEDIUM, LOW).")
    evidence: SourceEvidence = Field(description="Source citation demonstrating the risk.")


class ArchitecturalRisk(BaseModel):
    """System-level architectural anti-pattern or cross-cutting constraint."""

    model_config = ConfigDict(extra="forbid")

    risk_id: str = Field(description="Unique canonical identifier for the architectural pattern.")
    risk_type: str = Field(description="Category of architectural constraint or risk.")
    affected_components: list[str] = Field(description="List of programs or components impacted.")
    architectural_consequence: str = Field(
        description="System-level architectural consequence or debt."
    )
    severity: str = Field(description="Assessed severity level (e.g. HIGH, MEDIUM, LOW).")
    evidence: SourceEvidence = Field(description="Representative source citation in system.")


class WorkingStorageState(BaseModel):
    """Working-storage state variable and operational role."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program declaring the working storage variable.")
    variable_name: str = Field(description="Identifier of the state variable.")
    picture_clause: str = Field(description="Declared PICTURE clause data type.")
    state_role: str = Field(
        description="Operational role of the variable (e.g. status flag, accumulator)."
    )
    evidence: SourceEvidence = Field(description="Source citation for the variable declaration.")


class SystemExecutionProtocol(BaseModel):
    """System-wide multi-program workflow or execution protocol."""

    model_config = ConfigDict(extra="forbid")

    protocol_name: str = Field(description="Canonical identifier for the multi-program workflow.")
    ordered_phases: list[str] = Field(
        description="Ordered sequence of high-level phases in protocol."
    )
    evidence: SourceEvidence = Field(
        description="Representative source citation grounding the protocol."
    )


class SystemAssessment(BaseModel):
    """Root container for multi-file legacy COBOL system assessment (Version 3.0.0)."""

    model_config = ConfigDict(extra="forbid")

    system_name: str = Field(description="Name or title of the analyzed legacy system.")
    components: list[SystemComponent] = Field(description="Identified system components and roles.")
    cross_program_calls: list[CrossProgramCall] = Field(
        description="Inter-program CALL invocations."
    )
    menu_dispatches: list[MenuDispatchOption] = Field(
        description="Menu selection dispatch branches."
    )
    copybook_references: list[SharedCopybookReference] = Field(
        description="Shared copybook inclusions."
    )
    record_fields: list[RecordFieldDeclaration] = Field(
        description="Shared record and copybook field layouts."
    )
    data_transfers: list[DataFlowTransfer] = Field(
        description="Cross-program and file data transfers."
    )
    resource_lifecycles: list[ResourceLifecycle] = Field(
        description="Shared file and resource lifecycles."
    )
    control_flow_loops: list[ControlFlowLoop] = Field(
        description="Iterative loops in procedural logic."
    )
    evaluate_selections: list[EvaluateSelection] = Field(
        description="Selection constructs in procedural logic."
    )
    arithmetic_computations: list[ArithmeticComputation] = Field(
        description="Arithmetic operations and counters."
    )
    conditional_branches: list[ConditionalBranch] = Field(
        description="Conditional checks and branch handlers."
    )
    interactive_io_operations: list[InteractiveIO] = Field(
        description="Interactive console I/O statements."
    )
    terminations: list[ProgramTermination] = Field(
        description="Run-unit and program termination points."
    )
    behavioral_risks: list[BehavioralRisk] = Field(
        description="Behavioral edge cases and operational risks."
    )
    architectural_risks: list[ArchitecturalRisk] = Field(
        description="System-level architectural risks and patterns."
    )
    working_storage_states: list[WorkingStorageState] = Field(
        description="Working-storage state variables."
    )
    system_protocols: list[SystemExecutionProtocol] = Field(
        description="Cross-file execution workflows and protocols."
    )
