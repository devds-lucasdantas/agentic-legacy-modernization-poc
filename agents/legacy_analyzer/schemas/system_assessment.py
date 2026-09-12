"""Pydantic schemas for Gate 3 Multi-File System Assessment (Candidate V3.1).

Defines neutral, structured system-level concepts and role-bound source evidence.
Strictly adheres to:
- Extra fields forbidden (extra='forbid').
- Zero fuzzy/NLP free-text comparisons: fields use canonical enums/tokens or exact coordinates.
- Role-bound multi-evidence models for relational and cross-program assertions.
"""

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION: str = "3.4.0"


class SourceEvidence(BaseModel):
    """Exact physical line coordinate span within a verified bundle file."""

    model_config = ConfigDict(extra="forbid")

    file_path: str = Field(description="Normalized repository relative path of the source file")
    line_start: int = Field(ge=1, description="1-indexed physical start line (inclusive)")
    line_end: int = Field(ge=1, description="1-indexed physical end line (inclusive)")


class ProgramDeclaration(BaseModel):
    """Declares a COBOL compilation unit / program identified in the system."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program identifier from PROGRAM-ID division")
    evidence: SourceEvidence


class CallOccurrence(BaseModel):
    """Exact physical occurrence of a CALL statement."""

    model_config = ConfigDict(extra="forbid")

    caller_program: str = Field(description="Enclosing program containing the CALL")
    target_program: str = Field(description="Target literal or identifier of the call")
    call_mechanism: str = Field(
        description="Invocation mechanism: LITERAL_TARGET or DYNAMIC_TARGET"
    )
    argument_identifier: str | None = Field(
        default=None, description="Identifier passed in USING clause if present"
    )
    evidence: SourceEvidence


class CallEdge(BaseModel):
    """Directed topological call edge between caller and target."""

    model_config = ConfigDict(extra="forbid")

    caller_program: str = Field(description="Calling program identifier")
    target_program: str = Field(description="Target program identifier")
    call_mechanism: str = Field(
        description="Invocation mechanism: LITERAL_TARGET or DYNAMIC_TARGET"
    )
    evidence: SourceEvidence


class InternalCallResolution(BaseModel):
    """Call occurrence that resolves internally within the system repository."""

    model_config = ConfigDict(extra="forbid")

    caller_program: str = Field(description="Calling program identifier")
    callee_program: str = Field(description="Callee program identifier resolved to internal file")
    call_evidence: SourceEvidence = Field(description="Evidence of the CALL statement")
    target_declaration_evidence: SourceEvidence = Field(
        description="Evidence of the target PROGRAM-ID declaration"
    )


class RecordField(BaseModel):
    """Field or condition name within a COBOL record declaration."""

    model_config = ConfigDict(extra="forbid")

    field_kind: str = Field(
        description=(
            "Field classification: DATA_FIELD (storage-bearing) or CONDITION_NAME (level-88)"
        )
    )
    level: int = Field(description="COBOL level number (e.g. 5, 88)")
    name: str = Field(description="Field or condition identifier")
    picture: str | None = Field(default=None, description="PICTURE clause if DATA_FIELD")
    usage: str | None = Field(
        default=None, description="Storage USAGE if DATA_FIELD: DISPLAY, COMP-3, BINARY"
    )
    condition_values: list[str] = Field(
        default_factory=list,
        description="Declared literal values for CONDITION_NAME (level-88)",
    )


class RecordLayout(BaseModel):
    """01 Record layout definition declared in program or copybook."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program or copybook declaring the record layout")
    record_name: str = Field(description="01 Record layout identifier")
    fields: list[RecordField] = Field(
        default_factory=list, description="Ordered elementary data fields and condition names"
    )
    evidence: SourceEvidence


class RecordLayoutRelation(BaseModel):
    """Binary relationship or comparison between two record layouts."""

    model_config = ConfigDict(extra="forbid")

    layout_a_name: str = Field(description="First layout identifier (e.g. container:field)")
    layout_b_name: str = Field(description="Second layout identifier (e.g. container:field)")
    relation_type: str = Field(
        description="Relationship classification: IDENTICAL, EQUIVALENT, or REPRESENTATION_MISMATCH"
    )
    evidence_a: SourceEvidence = Field(description="Source evidence for layout A")
    evidence_b: SourceEvidence = Field(description="Source evidence for layout B")


