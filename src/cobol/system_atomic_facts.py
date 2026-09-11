"""Canonical System Atomic Fact representations for Gate 3 COBOL System Analysis (Candidate V3.1).

Defines normalized, immutable, hashable domain primitives matching the 18 approved
model-visible concepts and role-bound source evidence.
Strictly adheres to Guardrail A:
- ZERO reliance on fuzzy/NLP/LLM semantic evaluation.
- Deterministic canonicalization and exact comparison.
- Role-bound multi-evidence coordinates for relational facts.
"""

from dataclasses import dataclass, field


def normalize_identifier(text: str) -> str:
    """Normalize a COBOL identifier: uppercase, strip, collapse whitespace."""
    return " ".join(text.strip().split()).upper()


def normalize_keyword(text: str) -> str:
    """Normalize a COBOL keyword: uppercase, strip, collapse whitespace."""
    return " ".join(text.strip().split()).upper()


def canonicalize_token(text: str) -> str:
    """Canonicalize a descriptive or categorical token: uppercase, strip, underscore-separated."""
    cleaned = " ".join(text.strip().split()).upper()
    return cleaned.replace(" ", "_").replace("-", "_")


# ---------------------------------------------------------------------------
# Base Semantic Fact Definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SystemAtomicFact:
    """Base class for all normalized, immutable, hashable system atomic facts."""

    fact_category: str

    def get_semantic_key(self) -> str:
        """Return a deterministic string key representing semantic identity."""
        raise NotImplementedError

    def semantic_key(self) -> str:
        """Alias for get_semantic_key."""
        return self.get_semantic_key()


# ---------------------------------------------------------------------------
# Evidence Span & Supported Fact Container
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceSpan:
    """Physical line coordinate span within a repository source file."""

    file_path: str
    line_start: int
    line_end: int

    def __post_init__(self) -> None:
        norm = self.file_path.replace("\\", "/")
        object.__setattr__(self, "file_path", norm)
        if self.line_start < 1 or self.line_end < self.line_start:
            raise ValueError(f"Invalid coordinate span [{self.line_start}, {self.line_end}]")


@dataclass(frozen=True)
class SupportedSystemFact:
    """An atomic fact bound to exact ground-truth role-bound source evidence."""

    fact: SystemAtomicFact
    proposition_id: str
    evidence_spans: dict[str, EvidenceSpan]

    @property
    def primary_evidence(self) -> EvidenceSpan:
        """Return the primary or first evidence span."""
        return next(iter(self.evidence_spans.values()))

    @property
    def file_path(self) -> str:
        return self.primary_evidence.file_path

    @property
    def line_start(self) -> int:
        return self.primary_evidence.line_start

    @property
    def line_end(self) -> int:
        return self.primary_evidence.line_end


# ---------------------------------------------------------------------------
# 1. Program Declaration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProgramDeclarationFact(SystemAtomicFact):
    """Program compilation unit declared via PROGRAM-ID."""

    program_id: str
    fact_category: str = field(default="PROGRAM_DECLARATION", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))

    def get_semantic_key(self) -> str:
        return f"PROGRAM:{self.program_id}"


# ---------------------------------------------------------------------------
# 2. Call Occurrence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CallOccurrenceFact(SystemAtomicFact):
    """Specific physical occurrence of a procedural CALL statement."""

    caller_program: str
    target_program: str
    call_mechanism: str  # LITERAL_TARGET or DYNAMIC_TARGET
    argument_identifier: str | None = None
    fact_category: str = field(default="CALL_OCCURRENCE", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "caller_program", normalize_identifier(self.caller_program))
        object.__setattr__(self, "target_program", normalize_identifier(self.target_program))
        object.__setattr__(self, "call_mechanism", canonicalize_token(self.call_mechanism))
        if self.argument_identifier:
            object.__setattr__(
                self, "argument_identifier", normalize_identifier(self.argument_identifier)
            )

    def get_semantic_key(self) -> str:
        arg_str = f":{self.argument_identifier}" if self.argument_identifier else ""
        return (
            f"CALL_OCCURRENCE:{self.caller_program}->{self.target_program}:"
            f"{self.call_mechanism}{arg_str}"
        )


