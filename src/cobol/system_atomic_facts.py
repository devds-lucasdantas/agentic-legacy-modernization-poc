"""Canonical System Atomic Fact representations for Gate 3 COBOL System Analysis.

Defines the semantic domain primitives for multi-file legacy banking system understanding.
Adheres strictly to Guardrail A:
- ZERO reliance on fuzzy/NLP/LLM evaluation.
- All truth-bearing fields are structured or deterministically normalized.
- Exact generic comparison against grounded facts.
"""

from collections.abc import Sequence
from dataclasses import dataclass


def normalize_identifier(text: str) -> str:
    """Normalize a COBOL identifier: uppercase, strip, collapse whitespace."""
    return " ".join(text.strip().split()).upper()


def normalize_keyword(text: str) -> str:
    """Normalize a COBOL keyword: uppercase, strip, collapse whitespace."""
    return " ".join(text.strip().split()).upper()


def normalize_predicate(text: str) -> str:
    """Normalize a condition predicate: uppercase, normalize operators, strip spaces."""
    s = " ".join(text.strip().split()).upper()
    # Normalize comparison operators
    s = s.replace("GREATER THAN OR EQUAL TO", ">=")
    s = s.replace("NOT LESS THAN", ">=")
    s = s.replace("EQUAL TO", "=")
    s = s.replace("EQUALS", "=")
    return s


def normalize_operations(ops: Sequence[str]) -> tuple[str, ...]:
    """Normalize a sequence of file/lifecycle operations (e.g. ['OPEN', 'READ', 'CLOSE'])."""
    return tuple(normalize_keyword(op) for op in ops)


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


# ---------------------------------------------------------------------------
# Group 1: Architecture & Component Topology
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComponentTopologyFact(SystemAtomicFact):
    """Program or component presence and root topology."""

    program_id: str
    component_role: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(self, "component_role", canonicalize_token(self.component_role))

    def get_semantic_key(self) -> str:
        return f"TOPOLOGY:{self.program_id}:{self.component_role}"


# ---------------------------------------------------------------------------
# Group 2: Cross-Program Invocations & Dispatching
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossProgramCallFact(SystemAtomicFact):
    """Inter-program CALL invocation."""

    caller_program: str
    callee_program: str
    call_mechanism: str  # e.g. 'DYNAMIC_CALL_LITERAL'
    parameters: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "caller_program", normalize_identifier(self.caller_program))
        object.__setattr__(self, "callee_program", normalize_identifier(self.callee_program))
        object.__setattr__(self, "call_mechanism", canonicalize_token(self.call_mechanism))
        object.__setattr__(
            self, "parameters", tuple(normalize_identifier(p) for p in self.parameters)
        )

    def get_semantic_key(self) -> str:
        params_str = ",".join(self.parameters)
        return (
            f"CALL:{self.caller_program}->{self.callee_program}:"
            f"{self.call_mechanism}:({params_str})"
        )


@dataclass(frozen=True)
class MenuDispatchFact(SystemAtomicFact):
    """Menu selection dispatch branch (e.g. Option '1' -> INIT-DB)."""

    program_id: str
    menu_key: str
    target_action: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(self, "menu_key", self.menu_key.strip())
        object.__setattr__(self, "target_action", normalize_identifier(self.target_action))

    def get_semantic_key(self) -> str:
        return f"DISPATCH:{self.program_id}:{self.menu_key}->{self.target_action}"


# ---------------------------------------------------------------------------
# Group 3: Shared Copybook Inclusion & Layout Grounding
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CopybookInclusionFact(SystemAtomicFact):
    """Copybook reference / inclusion via COPY statement."""

    program_id: str
    copybook_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(self, "copybook_name", normalize_identifier(self.copybook_name))

    def get_semantic_key(self) -> str:
        return f"COPYBOOK_INCLUSION:{self.program_id}:{self.copybook_name}"


@dataclass(frozen=True)
class FieldLayoutFact(SystemAtomicFact):
    """Field declaration and representation in copybook or record."""

    container_name: str
    field_name: str
    picture_clause: str
    storage_format: str  # e.g. 'COMP-3' or 'DISPLAY'

    def __post_init__(self) -> None:
        object.__setattr__(self, "container_name", normalize_identifier(self.container_name))
        object.__setattr__(self, "field_name", normalize_identifier(self.field_name))
        object.__setattr__(self, "picture_clause", normalize_identifier(self.picture_clause))
        object.__setattr__(self, "storage_format", canonicalize_token(self.storage_format))

    def get_semantic_key(self) -> str:
        return (
            f"FIELD_LAYOUT:{self.container_name}:{self.field_name}:"
            f"{self.picture_clause}:{self.storage_format}"
        )


