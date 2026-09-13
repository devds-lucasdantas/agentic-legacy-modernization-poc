"""Pydantic schemas for Gate 3 Multi-File System Assessment (Contract 3.5.1).

Defines neutral, structured system-level concepts and role-bound source evidence.
Strictly adheres to:
- Extra fields forbidden (extra='forbid').
- Zero fuzzy/NLP free-text comparisons: fields use canonical enums/tokens or exact coordinates.
- Role-bound multi-evidence models for relational and cross-program assertions.
- Reject, never repair: non-canonical model values are strictly rejected.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION: str = "3.5.1"


def validate_canonical_identifier(name: str, value: str) -> str:
    """Validate that a COBOL identifier is in canonical contract form.

    Enforces: non-empty, uppercase, no leading/trailing whitespace, no multiple spaces.
    Reject, never silently repair.
    """
    if not value or value != value.strip():
        raise ValueError(f"{name} must not have leading or trailing whitespace, got '{value}'")
    if "  " in value:
        raise ValueError(f"{name} must not contain consecutive internal spaces, got '{value}'")
    if value != value.upper():
        raise ValueError(f"{name} must be canonical uppercase identifier, got '{value}'")
    return value


def validate_canonical_literal_text(name: str, value: str) -> str:
    """Validate that source/literal text is in canonical unquoted form without whitespace repair."""
    if not value or value != value.strip():
        raise ValueError(f"{name} must not have leading or trailing whitespace, got '{value}'")
    if (value.startswith("'") and value.endswith("'")) or (
        value.startswith('"') and value.endswith('"')
    ):
        raise ValueError(f"{name} must not be enclosed in quotes, got '{value}'")
    return value


# ---------------------------------------------------------------------------
# Closed Categorical Domains
# ---------------------------------------------------------------------------

CallMechanism = Literal["LITERAL_TARGET", "DYNAMIC_TARGET"]
StatementType = Literal["STOP_RUN", "GOBACK", "EXIT_PROGRAM"]
ConstraintType = Literal["PROCESS_TERMINATION_ON_CALL", "RETURN_TO_CALLER"]
PlatformFamily = Literal["WINDOWS"]
ComputationVerb = Literal["ADD", "SUBTRACT"]
TransferVerb = Literal["MOVE"]
LifecycleAccessMode = Literal["INPUT", "OUTPUT", "IO", "EXTEND"]
LifecycleOperationVerb = Literal[
    "OPEN_INPUT",
    "OPEN_OUTPUT",
    "OPEN_IO",
    "OPEN_EXTEND",
    "READ",
    "WRITE",
    "REWRITE",
    "DELETE",
    "CLOSE",
]
OperationKind = Literal["DELETE", "RENAME", "COPY", "MOVE", "EXECUTE"]
RecordRelationType = Literal["IDENTICAL", "EQUIVALENT", "REPRESENTATION_MISMATCH"]
FileOrganization = Literal["LINE_SEQUENTIAL", "SEQUENTIAL", "INDEXED", "RELATIVE"]
CausalProvenance = Literal[
    "UNKNOWN",
    "INITIALIZER_DISCREPANCY",
    "CONCURRENT_MUTATION",
    "UNTRACKED_TRANSACTION_BATCH",
    "CORRUPTED_RECORD",
]
RiskCategory = Literal[
    "IO_ERROR_HANDLING",
    "DATA_INTEGRITY",
]
RiskBasisKind = Literal[
    "MISSING_ERROR_STATUS",
    "NON_ATOMIC_EXTERNAL_MUTATION",
]
ImpactCategory = Literal[
    "ERROR_VISIBILITY",
    "DATA_INTEGRITY",
]


class SourceEvidence(BaseModel):
    """Exact physical line coordinate span occupied by that statement only within a file."""

    model_config = ConfigDict(extra="forbid")

    file_path: str = Field(description="Normalized repository relative path of the source file")
    line_start: int = Field(
        ge=1,
        description="1-indexed physical start line occupied by the statement only (inclusive)",
    )
    line_end: int = Field(
        ge=1,
        description="1-indexed physical end line occupied by the statement only (inclusive)",
    )

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, v: str) -> str:
        if not v or v != v.strip():
            raise ValueError(f"file_path must not have leading or trailing whitespace, got '{v}'")
        if "\\" in v:
            raise ValueError(f"file_path must use forward slashes, got '{v}'")
        return v


class ProgramDeclaration(BaseModel):
    """Declares a COBOL compilation unit / program identified in the system."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(
        description="Program identifier from PROGRAM-ID division (logical identifier only)"
    )
    evidence: SourceEvidence = Field(
        description="Exact physical line span occupied by the PROGRAM-ID declaration statement only"
    )

    @field_validator("program_id")
    @classmethod
    def check_program_id(cls, v: str) -> str:
        return validate_canonical_identifier("program_id", v)