# ---------------------------------------------------------------------------
# 3. Call Edge
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CallEdgeFact(SystemAtomicFact):
    """Unique directed topological edge in the system call graph."""

    caller_program: str
    target_program: str
    call_mechanism: str
    fact_category: str = field(default="CALL_EDGE", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "caller_program", normalize_identifier(self.caller_program))
        object.__setattr__(self, "target_program", normalize_identifier(self.target_program))
        object.__setattr__(self, "call_mechanism", canonicalize_token(self.call_mechanism))

    def get_semantic_key(self) -> str:
        return f"CALL_EDGE:{self.caller_program}->{self.target_program}:{self.call_mechanism}"


# ---------------------------------------------------------------------------
# 4. Internal Call Resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InternalCallResolutionFact(SystemAtomicFact):
    """Resolution of a CALL occurrence to an internal compilation unit."""

    caller_program: str
    callee_program: str
    fact_category: str = field(default="INTERNAL_CALL_RESOLUTION", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "caller_program", normalize_identifier(self.caller_program))
        object.__setattr__(self, "callee_program", normalize_identifier(self.callee_program))

    def get_semantic_key(self) -> str:
        return f"INTERNAL_CALL:{self.caller_program}->{self.callee_program}"


# ---------------------------------------------------------------------------
# 5. Record Layout
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordLayoutFact(SystemAtomicFact):
    """01 Record layout declaration in program or copybook."""

    program_id: str
    record_name: str
    field_count: int
    storage_format: str  # DISPLAY, COMP-3
    fact_category: str = field(default="RECORD_LAYOUT", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(self, "record_name", normalize_identifier(self.record_name))
        object.__setattr__(self, "storage_format", canonicalize_token(self.storage_format))

    def get_semantic_key(self) -> str:
        return (
            f"RECORD_LAYOUT:{self.program_id}:{self.record_name}:"
            f"{self.field_count}:{self.storage_format}"
        )


# ---------------------------------------------------------------------------
# 6. Record Layout Relation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordLayoutRelationFact(SystemAtomicFact):
    """Binary relation or representation comparison between two record layouts."""

    layout_a_name: str
    layout_b_name: str
    relation_type: str  # IDENTICAL, EQUIVALENT, REPRESENTATION_MISMATCH
    fact_category: str = field(default="RECORD_LAYOUT_RELATION", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "layout_a_name", normalize_identifier(self.layout_a_name))
        object.__setattr__(self, "layout_b_name", normalize_identifier(self.layout_b_name))
        object.__setattr__(self, "relation_type", canonicalize_token(self.relation_type))

    def get_semantic_key(self) -> str:
        # Order-invariant representation for comparison
        pair = sorted([self.layout_a_name, self.layout_b_name])
        return f"LAYOUT_RELATION:{pair[0]}:{pair[1]}:{self.relation_type}"


# ---------------------------------------------------------------------------
# 7. File Binding
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileBindingFact(SystemAtomicFact):
    """File-Control SELECT ... ASSIGN TO clause."""

    program_id: str
    internal_file_name: str
    external_file_name: str
    organization: str
    fact_category: str = field(default="FILE_BINDING", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(
            self, "internal_file_name", normalize_identifier(self.internal_file_name)
        )
        clean_ext = self.external_file_name.strip("'\"")
        object.__setattr__(self, "external_file_name", normalize_identifier(clean_ext))
        object.__setattr__(self, "organization", canonicalize_token(self.organization))

    def get_semantic_key(self) -> str:
        return (
            f"FILE_BINDING:{self.program_id}:{self.internal_file_name}:"
            f"{self.external_file_name}:{self.organization}"
        )


# ---------------------------------------------------------------------------
# 8. File Operation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileOperationFact(SystemAtomicFact):
    """Discrete file I/O verb executed on an internal file."""

    program_id: str
    internal_file_name: str
    operation_verb: str  # OPEN_INPUT, OPEN_OUTPUT, READ, WRITE, CLOSE
    fact_category: str = field(default="FILE_OPERATION", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(
            self, "internal_file_name", normalize_identifier(self.internal_file_name)
        )
        object.__setattr__(self, "operation_verb", canonicalize_token(self.operation_verb))

    def get_semantic_key(self) -> str:
        return f"FILE_OP:{self.program_id}:{self.internal_file_name}:{self.operation_verb}"


# ---------------------------------------------------------------------------
# 9. Termination Site
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TerminationSiteFact(SystemAtomicFact):
    """Explicit run-unit termination statement in procedure division."""

    program_id: str
    statement_type: str  # STOP_RUN, GOBACK, EXIT_PROGRAM
    fact_category: str = field(default="TERMINATION_SITE", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(self, "statement_type", canonicalize_token(self.statement_type))

    def get_semantic_key(self) -> str:
        return f"TERMINATION:{self.program_id}:{self.statement_type}"


# ---------------------------------------------------------------------------
# 10. Caller Continuation Constraint
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CallerContinuationConstraintFact(SystemAtomicFact):
    """Control flow constraint on caller imposed by subprogram termination."""

    caller_program: str
    callee_program: str
    constraint_type: str  # PROCESS_TERMINATION_ON_CALL or RETURN_TO_CALLER
    fact_category: str = field(default="CALLER_CONTINUATION_CONSTRAINT", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "caller_program", normalize_identifier(self.caller_program))
        object.__setattr__(self, "callee_program", normalize_identifier(self.callee_program))
        object.__setattr__(self, "constraint_type", canonicalize_token(self.constraint_type))

    def get_semantic_key(self) -> str:
        return (
            f"CONTINUATION_CONSTRAINT:{self.caller_program}->{self.callee_program}:"
            f"{self.constraint_type}"
        )


# ---------------------------------------------------------------------------
# 11. Command Invocation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandInvocationFact(SystemAtomicFact):
    """Operating system shell command invocation via SYSTEM library."""

    program_id: str
    command_template: str
    target_operand: str
    fact_category: str = field(default="COMMAND_INVOCATION", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        clean_cmd = self.command_template.strip("'\"")
        object.__setattr__(self, "command_template", clean_cmd)
        object.__setattr__(self, "target_operand", normalize_identifier(self.target_operand))

    def get_semantic_key(self) -> str:
        return f"COMMAND_INVOCATION:{self.program_id}:{self.command_template}:{self.target_operand}"


# ---------------------------------------------------------------------------
# 12. Data Transfer Relation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DataTransferRelationFact(SystemAtomicFact):
    """Explicit data transfer between records or memory structures."""

    program_id: str
    source_entity: str
    target_entity: str
    transfer_verb: str  # MOVE
    fact_category: str = field(default="DATA_TRANSFER_RELATION", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(self, "source_entity", normalize_identifier(self.source_entity))
        object.__setattr__(self, "target_entity", normalize_identifier(self.target_entity))
        object.__setattr__(self, "transfer_verb", canonicalize_token(self.transfer_verb))

    def get_semantic_key(self) -> str:
        return (
            f"DATA_TRANSFER:{self.program_id}:{self.source_entity}->"
            f"{self.target_entity}:{self.transfer_verb}"
        )


# ---------------------------------------------------------------------------
# 13. Resource Lifecycle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResourceLifecycleFact(SystemAtomicFact):
    """Complete operation sequence and mode for an internal file handle."""

    program_id: str
    resource_name: str
    access_mode: str  # INPUT or OUTPUT
    ordered_operations: tuple[str, ...]
    fact_category: str = field(default="RESOURCE_LIFECYCLE", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(self, "resource_name", normalize_identifier(self.resource_name))
        object.__setattr__(self, "access_mode", canonicalize_token(self.access_mode))
        object.__setattr__(
            self,
            "ordered_operations",
            tuple(canonicalize_token(op) for op in self.ordered_operations),
        )

    def get_semantic_key(self) -> str:
        ops_str = "->".join(self.ordered_operations)
        return (
            f"RESOURCE_LIFECYCLE:{self.program_id}:{self.resource_name}:"
            f"{self.access_mode}:({ops_str})"
        )


# ---------------------------------------------------------------------------
# 14. Operation Sequence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OperationSequenceFact(SystemAtomicFact):
    """Strict temporal ordering between two procedural operations."""

    program_id: str
    first_operation: str
    second_operation: str
    sequence_rationale: str
    fact_category: str = field(default="OPERATION_SEQUENCE", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(self, "first_operation", canonicalize_token(self.first_operation))
        object.__setattr__(self, "second_operation", canonicalize_token(self.second_operation))
        object.__setattr__(self, "sequence_rationale", canonicalize_token(self.sequence_rationale))

    def get_semantic_key(self) -> str:
        return f"OP_SEQUENCE:{self.program_id}:{self.first_operation}->{self.second_operation}"


# ---------------------------------------------------------------------------
# 15. Computation Dataflow
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComputationDataflowFact(SystemAtomicFact):
    """Arithmetic transformation or accumulation dataflow."""

    program_id: str
    source_field: str
    target_field: str
    operation_verb: str  # ADD, SUBTRACT, MOVE
    fact_category: str = field(default="COMPUTATION_DATAFLOW", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(self, "source_field", normalize_identifier(self.source_field))
        object.__setattr__(self, "target_field", normalize_identifier(self.target_field))
        object.__setattr__(self, "operation_verb", canonicalize_token(self.operation_verb))

    def get_semantic_key(self) -> str:
        return (
            f"DATAFLOW:{self.program_id}:{self.source_field}->"
            f"{self.target_field}:{self.operation_verb}"
        )


# ---------------------------------------------------------------------------
# 16. Platform Dependency
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlatformDependencyFact(SystemAtomicFact):
    """Operating system or platform execution constraint."""

    program_id: str
    platform_family: str  # WINDOWS, POSIX, etc.
    command_literal: str
    fact_category: str = field(default="PLATFORM_DEPENDENCY", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        plat = canonicalize_token(self.platform_family)
        if plat in ("WINDOWS_CMD", "WIN_CMD", "WINDOWS_CMD_SHELL"):
            plat = "WINDOWS"
        object.__setattr__(self, "platform_family", plat)
        clean_cmd = self.command_literal.strip("'\"")
        object.__setattr__(self, "command_literal", clean_cmd)

    def get_semantic_key(self) -> str:
        return f"PLATFORM:{self.program_id}:{self.platform_family}:{self.command_literal}"


# ---------------------------------------------------------------------------
# 17. Behavioral Risk
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BehavioralRiskFact(SystemAtomicFact):
    """System-level behavioral risk or operational fragility."""

    program_id: str
    risk_category: str  # IO_ERROR_HANDLING, DATA_INTEGRITY, CONTROL_FLOW, etc.
    precondition: str
    possible_consequence: str
    severity: str  # HIGH, MEDIUM, LOW
    fact_category: str = field(default="BEHAVIORAL_RISK", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        rc = canonicalize_token(self.risk_category)
        if rc in ("MISSING_FILE_STATUS_CHECK", "FILE_STATUS_CHECK_MISSING"):
            rc = "IO_ERROR_HANDLING"
        elif rc in ("NON_ATOMIC_FILE_UPDATE", "NON_ATOMIC_UPDATE"):
            rc = "DATA_INTEGRITY"
        elif rc in ("CALLEE_PROCESS_TERMINATION", "UNCONTROLLED_TERMINATION"):
            rc = "CONTROL_FLOW"
        object.__setattr__(self, "risk_category", rc)
        object.__setattr__(
            self, "possible_consequence", canonicalize_token(self.possible_consequence)
        )
        object.__setattr__(self, "severity", canonicalize_token(self.severity))

    def get_semantic_key(self) -> str:
        return (
            f"RISK:{self.program_id}:{self.risk_category}:"
            f"{self.possible_consequence}:{self.severity}"
        )


# ---------------------------------------------------------------------------
# 18. Data State Comparison
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DataStateComparisonFact(SystemAtomicFact):
    """Discrepancy observed between DAT record and source initializer code."""

    entity_id: str
    dat_record_value: str
    initializer_code_value: str
    causal_provenance: str  # UNKNOWN
    fact_category: str = field(default="DATA_STATE_COMPARISON", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_id", normalize_identifier(self.entity_id))
        object.__setattr__(self, "dat_record_value", self.dat_record_value.strip())
        object.__setattr__(self, "initializer_code_value", self.initializer_code_value.strip())
        object.__setattr__(self, "causal_provenance", canonicalize_token(self.causal_provenance))

    def get_semantic_key(self) -> str:
        return (
            f"DATA_STATE_CMP:{self.entity_id}:{self.dat_record_value}:"
            f"{self.initializer_code_value}:{self.causal_provenance}"
        )