class FileBinding(BaseModel):
    """SELECT clause mapping an internal file handle to an external dataset."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program declaring the file binding")
    internal_file_name: str = Field(description="COBOL FD / SELECT file identifier")
    external_file_name: str = Field(description="Target dataset literal assigned")
    organization: str = Field(description="File organization: LINE_SEQUENTIAL, SEQUENTIAL, etc.")
    evidence: SourceEvidence


class FileOperation(BaseModel):
    """Individual file I/O operation statement."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program executing the file operation")
    internal_file_name: str = Field(description="COBOL internal file handle")
    operation_verb: str = Field(
        description="COBOL I/O verb: OPEN_INPUT, OPEN_OUTPUT, READ, WRITE, CLOSE"
    )
    evidence: SourceEvidence


class TerminationSite(BaseModel):
    """Explicit run-unit termination statement."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program containing the termination statement")
    statement_type: str = Field(description="Termination verb: STOP_RUN, GOBACK, EXIT_PROGRAM")
    evidence: SourceEvidence


class CallerContinuationConstraint(BaseModel):
    """Behavioral constraint where callee termination alters caller control flow."""

    model_config = ConfigDict(extra="forbid")

    caller_program: str = Field(description="Calling program expecting return")
    callee_program: str = Field(description="Invoked subprogram")
    constraint_type: str = Field(
        description="Constraint effect: PROCESS_TERMINATION_ON_CALL or RETURN_TO_CALLER"
    )
    call_evidence: SourceEvidence = Field(description="Evidence of the CALL statement")
    callee_termination_evidence: SourceEvidence = Field(
        description="Evidence of the subprogram termination statement"
    )


class CommandInvocation(BaseModel):
    """External OS shell command assembled and dispatched via SYSTEM."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program executing the command")
    command_template: str = Field(description="Command string literal or assembled template")
    target_operand: str = Field(description="Buffer variable passed to runtime system interface")
    assignment_evidence: SourceEvidence = Field(description="Evidence of MOVE literal TO buffer")
    call_evidence: SourceEvidence = Field(description="Evidence of CALL 'SYSTEM' USING buffer")


class DataTransferRelation(BaseModel):
    """Record-to-record or inter-variable data movement."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program performing the transfer")
    source_entity: str = Field(description="Source field or record identifier")
    target_entity: str = Field(description="Destination field or record identifier")
    transfer_verb: str = Field(description="COBOL data transfer verb: MOVE")
    evidence: SourceEvidence


class ResourceLifecycle(BaseModel):
    """Aggregated lifecycle of a resource across operations within a program."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program accessing the resource")
    resource_name: str = Field(description="Internal file or resource identifier")
    access_mode: str = Field(description="Access mode: INPUT or OUTPUT")
    ordered_operations: list[str] = Field(description="Ordered sequence of operations performed")
    evidence: SourceEvidence


class OperationSequence(BaseModel):
    """Strict temporal ordering between two procedural operations."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program containing the sequence")
    first_operation: str = Field(
        description="First operation kind: DELETE, RENAME, COPY, MOVE, EXECUTE"
    )
    second_operation: str = Field(
        description="Second operation kind: DELETE, RENAME, COPY, MOVE, EXECUTE"
    )
    first_assignment_evidence: SourceEvidence = Field(
        description="Evidence of first command literal assignment"
    )
    first_call_evidence: SourceEvidence = Field(
        description="Evidence of first command dispatch call"
    )
    second_assignment_evidence: SourceEvidence = Field(
        description="Evidence of second command literal assignment"
    )
    second_call_evidence: SourceEvidence = Field(
        description="Evidence of second command dispatch call"
    )


class ComputationDataflow(BaseModel):
    """Dataflow accumulation or transformation between fields."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program performing computation")
    source_field: str = Field(description="Input operand field")
    target_field: str = Field(description="Accumulating target field")
    operation_verb: str = Field(description="Arithmetic or movement verb: ADD, SUBTRACT, MOVE")
    evidence: SourceEvidence