# ---------------------------------------------------------------------------
# Group 4: Cross-Program Data Transfer & Record Mapping
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DataTransferFact(SystemAtomicFact):
    """Data movement between memory structures or file records."""

    program_id: str
    source_entity: str
    target_entity: str
    transfer_verb: str  # e.g. 'MOVE' or 'WRITE'

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(self, "source_entity", normalize_identifier(self.source_entity))
        object.__setattr__(self, "target_entity", normalize_identifier(self.target_entity))
        object.__setattr__(self, "transfer_verb", normalize_keyword(self.transfer_verb))

    def get_semantic_key(self) -> str:
        return (
            f"DATA_TRANSFER:{self.program_id}:{self.transfer_verb}:"
            f"{self.source_entity}->{self.target_entity}"
        )


# ---------------------------------------------------------------------------
# Group 5: Shared File Lifecycle Operations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResourceLifecycleFact(SystemAtomicFact):
    """File lifecycle operations within a program."""

    program_id: str
    resource_name: str
    access_mode: str  # e.g. 'INPUT', 'OUTPUT', 'I-O'
    operations: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(self, "resource_name", normalize_identifier(self.resource_name))
        object.__setattr__(self, "access_mode", normalize_keyword(self.access_mode))
        object.__setattr__(self, "operations", normalize_operations(self.operations))

    def get_semantic_key(self) -> str:
        ops_str = ",".join(self.operations)
        return f"LIFECYCLE:{self.program_id}:{self.resource_name}:{self.access_mode}:({ops_str})"


# ---------------------------------------------------------------------------
# Group 6: Control Flow Topology & Paragraph Sequences
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ControlFlowLoopFact(SystemAtomicFact):
    """Loop construct (PERFORM UNTIL)."""

    program_id: str
    loop_predicate: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(self, "loop_predicate", normalize_predicate(self.loop_predicate))

    def get_semantic_key(self) -> str:
        return f"LOOP:{self.program_id}:{self.loop_predicate}"


@dataclass(frozen=True)
class EvaluateBranchingFact(SystemAtomicFact):
    """Multi-way branch construct (EVALUATE)."""

    program_id: str
    selection_subject: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(self, "selection_subject", normalize_identifier(self.selection_subject))

    def get_semantic_key(self) -> str:
        return f"EVALUATE:{self.program_id}:{self.selection_subject}"


# ---------------------------------------------------------------------------
# Group 7: Arithmetic Operations & Computation Sequences
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArithmeticOperationFact(SystemAtomicFact):
    """Arithmetic statement (ADD, SUBTRACT, COMPUTE)."""

    program_id: str
    verb: str
    operand: str
    target_field: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(self, "verb", normalize_keyword(self.verb))
        object.__setattr__(self, "operand", normalize_identifier(self.operand))
        object.__setattr__(self, "target_field", normalize_identifier(self.target_field))

    def get_semantic_key(self) -> str:
        return f"ARITHMETIC:{self.program_id}:{self.verb}:{self.operand}->{self.target_field}"


# ---------------------------------------------------------------------------
# Group 8: Conditional Branching & Evaluation Predicates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConditionalBranchFact(SystemAtomicFact):
    """Conditional decision predicate (IF condition or AT END handler)."""

    program_id: str
    condition_kind: str  # 'IF_PREDICATE', 'WHEN_OTHER', 'AT_END'
    predicate: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(self, "condition_kind", canonicalize_token(self.condition_kind))
        object.__setattr__(self, "predicate", normalize_predicate(self.predicate))

    def get_semantic_key(self) -> str:
        return f"CONDITIONAL:{self.program_id}:{self.condition_kind}:{self.predicate}"


# ---------------------------------------------------------------------------
# Group 9: Interactive I/O Operations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InteractiveIOFact(SystemAtomicFact):
    """Terminal / console interaction (DISPLAY, ACCEPT)."""

    program_id: str
    io_verb: str  # 'DISPLAY', 'ACCEPT'
    target_identifier: str  # Variable accepted into or literal/field displayed

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(self, "io_verb", normalize_keyword(self.io_verb))
        object.__setattr__(self, "target_identifier", normalize_identifier(self.target_identifier))

    def get_semantic_key(self) -> str:
        return f"INTERACTIVE_IO:{self.program_id}:{self.io_verb}:{self.target_identifier}"