class CallOccurrence(BaseModel):
    """Exact physical occurrence of a CALL statement."""

    model_config = ConfigDict(extra="forbid")

    caller_program: str = Field(description="Enclosing program containing the CALL")
    target_program: str = Field(description="Target literal or identifier of the call")
    call_mechanism: CallMechanism = Field(
        description="Invocation mechanism: LITERAL_TARGET or DYNAMIC_TARGET"
    )
    argument_identifier: str | None = Field(
        default=None, description="Identifier passed in USING clause if present"
    )
    evidence: SourceEvidence = Field(
        description="Exact physical line span occupied by the CALL statement only"
    )

    @field_validator("caller_program")
    @classmethod
    def check_caller_program(cls, v: str) -> str:
        return validate_canonical_identifier("caller_program", v)

    @field_validator("target_program")
    @classmethod
    def check_target_program(cls, v: str) -> str:
        return validate_canonical_identifier("target_program", v)

    @field_validator("argument_identifier")
    @classmethod
    def check_argument_identifier(cls, v: str | None) -> str | None:
        if v is not None:
            return validate_canonical_identifier("argument_identifier", v)
        return v


class CallEdge(BaseModel):
    """Directed topological call edge between caller and target."""

    model_config = ConfigDict(extra="forbid")

    caller_program: str = Field(description="Calling program identifier")
    target_program: str = Field(description="Target program identifier")
    call_mechanism: CallMechanism = Field(
        description="Invocation mechanism: LITERAL_TARGET or DYNAMIC_TARGET"
    )
    evidence: SourceEvidence = Field(
        description=(
            "Exact physical line span occupied by the FIRST source-order "
            "CALL statement occurrence that establishes that unique directed edge"
        )
    )

    @field_validator("caller_program")
    @classmethod
    def check_caller_program(cls, v: str) -> str:
        return validate_canonical_identifier("caller_program", v)

    @field_validator("target_program")
    @classmethod
    def check_target_program(cls, v: str) -> str:
        return validate_canonical_identifier("target_program", v)


class InternalCallResolution(BaseModel):
    """Call occurrence that resolves internally within the system repository."""

    model_config = ConfigDict(extra="forbid")

    caller_program: str = Field(description="Calling program identifier")
    callee_program: str = Field(description="Callee program identifier resolved to internal file")
    call_evidence: SourceEvidence = Field(
        description="Exact physical line span occupied by the CALL statement in caller"
    )
    target_declaration_evidence: SourceEvidence = Field(
        description=(
            "Exact physical line span occupied by the target PROGRAM-ID declaration in callee"
        )
    )

    @field_validator("caller_program")
    @classmethod
    def check_caller_program(cls, v: str) -> str:
        return validate_canonical_identifier("caller_program", v)

    @field_validator("callee_program")
    @classmethod
    def check_callee_program(cls, v: str) -> str:
        return validate_canonical_identifier("callee_program", v)