class PlatformDependency(BaseModel):
    """Environment or operating system platform constraint."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program containing dependency")
    platform_family: str = Field(
        description="Platform family identifier (e.g. WINDOWS, POSIX, MAINFRAME_OS)"
    )
    command_literal: str = Field(description="Platform-specific command syntax invoked")
    evidence: SourceEvidence


class BehavioralRisk(BaseModel):
    """Identified operational or architectural defect supported by source evidence."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Affected program identifier")
    risk_category: str = Field(
        description=(
            "Standardized risk category classification representing system fault domain: "
            "IO_ERROR_HANDLING, DATA_INTEGRITY, CONTROL_FLOW, PORTABILITY, "
            "RESOURCE_LIFECYCLE, CONCURRENCY_ERROR, DATA_CORRUPTION, CONFIGURATION"
        )
    )
    risk_basis_kind: str = Field(
        description=(
            "Standardized underlying risk basis kind: MISSING_ERROR_STATUS, "
            "NON_ATOMIC_EXTERNAL_MUTATION, NON_RETURNING_TERMINATION, "
            "UNCHECKED_EXTERNAL_RESULT, INVALID_INPUT_HANDLING, RESOURCE_LIFECYCLE_FAILURE, "
            "RESOURCE_LEAK, DEADLOCK_RISK, INCORRECT_PRECISION, INCOMPLETE_INITIALIZATION"
        )
    )
    impact_category: str = Field(
        description=(
            "System impact classification: AVAILABILITY, "
            "ERROR_VISIBILITY, CONTROL_FLOW, DATA_INTEGRITY, PORTABILITY, "
            "SECURITY_INTEGRITY, PERFORMANCE"
        )
    )
    resource_name: str | None = Field(
        default=None,
        description=(
            "Internal resource or dataset name associated with the risk (e.g. internal file name "
            "for file-scoped risks, target canonical dataset for external mutation risks, "
            "or null if not resource-scoped)"
        ),
    )
    operation_evidence: SourceEvidence = Field(description="Evidence for unhandled operation")
    affected_resource_evidence: SourceEvidence = Field(
        description="Evidence for affected resource or file binding"
    )


class DataStateComparison(BaseModel):
    """Observed discrepancy between data file contents and source initializer code."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(description="Target entity/account identifier compared")
    dat_record_value: str = Field(description="Value observed in persistent DAT record")
    initializer_code_value: str = Field(description="Value written by initialization program")
    causal_provenance: str = Field(
        description=(
            "Causal provenance classification (e.g. UNKNOWN, INITIALIZER_DISCREPANCY, "
            "CONCURRENT_MUTATION, UNTRACKED_TRANSACTION_BATCH, CORRUPTED_RECORD)"
        )
    )
    dat_evidence: SourceEvidence = Field(description="Evidence from data file")
    initializer_evidence: SourceEvidence = Field(description="Evidence from initializer program")


class SystemAssessment(BaseModel):
    """Comprehensive system-level architectural assessment for Gate 3."""

    model_config = ConfigDict(extra="forbid")

    system_name: str = Field(description="Formal name of the analyzed legacy system")
    program_declarations: list[ProgramDeclaration] = Field(
        default_factory=list, description="All declared programs in the system"
    )
    call_occurrences: list[CallOccurrence] = Field(
        default_factory=list, description="All individual CALL occurrences"
    )
    call_edges: list[CallEdge] = Field(
        default_factory=list, description="Unique topological call graph edges"
    )
    internal_call_resolutions: list[InternalCallResolution] = Field(
        default_factory=list, description="Internal cross-program call resolutions"
    )
    record_layouts: list[RecordLayout] = Field(
        default_factory=list, description="Core record field declarations"
    )
    record_layout_relations: list[RecordLayoutRelation] = Field(
        default_factory=list, description="Binary comparisons between record representations"
    )
    file_bindings: list[FileBinding] = Field(
        default_factory=list, description="File-control SELECT/ASSIGN dataset bindings"
    )
    file_operations: list[FileOperation] = Field(
        default_factory=list, description="Individual file operations"
    )
    termination_sites: list[TerminationSite] = Field(
        default_factory=list, description="Program termination statements"
    )
    caller_continuation_constraints: list[CallerContinuationConstraint] = Field(
        default_factory=list,
        description="Caller control flow constraints imposed by callee termination",
    )
    command_invocations: list[CommandInvocation] = Field(
        default_factory=list, description="External command invocations via SYSTEM"
    )
    data_transfer_relations: list[DataTransferRelation] = Field(
        default_factory=list, description="Record-to-record data transfer relations"
    )
    resource_lifecycles: list[ResourceLifecycle] = Field(
        default_factory=list, description="Resource lifecycle sequences"
    )
    operation_sequences: list[OperationSequence] = Field(
        default_factory=list, description="Temporal operation sequences"
    )
    computation_dataflows: list[ComputationDataflow] = Field(
        default_factory=list, description="Arithmetic computation dataflows"
    )
    platform_dependencies: list[PlatformDependency] = Field(
        default_factory=list, description="Host operating system platform dependencies"
    )
    behavioral_risks: list[BehavioralRisk] = Field(
        default_factory=list, description="System behavioral risks"
    )
    data_state_comparisons: list[DataStateComparison] = Field(
        default_factory=list, description="Discrepancies between data state and initializer code"
    )