# ---------------------------------------------------------------------------
# Group 10: Run-Unit Termination Semantics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TerminationFact(SystemAtomicFact):
    """Program or run-unit termination statement (STOP RUN, EXIT PROGRAM, GOBACK)."""

    program_id: str
    termination_verb: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(self, "termination_verb", normalize_keyword(self.termination_verb))

    def get_semantic_key(self) -> str:
        return f"TERMINATION:{self.program_id}:{self.termination_verb}"


# ---------------------------------------------------------------------------
# Group 11: Behavioral Risks & Edge Cases
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BehavioralRiskFact(SystemAtomicFact):
    """Behavioral edge-case or procedural risk with canonicalized elements."""

    program_id: str
    risk_category: str
    precondition: str
    ordered_operations: tuple[str, ...]
    possible_consequence: str
    severity: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(self, "risk_category", canonicalize_token(self.risk_category))
        object.__setattr__(self, "precondition", canonicalize_token(self.precondition))
        object.__setattr__(
            self, "ordered_operations", normalize_operations(self.ordered_operations)
        )
        object.__setattr__(
            self, "possible_consequence", canonicalize_token(self.possible_consequence)
        )
        object.__setattr__(self, "severity", canonicalize_token(self.severity))

    def get_semantic_key(self) -> str:
        ops_str = ",".join(self.ordered_operations)
        return (
            f"BEHAVIORAL_RISK:{self.program_id}:{self.risk_category}:{self.precondition}:"
            f"({ops_str}):{self.possible_consequence}:{self.severity}"
        )


# ---------------------------------------------------------------------------
# Group 12: System-Level Architectural Risks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArchitecturalRiskFact(SystemAtomicFact):
    """System-level architectural anti-pattern or cross-cutting risk."""

    risk_id: str
    risk_type: str
    affected_components: tuple[str, ...]
    architectural_consequence: str
    severity: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "risk_id", canonicalize_token(self.risk_id))
        object.__setattr__(self, "risk_type", canonicalize_token(self.risk_type))
        object.__setattr__(
            self,
            "affected_components",
            tuple(sorted(normalize_identifier(c) for c in self.affected_components)),
        )
        object.__setattr__(
            self, "architectural_consequence", canonicalize_token(self.architectural_consequence)
        )
        object.__setattr__(self, "severity", canonicalize_token(self.severity))

    def get_semantic_key(self) -> str:
        comps_str = ",".join(self.affected_components)
        return (
            f"ARCHITECTURAL_RISK:{self.risk_id}:{self.risk_type}:({comps_str}):"
            f"{self.architectural_consequence}:{self.severity}"
        )


# ---------------------------------------------------------------------------
# Group 13: In-Memory Working Storage State & Flags
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkingStorageStateFact(SystemAtomicFact):
    """Working-storage state variable and semantic role."""

    program_id: str
    variable_name: str
    picture_clause: str
    state_role: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", normalize_identifier(self.program_id))
        object.__setattr__(self, "variable_name", normalize_identifier(self.variable_name))
        object.__setattr__(self, "picture_clause", normalize_identifier(self.picture_clause))
        object.__setattr__(self, "state_role", canonicalize_token(self.state_role))

    def get_semantic_key(self) -> str:
        return (
            f"WS_STATE:{self.program_id}:{self.variable_name}:"
            f"{self.picture_clause}:{self.state_role}"
        )


# ---------------------------------------------------------------------------
# Group 14: Cross-File Transaction Processing Protocol
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TransactionProtocolFact(SystemAtomicFact):
    """System-wide multi-program execution protocol."""

    protocol_name: str
    ordered_phases: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "protocol_name", canonicalize_token(self.protocol_name))
        object.__setattr__(
            self, "ordered_phases", tuple(canonicalize_token(p) for p in self.ordered_phases)
        )

    def get_semantic_key(self) -> str:
        phases_str = "->".join(self.ordered_phases)
        return f"PROTOCOL:{self.protocol_name}:({phases_str})"


# ---------------------------------------------------------------------------
# Grounded Occurrence Definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SupportedSystemFact:
    """An atomic fact bound to exact ground-truth source evidence."""

    fact: SystemAtomicFact
    proposition_id: str
    file_path: str
    line_start: int
    line_end: int

    def __post_init__(self) -> None:
        norm_path = self.file_path.replace("\\", "/")
        object.__setattr__(self, "file_path", norm_path)
        if self.line_start < 1 or self.line_end < self.line_start:
            raise ValueError(
                f"Invalid line span [{self.line_start}, {self.line_end}] for {self.file_path}"
            )