class RecordField(BaseModel):
    """Field or condition name within a COBOL record declaration."""

    model_config = ConfigDict(extra="forbid")

    field_kind: Literal["DATA_FIELD", "CONDITION_NAME"] = Field(
        description=(
            "Field classification: DATA_FIELD (storage-bearing) or CONDITION_NAME (level-88)"
        )
    )
    level: int = Field(description="COBOL level number (e.g. 5, 88)")
    name: str = Field(description="Field or condition identifier")
    picture: str | None = Field(
        default=None,
        description=(
            "Canonical PICTURE clause body without 'PIC'/'PICTURE' keyword or terminal period"
        ),
    )
    usage: Literal["DISPLAY", "COMP-3", "BINARY"] | None = Field(
        default=None,
        description=(
            "Explicit storage USAGE: DISPLAY, COMP-3, BINARY "
            "(implicit COBOL usage must be explicit DISPLAY)"
        ),
    )
    condition_values: list[str] = Field(
        default_factory=list,
        description="Declared literal values for CONDITION_NAME (level-88)",
    )

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        return validate_canonical_identifier("name", v)

    @field_validator("picture")
    @classmethod
    def validate_picture(cls, v: str | None) -> str | None:
        if v is not None:
            if v != v.strip():
                raise ValueError(f"picture must not have leading or trailing whitespace, got '{v}'")
            upper = v.upper()
            if upper.startswith("PIC ") or upper.startswith("PICTURE "):
                raise ValueError(
                    "picture must be canonical specification without 'PIC'/'PICTURE' keyword, "
                    f"got '{v}'"
                )
            if v.endswith("."):
                raise ValueError(f"picture must not contain terminal period '.', got '{v}'")
            if v != upper:
                raise ValueError(f"picture must be uppercase specification, got '{v}'")
        return v

    @field_validator("condition_values")
    @classmethod
    def validate_condition_values(cls, v: list[str]) -> list[str]:
        for item in v:
            validate_canonical_literal_text("condition_values item", item)
        return v

    @model_validator(mode="after")
    def validate_field_usage_and_picture(self) -> "RecordField":
        if self.field_kind == "DATA_FIELD":
            if self.usage is None:
                raise ValueError(
                    f"DATA_FIELD '{self.name}' must explicitly declare usage "
                    "('DISPLAY', 'COMP-3', 'BINARY'); implicit COBOL usage must be explicit DISPLAY"
                )
            if self.picture is None:
                raise ValueError(f"DATA_FIELD '{self.name}' must provide picture specification")
        elif self.field_kind == "CONDITION_NAME":
            if self.usage is not None:
                raise ValueError(
                    f"CONDITION_NAME '{self.name}' must have null usage, got '{self.usage}'"
                )
            if self.picture is not None:
                raise ValueError(
                    f"CONDITION_NAME '{self.name}' must have null picture, got '{self.picture}'"
                )
        return self


class RecordLayout(BaseModel):
    """01 Record layout definition declared in program or copybook."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(
        description="Canonical logical container identifier without path or file extension"
    )
    record_name: str = Field(description="01 Record layout identifier")
    fields: list[RecordField] = Field(
        default_factory=list, description="Ordered elementary data fields and condition names"
    )
    evidence: SourceEvidence = Field(
        description=(
            "Exact physical line span occupied by the 01 record declaration "
            "and its constituent fields"
        )
    )

    @field_validator("program_id")
    @classmethod
    def validate_program_id(cls, v: str) -> str:
        u = v.upper()
        if "/" in v or "\\" in v or u.endswith(".CPY") or u.endswith(".CBL"):
            raise ValueError(
                f"program_id must be canonical logical identifier without path or file extension, "
                f"got '{v}'"
            )
        return validate_canonical_identifier("program_id", v)

    @field_validator("record_name")
    @classmethod
    def check_record_name(cls, v: str) -> str:
        return validate_canonical_identifier("record_name", v)


class RecordLayoutRelation(BaseModel):
    """Binary relationship or comparison between two record layouts."""

    model_config = ConfigDict(extra="forbid")

    layout_a_name: str = Field(
        description="First layout identifier formatted as CONTAINER:RECORD (e.g. CONTAINER:RECORD)"
    )
    layout_b_name: str = Field(
        description="Second layout identifier formatted as CONTAINER:RECORD (e.g. CONTAINER:RECORD)"
    )
    relation_type: RecordRelationType = Field(
        description="Relationship classification: IDENTICAL, EQUIVALENT, or REPRESENTATION_MISMATCH"
    )
    evidence_a: SourceEvidence = Field(description="Exact source evidence for layout A")
    evidence_b: SourceEvidence = Field(description="Exact source evidence for layout B")

    @field_validator("layout_a_name")
    @classmethod
    def check_layout_a(cls, v: str) -> str:
        if ":" not in v:
            raise ValueError(f"layout_a_name must be CONTAINER:RECORD, got '{v}'")
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError(f"layout_a_name must have single colon, got '{v}'")
        validate_canonical_identifier("layout_a container", parts[0])
        validate_canonical_identifier("layout_a record", parts[1])
        return v

    @field_validator("layout_b_name")
    @classmethod
    def check_layout_b(cls, v: str) -> str:
        if ":" not in v:
            raise ValueError(f"layout_b_name must be CONTAINER:RECORD, got '{v}'")
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError(f"layout_b_name must have single colon, got '{v}'")
        validate_canonical_identifier("layout_b container", parts[0])
        validate_canonical_identifier("layout_b record", parts[1])
        return v


class FileBinding(BaseModel):
    """SELECT clause mapping an internal file handle to an external dataset."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program declaring the file binding")
    internal_file_name: str = Field(description="COBOL FD / SELECT file identifier")
    external_file_name: str = Field(description="Target dataset literal assigned")
    organization: FileOrganization = Field(
        description="File organization: LINE_SEQUENTIAL, SEQUENTIAL, INDEXED, or RELATIVE"
    )
    evidence: SourceEvidence = Field(
        description="Exact physical line span occupied by the SELECT ... ASSIGN statement only"
    )

    @field_validator("program_id")
    @classmethod
    def check_program_id(cls, v: str) -> str:
        return validate_canonical_identifier("program_id", v)

    @field_validator("internal_file_name")
    @classmethod
    def check_internal_file_name(cls, v: str) -> str:
        return validate_canonical_identifier("internal_file_name", v)

    @field_validator("external_file_name")
    @classmethod
    def check_external_file_name(cls, v: str) -> str:
        return validate_canonical_literal_text("external_file_name", v)


class FileOperation(BaseModel):
    """Individual file I/O operation statement."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program executing the file operation")
    internal_file_name: str = Field(description="COBOL internal file handle")
    operation_verb: LifecycleOperationVerb = Field(
        description=(
            "COBOL I/O verb: OPEN_INPUT, OPEN_OUTPUT, OPEN_IO, OPEN_EXTEND, "
            "READ, WRITE, REWRITE, DELETE, CLOSE"
        )
    )
    evidence: SourceEvidence = Field(
        description="Exact physical line span occupied by the file I/O statement only"
    )

    @field_validator("program_id")
    @classmethod
    def check_program_id(cls, v: str) -> str:
        return validate_canonical_identifier("program_id", v)

    @field_validator("internal_file_name")
    @classmethod
    def check_internal_file_name(cls, v: str) -> str:
        return validate_canonical_identifier("internal_file_name", v)


class TerminationSite(BaseModel):
    """Explicit run-unit termination statement."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program containing the termination statement")
    statement_type: StatementType = Field(
        description="Termination verb: STOP_RUN, GOBACK, EXIT_PROGRAM"
    )
    evidence: SourceEvidence = Field(
        description="Exact physical line span occupied by the termination statement only"
    )

    @field_validator("program_id")
    @classmethod
    def check_program_id(cls, v: str) -> str:
        return validate_canonical_identifier("program_id", v)


class CallerContinuationConstraint(BaseModel):
    """Behavioral constraint where callee termination alters caller control flow."""

    model_config = ConfigDict(extra="forbid")

    caller_program: str = Field(description="Calling program expecting return")
    callee_program: str = Field(description="Invoked subprogram")
    constraint_type: ConstraintType = Field(
        description="Constraint effect: PROCESS_TERMINATION_ON_CALL or RETURN_TO_CALLER"
    )
    call_evidence: SourceEvidence = Field(
        description="Exact physical line span occupied by the CALL statement in caller"
    )
    callee_termination_evidence: SourceEvidence = Field(
        description="Exact physical line span occupied by the termination statement in callee"
    )

    @field_validator("caller_program")
    @classmethod
    def check_caller_program(cls, v: str) -> str:
        return validate_canonical_identifier("caller_program", v)

    @field_validator("callee_program")
    @classmethod
    def check_callee_program(cls, v: str) -> str:
        return validate_canonical_identifier("callee_program", v)


class CommandInvocation(BaseModel):
    """External OS shell command assembled and dispatched via SYSTEM."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program executing the command")
    command_template: str = Field(description="Command string literal or assembled template")
    target_operand: str = Field(description="Buffer variable passed to runtime system interface")
    assignment_evidence: SourceEvidence = Field(
        description="Exact physical line span of MOVE literal TO buffer"
    )
    call_evidence: SourceEvidence = Field(
        description="Exact physical line span of CALL 'SYSTEM' USING buffer"
    )

    @field_validator("program_id")
    @classmethod
    def check_program_id(cls, v: str) -> str:
        return validate_canonical_identifier("program_id", v)

    @field_validator("target_operand")
    @classmethod
    def check_target_operand(cls, v: str) -> str:
        return validate_canonical_identifier("target_operand", v)

    @field_validator("command_template")
    @classmethod
    def check_command_template(cls, v: str) -> str:
        return validate_canonical_literal_text("command_template", v)


class DataTransferRelation(BaseModel):
    """Record-to-record 01-level data movement between declared records."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program performing the transfer")
    source_entity: str = Field(description="Source 01-level record identifier")
    target_entity: str = Field(description="Destination 01-level record identifier")
    transfer_verb: TransferVerb = Field(description="COBOL data transfer verb: MOVE")
    evidence: SourceEvidence = Field(
        description="Exact physical line span occupied by the MOVE record statement only"
    )

    @field_validator("program_id")
    @classmethod
    def check_program_id(cls, v: str) -> str:
        return validate_canonical_identifier("program_id", v)

    @field_validator("source_entity")
    @classmethod
    def check_source_entity(cls, v: str) -> str:
        return validate_canonical_identifier("source_entity", v)

    @field_validator("target_entity")
    @classmethod
    def check_target_entity(cls, v: str) -> str:
        return validate_canonical_identifier("target_entity", v)


class ResourceLifecycle(BaseModel):
    """File or dataset access lifecycle within a procedural unit."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program accessing resource")
    resource_name: str = Field(description="Internal file or resource identifier")
    access_mode: LifecycleAccessMode = Field(
        description="Access mode: INPUT, OUTPUT, IO, or EXTEND"
    )
    ordered_operations: list[LifecycleOperationVerb] = Field(
        description=(
            "Ordered sequence of canonical lifecycle operation verbs (no descriptive modifiers)"
        )
    )
    evidence: SourceEvidence = Field(
        description=(
            "Exact physical line span from the FIRST resource operation through "
            "the LAST resource operation for that lifecycle"
        )
    )

    @field_validator("program_id")
    @classmethod
    def check_program_id(cls, v: str) -> str:
        return validate_canonical_identifier("program_id", v)

    @field_validator("resource_name")
    @classmethod
    def check_resource_name(cls, v: str) -> str:
        return validate_canonical_identifier("resource_name", v)

    @field_validator("ordered_operations")
    @classmethod
    def validate_ordered_operations(
        cls, v: list[LifecycleOperationVerb]
    ) -> list[LifecycleOperationVerb]:
        for op in v:
            if "(" in str(op) or ")" in str(op):
                raise ValueError(
                    f"ordered_operations must be canonical operation verbs "
                    f"without descriptive modifiers, got '{op}'"
                )
        return v


class OperationSequence(BaseModel):
    """Strict temporal ordering between two procedural operations."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program containing the sequence")
    first_operation: OperationKind = Field(
        description="First operation kind: DELETE, RENAME, COPY, MOVE, EXECUTE"
    )
    second_operation: OperationKind = Field(
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

    @field_validator("program_id")
    @classmethod
    def check_program_id(cls, v: str) -> str:
        return validate_canonical_identifier("program_id", v)


class ComputationDataflow(BaseModel):
    """Dataflow accumulation or transformation between fields."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program performing computation")
    source_field: str = Field(description="Input operand field")
    target_field: str = Field(description="Accumulating target field")
    operation_verb: ComputationVerb = Field(
        description="Arithmetic operation verb: ADD or SUBTRACT"
    )
    evidence: SourceEvidence = Field(
        description="Exact physical line span occupied by the computation statement only"
    )

    @field_validator("program_id")
    @classmethod
    def check_program_id(cls, v: str) -> str:
        return validate_canonical_identifier("program_id", v)

    @field_validator("source_field")
    @classmethod
    def check_source_field(cls, v: str) -> str:
        return validate_canonical_identifier("source_field", v)

    @field_validator("target_field")
    @classmethod
    def check_target_field(cls, v: str) -> str:
        return validate_canonical_identifier("target_field", v)


class PlatformDependency(BaseModel):
    """Environment or operating system platform constraint."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Program containing dependency")
    platform_family: PlatformFamily = Field(description="Platform family identifier (WINDOWS)")
    command_literal: str = Field(
        description=(
            "Exact concrete platform-specific command syntax literal invoked "
            "(no templates or placeholders)"
        )
    )
    evidence: SourceEvidence = Field(
        description="Exact physical line span of the statement containing the command literal"
    )

    @field_validator("program_id")
    @classmethod
    def check_program_id(cls, v: str) -> str:
        return validate_canonical_identifier("program_id", v)

    @field_validator("command_literal")
    @classmethod
    def validate_command_literal(cls, v: str) -> str:
        val = validate_canonical_literal_text("command_literal", v)
        if "<" in val or ">" in val or "..." in val or "*" in val:
            raise ValueError(
                f"command_literal must be an exact discrete command literal, "
                f"not a regex or template: '{v}'"
            )
        return val


class BehavioralRisk(BaseModel):
    """Identified operational or architectural defect supported by source evidence."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(description="Affected program identifier")
    risk_category: RiskCategory = Field(
        description="Standardized risk category classification representing system fault domain"
    )
    risk_basis_kind: RiskBasisKind = Field(
        description="Standardized underlying operational or architectural risk basis kind"
    )
    impact_category: ImpactCategory = Field(description="Standardized system impact classification")
    resource_name: str | None = Field(
        default=None,
        description=(
            "Internal resource or dataset name associated with the risk (e.g. internal file name "
            "for file-scoped risks, target canonical dataset for external mutation risks, "
            "or null if not resource-scoped)"
        ),
    )
    operation_evidence: SourceEvidence = Field(
        description=(
            "Exact physical line span of the operation envelope (for MISSING_ERROR_STATUS: "
            "from first grounded file operation through last grounded file operation on affected "
            "binding; for NON_ATOMIC_EXTERNAL_MUTATION: exact mutation dispatch interval covering "
            "the external mutation calls)"
        )
    )
    affected_resource_evidence: SourceEvidence = Field(
        description=(
            "Exact physical line span of the affected resource declaration "
            "(for MISSING_ERROR_STATUS: exact SELECT/ASSIGN binding span; "
            "for NON_ATOMIC_EXTERNAL_MUTATION: exact target-identifying command assignment "
            "statement)"
        )
    )

    @field_validator("program_id")
    @classmethod
    def check_program_id(cls, v: str) -> str:
        return validate_canonical_identifier("program_id", v)

    @field_validator("resource_name")
    @classmethod
    def check_resource_name(cls, v: str | None) -> str | None:
        if v is not None:
            return validate_canonical_identifier("resource_name", v)
        return v


class DataStateComparison(BaseModel):
    """Observed discrepancy between data file contents and source initializer code."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(description="Target entity/account identifier compared")
    dat_record_value: str = Field(description="Value observed in persistent DAT record")
    initializer_code_value: str = Field(description="Value written by initialization program")
    causal_provenance: CausalProvenance = Field(
        description=(
            "Causal provenance classification: UNKNOWN, INITIALIZER_DISCREPANCY, "
            "CONCURRENT_MUTATION, UNTRACKED_TRANSACTION_BATCH, or CORRUPTED_RECORD"
        )
    )
    dat_evidence: SourceEvidence = Field(description="Evidence from data file")
    initializer_evidence: SourceEvidence = Field(description="Evidence from initializer program")

    @field_validator("entity_id")
    @classmethod
    def check_entity_id(cls, v: str) -> str:
        return validate_canonical_identifier("entity_id", v)

    @field_validator("dat_record_value")
    @classmethod
    def check_dat_record_value(cls, v: str) -> str:
        return validate_canonical_literal_text("dat_record_value", v)

    @field_validator("initializer_code_value")
    @classmethod
    def check_initializer_code_value(cls, v: str) -> str:
        return validate_canonical_literal_text("initializer_code_value", v)


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
