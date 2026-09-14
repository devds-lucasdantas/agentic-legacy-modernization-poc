"""Isolated generic 3-tier COBOL parser and ParserCoverageCertificate generator for Gate 3.

Implements a generic quote-aware lexer and COBOL subset parser with AST nodes
and deterministic fact extraction.
Strictly adheres to:
- Blocker 2: ZERO hardcoded fixture facts; ZERO fixture-specific variable or program names.
- Blocker 4: Extracts all approved system-level concepts from source AST.
- Blocker 9: Produces role-bound multi-evidence coordinates for relational facts.
- Guardrail D: Real ParserCoverageCertificate computed directly from source bytes.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from src.cobol.identifier_domain import (
    is_canonical_cobol_identifier,
    is_computation_operand,
    is_numeric_literal,
)
from src.cobol.multi_source_reader import MultiSourceBundle, TargetFile
from src.cobol.system_atomic_facts import (
    BehavioralRiskFact,
    CallEdgeFact,
    CallerContinuationConstraintFact,
    CallOccurrenceFact,
    CommandInvocationFact,
    ComputationDataflowFact,
    DataStateComparisonFact,
    DataTransferRelationFact,
    EvidenceSpan,
    FileBindingFact,
    FileOperationFact,
    InternalCallResolutionFact,
    OperationSequenceFact,
    PlatformDependencyFact,
    ProgramDeclarationFact,
    RecordFieldFact,
    RecordLayoutFact,
    RecordLayoutRelationFact,
    ResourceLifecycleFact,
    SupportedSystemFact,
    TerminationSiteFact,
    canonicalize_picture,
    exact_syntactic_unquote,
)


class StatementClassification(StrEnum):
    """Three-state statement classification required by Gate 3 grammar contract."""

    PARSED_AND_SCORED = "PARSED_AND_SCORED"
    RECOGNIZED_BUT_UNSCORED = "RECOGNIZED_BUT_UNSCORED"
    UNSUPPORTED_RELEVANT = "UNSUPPORTED_RELEVANT"


class ExecutionEffect(StrEnum):
    """Conservative execution continuation effect domain for Gate 3 Contract 3.5.3."""

    MUST_PROCESS_TERMINATE = "MUST_PROCESS_TERMINATE"
    MUST_RETURN_TO_CALLER = "MUST_RETURN_TO_CALLER"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TerminationWitness:
    """Exact provenance of a terminal statement in source code."""

    program_id: str
    file_path: str
    line_start: int
    line_end: int
    termination_kind: str  # "STOP_RUN", "GOBACK", "EXIT_PROGRAM"

    @property
    def verb(self) -> str:
        return self.termination_kind


@dataclass(frozen=True)
class FlowResult:
    """Control-flow outcome algebra with outcome-bound termination provenance."""

    fallthrough_possible: bool
    process_termination_witnesses: tuple[TerminationWitness, ...] = ()
    return_witnesses: tuple[TerminationWitness, ...] = ()
    unknown: bool = False

    @property
    def is_definite_process_terminate(self) -> bool:
        return (
            not self.fallthrough_possible
            and not self.unknown
            and len(self.return_witnesses) == 0
            and len(self.process_termination_witnesses) > 0
        )

    @property
    def is_definite_return(self) -> bool:
        return (
            not self.fallthrough_possible
            and not self.unknown
            and len(self.process_termination_witnesses) == 0
            and len(self.return_witnesses) > 0
        )

    @property
    def effect(self) -> ExecutionEffect:
        if self.is_definite_process_terminate:
            return ExecutionEffect.MUST_PROCESS_TERMINATE
        if self.is_definite_return:
            return ExecutionEffect.MUST_RETURN_TO_CALLER
        return ExecutionEffect.UNKNOWN

    def __iter__(self):
        primary_w = (
            self.process_termination_witnesses[0]
            if self.process_termination_witnesses
            else (self.return_witnesses[0] if self.return_witnesses else None)
        )
        yield self.effect
        yield primary_w


@dataclass(frozen=True)
class ClassifiedStatement:
    """Represents a classified logical COBOL statement or structural header."""

    file_path: str
    line_start: int
    line_end: int
    verb: str
    raw_text: str
    classification: StatementClassification
    description: str
    has_terminal_period: bool = False


@dataclass(frozen=True)
class ParserCoverageCertificate:
    """Immutable parser coverage certificate computed directly from source."""

    physical_line_count: int
    blank_line_count: int
    comment_line_count: int
    data_fixture_line_count: int
    logical_statement_count: int
    parsed_and_scored_count: int
    recognized_but_unscored_count: int
    unsupported_relevant_count: int
    per_statement_classifications: list[dict[str, Any]]
    certificate_sha256: str

    def to_dict(self) -> dict[str, Any]:
        """Convert certificate to serializable dictionary."""
        return asdict(self)

    @property
    def is_evaluation_blocked(self) -> bool:
        """Return True if any procedural/declarative statement is unsupported relevant."""
        return self.unsupported_relevant_count > 0


@dataclass(frozen=True)
class FileBindingStatusRecord:
    """Detailed host record of a file binding's declarations and grounded operations."""

    program_id: str
    internal_file_name: str
    has_file_status: bool
    resource_span: EvidenceSpan
    operations_span: EvidenceSpan | None


@dataclass(frozen=True)
class FileStatusCertificate:
    """Host certificate verifying FILE STATUS declaration presence/absence per file binding."""

    bindings: dict[tuple[str, str], FileBindingStatusRecord]

    def has_status(self, program_id: str, internal_file_name: str) -> bool:
        rec = self.bindings.get((program_id.upper(), internal_file_name.upper()))
        return rec.has_file_status if rec is not None else False

    def binding_exists(self, program_id: str, internal_file_name: str) -> bool:
        return (program_id.upper(), internal_file_name.upper()) in self.bindings

    @property
    def bindings_file_status(self) -> dict[tuple[str, str], bool]:
        """Compatibility dictionary mapping (program_id, internal_file_name) -> has_file_status."""
        return {k: v.has_file_status for k, v in self.bindings.items()}


# ---------------------------------------------------------------------------
# Generic AST Node Definitions (Pure Syntax, Zero Fixture Semantics)
# ---------------------------------------------------------------------------


@dataclass
class ASTDataField:
    """Declared record data field or condition name."""

    level: int
    name: str
    picture: str | None
    usage: str  # DISPLAY, COMP-3, etc.
    line_start: int
    line_end: int
    field_kind: str = "DATA_FIELD"  # DATA_FIELD or CONDITION_NAME
    condition_values: list[str] = field(default_factory=list)


@dataclass
class ASTRecordDeclaration:
    """01 record definition containing subordinate fields."""

    container_name: str
    line_start: int
    line_end: int
    fields: list[ASTDataField] = field(default_factory=list)
    owning_fd: str | None = None
    is_unsupported: bool = False
    initial_value: str | None = None


@dataclass
class ASTFileBinding:
    """SELECT ... ASSIGN TO clause."""

    internal_file_name: str
    external_file_name: str
    organization: str
    has_file_status: bool
    line_start: int
    line_end: int


@dataclass
class ASTStatement:
    """Base procedural statement node."""

    verb: str
    line_start: int
    line_end: int


@dataclass
class ASTCall(ASTStatement):
    target: str
    is_literal: bool
    using_args: list[str] = field(default_factory=list)


@dataclass
class ASTMove(ASTStatement):
    source_operand: str
    target_operand: str
    is_literal_source: bool = False


@dataclass
class ASTFileOp(ASTStatement):
    internal_file_name: str
    access_mode: str | None = None  # INPUT, OUTPUT for OPEN


@dataclass
class ASTTermination(ASTStatement):
    pass


@dataclass
class ASTSentenceBoundary(ASTStatement):
    pass


@dataclass
class ASTArithmetic(ASTStatement):
    operand: str
    target: str


@dataclass
class ASTPerformUntil(ASTStatement):
    condition_identifier: str
    comparison_operator: str
    exit_literal: str


@dataclass
class ASTCompilationUnit:
    """Parsed COBOL compilation unit (Program or Copybook)."""

    program_id: str | None
    file_path: str
    file_type: str
    line_start: int
    line_end: int
    file_bindings: list[ASTFileBinding] = field(default_factory=list)
    record_declarations: list[ASTRecordDeclaration] = field(default_factory=list)
    statements: list[ASTStatement] = field(default_factory=list)


# ---------------------------------------------------------------------------
def _safe_unquote(token: str) -> str:
    """Unquote token if syntactically quoted; otherwise return token unchanged."""
    t = token.strip()
    if len(t) >= 2 and ((t[0] == "'" and t[-1] == "'") or (t[0] == '"' and t[-1] == '"')):
        return exact_syntactic_unquote(t)
    return t


def tokenize_cobol_line(line: str) -> list[str]:
    """Tokenize a COBOL line preserving single-quoted and double-quoted literals."""
    tokens: list[str] = []
    i = 0
    n = len(line)
    while i < n:
        while i < n and line[i].isspace():
            i += 1
        if i >= n:
            break
        char = line[i]
        if char in ("'", '"'):
            quote = char
            start = i
            i += 1
            while i < n and line[i] != quote:
                i += 1
            if i < n:
                i += 1
            while (
                i < n
                and not line[i].isspace()
                and line[i] not in (",", ";")
                and not (line[i] == "." and (i + 1 >= n or line[i + 1].isspace()))
            ):
                i += 1
            tokens.append(line[start:i])
        elif char == "." and (i + 1 >= n or line[i + 1].isspace()):
            tokens.append(".")
            i += 1
        elif char in (",", ";") and (i + 1 >= n or line[i + 1].isspace()):
            tokens.append(char)
            i += 1
        else:
            start = i
            while i < n and not line[i].isspace() and line[i] not in ("'", '"'):
                if line[i] in (".", ",", ";") and (i + 1 >= n or line[i + 1].isspace()):
                    break
                i += 1
            tokens.append(line[start:i])
    return tokens


def is_cobol_structural_boundary(line: str) -> bool:
    """Check if a line represents an obvious COBOL structural boundary.

    Structural boundaries include:
    - Another data declaration level: 01-49, 77, 88
    - FD / SD / RD / CD declarations
    - Division / Section headers: e.g. PROCEDURE DIVISION, WORKING-STORAGE SECTION, etc.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("*") or (len(line) >= 7 and line[6] == "*"):
        return False
    upper = stripped.upper()
    tokens = upper.split()
    if not tokens:
        return False
    first = tokens[0].rstrip(".")
    if first.isdigit():
        val = int(first)
        if (1 <= val <= 49) or val in (77, 88):
            return True
    if first in ("FD", "SD", "RD", "CD"):
        return True
    if any(kw in upper for kw in ("DIVISION", "SECTION")):
        return True
    return False


PROCEDURAL_KEYWORD_VOCABULARY: frozenset[str] = frozenset(
    {
        "CALL",
        "MOVE",
        "IF",
        "ELSE",
        "END-IF",
        "EVALUATE",
        "WHEN",
        "END-EVALUATE",
        "PERFORM",
        "END-PERFORM",
        "GO",
        "GOTO",
        "STOP",
        "GOBACK",
        "DISPLAY",
        "ACCEPT",
        "READ",
        "WRITE",
        "OPEN",
        "CLOSE",
        "ADD",
        "SUBTRACT",
        "COMPUTE",
        "MULTIPLY",
        "DIVIDE",
        "EXIT",
        "SECTION",
    }
)

PROCEDURAL_STATEMENT_STARTERS: frozenset[str] = frozenset(
    k for k in PROCEDURAL_KEYWORD_VOCABULARY if k != "SECTION"
)

PROCEDURAL_CONTROL_FLOW_BARRIERS: frozenset[str] = PROCEDURAL_KEYWORD_VOCABULARY


def is_unquoted_procedural_starter(tok: str) -> bool:
    """Check if an unquoted token is an exact procedural statement starter.

    Quoted literals and hyphenated identifiers (e.g. ELSE-FLAG) return False.
    """
    if (tok.startswith("'") and tok.endswith("'")) or (tok.startswith('"') and tok.endswith('"')):
        return False
    return tok.upper().rstrip(".") in PROCEDURAL_STATEMENT_STARTERS


def is_unquoted_barrier(tok: str) -> bool:
    """Check if an unquoted token is a procedural control-flow barrier."""
    if (tok.startswith("'") and tok.endswith("'")) or (tok.startswith('"') and tok.endswith('"')):
        return False
    return tok.upper().rstrip(".") in PROCEDURAL_CONTROL_FLOW_BARRIERS


def consume_optional_terminal_period(tokens: list[str]) -> tuple[bool, list[str], bool]:
    """Consume single terminal period token from procedural tokens.

    Returns (True, clean_tokens, terminated) if valid: exactly 0 or 1 terminal period, and zero
    interior period tokens.
    Returns (False, tokens, False) if period occurs at an interior position (e.g. CALL . TARGET)
    or if multiple periods occur.
    Numeric literals (e.g. 100.50) and quoted literals (e.g. 'file.name') are preserved.
    """
    if not tokens:
        return True, [], False

    clean = list(tokens)
    terminated = False
    # 1. Pop standalone terminal period token if present
    if clean and clean[-1] == ".":
        clean.pop()
        terminated = True
    elif (
        clean
        and clean[-1].endswith(".")
        and not (
            (clean[-1].startswith("'") and clean[-1].endswith("'"))
            or (clean[-1].startswith('"') and clean[-1].endswith('"'))
        )
    ):
        val = clean[-1]
        if not re.match(r"^[+-]?[0-9]+\.[0-9]+$", val):
            clean[-1] = val[:-1]
            terminated = True

    # 2. Verify no unquoted interior period exists in clean tokens
    for t in clean:
        if t == ".":
            return False, tokens, False
        if not ((t.startswith("'") and t.endswith("'")) or (t.startswith('"') and t.endswith('"'))):
            if "." in t and not re.match(r"^[+-]?[0-9]+\.[0-9]+$", t):
                return False, tokens, False

    return True, clean, terminated


SUPPORTED_PICTURE_PATTERN: re.Pattern[str] = re.compile(
    r"^(?:"
    r"[AX](?:\([1-9][0-9]*\))?|"
    r"S?9+(?:\([1-9][0-9]*\))?(?:V9+(?:\([1-9][0-9]*\))?)?|"
    r"V9+(?:\([1-9][0-9]*\))?|"
    r"[+-]+(?:\([1-9][0-9]*\))?9*(?:\([1-9][0-9]*\))?(?:V9+(?:\([1-9][0-9]*\))?)?|"
    r"\$?[Z9*]+(?:,[Z9*]+)*(?:\.[0-9Z*]+)?"
    r")$",
    re.IGNORECASE,
)


def is_valid_supported_picture(pic: str | None) -> bool:
    """Validate picture clause against Contract 3.5.3 frozen supported picture grammar."""
    if not pic:
        return False
    p = pic.strip()
    return bool(SUPPORTED_PICTURE_PATTERN.match(p))


def consume_declaration_period(tokens: list[str]) -> tuple[bool, list[str], bool]:
    """Consume single terminal period from data division declaration tokens.

    Returns (True, clean_tokens, terminated) if valid: exactly 0 or 1 terminal period, and zero
    interior period tokens.
    Returns (False, tokens, False) if period occurs at an interior position (e.g. '05 F. PIC X.').
    Numeric literals and supported picture strings containing periods are preserved.
    """
    if not tokens:
        return True, [], False

    clean = list(tokens)
    terminated = False
    if clean and clean[-1] == ".":
        clean.pop()
        terminated = True
    elif (
        clean
        and clean[-1].endswith(".")
        and not (
            (clean[-1].startswith("'") and clean[-1].endswith("'"))
            or (clean[-1].startswith('"') and clean[-1].endswith('"'))
        )
    ):
        val = clean[-1]
        if not re.match(r"^[+-]?[0-9]+\.[0-9]+$", val) and not is_valid_supported_picture(val):
            clean[-1] = val[:-1]
            terminated = True

    # Check for interior period tokens or period-affixed tokens
    for idx_t, t in enumerate(clean):
        if idx_t == 0 and t.upper().rstrip(".") == "PROGRAM-ID":
            continue
        if idx_t == 1 and t == "." and clean[0].upper().rstrip(".") == "PROGRAM-ID":
            continue
        if t == ".":
            return False, tokens, False
        if not ((t.startswith("'") and t.endswith("'")) or (t.startswith('"') and t.endswith('"'))):
            if (
                "." in t
                and not re.match(r"^[+-]?[0-9]+\.[0-9]+$", t)
                and not is_valid_supported_picture(t)
            ):
                return False, tokens, False

    return True, clean, terminated



def has_procedural_barrier_between(
    lines: list[str],
    line_start_excl: int,
    line_end_excl: int,
) -> bool:
    """Check if lines between line_start_excl and line_end_excl contain a control barrier.

    Barriers include:
    - Branching / conditionals: IF, ELSE, END-IF, EVALUATE, WHEN, END-EVALUATE
    - Loops: PERFORM, END-PERFORM
    - Control transfers / exits: GO, GOTO, STOP, GOBACK, EXIT
    - Regional markers: SECTION headers, paragraph label lines
    - I/O / side-effect statements: DISPLAY, ACCEPT
    """
    # 1. Check endpoint lines for control-flow delimiters outside statement
    if 1 <= line_start_excl <= len(lines):
        raw_start = lines[line_start_excl - 1].strip()
        if (
            raw_start
            and not raw_start.startswith("*")
            and not (len(lines[line_start_excl - 1]) >= 7 and lines[line_start_excl - 1][6] == "*")
        ):
            toks_start = tokenize_cobol_line(raw_start)
            for t in toks_start:
                if is_unquoted_barrier(t) and t.upper().rstrip(".") not in ("MOVE", "CALL"):
                    return True

    if 1 <= line_end_excl <= len(lines):
        raw_end = lines[line_end_excl - 1].strip()
        if (
            raw_end
            and not raw_end.startswith("*")
            and not (len(lines[line_end_excl - 1]) >= 7 and lines[line_end_excl - 1][6] == "*")
        ):
            toks_end = tokenize_cobol_line(raw_end)
            for t in toks_end:
                if is_unquoted_barrier(t) and t.upper().rstrip(".") not in ("MOVE", "CALL"):
                    return True

    # 2. Check intervening lines
    for l_num in range(line_start_excl + 1, line_end_excl):
        if l_num > len(lines):
            break
        raw = lines[l_num - 1]
        stripped = raw.strip()
        if not stripped or stripped.startswith("*") or (len(raw) >= 7 and raw[6] == "*"):
            continue
        toks = tokenize_cobol_line(raw)
        toks_upper = [t.upper() for t in toks if t != "."]
        if any(w in toks_upper for w in PROCEDURAL_CONTROL_FLOW_BARRIERS):
            return True
        # Paragraph label heuristic: single token on line ending with period
        if stripped.endswith(".") and len(toks_upper) == 1:
            return True
    return False


def parse_cobol_picture(pic: str | None) -> tuple[int, int]:
    """Parse a COBOL PICTURE clause into (total_character_width, decimal_places)."""
    if not pic:
        return (0, 0)
    p = pic.upper().strip().rstrip(".")
    parts = p.split("V")
    int_part = parts[0]
    dec_part = parts[1] if len(parts) > 1 else ""

    def _calc_part_len(part_str: str) -> int:
        length = 0
        i = 0
        while i < len(part_str):
            char = part_str[i]
            if char in ("9", "X", "A", "Z", "*"):
                if i + 1 < len(part_str) and part_str[i + 1] == "(":
                    close_idx = part_str.find(")", i + 2)
                    if close_idx != -1:
                        rep = int(part_str[i + 2 : close_idx])
                        length += rep
                        i = close_idx + 1
                        continue
                length += 1
            i += 1
        return length

    int_len = _calc_part_len(int_part)
    dec_len = _calc_part_len(dec_part)
    return (int_len + dec_len, dec_len)


@dataclass(frozen=True)
class MutationCommandResult:
    status: str  # "NOT_MUTATION", "MUTATION_PARSED", "MUTATION_UNSUPPORTED"
    operation: str | None = None  # "DELETE", "RENAME", "COPY"
    source_operand: str | None = None
    target_operand: str | None = None
    reason: str | None = None


class CommandDialect(StrEnum):
    SUPPORTED_WINDOWS_CMD = "SUPPORTED_WINDOWS_CMD"
    UNSUPPORTED_WRAPPER = "UNSUPPORTED_WRAPPER"
    OTHER_COMMAND = "OTHER_COMMAND"


def classify_command_dialect(cmd_text: str) -> tuple[CommandDialect, str, str | None]:
    """Classify the command dialect and return (dialect, unwrapped_command, error_reason)."""
    clean = cmd_text.strip()

    # 1. Lexical recognition of POSIX shell wrapper families (quoted, unquoted, bare, path-based)
    m_posix = re.match(
        r'^(?:/(?:usr/)?bin/(?:ba)?sh|(?:ba)?sh|"(?:/(?:usr/)?bin/)?(?:ba)?sh"|\'(?:/(?:usr/)?bin/)?(?:ba)?sh\')(?:\s+(.*))?$',
        clean,
        flags=re.IGNORECASE,
    )
    if m_posix:
        return (
            CommandDialect.UNSUPPORTED_WRAPPER,
            clean,
            (
                "POSIX shell wrapper establishes an unrepresentable "
                "platform dependency outside Contract 3.5.3 frozen schema"
            ),
        )

    # 2. cmd.exe wrapper family
    m_cmd = re.match(
        r'^(?:cmd(?:\.exe)?|"cmd(?:\.exe)?"|\'cmd(?:\.exe)?\')(?:\s+(.*))?$',
        clean,
        flags=re.IGNORECASE,
    )
    if m_cmd:
        args = (m_cmd.group(1) or "").strip()
        if not args:
            return (
                CommandDialect.UNSUPPORTED_WRAPPER,
                clean,
                "Incomplete cmd.exe wrapper syntax (no arguments)",
            )
        m_c = re.match(r"^/c(?:\s+(.*))?$", args, flags=re.IGNORECASE)
        if m_c:
            inner = (m_c.group(1) or "").strip()
            if not inner:
                return (
                    CommandDialect.UNSUPPORTED_WRAPPER,
                    clean,
                    "Incomplete cmd.exe wrapper syntax (/c without command)",
                )
            return (CommandDialect.SUPPORTED_WINDOWS_CMD, inner, None)
        else:
            return (
                CommandDialect.UNSUPPORTED_WRAPPER,
                clean,
                f"Unsupported cmd.exe wrapper options: '{args}'",
            )

    return (
        CommandDialect.OTHER_COMMAND,
        clean,
        f"Unsupported command or shell wrapper: '{clean}'",
    )


SHELL_METACHARACTERS: frozenset[str] = frozenset(
    {">", "<", "|", "&", "^", "%", "!", "*", "?", "(", ")"}
)

ALL_MUTATION_VERBS: frozenset[str] = frozenset(
    {"del", "delete", "erase", "rm", "ren", "rename", "mv", "move", "copy", "cp"}
)


def tokenize_windows_mutation_operands(text: str) -> tuple[bool, list[str], str | None]:
    """Tokenize Windows mutation command operands.

    Supports unquoted operands and double-quote grouped operands ("...").
    Does NOT treat single quotes as Windows grouping quotes.
    Rejects shell metacharacters and wildcards (><|&^%!*?()).
    Rejects non-ASCII characters, Unicode whitespace (NBSP, tabs, etc.),
    consecutive spaces, and boundary whitespace.
    Returns (True, operands, None) on success.
    Returns (False, [], reason) on malformed quoting, invalid syntax, or metacharacters.
    """
    if any(ord(c) >= 128 for c in text):
        return False, [], "Non-ASCII character in mutation command text"

    for c in text:
        if c in SHELL_METACHARACTERS:
            return False, [], f"Shell metacharacter or wildcard '{c}' in mutation command text"

    operands: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        char = text[i]
        if char == '"':
            # Double-quoted grouped operand
            start = i
            i += 1
            while i < n and text[i] != '"':
                i += 1
            if i >= n:
                return False, [], "Unclosed double quote in mutation operand"
            i += 1
            if i < n and not text[i].isspace():
                return False, [], "Attached character after closing quote in mutation operand"
            raw = text[start:i]
            semantic = raw[1:-1]
            if not semantic:
                return False, [], "Empty filename operand in mutation command"
            if any(ord(c) >= 128 for c in semantic):
                return False, [], "Non-ASCII character in mutation operand"
            if any(c in "\t\r\n\u00a0" for c in semantic):
                return False, [], "Unsupported whitespace in mutation operand"
            if "  " in semantic:
                return False, [], "Lossy whitespace in mutation operand: consecutive whitespace"
            if semantic != semantic.strip():
                return False, [], "Lossy whitespace in mutation operand: boundary whitespace"
            operands.append(semantic)
        elif char == "'":
            return (
                False,
                [],
                "Single quote unsupported as grouping syntax in Windows mutation operand",
            )
        else:
            # Unquoted operand
            start = i
            while i < n and not text[i].isspace():
                if text[i] in ('"', "'"):
                    return False, [], "Stray quote inside unquoted mutation operand"
                i += 1
            raw = text[start:i]
            if not raw:
                return False, [], "Empty filename operand in mutation command"
            if any(ord(c) >= 128 for c in raw):
                return False, [], "Non-ASCII character in mutation operand"
            if any(c in "\t\r\n\u00a0" for c in raw):
                return False, [], "Unsupported whitespace in mutation operand"
            if "  " in raw:
                return False, [], "Lossy whitespace in mutation operand: consecutive whitespace"
            if raw != raw.strip():
                return False, [], "Lossy whitespace in mutation operand: boundary whitespace"
            operands.append(raw)
    return True, operands, None


@dataclass(frozen=True)
class CleanControlResult:
    is_allowed: bool
    reason: str | None = None


def classify_clean_control_command(unwrapped_cmd: str) -> CleanControlResult:
    """Classify non-mutation Windows shell command for fail-closed safety.

    Permits only safe, well-defined control commands:
    - 'echo' <text>: with no shell metacharacters (><|&^%!*?())
    - 'dir' [path]: bare or targeting a file/directory path without shell switches or metacharacters

    Rejects any ungrounded command, unknown executable/verb, shell metacharacters, or switches.
    """
    clean = unwrapped_cmd.strip()
    if not clean:
        return CleanControlResult(is_allowed=False, reason="Empty command inside cmd.exe wrapper")

    if any(ord(c) >= 128 for c in clean):
        return CleanControlResult(is_allowed=False, reason="Non-ASCII characters in command text")

    if any(c in SHELL_METACHARACTERS for c in clean):
        return CleanControlResult(
            is_allowed=False,
            reason="Shell metacharacters not permitted in control command",
        )

    tokens = clean.split()
    verb = tokens[0].lower()

    if verb == "echo":
        return CleanControlResult(is_allowed=True)

    if verb == "dir":
        for arg in tokens[1:]:
            if arg.startswith("/") or arg.startswith("-"):
                return CleanControlResult(
                    is_allowed=False,
                    reason=f"Switches not supported in clean control command: '{arg}'",
                )
        return CleanControlResult(is_allowed=True)

    return CleanControlResult(
        is_allowed=False,
        reason=f"Unsupported non-mutation command verb or executable: '{verb}'",
    )


def classify_mutation_command(cmd_text: str) -> MutationCommandResult:
    """Classify a shell command for mutation sequence and risk analysis.

    Returns:
    - NOT_MUTATION: command does not enter the mutation verb family (e.g. echo, dir).
    - MUTATION_PARSED: command successfully tokenized into deterministic operation and operands.
    - MUTATION_UNSUPPORTED: command belongs to mutation family but has malformed/unsupported syntax.
    """
    dialect, unwrapped, wrapper_err = classify_command_dialect(cmd_text)

    if dialect == CommandDialect.UNSUPPORTED_WRAPPER:
        words = [w.strip("()") for w in cmd_text.split()]
        if any(w.lower() in ALL_MUTATION_VERBS for w in words):
            return MutationCommandResult(
                status="MUTATION_UNSUPPORTED",
                reason=wrapper_err or "Unsupported shell mutation wrapper",
            )
        return MutationCommandResult(
            status="MUTATION_UNSUPPORTED",
            reason=wrapper_err or "Unsupported shell command wrapper",
        )

    if dialect == CommandDialect.OTHER_COMMAND:
        words = [w.strip("()") for w in unwrapped.split()]
        if words and words[0].lower() in ALL_MUTATION_VERBS:
            return MutationCommandResult(
                status="MUTATION_UNSUPPORTED",
                reason=(
                    "Bare mutation commands without explicit supported "
                    "Windows shell wrapper are unsupported"
                ),
            )
        return MutationCommandResult(status="NOT_MUTATION")

    # dialect == CommandDialect.SUPPORTED_WINDOWS_CMD
    # Check for lossy whitespace in unwrapped command string
    if any(c in "\t\r\n\u00a0" for c in unwrapped):
        return MutationCommandResult(
            status="MUTATION_UNSUPPORTED",
            reason="Unsupported whitespace in Windows mutation command text",
        )
    if "  " in unwrapped:
        words_check = unwrapped.split()
        if any(w.strip("()").lower() in ALL_MUTATION_VERBS for w in words_check):
            return MutationCommandResult(
                status="MUTATION_UNSUPPORTED",
                reason="Lossy whitespace in mutation command: consecutive whitespace",
            )

    # Check grouping/parens BEFORE early NOT_MUTATION classification
    if "(" in unwrapped or ")" in unwrapped:
        words_parens = [w.strip("()") for w in unwrapped.split()]
        if any(w.lower() in ALL_MUTATION_VERBS for w in words_parens):
            return MutationCommandResult(
                status="MUTATION_UNSUPPORTED",
                reason="Parentheses or grouping syntax unsupported in Windows mutation commands",
            )

    words = unwrapped.split()
    if not words:
        return MutationCommandResult(status="NOT_MUTATION")

    first_word = words[0]
    if first_word.startswith("(") or first_word.endswith(")"):
        clean_verb = first_word.strip("()").lower()
        if clean_verb in ALL_MUTATION_VERBS:
            return MutationCommandResult(
                status="MUTATION_UNSUPPORTED",
                reason="Parentheses or grouping syntax unsupported in Windows mutation commands",
            )

    verb = first_word.lower()
    # Explicitly reject POSIX or non-minimal verbs
    if verb in ALL_MUTATION_VERBS and verb not in ("del", "ren"):
        return MutationCommandResult(
            status="MUTATION_UNSUPPORTED",
            reason=(
                f"Unsupported mutation verb '{verb}' for Windows dialect "
                "(only minimal del/ren supported)"
            ),
        )

    if verb not in ("del", "ren"):
        return MutationCommandResult(status="NOT_MUTATION")

    op_type = "DELETE" if verb == "del" else "RENAME"
    rem_text = unwrapped[len(first_word) :].strip()

    valid, operands, err_reason = tokenize_windows_mutation_operands(rem_text)
    if not valid:
        return MutationCommandResult(
            status="MUTATION_UNSUPPORTED",
            operation=op_type,
            reason=err_reason or f"Malformed or unsupported operand syntax for {op_type}",
        )

    # Check for switches: operands starting with / or -
    for op in operands:
        if op.startswith("/") or op.startswith("-"):
            return MutationCommandResult(
                status="MUTATION_UNSUPPORTED",
                operation=op_type,
                reason=f"Unsupported switch '{op}' in {op_type} command",
            )

    if op_type == "DELETE":
        if len(operands) != 1:
            return MutationCommandResult(
                status="MUTATION_UNSUPPORTED",
                operation=op_type,
                reason=f"DELETE expects exactly 1 operand, got {len(operands)}",
            )
        return MutationCommandResult(
            status="MUTATION_PARSED",
            operation="DELETE",
            target_operand=operands[0],
        )
    elif op_type == "RENAME":
        if len(operands) != 2:
            return MutationCommandResult(
                status="MUTATION_UNSUPPORTED",
                operation=op_type,
                reason=f"RENAME expects exactly 2 operands (source, target), got {len(operands)}",
            )
        return MutationCommandResult(
            status="MUTATION_PARSED",
            operation="RENAME",
            source_operand=operands[0],
            target_operand=operands[1],
        )

    return MutationCommandResult(status="NOT_MUTATION")


def classify_command_operation(cmd_text: str) -> tuple[str, str | None, str | None]:
    """Backwards-compatible wrapper around classify_mutation_command."""
    res = classify_mutation_command(cmd_text)
    if res.status == "MUTATION_PARSED":
        return (res.operation or "EXECUTE", res.source_operand, res.target_operand)
    elif res.status == "MUTATION_UNSUPPORTED":
        return ("MALFORMED_MUTATION", None, None)
    else:
        return ("EXECUTE", None, None)


# ---------------------------------------------------------------------------
# Generic System COBOL Parser
# ---------------------------------------------------------------------------


class SystemCobolParser:
    """Generic 3-tier parser for multi-source COBOL applications."""

    def __init__(self, bundle: MultiSourceBundle) -> None:
        self.bundle = bundle
        self.statements: list[ClassifiedStatement] = []
        self.compilation_units: list[ASTCompilationUnit] = []
        self.supported_facts: list[SupportedSystemFact] = []
        self._file_status_certificate: FileStatusCertificate = FileStatusCertificate({})
        self._parsed = False

    def parse_system(self) -> ParserCoverageCertificate:
        """Parse all bundle files, classify statements, and derive coverage certificate."""
        if self._parsed:
            return self.get_parser_coverage_certificate()

        physical_count = 0
        blank_count = 0
        comment_count = 0
        data_count = 0
        self.statements.clear()
        self.compilation_units.clear()
        self.supported_facts.clear()

        # Phase 1: Lexical and AST parse across all files
        for rel_path, target_file in sorted(self.bundle.files.items()):
            lines = target_file.get_lines()
            physical_count += len(lines)

            if target_file.file_type == "DATA":
                data_count += len(lines)
                continue

            unit = self._parse_file_unit(target_file)
            self.compilation_units.append(unit)

            # Account for blank and comment lines
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    blank_count += 1
                elif line.startswith("*") or (len(line) >= 7 and line[6] == "*"):
                    comment_count += 1

        # Phase 2: Derive system-level facts from parsed AST structures
        self._extract_generic_system_facts()

        # Phase 3: Construct coverage certificate
        logical_count = len(self.statements)
        parsed_scored = sum(
            1
            for s in self.statements
            if s.classification == StatementClassification.PARSED_AND_SCORED
        )
        recognized_unscored = sum(
            1
            for s in self.statements
            if s.classification == StatementClassification.RECOGNIZED_BUT_UNSCORED
        )
        unsupported = sum(
            1
            for s in self.statements
            if s.classification == StatementClassification.UNSUPPORTED_RELEVANT
        )

        per_classifications: list[dict[str, Any]] = [
            {
                "file": s.file_path,
                "span": [s.line_start, s.line_end],
                "verb": s.verb,
                "classification": s.classification.value,
            }
            for s in self.statements
        ]
        cert_dict: dict[str, Any] = {
            "physical_line_count": physical_count,
            "blank_line_count": blank_count,
            "comment_line_count": comment_count,
            "data_fixture_line_count": data_count,
            "logical_statement_count": logical_count,
            "parsed_and_scored_count": parsed_scored,
            "recognized_but_unscored_count": recognized_unscored,
            "unsupported_relevant_count": unsupported,
            "per_statement_classifications": per_classifications,
        }

        cert_json = json.dumps(cert_dict, sort_keys=True, indent=2)
        cert_hash = hashlib.sha256(cert_json.encode("utf-8")).hexdigest()

        self._certificate = ParserCoverageCertificate(
            physical_line_count=physical_count,
            blank_line_count=blank_count,
            comment_line_count=comment_count,
            data_fixture_line_count=data_count,
            logical_statement_count=logical_count,
            parsed_and_scored_count=parsed_scored,
            recognized_but_unscored_count=recognized_unscored,
            unsupported_relevant_count=unsupported,
            per_statement_classifications=per_classifications,
            certificate_sha256=cert_hash,
        )

        self._parsed = True
        return self._certificate

    def get_parser_coverage_certificate(self) -> ParserCoverageCertificate:
        """Return cached coverage certificate."""
        if not self._parsed:
            return self.parse_system()
        return self._certificate

    @property
    def file_status_certificate(self) -> FileStatusCertificate:
        """Return host certificate for FILE STATUS declarations."""
        if not self._parsed:
            self.parse_system()
        return self._file_status_certificate

    def get_file_status_certificate(self) -> FileStatusCertificate:
        """Return host certificate for FILE STATUS declarations."""
        return self.file_status_certificate

    @property
    def is_evaluation_blocked(self) -> bool:
        """Return True if parser encountered any unsupported relevant statements."""
        cert = self.get_parser_coverage_certificate()
        return cert.is_evaluation_blocked

    def get_supported_facts(self) -> list[SupportedSystemFact]:
        """Return all supported system facts extracted from AST."""
        if not self._parsed:
            self.parse_system()
        return self.supported_facts

    # -----------------------------------------------------------------------
    # File Unit AST Parser
    # -----------------------------------------------------------------------

    def _parse_file_unit(self, target_file: TargetFile) -> ASTCompilationUnit:
        lines = target_file.get_lines()
        unit = ASTCompilationUnit(
            program_id=None,
            file_path=target_file.relative_path,
            file_type=target_file.file_type,
            line_start=1,
            line_end=len(lines),
        )

        i = 0
        n = len(lines)
        current_record: ASTRecordDeclaration | None = None
        current_fd: str | None = None
        in_procedure_division = False

        while i < n:
            raw_line = lines[i]
            line_num = i + 1
            stripped = raw_line.strip()

            if (
                not stripped
                or raw_line.startswith("*")
                or (len(raw_line) >= 7 and raw_line[6] == "*")
            ):
                i += 1
                continue

            if not in_procedure_division:
                raw_decl_tokens = tokenize_cobol_line(raw_line)
                valid_decl, decl_tokens, decl_terminated = consume_declaration_period(
                    raw_decl_tokens
                )
                if not valid_decl:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            raw_decl_tokens[0] if raw_decl_tokens else "UNKNOWN",
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            "Invalid period placement or interior period in declaration line",
                        )
                    )
                    if current_record:
                        current_record.is_unsupported = True
                        current_record.line_end = max(current_record.line_end, line_num)
                    i += 1
                    continue
                if not decl_tokens:
                    i += 1
                    continue
                tokens = decl_tokens
                first = tokens[0].upper()
                line_is_terminated = decl_terminated
            else:
                raw_tokens = tokenize_cobol_line(raw_line)
                valid_period, procedural_tokens, line_is_terminated = (
                    consume_optional_terminal_period(raw_tokens)
                )
                if not valid_period:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            raw_tokens[0] if raw_tokens else "UNKNOWN",
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            "Invalid period placement or interior period in procedural statement",
                        )
                    )
                    i += 1
                    continue
                if not procedural_tokens:
                    if line_is_terminated:
                        stmt = ASTSentenceBoundary(
                            verb="SENTENCE_BOUNDARY",
                            line_start=line_num,
                            line_end=line_num,
                        )
                        unit.statements.append(stmt)
                        self.statements.append(
                            ClassifiedStatement(
                                target_file.relative_path,
                                line_num,
                                line_num,
                                "SENTENCE_BOUNDARY",
                                raw_line,
                                StatementClassification.RECOGNIZED_BUT_UNSCORED,
                                "Standalone sentence terminator",
                                has_terminal_period=True,
                            )
                        )
                    i += 1
                    continue
                tokens = procedural_tokens
                first = tokens[0].upper()

            # IDENTIFICATION DIVISION
            if (
                first == "IDENTIFICATION"
                and len(tokens) > 1
                and tokens[1].upper().startswith("DIV")
            ):
                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        line_num,
                        line_num,
                        "IDENTIFICATION_DIVISION",
                        raw_line,
                        StatementClassification.RECOGNIZED_BUT_UNSCORED,
                        "Division header",
                    )
                )
                i += 1
                continue

            # PROGRAM-ID
            if first.startswith("PROGRAM-ID"):
                id_tokens = [t for t in tokens[1:] if t != "."]
                prog_name = id_tokens[0].rstrip(".") if id_tokens else ""
                if not is_canonical_cobol_identifier(prog_name):
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            "PROGRAM-ID",
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            f"Invalid PROGRAM-ID identifier: {prog_name}",
                        )
                    )
                    i += 1
                    continue
                unit.program_id = prog_name
                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        line_num,
                        line_num,
                        "PROGRAM-ID",
                        raw_line,
                        StatementClassification.PARSED_AND_SCORED,
                        "Program identifier",
                    )
                )
                i += 1
                continue

            # ENVIRONMENT DIVISION / SECTIONS
            if first in ("ENVIRONMENT", "INPUT-OUTPUT", "FILE-CONTROL"):
                verb = f"{first}_HEADER"
                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        line_num,
                        line_num,
                        verb,
                        raw_line,
                        StatementClassification.RECOGNIZED_BUT_UNSCORED,
                        "Environment/Section header",
                    )
                )
                i += 1
                continue

            # SELECT ... ASSIGN TO ...
            if first == "SELECT":
                start_l = line_num
                clause_lines = [raw_line]
                curr_i = i

                # Slurp continuation lines until period or structural boundary
                while curr_i + 1 < n:
                    if "." in tokenize_cobol_line(lines[curr_i]):
                        break
                    next_line = lines[curr_i + 1]
                    if is_cobol_structural_boundary(next_line):
                        break
                    curr_i += 1
                    clause_lines.append(next_line)

                end_l = curr_i + 1
                clause_text = " ".join(clause_lines)

                # Quote-preserving tokenization
                c_toks = tokenize_cobol_line(clause_text)
                sel_valid = True
                sel_reason = ""
                idx = 0
                internal_name = ""
                assign_target = ""
                has_status = False

                if idx < len(c_toks) and c_toks[idx].upper() == "SELECT":
                    idx += 1
                else:
                    sel_valid = False
                    sel_reason = "Missing SELECT keyword"

                if sel_valid:
                    if idx < len(c_toks) and is_canonical_cobol_identifier(c_toks[idx]):
                        internal_name = c_toks[idx]
                        idx += 1
                    else:
                        sel_valid = False
                        sel_reason = "Invalid internal file identifier in SELECT"

                if sel_valid:
                    if idx < len(c_toks) and c_toks[idx].upper() == "ASSIGN":
                        idx += 1
                        if idx < len(c_toks) and c_toks[idx].upper() == "TO":
                            idx += 1
                    else:
                        sel_valid = False
                        sel_reason = "Missing ASSIGN [TO] clause in SELECT"

                if sel_valid:
                    if idx < len(c_toks):
                        raw_lit = c_toks[idx]
                        if (
                            raw_lit.startswith("'") and raw_lit.endswith("'") and len(raw_lit) >= 2
                        ) or (
                            raw_lit.startswith('"') and raw_lit.endswith('"') and len(raw_lit) >= 2
                        ):
                            try:
                                unquoted = exact_syntactic_unquote(raw_lit)
                                if not unquoted or raw_lit[0] in unquoted:
                                    sel_valid = False
                                    sel_reason = "Invalid quoted literal in ASSIGN TO"
                                else:
                                    assign_target = unquoted
                                    idx += 1
                            except ValueError:
                                sel_valid = False
                                sel_reason = "Malformed quotes in ASSIGN TO literal"
                        else:
                            sel_valid = False
                            sel_reason = "ASSIGN target must be a quoted string literal"
                    else:
                        sel_valid = False
                        sel_reason = "Missing target literal after ASSIGN"

                org_val = "LINE_SEQUENTIAL"
                # ORGANIZATION [IS] LINE SEQUENTIAL or SEQUENTIAL is MANDATORY
                if sel_valid:
                    if idx < len(c_toks) and c_toks[idx].upper() == "ORGANIZATION":
                        idx += 1
                        if idx < len(c_toks) and c_toks[idx].upper() == "IS":
                            idx += 1
                        if (
                            idx + 1 < len(c_toks)
                            and c_toks[idx].upper() == "LINE"
                            and c_toks[idx + 1].upper() == "SEQUENTIAL"
                        ):
                            idx += 2
                            org_val = "LINE_SEQUENTIAL"
                        elif idx < len(c_toks) and c_toks[idx].upper() == "SEQUENTIAL":
                            idx += 1
                            org_val = "SEQUENTIAL"
                        else:
                            sel_valid = False
                            sel_reason = (
                                "Unsupported file organization "
                                "(only LINE SEQUENTIAL and SEQUENTIAL supported)"
                            )
                    else:
                        sel_valid = False
                        sel_reason = (
                            "Missing mandatory ORGANIZATION clause "
                            "(LINE SEQUENTIAL or SEQUENTIAL required)"
                        )

                # Optional FILE STATUS [IS] <identifier>
                if sel_valid and idx < len(c_toks) and c_toks[idx].upper() == "FILE":
                    idx += 1
                    if idx < len(c_toks) and c_toks[idx].upper() == "STATUS":
                        idx += 1
                        if idx < len(c_toks) and c_toks[idx].upper() == "IS":
                            idx += 1
                        if idx < len(c_toks) and is_canonical_cobol_identifier(c_toks[idx]):
                            has_status = True
                            idx += 1
                        else:
                            sel_valid = False
                            sel_reason = "Invalid or missing FILE STATUS identifier"
                    else:
                        sel_valid = False
                        sel_reason = "Invalid FILE STATUS syntax"

                # Optional terminal period
                if sel_valid and idx < len(c_toks) and c_toks[idx] == ".":
                    idx += 1

                # Complete consumption check
                if sel_valid and idx != len(c_toks):
                    sel_valid = False
                    sel_reason = (
                        f"Unconsumed trailing tokens in SELECT clause: {' '.join(c_toks[idx:])}"
                    )

                if not sel_valid:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            start_l,
                            end_l,
                            "SELECT",
                            clause_text,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            sel_reason or "Unsupported or malformed SELECT clause",
                        )
                    )
                    i = curr_i + 1
                    continue

                unit.file_bindings.append(
                    ASTFileBinding(
                        internal_file_name=internal_name,
                        external_file_name=assign_target,
                        organization=org_val,
                        has_file_status=has_status,
                        line_start=start_l,
                        line_end=end_l,
                    )
                )
                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        start_l,
                        end_l,
                        "SELECT",
                        clause_text,
                        StatementClassification.PARSED_AND_SCORED,
                        "File control binding SELECT ... ASSIGN TO",
                    )
                )
                i = curr_i + 1
                continue

            # DATA DIVISION / SECTIONS / FD / COPY
            if first == "COPY":
                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        line_num,
                        line_num,
                        "COPY",
                        raw_line,
                        StatementClassification.RECOGNIZED_BUT_UNSCORED,
                        "Copybook inclusion directive",
                    )
                )
                i += 1
                continue

            if first in ("DATA", "FILE", "WORKING-STORAGE"):
                current_record = None
                if first in ("WORKING-STORAGE", "LOCAL-STORAGE", "LINKAGE"):
                    current_fd = None
                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        line_num,
                        line_num,
                        f"{first}_HEADER",
                        raw_line,
                        StatementClassification.RECOGNIZED_BUT_UNSCORED,
                        "Data section header",
                    )
                )
                i += 1
                continue

            if first == "FD":
                current_record = None
                fd_name = tokens[1].rstrip(".") if len(tokens) > 1 else ""
                if not is_canonical_cobol_identifier(fd_name):
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            "FD",
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            f"Invalid FD identifier: {fd_name}",
                        )
                    )
                    i += 1
                    continue
                current_fd = fd_name
                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        line_num,
                        line_num,
                        "FD",
                        raw_line,
                        StatementClassification.PARSED_AND_SCORED,
                        "File descriptor declaration",
                    )
                )
                i += 1
                continue

            # Record and Field Declarations (01, 05, 88)
            if first == "01":
                rec_valid = True
                rec_err = ""
                rec_name = tokens[1].rstrip(".") if len(tokens) > 1 else ""
                if not is_canonical_cobol_identifier(rec_name):
                    rec_valid = False
                    rec_err = f"Invalid 01 record identifier: {rec_name}"

                consumed_indices = {0, 1}
                init_val = None
                toks_upper = [t.upper() for t in tokens]

                # 1. Look for PIC / PICTURE
                pic_val = None
                for p_kw in ("PIC", "PICTURE"):
                    if p_kw in toks_upper:
                        idx_p = toks_upper.index(p_kw)
                        consumed_indices.add(idx_p)
                        next_p = idx_p + 1
                        if next_p < len(tokens) and toks_upper[next_p] == "IS":
                            consumed_indices.add(next_p)
                            next_p += 1
                        if next_p < len(tokens):
                            pic_raw = tokens[next_p].rstrip(".")
                            if is_valid_supported_picture(pic_raw):
                                pic_val = canonicalize_picture(pic_raw)
                            else:
                                rec_valid = False
                                rec_err = f"Invalid PICTURE clause in 01 declaration: {pic_raw}"
                            consumed_indices.add(next_p)
                        else:
                            rec_valid = False
                            rec_err = "Missing PICTURE string after PIC in 01 declaration"
                        break

                # 2. Look for USAGE
                if "USAGE" in toks_upper:
                    idx_u = toks_upper.index("USAGE")
                    consumed_indices.add(idx_u)
                    next_u = idx_u + 1
                    if next_u < len(tokens) and toks_upper[next_u] == "IS":
                        consumed_indices.add(next_u)
                        next_u += 1
                    if next_u < len(tokens):
                        consumed_indices.add(next_u)
                    else:
                        rec_valid = False
                        rec_err = "Missing USAGE value in 01 declaration"
                else:
                    for idx_tok, tok_u in enumerate(toks_upper):
                        if idx_tok in consumed_indices:
                            continue
                        clean_tok = tok_u.rstrip(".")
                        if clean_tok in ("PACKED-DECIMAL", "COMP-3", "COMP", "BINARY", "DISPLAY"):
                            consumed_indices.add(idx_tok)
                            break

                # 3. Look for VALUE
                if "VALUE" in toks_upper:
                    v_idx = toks_upper.index("VALUE")
                    consumed_indices.add(v_idx)
                    next_v = v_idx + 1
                    if next_v < len(tokens) and toks_upper[next_v] == "IS":
                        consumed_indices.add(next_v)
                        next_v += 1
                    if next_v < len(tokens) and toks_upper[next_v] == "ALL":
                        consumed_indices.add(next_v)
                        next_v += 1
                    if next_v < len(tokens):
                        init_val = _safe_unquote(tokens[next_v].rstrip("."))
                        consumed_indices.add(next_v)
                    else:
                        rec_valid = False
                        rec_err = "Missing VALUE literal in 01 declaration"

                # 4. Complete consumption check
                # (rejects OCCURS, REDEFINES, unsupported clauses/tails)
                unconsumed = [
                    tokens[j]
                    for j in range(len(tokens))
                    if j not in consumed_indices and tokens[j] != "."
                ]
                if rec_valid and unconsumed:
                    rec_valid = False
                    uncons_str = " ".join(unconsumed)
                    rec_err = (
                        f"Unsupported clauses or unconsumed tokens in 01 declaration: {uncons_str}"
                    )

                if not rec_valid:
                    current_record = ASTRecordDeclaration(
                        container_name=rec_name or "INVALID",
                        line_start=line_num,
                        line_end=line_num,
                        owning_fd=current_fd,
                        is_unsupported=True,
                    )
                    unit.record_declarations.append(current_record)
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            "RECORD_01",
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            rec_err or f"Invalid 01 record declaration: {rec_name}",
                        )
                    )
                    i += 1
                    continue

                current_record = ASTRecordDeclaration(
                    container_name=rec_name,
                    line_start=line_num,
                    line_end=line_num,
                    owning_fd=current_fd,
                    initial_value=init_val,
                )
                unit.record_declarations.append(current_record)
                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        line_num,
                        line_num,
                        "RECORD_01",
                        raw_line,
                        StatementClassification.PARSED_AND_SCORED,
                        "Record level 01 header",
                    )
                )
                i += 1
                continue

            if first == "05":
                f_name = tokens[1].rstrip(".") if len(tokens) > 1 else ""
                if not is_canonical_cobol_identifier(f_name):
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            "FIELD_05",
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            f"Invalid 05 field identifier: {f_name}",
                        )
                    )
                    if current_record:
                        current_record.is_unsupported = True
                    i += 1
                    continue

                consumed_indices = {0, 1}
                pic_val = None
                explicit_usage = None
                usage_val = "DISPLAY"
                field_valid = True
                field_err = ""

                # 1. Look for PIC / PICTURE
                toks_upper = [t.upper() for t in tokens]
                for p_kw in ("PIC", "PICTURE"):
                    if p_kw in toks_upper:
                        idx_p = toks_upper.index(p_kw)
                        consumed_indices.add(idx_p)
                        next_i = idx_p + 1
                        if next_i < len(tokens) and toks_upper[next_i] == "IS":
                            consumed_indices.add(next_i)
                            next_i += 1
                        if next_i < len(tokens):
                            pic_raw = tokens[next_i].rstrip(".")
                            if is_valid_supported_picture(pic_raw):
                                pic_val = canonicalize_picture(pic_raw)
                            else:
                                field_valid = False
                                field_err = f"Invalid PICTURE clause: {pic_raw}"
                            consumed_indices.add(next_i)
                        else:
                            field_valid = False
                            field_err = "Missing PICTURE string after PIC"
                        break

                # 2. Look for explicit USAGE keyword or explicit usage token
                if "USAGE" in toks_upper:
                    idx_u = toks_upper.index("USAGE")
                    consumed_indices.add(idx_u)
                    next_u = idx_u + 1
                    if next_u < len(tokens) and toks_upper[next_u] == "IS":
                        consumed_indices.add(next_u)
                        next_u += 1
                    if next_u < len(tokens):
                        explicit_usage = toks_upper[next_u].rstrip(".")
                        consumed_indices.add(next_u)
                    else:
                        field_valid = False
                        field_err = "Missing USAGE value after USAGE keyword"
                else:
                    # Check for unconsumed explicit usage token
                    for idx_tok, tok_u in enumerate(toks_upper):
                        if idx_tok in consumed_indices:
                            continue
                        clean_tok = tok_u.rstrip(".")
                        if clean_tok in ("PACKED-DECIMAL", "COMP-3", "COMP", "BINARY", "DISPLAY"):
                            explicit_usage = clean_tok
                            consumed_indices.add(idx_tok)
                            break

                # Validate explicit USAGE
                if field_valid and explicit_usage is not None:
                    if explicit_usage == "PACKED-DECIMAL":
                        usage_val = "COMP-3"
                    elif explicit_usage == "COMP-3":
                        usage_val = "COMP-3"
                    elif explicit_usage in ("COMP", "BINARY"):
                        usage_val = "BINARY"
                    elif explicit_usage == "DISPLAY":
                        usage_val = "DISPLAY"
                    else:
                        field_valid = False
                        field_err = f"Unsupported explicit USAGE: {explicit_usage}"
                elif field_valid:
                    # Implicit missing USAGE defaults to DISPLAY
                    usage_val = "DISPLAY"

                # Check terminal period
                if tokens and tokens[-1] == ".":
                    consumed_indices.add(len(tokens) - 1)

                # Complete consumption check
                unconsumed = [
                    tokens[j]
                    for j in range(len(tokens))
                    if j not in consumed_indices and tokens[j] != "."
                ]
                if field_valid and unconsumed:
                    field_valid = False
                    uncons_str = " ".join(unconsumed)
                    field_err = f"Unconsumed trailing tokens in 05 field declaration: {uncons_str}"

                if not field_valid:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            "FIELD_05",
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            field_err or "Unsupported 05 field syntax",
                        )
                    )
                    if current_record:
                        current_record.is_unsupported = True
                    i += 1
                    continue

                ast_field = ASTDataField(
                    level=5,
                    name=f_name,
                    picture=pic_val,
                    usage=usage_val,
                    line_start=line_num,
                    line_end=line_num,
                    field_kind="DATA_FIELD",
                    condition_values=[],
                )
                if current_record:
                    current_record.fields.append(ast_field)
                    current_record.line_end = line_num

                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        line_num,
                        line_num,
                        "FIELD_05",
                        raw_line,
                        StatementClassification.PARSED_AND_SCORED,
                        "Subordinate record field 05",
                    )
                )
                i += 1
                continue

            if first == "88":
                start_l = line_num
                combined_clause_lines = [raw_line]
                curr_i = i

                def _has_terminating_period(text: str) -> bool:
                    toks = tokenize_cobol_line(text)
                    return bool(toks and toks[-1] == ".")

                is_safely_terminated = _has_terminating_period(raw_line)

                while not is_safely_terminated and (curr_i + 1) < n:
                    next_line = lines[curr_i + 1]
                    if is_cobol_structural_boundary(next_line):
                        break
                    curr_i += 1
                    combined_clause_lines.append(next_line)
                    combined_text = " ".join(combined_clause_lines)
                    if _has_terminating_period(combined_text):
                        is_safely_terminated = True
                        break

                end_l = curr_i + 1
                clause_text = " ".join(combined_clause_lines)

                is_supported = is_safely_terminated
                cond_vals: list[str] = []
                cond_name = ""

                if is_supported:
                    c_tokens = tokenize_cobol_line(clause_text)

                    # F-09: Premature period terminates 88 clause; trailing tokens are unsupported.
                    if "." in c_tokens[:-1]:
                        is_supported = False
                    else:
                        no_dot_tokens = [t for t in c_tokens if t != "."]
                        if len(no_dot_tokens) > 1 and no_dot_tokens[0] == "88":
                            cond_name = no_dot_tokens[1]
                            if not is_canonical_cobol_identifier(cond_name):
                                is_supported = False
                        else:
                            is_supported = False

                        val_tokens_upper = [t.upper() for t in no_dot_tokens]
                        if len(no_dot_tokens) < 3 or val_tokens_upper[2] not in ("VALUE", "VALUES"):
                            is_supported = False
                            start_idx = -1
                        else:
                            start_idx = 3
                            if start_idx < len(no_dot_tokens) and val_tokens_upper[start_idx] in (
                                "IS",
                                "ARE",
                            ):
                                start_idx += 1

                        if not cond_name or start_idx == -1 or start_idx >= len(no_dot_tokens):
                            is_supported = False
                        else:
                            for t in no_dot_tokens[start_idx:]:
                                if t in (",", ";"):
                                    continue
                                t_upper = t.upper()
                                if t_upper in (
                                    "THRU",
                                    "THROUGH",
                                    "OR",
                                    "AND",
                                    "TO",
                                    "WHEN",
                                    "ALSO",
                                ):
                                    is_supported = False
                                    break
                                if ".." in t:
                                    is_supported = False
                                    break
                                if "\\" in t:
                                    is_supported = False
                                    break

                                if (t.startswith("'") and t.endswith("'") and len(t) >= 2) or (
                                    t.startswith('"') and t.endswith('"') and len(t) >= 2
                                ):
                                    try:
                                        inner = exact_syntactic_unquote(t)
                                    except ValueError:
                                        is_supported = False
                                        break
                                    if t[0] in inner:
                                        is_supported = False
                                        break
                                    cond_vals.append(inner)
                                else:
                                    if re.match(r"^[+-]?\d+(?:\.\d+)?$", t):
                                        cond_vals.append(t)
                                    else:
                                        is_supported = False
                                        break

                            if not cond_vals:
                                is_supported = False

                if is_supported:
                    ast_cond = ASTDataField(
                        level=88,
                        name=cond_name,
                        picture=None,
                        usage="DISPLAY",
                        line_start=start_l,
                        line_end=end_l,
                        field_kind="CONDITION_NAME",
                        condition_values=cond_vals,
                    )
                    if current_record:
                        current_record.fields.append(ast_cond)
                        current_record.line_end = max(current_record.line_end, end_l)

                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            start_l,
                            end_l,
                            "CONDITION_88",
                            clause_text,
                            StatementClassification.PARSED_AND_SCORED,
                            "Condition level 88",
                        )
                    )
                else:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            start_l,
                            end_l,
                            "CONDITION_88",
                            clause_text,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            "Unsupported condition level 88 syntax or trailing fragment",
                        )
                    )
                    if current_record:
                        current_record.is_unsupported = True
                i = curr_i + 1
                continue

            # PROCEDURE DIVISION / PARAGRAPHS
            if first == "PROCEDURE" and len(tokens) > 1 and tokens[1].upper().startswith("DIV"):
                current_record = None
                in_procedure_division = True
                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        line_num,
                        line_num,
                        "PROCEDURE_DIVISION",
                        raw_line,
                        StatementClassification.RECOGNIZED_BUT_UNSCORED,
                        "Procedure division header",
                        has_terminal_period=line_is_terminated,
                    )
                )
                i += 1
                continue

            if len(tokens) == 2 and tokens[1].upper() == "SECTION":
                current_record = None
                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        line_num,
                        line_num,
                        "SECTION_HEADER",
                        raw_line,
                        StatementClassification.RECOGNIZED_BUT_UNSCORED,
                        "Section header",
                        has_terminal_period=line_is_terminated,
                    )
                )
                i += 1
                continue

            if in_procedure_division and stripped.endswith(".") and len(tokens) == 1:
                if (
                    first not in PROCEDURAL_KEYWORD_VOCABULARY
                    and first not in PROCEDURAL_STATEMENT_STARTERS
                ):
                    if is_canonical_cobol_identifier(first):
                        self.statements.append(
                            ClassifiedStatement(
                                target_file.relative_path,
                                line_num,
                                line_num,
                                "PARAGRAPH_HEADER",
                                raw_line,
                                StatementClassification.RECOGNIZED_BUT_UNSCORED,
                                "Paragraph header",
                                has_terminal_period=line_is_terminated,
                            )
                        )
                        i += 1
                        continue
                    else:
                        self.statements.append(
                            ClassifiedStatement(
                                target_file.relative_path,
                                line_num,
                                line_num,
                                "PARAGRAPH_HEADER",
                                raw_line,
                                StatementClassification.UNSUPPORTED_RELEVANT,
                                f"Invalid paragraph header identifier: {first}",
                                has_terminal_period=line_is_terminated,
                            )
                        )
                        i += 1
                        continue

            # PROCEDURAL VERBS
            if first == "CALL":
                call_valid = True
                target_str = ""
                is_lit = False
                using_list: list[str] = []

                if len(tokens) not in (2, 4):
                    call_valid = False
                elif len(tokens) == 4 and tokens[2].upper() != "USING":
                    call_valid = False
                else:
                    raw_target = tokens[1]
                    is_quote_like = (
                        raw_target.startswith("'")
                        or raw_target.startswith('"')
                        or "'" in raw_target
                        or '"' in raw_target
                    )
                    if is_quote_like:
                        quote_char = raw_target[0] if raw_target[0] in ("'", '"') else None
                        if (
                            quote_char
                            and raw_target.endswith(quote_char)
                            and len(raw_target) >= 2
                            and "\\" not in raw_target
                        ):
                            content = raw_target[1:-1]
                            if quote_char not in content and is_canonical_cobol_identifier(content):
                                target_str = content
                                is_lit = True
                            else:
                                call_valid = False
                        else:
                            call_valid = False
                    else:
                        # Dynamic target
                        if is_canonical_cobol_identifier(
                            raw_target
                        ) and not is_unquoted_procedural_starter(raw_target):
                            target_str = raw_target
                            is_lit = False
                        else:
                            call_valid = False

                    if call_valid and len(tokens) == 4:
                        arg = tokens[3]
                        if is_canonical_cobol_identifier(
                            arg
                        ) and not is_unquoted_procedural_starter(arg):
                            using_list = [arg]
                        else:
                            call_valid = False

                if not call_valid:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            "CALL",
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            "Unsupported CALL target, operands, or unconsumed tokens",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                    i += 1
                    continue

                call_node = ASTCall(
                    verb="CALL",
                    target=target_str,
                    is_literal=is_lit,
                    using_args=using_list,
                    line_start=line_num,
                    line_end=line_num,
                )
                unit.statements.append(call_node)
                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        line_num,
                        line_num,
                        "CALL",
                        raw_line,
                        StatementClassification.PARSED_AND_SCORED,
                        "Procedural CALL statement",
                        has_terminal_period=line_is_terminated,
                    )
                )
                i += 1
                continue

            if first == "MOVE":
                move_valid = True
                src_val = ""
                dest_val = ""
                is_lit_src = False

                if len(tokens) != 4 or tokens[2].upper() != "TO":
                    move_valid = False
                else:
                    src_raw = tokens[1]
                    dest_raw = tokens[3]

                    if is_canonical_cobol_identifier(
                        dest_raw
                    ) and not is_unquoted_procedural_starter(dest_raw):
                        dest_val = dest_raw
                    else:
                        move_valid = False

                    is_quote_like = (
                        src_raw.startswith("'")
                        or src_raw.startswith('"')
                        or "'" in src_raw
                        or '"' in src_raw
                    )
                    if is_quote_like:
                        if (
                            src_raw[0] in ("'", '"')
                            and src_raw.endswith(src_raw[0])
                            and len(src_raw) >= 2
                            and "\\" not in src_raw
                        ):
                            quote_char = src_raw[0]
                            content = src_raw[1:-1]
                            if quote_char not in content:
                                is_lit_src = True
                                src_val = src_raw
                            else:
                                move_valid = False
                        else:
                            move_valid = False
                    else:
                        figurative = {
                            "ZERO",
                            "ZEROS",
                            "ZEROES",
                            "SPACE",
                            "SPACES",
                            "HIGH-VALUE",
                            "HIGH-VALUES",
                            "LOW-VALUE",
                            "LOW-VALUES",
                            "QUOTE",
                            "QUOTES",
                            "NULL",
                            "NULLS",
                        }
                        if (
                            src_raw.upper() in figurative
                            or is_numeric_literal(src_raw)
                            or (
                                is_canonical_cobol_identifier(src_raw)
                                and not is_unquoted_procedural_starter(src_raw)
                            )
                        ):
                            is_lit_src = False
                            src_val = src_raw
                        else:
                            move_valid = False

                if not move_valid:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            "MOVE",
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            "Unsupported MOVE syntax, literal, operands, or unconsumed tokens",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                    i += 1
                    continue

                move_node = ASTMove(
                    verb="MOVE",
                    source_operand=src_val,
                    target_operand=dest_val,
                    is_literal_source=is_lit_src,
                    line_start=line_num,
                    line_end=line_num,
                )
                unit.statements.append(move_node)
                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        line_num,
                        line_num,
                        "MOVE",
                        raw_line,
                        StatementClassification.PARSED_AND_SCORED,
                        "Data MOVE statement",
                        has_terminal_period=line_is_terminated,
                    )
                )
                i += 1
                continue

            if first == "OPEN":
                open_valid = True
                mode = "IO"
                target_f = ""
                if len(tokens) != 3:
                    open_valid = False
                else:
                    mode_tok = tokens[1].upper()
                    if mode_tok in ("INPUT", "OUTPUT", "I-O", "IO", "EXTEND"):
                        mode = "IO" if mode_tok in ("I-O", "IO") else mode_tok
                    else:
                        open_valid = False
                    target_f = tokens[2]
                    if not is_canonical_cobol_identifier(
                        target_f
                    ) or is_unquoted_procedural_starter(target_f):
                        open_valid = False

                if not open_valid:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            "OPEN",
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            "Unsupported OPEN syntax or unconsumed tokens",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                    i += 1
                    continue

                fop_node = ASTFileOp(
                    verb="OPEN",
                    internal_file_name=target_f,
                    access_mode=mode,
                    line_start=line_num,
                    line_end=line_num,
                )
                unit.statements.append(fop_node)
                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        line_num,
                        line_num,
                        "OPEN",
                        raw_line,
                        StatementClassification.PARSED_AND_SCORED,
                        "File OPEN statement",
                        has_terminal_period=line_is_terminated,
                    )
                )
                i += 1
                continue

            if first in ("READ", "WRITE", "CLOSE"):
                fop_valid = True
                target_f = ""
                if len(tokens) != 2:
                    fop_valid = False
                else:
                    target_f = tokens[1]
                    if not is_canonical_cobol_identifier(
                        target_f
                    ) or is_unquoted_procedural_starter(target_f):
                        fop_valid = False

                if not fop_valid:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            first,
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            f"Unsupported {first} syntax or unconsumed tokens",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                    i += 1
                    continue

                fop_node = ASTFileOp(
                    verb=first,
                    internal_file_name=target_f,
                    access_mode=None,
                    line_start=line_num,
                    line_end=line_num,
                )
                unit.statements.append(fop_node)
                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        line_num,
                        line_num,
                        first,
                        raw_line,
                        StatementClassification.PARSED_AND_SCORED,
                        f"File {first} statement",
                        has_terminal_period=line_is_terminated,
                    )
                )
                i += 1
                continue

            if first in ("ADD", "SUBTRACT"):
                start_l = line_num
                full_text = raw_line
                cur_toks = list(tokens)
                has_sentence_ended = line_is_terminated
                while (
                    not (
                        "TO" in [t.upper() for t in cur_toks]
                        or "FROM" in [t.upper() for t in cur_toks]
                    )
                    and (i + 1) < n
                ):
                    if has_sentence_ended:
                        break
                    i += 1
                    full_text += " " + lines[i].strip()
                    next_valid, next_toks, next_term = consume_optional_terminal_period(
                        tokenize_cobol_line(lines[i])
                    )
                    if not next_valid:
                        cur_toks = ["INVALID_PERIOD"]
                        break
                    cur_toks.extend(next_toks)
                    has_sentence_ended = next_term
                end_l = i + 1

                arith_valid = True
                op = ""
                tgt = ""
                if len(cur_toks) != 4:
                    arith_valid = False
                elif first == "ADD" and cur_toks[2].upper() != "TO":
                    arith_valid = False
                elif first == "SUBTRACT" and cur_toks[2].upper() != "FROM":
                    arith_valid = False
                else:
                    op = cur_toks[1]
                    tgt = cur_toks[3]
                    if is_unquoted_procedural_starter(op) or is_unquoted_procedural_starter(tgt):
                        arith_valid = False
                    elif not is_computation_operand(op):
                        arith_valid = False
                    elif not is_canonical_cobol_identifier(tgt):
                        arith_valid = False

                if not arith_valid:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            start_l,
                            end_l,
                            first,
                            full_text,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            f"Unsupported {first} arithmetic syntax or unconsumed tokens",
                            has_terminal_period=has_sentence_ended,
                        )
                    )
                    i += 1
                    continue

                arith_node = ASTArithmetic(
                    verb=first,
                    operand=op,
                    target=tgt,
                    line_start=start_l,
                    line_end=end_l,
                )
                unit.statements.append(arith_node)
                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        start_l,
                        end_l,
                        first,
                        full_text,
                        StatementClassification.PARSED_AND_SCORED,
                        f"Arithmetic {first} statement",
                        has_terminal_period=has_sentence_ended,
                    )
                )
                i += 1
                continue

            if first in ("COMPUTE", "MULTIPLY", "DIVIDE"):
                start_l = i + 1
                cur_valid, cur_toks, has_sentence_ended = consume_optional_terminal_period(tokens)
                full_text = raw_line
                while (
                    not has_sentence_ended
                    and not any(
                        is_cobol_structural_boundary(lines[i + 1]) for _ in [1] if (i + 1) < n
                    )
                    and (i + 1) < n
                ):
                    if has_sentence_ended:
                        break
                    i += 1
                    full_text += " " + lines[i].strip()
                    next_valid, next_toks, next_term = consume_optional_terminal_period(
                        tokenize_cobol_line(lines[i])
                    )
                    if not next_valid:
                        break
                    cur_toks.extend(next_toks)
                    has_sentence_ended = next_term
                end_l = i + 1

                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        start_l,
                        end_l,
                        first,
                        full_text,
                        StatementClassification.UNSUPPORTED_RELEVANT,
                        (
                            f"Unrepresentable arithmetic {first} statement "
                            "in Contract 3.5.3 frozen wire schema"
                        ),
                        has_terminal_period=has_sentence_ended,
                    )
                )
                i += 1
                continue

            if first == "EXIT":
                if len(tokens) == 2 and tokens[1].upper() == "PROGRAM":
                    term_verb = "EXIT_PROGRAM"
                    term_node = ASTTermination(
                        verb=term_verb,
                        line_start=line_num,
                        line_end=line_num,
                    )
                    unit.statements.append(term_node)
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            term_verb,
                            raw_line,
                            StatementClassification.PARSED_AND_SCORED,
                            f"Run-unit {term_verb} termination",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                elif len(tokens) == 1:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            "EXIT",
                            raw_line,
                            StatementClassification.RECOGNIZED_BUT_UNSCORED,
                            "Common procedure end point EXIT statement",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                else:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            "EXIT",
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            "Unsupported compound EXIT statement or unconsumed tokens",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                i += 1
                continue

            if first in ("GOBACK", "STOP"):
                term_valid = True
                term_verb = ""
                if first == "GOBACK":
                    if len(tokens) != 1:
                        term_valid = False
                    else:
                        term_verb = "GOBACK"
                elif first == "STOP":
                    if len(tokens) == 2 and tokens[1].upper() == "RUN":
                        term_verb = "STOP_RUN"
                    else:
                        term_valid = False

                if not term_valid:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            first,
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            f"Unsupported compound {first} statement or unconsumed tokens",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                    i += 1
                    continue

                term_node = ASTTermination(
                    verb=term_verb,
                    line_start=line_num,
                    line_end=line_num,
                )
                unit.statements.append(term_node)
                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        line_num,
                        line_num,
                        term_verb,
                        raw_line,
                        StatementClassification.PARSED_AND_SCORED,
                        f"Run-unit {term_verb} termination",
                        has_terminal_period=line_is_terminated,
                    )
                )
                i += 1
                continue

            if first == "PERFORM":
                perf_valid = False
                is_until = False
                cond_id = ""
                op = ""
                exit_val = ""
                if (
                    len(tokens) == 2
                    and is_canonical_cobol_identifier(tokens[1])
                    and not is_unquoted_procedural_starter(tokens[1])
                ):
                    perf_valid = True
                elif (
                    len(tokens) == 5
                    and tokens[1].upper() == "UNTIL"
                    and tokens[3] in ("=", "!=", "<>", "<", ">", "<=", ">=")
                ):
                    left_op = tokens[2]
                    right_op = tokens[4]
                    left_ok = is_canonical_cobol_identifier(left_op) or is_numeric_literal(left_op)
                    right_ok = (
                        is_canonical_cobol_identifier(right_op)
                        or is_numeric_literal(right_op)
                        or (right_op.startswith("'") and right_op.endswith("'"))
                        or (right_op.startswith('"') and right_op.endswith('"'))
                    )
                    if left_ok and right_ok:
                        perf_valid = True
                        is_until = True
                        if is_canonical_cobol_identifier(left_op):
                            cond_id = left_op
                            op = tokens[3]
                            exit_val = exact_syntactic_unquote(right_op)
                        elif is_canonical_cobol_identifier(right_op):
                            cond_id = right_op
                            op = tokens[3]
                            exit_val = exact_syntactic_unquote(left_op)

                if not perf_valid:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            "PERFORM",
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            "Unsupported PERFORM syntax or unconsumed tokens",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                else:
                    if is_until:
                        unit.statements.append(
                            ASTPerformUntil(
                                verb="PERFORM",
                                line_start=line_num,
                                line_end=line_num,
                                condition_identifier=cond_id,
                                comparison_operator=op,
                                exit_literal=exit_val,
                            )
                        )
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            "PERFORM",
                            raw_line,
                            StatementClassification.PARSED_AND_SCORED,
                            "Procedural loop PERFORM",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                i += 1
                continue

            if first in ("IF", "EVALUATE", "WHEN"):
                branch_valid = False
                if first == "IF":
                    rel_ops = ("=", "!=", "<>", "<", ">", "<=", ">=")
                    if len(tokens) == 4 and tokens[2] in rel_ops:
                        left_op, right_op = tokens[1], tokens[3]
                        left_ok = is_canonical_cobol_identifier(left_op) or is_numeric_literal(
                            left_op
                        )
                        right_ok = (
                            is_canonical_cobol_identifier(right_op)
                            or is_numeric_literal(right_op)
                            or (right_op.startswith("'") and right_op.endswith("'"))
                            or (right_op.startswith('"') and right_op.endswith('"'))
                        )
                        if left_ok and right_ok:
                            branch_valid = True
                    elif len(tokens) == 6 and tokens[2] in rel_ops and tokens[4].upper() == "OR":
                        left_op, right_op1, right_op2 = tokens[1], tokens[3], tokens[5]
                        left_ok = is_canonical_cobol_identifier(left_op) or is_numeric_literal(
                            left_op
                        )
                        r1_ok = (
                            is_canonical_cobol_identifier(right_op1)
                            or is_numeric_literal(right_op1)
                            or (right_op1.startswith("'") and right_op1.endswith("'"))
                            or (right_op1.startswith('"') and right_op1.endswith('"'))
                        )
                        r2_ok = (
                            is_canonical_cobol_identifier(right_op2)
                            or is_numeric_literal(right_op2)
                            or (right_op2.startswith("'") and right_op2.endswith("'"))
                            or (right_op2.startswith('"') and right_op2.endswith('"'))
                        )
                        if left_ok and r1_ok and r2_ok:
                            branch_valid = True
                elif first == "EVALUATE":
                    if len(tokens) == 2 and (
                        is_canonical_cobol_identifier(tokens[1])
                        or tokens[1].upper() in ("TRUE", "FALSE")
                    ):
                        branch_valid = True
                elif first == "WHEN":
                    if len(tokens) == 2:
                        w_op = tokens[1]
                        if (
                            w_op.upper() == "OTHER"
                            or is_canonical_cobol_identifier(w_op)
                            or is_numeric_literal(w_op)
                            or (w_op.startswith("'") and w_op.endswith("'"))
                            or (w_op.startswith('"') and w_op.endswith('"'))
                        ):
                            branch_valid = True

                if not branch_valid:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            first,
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            f"Unsupported {first} syntax or unconsumed tokens",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                else:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            first,
                            raw_line,
                            StatementClassification.PARSED_AND_SCORED,
                            f"Branching {first} statement",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                i += 1
                continue

            if first in ("ELSE", "END-IF", "END-EVALUATE", "END-PERFORM", "END-READ"):
                if len(tokens) == 1:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            first,
                            raw_line,
                            StatementClassification.RECOGNIZED_BUT_UNSCORED,
                            f"Procedural delimiter {first}",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                else:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            first,
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            f"Unsupported {first} delimiter syntax or unconsumed tokens",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                i += 1
                continue

            if first == "ACCEPT":
                if (
                    len(tokens) == 2
                    and is_canonical_cobol_identifier(tokens[1])
                    and not is_unquoted_procedural_starter(tokens[1])
                ):
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            first,
                            raw_line,
                            StatementClassification.RECOGNIZED_BUT_UNSCORED,
                            "Procedural console I/O ACCEPT",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                else:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            first,
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            "Unsupported ACCEPT syntax or unconsumed tokens",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                i += 1
                continue

            if first == "DISPLAY":
                declared_ids = (
                    {f.name.upper() for rec in unit.record_declarations for f in rec.fields}
                    | {rec.container_name.upper() for rec in unit.record_declarations}
                    | {fb.internal_file_name.upper() for fb in unit.file_bindings}
                )
                disp_valid = False
                if len(tokens) >= 5 and [t.upper() for t in tokens[-3:]] == [
                    "WITH",
                    "NO",
                    "ADVANCING",
                ]:
                    items = tokens[1:-3]
                    if len(items) == 1:
                        item = items[0]
                        if (item.startswith("'") and item.endswith("'")) or (
                            item.startswith('"') and item.endswith('"')
                        ):
                            disp_valid = True
                        elif is_canonical_cobol_identifier(item) and item.upper() in declared_ids:
                            disp_valid = True
                elif len(tokens) == 2:
                    item = tokens[1]
                    if (item.startswith("'") and item.endswith("'")) or (
                        item.startswith('"') and item.endswith('"')
                    ):
                        disp_valid = True
                    elif is_canonical_cobol_identifier(item) and item.upper() in declared_ids:
                        disp_valid = True
                elif len(tokens) == 3:
                    item1 = tokens[1]
                    item2 = tokens[2]
                    is_lit1 = (item1.startswith("'") and item1.endswith("'")) or (
                        item1.startswith('"') and item1.endswith('"')
                    )
                    if (
                        is_lit1
                        and is_canonical_cobol_identifier(item2)
                        and item2.upper() in declared_ids
                    ):
                        disp_valid = True

                if disp_valid:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            first,
                            raw_line,
                            StatementClassification.RECOGNIZED_BUT_UNSCORED,
                            "Procedural console I/O DISPLAY",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                else:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            first,
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            "Unsupported DISPLAY syntax or unconsumed tokens",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                i += 1
                continue

            if first == "AT":
                if len(tokens) == 2 and tokens[1].upper() == "END":
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            first,
                            raw_line,
                            StatementClassification.RECOGNIZED_BUT_UNSCORED,
                            "Procedural clause helper AT END",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                else:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            first,
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            "Unsupported AT clause syntax or unconsumed tokens",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                i += 1
                continue

            if first == "NOT":
                if len(tokens) == 3 and tokens[1].upper() == "AT" and tokens[2].upper() == "END":
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            first,
                            raw_line,
                            StatementClassification.RECOGNIZED_BUT_UNSCORED,
                            "Procedural clause helper NOT AT END",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                else:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            first,
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            "Unsupported NOT clause syntax or unconsumed tokens",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                i += 1
                continue

            if first == "GO":
                if (
                    len(tokens) == 3
                    and tokens[1].upper() == "TO"
                    and is_canonical_cobol_identifier(tokens[2])
                    and not is_unquoted_procedural_starter(tokens[2])
                ):
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            first,
                            raw_line,
                            StatementClassification.RECOGNIZED_BUT_UNSCORED,
                            "Procedural control-flow barrier GO TO",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                else:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            first,
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            "Unsupported GO TO syntax or unconsumed tokens",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                i += 1
                continue

            if first == "GOTO":
                if (
                    len(tokens) == 2
                    and is_canonical_cobol_identifier(tokens[1])
                    and not is_unquoted_procedural_starter(tokens[1])
                ):
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            first,
                            raw_line,
                            StatementClassification.RECOGNIZED_BUT_UNSCORED,
                            "Procedural control-flow barrier GOTO",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                else:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            first,
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            "Unsupported GOTO syntax or unconsumed tokens",
                            has_terminal_period=line_is_terminated,
                        )
                    )
                i += 1
                continue

            # Non-allowlisted statements MUST be classified as UNSUPPORTED_RELEVANT
            self.statements.append(
                ClassifiedStatement(
                    target_file.relative_path,
                    line_num,
                    line_num,
                    first,
                    raw_line,
                    StatementClassification.UNSUPPORTED_RELEVANT,
                    f"Unsupported procedural/declarative statement: {first}",
                    has_terminal_period=line_is_terminated,
                )
            )
            if not in_procedure_division and current_record:
                current_record.is_unsupported = True
                current_record.line_end = max(current_record.line_end, line_num)
            i += 1

        return unit

    def _parse_procedural_cf_block(
        self,
        stmts: list[ClassifiedStatement],
        start_idx: int = 0,
        stop_verbs: set[str] | None = None,
        stop_on_period: bool = False,
    ) -> tuple[list[Any], int, bool]:
        """Parse procedural statements into hierarchical control-flow blocks.

        Respects COBOL sentence boundaries where a period terminates open conditional scopes.
        Returns (nodes, next_idx, period_terminated).
        """
        if stop_verbs is None:
            stop_verbs = set()
        nodes: list[Any] = []
        i = start_idx
        while i < len(stmts):
            s = stmts[i]
            if s.verb in stop_verbs:
                return nodes, i, False

            if s.verb == "IF":
                then_nodes, next_i, p_term = self._parse_procedural_cf_block(
                    stmts, i + 1, {"ELSE", "END-IF"}, stop_on_period=True
                )
                else_nodes: list[Any] = []
                if p_term:
                    nodes.append(("IF", s, then_nodes, else_nodes))
                    i = next_i
                    if stop_on_period:
                        return nodes, i, True
                    continue

                if next_i < len(stmts) and stmts[next_i].verb == "ELSE":
                    else_nodes, next_i, p_term_else = self._parse_procedural_cf_block(
                        stmts, next_i + 1, {"END-IF"}, stop_on_period=True
                    )
                    if p_term_else:
                        nodes.append(("IF", s, then_nodes, else_nodes))
                        i = next_i
                        if stop_on_period:
                            return nodes, i, True
                        continue

                end_if_term = False
                if next_i < len(stmts) and stmts[next_i].verb == "END-IF":
                    if stmts[next_i].has_terminal_period:
                        end_if_term = True
                    next_i += 1
                nodes.append(("IF", s, then_nodes, else_nodes))
                i = next_i
                if end_if_term and stop_on_period:
                    return nodes, i, True

            elif s.verb == "PERFORM" and "UNTIL" in s.raw_text.upper():
                body_nodes, next_i, p_term = self._parse_procedural_cf_block(
                    stmts, i + 1, {"END-PERFORM"}, stop_on_period=True
                )
                end_perf_term = False
                if next_i < len(stmts) and stmts[next_i].verb == "END-PERFORM":
                    if stmts[next_i].has_terminal_period:
                        end_perf_term = True
                    next_i += 1
                nodes.append(("PERFORM_UNTIL", s, body_nodes))
                i = next_i
                if (p_term or end_perf_term) and stop_on_period:
                    return nodes, i, True

            elif s.verb == "SENTENCE_BOUNDARY":
                i += 1
                if stop_on_period:
                    return nodes, i, True
                continue

            elif s.verb == "READ":
                if s.has_terminal_period:
                    nodes.append(("READ", s, [], []))
                    i += 1
                    if stop_on_period:
                        return nodes, i, True
                    continue

                at_end_nodes: list[Any] = []
                not_at_end_nodes: list[Any] = []
                cur_mode: str | None = None
                next_i = i + 1
                read_p_term = False
                while next_i < len(stmts):
                    v = stmts[next_i].verb
                    if v in stop_verbs:
                        break
                    if v == "END-READ":
                        if stmts[next_i].has_terminal_period:
                            read_p_term = True
                        next_i += 1
                        break
                    if v == "AT":
                        cur_mode = "AT_END"
                        next_i += 1
                        continue
                    if v == "NOT":
                        cur_mode = "NOT_AT_END"
                        next_i += 1
                        continue
                    if cur_mode is None:
                        # Non-clause statement after unterminated READ: stop clause parsing!
                        break
                    sub_nodes, next_i, p_sub = self._parse_procedural_cf_block(
                        stmts, next_i, {"AT", "NOT", "END-READ"}, stop_on_period=True
                    )
                    if cur_mode == "AT_END":
                        at_end_nodes.extend(sub_nodes)
                    elif cur_mode == "NOT_AT_END":
                        not_at_end_nodes.extend(sub_nodes)
                    if p_sub:
                        read_p_term = True
                        break

                nodes.append(("READ", s, at_end_nodes, not_at_end_nodes))
                i = next_i
                if read_p_term and stop_on_period:
                    return nodes, i, True

            elif s.verb == "EVALUATE":
                when_blocks: list[tuple[ClassifiedStatement, list[Any]]] = []
                cur_when_stmt: ClassifiedStatement | None = None
                cur_when_nodes: list[Any] = []
                next_i = i + 1
                eval_p_term = False
                while next_i < len(stmts):
                    v = stmts[next_i].verb
                    if v in stop_verbs:
                        break
                    if v == "END-EVALUATE":
                        if cur_when_stmt:
                            when_blocks.append((cur_when_stmt, cur_when_nodes))
                            cur_when_stmt = None
                            cur_when_nodes = []
                        if stmts[next_i].has_terminal_period:
                            eval_p_term = True
                        next_i += 1
                        break
                    if v == "WHEN":
                        if cur_when_stmt:
                            when_blocks.append((cur_when_stmt, cur_when_nodes))
                            cur_when_nodes = []
                        cur_when_stmt = stmts[next_i]
                        next_i += 1
                        continue
                    sub_nodes, next_i, p_sub = self._parse_procedural_cf_block(
                        stmts, next_i, {"WHEN", "END-EVALUATE"}, stop_on_period=True
                    )
                    cur_when_nodes.extend(sub_nodes)
                    if p_sub:
                        eval_p_term = True
                        break

                if cur_when_stmt:
                    when_blocks.append((cur_when_stmt, cur_when_nodes))
                nodes.append(("EVALUATE", s, when_blocks))
                i = next_i
                if eval_p_term and stop_on_period:
                    return nodes, i, True

            else:
                nodes.append(("STMT", s))
                i += 1
                if s.has_terminal_period and stop_on_period:
                    return nodes, i, True

        return nodes, i, False

    def _verify_finite_loop_progress(
        self,
        loop_stmt: ClassifiedStatement,
        body_nodes: list[Any],
        callee_unit: ASTCompilationUnit,
    ) -> bool:
        """Verify that a PERFORM UNTIL loop has proven finite-progress semantics."""
        perf_node = next(
            (
                s
                for s in callee_unit.statements
                if isinstance(s, ASTPerformUntil) and s.line_start == loop_stmt.line_start
            ),
            None,
        )
        if perf_node is None:
            return False

        cond_id = perf_node.condition_identifier
        op = perf_node.comparison_operator
        exit_lit = perf_node.exit_literal

        if op != "=" or not cond_id or not exit_lit:
            return False

        # Premise 1: Initialization before loop
        init_moves = [
            s
            for s in callee_unit.statements
            if isinstance(s, ASTMove)
            and s.target_operand == cond_id
            and s.line_end < loop_stmt.line_start
        ]
        if init_moves:
            latest_init = init_moves[-1]
            if _safe_unquote(latest_init.source_operand) == exit_lit:
                return False
            check_from = latest_init.line_end
        else:
            rec = next(
                (r for r in callee_unit.record_declarations if r.container_name == cond_id),
                None,
            )
            if not rec or rec.initial_value is None:
                return False
            if _safe_unquote(rec.initial_value) == exit_lit:
                return False
            check_from = 0

        # Ensure no intervening statement before loop overwrote cond_id with exit_lit
        intervening_stmts = [
            s
            for s in callee_unit.statements
            if s.line_start > check_from and s.line_end < loop_stmt.line_start
        ]
        for s in intervening_stmts:
            if isinstance(s, ASTMove) and s.target_operand == cond_id:
                if _safe_unquote(s.source_operand) == exit_lit:
                    return False
            if isinstance(s, ASTArithmetic) and s.target == cond_id:
                return False

        # Premise 2: Open sequential input resource prior to loop
        open_ops = [
            s
            for s in callee_unit.statements
            if isinstance(s, ASTFileOp)
            and s.verb == "OPEN"
            and s.access_mode == "INPUT"
            and s.line_end < loop_stmt.line_start
        ]
        if not open_ops:
            return False
        latest_open = open_ops[-1]
        file_id = latest_open.internal_file_name

        binding = next(
            (fb for fb in callee_unit.file_bindings if fb.internal_file_name == file_id),
            None,
        )
        if binding is None or binding.organization not in ("SEQUENTIAL", "LINE_SEQUENTIAL"):
            return False

        # Premise 3: Body inspection
        def _collect_kinds(nodes: list[Any], target_kind: str) -> list[Any]:
            res: list[Any] = []
            for n in nodes:
                if n[0] == target_kind:
                    res.append(n)
                if n[0] == "IF":
                    res.extend(_collect_kinds(n[2], target_kind))
                    res.extend(_collect_kinds(n[3], target_kind))
                elif n[0] == "READ":
                    res.extend(_collect_kinds(n[2], target_kind))
                    res.extend(_collect_kinds(n[3], target_kind))
                elif n[0] == "EVALUATE":
                    for _, wb in n[2]:
                        res.extend(_collect_kinds(wb, target_kind))
                elif n[0] == "PERFORM_UNTIL":
                    res.extend(_collect_kinds(n[2], target_kind))
            return res

        # No nested loops
        if _collect_kinds(body_nodes, "PERFORM_UNTIL"):
            return False

        # Exactly one READ on the open resource
        read_nodes = _collect_kinds(body_nodes, "READ")
        if len(read_nodes) != 1:
            return False
        rn = read_nodes[0]
        read_stmt: ClassifiedStatement = rn[1]
        ast_read = next(
            (
                s
                for s in callee_unit.statements
                if isinstance(s, ASTFileOp)
                and s.verb == "READ"
                and s.line_start == read_stmt.line_start
            ),
            None,
        )
        if ast_read is None or ast_read.internal_file_name != file_id:
            return False

        # Premise 4: AT END sets condition_identifier to exit_literal
        at_end_nodes = rn[2]
        at_end_moves = [
            s
            for s in callee_unit.statements
            if isinstance(s, ASTMove)
            and any(n[0] == "STMT" and n[1].line_start == s.line_start for n in at_end_nodes)
        ]
        has_exit_move = any(
            m.target_operand == cond_id and _safe_unquote(m.source_operand) == exit_lit
            for m in at_end_moves
        )
        if not has_exit_move:
            return False

        # Premise 5: No other statement in body modifies cond_id
        def _get_all_stmts(nodes: list[Any]) -> list[ClassifiedStatement]:
            res: list[ClassifiedStatement] = []
            for n in nodes:
                if n[0] == "STMT":
                    res.append(n[1])
                elif n[0] == "IF":
                    res.extend(_get_all_stmts(n[2]))
                    res.extend(_get_all_stmts(n[3]))
                elif n[0] == "READ":
                    res.extend(_get_all_stmts(n[3]))
                elif n[0] == "EVALUATE":
                    for _, wb in n[2]:
                        res.extend(_get_all_stmts(wb))
            return res

        non_at_end_stmts = _get_all_stmts(body_nodes)
        for cstmt in non_at_end_stmts:
            if cstmt.classification == StatementClassification.UNSUPPORTED_RELEVANT:
                return False
            ast_m = next(
                (
                    m
                    for m in callee_unit.statements
                    if isinstance(m, ASTMove) and m.line_start == cstmt.line_start
                ),
                None,
            )
            if ast_m and ast_m.target_operand == cond_id:
                return False
            ast_a = next(
                (
                    a
                    for a in callee_unit.statements
                    if isinstance(a, ASTArithmetic) and a.line_start == cstmt.line_start
                ),
                None,
            )
            if ast_a and ast_a.target == cond_id:
                return False
            if cstmt.verb == "ACCEPT" and cond_id in tokenize_cobol_line(cstmt.raw_text):
                return False

        # Premise 6: No CLOSE or OPEN on file_id in body, no unresolved CALLs
        all_body_stmts: list[ClassifiedStatement] = []

        def _collect_all_stmts(nodes: list[Any]) -> None:
            for n in nodes:
                if n[0] == "STMT":
                    all_body_stmts.append(n[1])
                elif n[0] == "IF":
                    _collect_all_stmts(n[2])
                    _collect_all_stmts(n[3])
                elif n[0] == "READ":
                    _collect_all_stmts(n[2])
                    _collect_all_stmts(n[3])
                elif n[0] == "EVALUATE":
                    for _, wb in n[2]:
                        _collect_all_stmts(wb)

        _collect_all_stmts(body_nodes)

        for cstmt in all_body_stmts:
            ast_f = next(
                (
                    f
                    for f in callee_unit.statements
                    if isinstance(f, ASTFileOp) and f.line_start == cstmt.line_start
                ),
                None,
            )
            if ast_f and ast_f.verb in ("OPEN", "CLOSE") and ast_f.internal_file_name == file_id:
                return False
            if cstmt.verb == "CALL":
                ast_c = next(
                    (
                        c
                        for c in callee_unit.statements
                        if isinstance(c, ASTCall) and c.line_start == cstmt.line_start
                    ),
                    None,
                )
                if not ast_c or not ast_c.is_literal:
                    return False
                if ast_c.target != "SYSTEM":
                    tgt_u = next(
                        (u for u in self.compilation_units if u.program_id == ast_c.target),
                        None,
                    )
                    if not tgt_u:
                        return False

        return True

    def _compose_branch_union(self, branches: list[FlowResult]) -> FlowResult:
        if not branches:
            return FlowResult(fallthrough_possible=True)
        if any(b.unknown for b in branches):
            return FlowResult(
                fallthrough_possible=any(b.fallthrough_possible for b in branches),
                process_termination_witnesses=tuple(
                    dict.fromkeys(w for b in branches for w in b.process_termination_witnesses)
                ),
                return_witnesses=tuple(
                    dict.fromkeys(w for b in branches for w in b.return_witnesses)
                ),
                unknown=True,
            )
        return FlowResult(
            fallthrough_possible=any(b.fallthrough_possible for b in branches),
            process_termination_witnesses=tuple(
                dict.fromkeys(w for b in branches for w in b.process_termination_witnesses)
            ),
            return_witnesses=tuple(dict.fromkeys(w for b in branches for w in b.return_witnesses)),
            unknown=False,
        )

    def _compose_sequence(self, first: FlowResult, second: FlowResult) -> FlowResult:
        if first.unknown:
            return FlowResult(
                fallthrough_possible=False,
                process_termination_witnesses=first.process_termination_witnesses,
                return_witnesses=first.return_witnesses,
                unknown=True,
            )
        if not first.fallthrough_possible:
            return first

        combined_proc = first.process_termination_witnesses + second.process_termination_witnesses
        all_proc = tuple(dict.fromkeys(combined_proc))
        all_ret = tuple(dict.fromkeys(first.return_witnesses + second.return_witnesses))
        if second.unknown:
            return FlowResult(
                fallthrough_possible=False,
                process_termination_witnesses=all_proc,
                return_witnesses=all_ret,
                unknown=True,
            )
        return FlowResult(
            fallthrough_possible=second.fallthrough_possible,
            process_termination_witnesses=all_proc,
            return_witnesses=all_ret,
            unknown=False,
        )

    def _analyze_cf_nodes(
        self,
        nodes: list[Any],
        callee_unit: ASTCompilationUnit,
        call_stack: frozenset[str],
    ) -> FlowResult:
        """Trace CFG nodes to conservatively determine execution effect."""
        current_result = FlowResult(fallthrough_possible=True)
        idx = 0
        while idx < len(nodes):
            if not current_result.fallthrough_possible:
                break
            if current_result.unknown:
                return FlowResult(
                    fallthrough_possible=False,
                    process_termination_witnesses=current_result.process_termination_witnesses,
                    return_witnesses=current_result.return_witnesses,
                    unknown=True,
                )

            node = nodes[idx]
            kind = node[0]
            node_res: FlowResult

            if kind == "STMT":
                s: ClassifiedStatement = node[1]
                if s.classification == StatementClassification.UNSUPPORTED_RELEVANT:
                    node_res = FlowResult(fallthrough_possible=False, unknown=True)
                elif s.verb in ("GO", "GOTO"):
                    node_res = FlowResult(fallthrough_possible=False, unknown=True)
                elif s.verb == "STOP_RUN":
                    witness = TerminationWitness(
                        program_id=callee_unit.program_id or "",
                        file_path=callee_unit.file_path,
                        line_start=s.line_start,
                        line_end=s.line_end,
                        termination_kind="STOP_RUN",
                    )
                    node_res = FlowResult(
                        fallthrough_possible=False,
                        process_termination_witnesses=(witness,),
                    )
                elif s.verb in ("GOBACK", "EXIT_PROGRAM"):
                    witness = TerminationWitness(
                        program_id=callee_unit.program_id or "",
                        file_path=callee_unit.file_path,
                        line_start=s.line_start,
                        line_end=s.line_end,
                        termination_kind=s.verb,
                    )
                    node_res = FlowResult(
                        fallthrough_possible=False,
                        return_witnesses=(witness,),
                    )
                elif s.verb == "CALL":
                    ast_call = next(
                        (
                            c
                            for c in callee_unit.statements
                            if isinstance(c, ASTCall) and c.line_start == s.line_start
                        ),
                        None,
                    )
                    if not ast_call or not ast_call.is_literal:
                        node_res = FlowResult(fallthrough_possible=False, unknown=True)
                    elif ast_call.target == "SYSTEM":
                        cmd_var = ast_call.using_args[0] if ast_call.using_args else None
                        if cmd_var:
                            prec_move = next(
                                (
                                    m
                                    for m in reversed(callee_unit.statements)
                                    if isinstance(m, ASTMove)
                                    and m.target_operand == cmd_var
                                    and m.line_end < s.line_start
                                ),
                                None,
                            )
                            if prec_move and prec_move.is_literal_source:
                                cmd_lit = exact_syntactic_unquote(prec_move.source_operand)
                                dialect, _, _ = classify_command_dialect(cmd_lit)
                                if dialect == CommandDialect.SUPPORTED_WINDOWS_CMD:
                                    node_res = FlowResult(fallthrough_possible=True)
                                else:
                                    node_res = FlowResult(fallthrough_possible=False, unknown=True)
                            else:
                                node_res = FlowResult(fallthrough_possible=False, unknown=True)
                        else:
                            node_res = FlowResult(fallthrough_possible=False, unknown=True)
                    else:
                        target = ast_call.target
                        target_unit = next(
                            (u for u in self.compilation_units if u.program_id == target),
                            None,
                        )
                        if not target_unit or target in call_stack:
                            node_res = FlowResult(fallthrough_possible=False, unknown=True)
                        else:
                            callee_flow = self._prove_callee_continuation(target_unit, call_stack)
                            if callee_flow.unknown:
                                node_res = FlowResult(fallthrough_possible=False, unknown=True)
                            else:
                                can_return_to_caller_from_callee = (
                                    callee_flow.fallthrough_possible
                                    or len(callee_flow.return_witnesses) > 0
                                )
                                node_res = FlowResult(
                                    fallthrough_possible=can_return_to_caller_from_callee,
                                    process_termination_witnesses=callee_flow.process_termination_witnesses,
                                    return_witnesses=(),
                                    unknown=callee_flow.unknown,
                                )
                elif s.verb in (
                    "DISPLAY",
                    "ACCEPT",
                    "MOVE",
                    "OPEN",
                    "CLOSE",
                    "WRITE",
                    "ADD",
                    "SUBTRACT",
                ):
                    node_res = FlowResult(fallthrough_possible=True)
                else:
                    node_res = FlowResult(fallthrough_possible=False, unknown=True)

            elif kind == "IF":
                then_nodes, else_nodes = node[2], node[3]
                then_res = self._analyze_cf_nodes(then_nodes, callee_unit, call_stack)
                else_res = (
                    self._analyze_cf_nodes(else_nodes, callee_unit, call_stack)
                    if else_nodes
                    else FlowResult(fallthrough_possible=True)
                )
                node_res = self._compose_branch_union([then_res, else_res])

            elif kind == "PERFORM_UNTIL":
                loop_stmt, body_nodes = node[1], node[2]
                if not self._verify_finite_loop_progress(loop_stmt, body_nodes, callee_unit):
                    node_res = FlowResult(fallthrough_possible=False, unknown=True)
                else:
                    body_res = self._analyze_cf_nodes(body_nodes, callee_unit, call_stack)
                    node_res = FlowResult(
                        fallthrough_possible=True,
                        process_termination_witnesses=body_res.process_termination_witnesses,
                        return_witnesses=body_res.return_witnesses,
                        unknown=body_res.unknown,
                    )

            elif kind == "READ":
                at_end_nodes, not_at_end_nodes = node[2], node[3]
                at_end_res = (
                    self._analyze_cf_nodes(at_end_nodes, callee_unit, call_stack)
                    if at_end_nodes
                    else FlowResult(fallthrough_possible=True)
                )
                not_at_end_res = (
                    self._analyze_cf_nodes(not_at_end_nodes, callee_unit, call_stack)
                    if not_at_end_nodes
                    else FlowResult(fallthrough_possible=True)
                )
                node_res = self._compose_branch_union([at_end_res, not_at_end_res])

            elif kind == "EVALUATE":
                when_blocks = node[2]
                if not when_blocks:
                    node_res = FlowResult(fallthrough_possible=True)
                else:
                    branch_results = [
                        self._analyze_cf_nodes(wb, callee_unit, call_stack) for _, wb in when_blocks
                    ]
                    has_when_other = any(
                        [t.upper().rstrip(".") for t in tokenize_cobol_line(w_stmt.raw_text)]
                        == ["WHEN", "OTHER"]
                        for w_stmt, _ in when_blocks
                    )
                    if not has_when_other:
                        branch_results.append(FlowResult(fallthrough_possible=True))
                    node_res = self._compose_branch_union(branch_results)

            else:
                node_res = FlowResult(fallthrough_possible=False, unknown=True)

            current_result = self._compose_sequence(current_result, node_res)
            idx += 1

        return current_result

    def _are_statements_in_same_linear_cf_segment(
        self,
        stmt1: ClassifiedStatement | ASTStatement,
        stmt2: ClassifiedStatement | ASTStatement,
        callee_unit: ASTCompilationUnit,
    ) -> bool:
        """Determine if stmt1 and stmt2 are consecutive in the same linear control-flow segment."""
        proc_idx = next(
            (
                i
                for i, s in enumerate(self.statements)
                if s.file_path == callee_unit.file_path and s.verb == "PROCEDURE_DIVISION"
            ),
            None,
        )
        if proc_idx is None:
            return False

        prog_stmts = [
            s
            for s in self.statements[proc_idx + 1 :]
            if s.file_path == callee_unit.file_path and s.verb != "PARAGRAPH_HEADER"
        ]
        nodes, _, _ = self._parse_procedural_cf_block(prog_stmts)

        def _check_linear_list(node_list: list[Any]) -> bool:
            for idx, n in enumerate(node_list):
                if n[0] == "STMT" and n[1].line_start == stmt1.line_start:
                    if idx + 1 < len(node_list):
                        next_n = node_list[idx + 1]
                        if next_n[0] == "STMT" and next_n[1].line_start == stmt2.line_start:
                            return True
                    return False
                elif n[0] == "IF":
                    if _check_linear_list(n[2]) or _check_linear_list(n[3]):
                        return True
                elif n[0] == "PERFORM_UNTIL":
                    if _check_linear_list(n[2]):
                        return True
                elif n[0] == "READ":
                    if _check_linear_list(n[2]) or _check_linear_list(n[3]):
                        return True
                elif n[0] == "EVALUATE":
                    for _, wb in n[2]:
                        if _check_linear_list(wb):
                            return True
            return False

        return _check_linear_list(nodes)

    def _prove_callee_continuation(
        self,
        callee_unit: ASTCompilationUnit,
        call_stack: frozenset[str] | None = None,
    ) -> FlowResult:
        """Conservative control-flow effect proof of callee termination outcome.

        Returns outcome-bound FlowResult.
        """
        curr_prog = callee_unit.program_id or ""
        if call_stack is None:
            call_stack = frozenset([curr_prog])
        elif curr_prog in call_stack:
            return FlowResult(fallthrough_possible=False, unknown=True)
        else:
            call_stack = call_stack | {curr_prog}

        callee_stmts = [s for s in self.statements if s.file_path == callee_unit.file_path]
        if any(
            s.classification == StatementClassification.UNSUPPORTED_RELEVANT for s in callee_stmts
        ):
            return FlowResult(fallthrough_possible=False, unknown=True)

        if any(s.verb in ("GO", "GOTO") for s in callee_stmts):
            return FlowResult(fallthrough_possible=False, unknown=True)

        proc_idx = next(
            (
                i
                for i, s in enumerate(self.statements)
                if s.file_path == callee_unit.file_path and s.verb == "PROCEDURE_DIVISION"
            ),
            None,
        )
        if proc_idx is None:
            return FlowResult(fallthrough_possible=False, unknown=True)

        prog_stmts = [
            s
            for s in self.statements[proc_idx + 1 :]
            if s.file_path == callee_unit.file_path and s.verb != "PARAGRAPH_HEADER"
        ]
        nodes, _, _ = self._parse_procedural_cf_block(prog_stmts)
        return self._analyze_cf_nodes(nodes, callee_unit, call_stack)

    # -----------------------------------------------------------------------
    # Generic Deterministic Fact Extraction (Zero Fixture Identifiers)
    # -----------------------------------------------------------------------

    def _extract_generic_system_facts(self) -> None:
        """Extract generic system facts across compilation units without hardcoded constants."""
        programs_by_id: dict[str, ASTCompilationUnit] = {}
        for u in self.compilation_units:
            if u.program_id:
                programs_by_id[u.program_id] = u

        # 1. Program Declarations
        for prog_id, unit in sorted(programs_by_id.items()):
            decl_stmt = next(
                (
                    s
                    for s in self.statements
                    if s.file_path == unit.file_path and s.verb == "PROGRAM-ID"
                ),
                None,
            )
            start_l = decl_stmt.line_start if decl_stmt else unit.line_start
            end_l = decl_stmt.line_end if decl_stmt else unit.line_start
            self.supported_facts.append(
                SupportedSystemFact(
                    fact=ProgramDeclarationFact(program_id=prog_id),
                    proposition_id=f"prop.program.{prog_id.lower().replace('-', '_')}",
                    evidence_spans={"evidence": EvidenceSpan(unit.file_path, start_l, end_l)},
                )
            )

        # 2. Call Occurrences & Edges & Internal Resolutions & Caller Constraints
        call_occurrences: list[tuple[ASTCompilationUnit, ASTCall]] = []
        unique_edges: set[tuple[str, str, str]] = set()

        for unit in self.compilation_units:
            for stmt in unit.statements:
                if isinstance(stmt, ASTCall):
                    call_occurrences.append((unit, stmt))
                    caller = unit.program_id or "UNKNOWN"
                    target = stmt.target
                    mech = "LITERAL_TARGET" if stmt.is_literal else "DYNAMIC_TARGET"
                    arg = stmt.using_args[0] if stmt.using_args else None

                    # Call occurrence
                    prop_idx = len(call_occurrences)
                    self.supported_facts.append(
                        SupportedSystemFact(
                            fact=CallOccurrenceFact(
                                caller_program=caller,
                                target_program=target,
                                call_mechanism=mech,
                                argument_identifier=arg,
                            ),
                            proposition_id=f"prop.call_occ.{caller.lower()}_{target.lower()}_{prop_idx}",
                            evidence_spans={
                                "evidence": EvidenceSpan(
                                    unit.file_path, stmt.line_start, stmt.line_end
                                )
                            },
                        )
                    )

                    # Call edge
                    edge_key = (caller, target, mech)
                    if edge_key not in unique_edges:
                        unique_edges.add(edge_key)
                        self.supported_facts.append(
                            SupportedSystemFact(
                                fact=CallEdgeFact(
                                    caller_program=caller,
                                    target_program=target,
                                    call_mechanism=mech,
                                ),
                                proposition_id=f"prop.call_edge.{caller.lower()}_{target.lower()}",
                                evidence_spans={
                                    "evidence": EvidenceSpan(
                                        unit.file_path, stmt.line_start, stmt.line_end
                                    )
                                },
                            )
                        )

                    # Internal call resolution
                    if stmt.is_literal and target in programs_by_id:
                        callee_unit = programs_by_id[target]
                        callee_decl = next(
                            (
                                s
                                for s in self.statements
                                if s.file_path == callee_unit.file_path and s.verb == "PROGRAM-ID"
                            ),
                            None,
                        )
                        callee_decl_start = callee_decl.line_start if callee_decl else 1
                        callee_decl_end = callee_decl.line_end if callee_decl else 1

                        self.supported_facts.append(
                            SupportedSystemFact(
                                fact=InternalCallResolutionFact(
                                    caller_program=caller,
                                    callee_program=target,
                                ),
                                proposition_id=f"prop.internal_call.{caller.lower()}_{target.lower()}",
                                evidence_spans={
                                    "call_evidence": EvidenceSpan(
                                        unit.file_path, stmt.line_start, stmt.line_end
                                    ),
                                    "target_declaration_evidence": EvidenceSpan(
                                        callee_unit.file_path, callee_decl_start, callee_decl_end
                                    ),
                                },
                            )
                        )

                        # Caller continuation constraint
                        callee_flow = self._prove_callee_continuation(callee_unit)
                        constraint_emitted = False
                        if callee_flow.is_definite_process_terminate:
                            if len(callee_flow.process_termination_witnesses) == 1:
                                w = callee_flow.process_termination_witnesses[0]
                                if w.program_id == target and w.file_path == callee_unit.file_path:
                                    self.supported_facts.append(
                                        SupportedSystemFact(
                                            fact=CallerContinuationConstraintFact(
                                                caller_program=caller,
                                                callee_program=target,
                                                constraint_type="PROCESS_TERMINATION_ON_CALL",
                                            ),
                                            proposition_id=f"prop.continuation.{caller.lower()}_{target.lower()}",
                                            evidence_spans={
                                                "call_evidence": EvidenceSpan(
                                                    unit.file_path, stmt.line_start, stmt.line_end
                                                ),
                                                "callee_termination_evidence": EvidenceSpan(
                                                    callee_unit.file_path,
                                                    w.line_start,
                                                    w.line_end,
                                                ),
                                            },
                                        )
                                    )
                                    constraint_emitted = True
                        elif callee_flow.is_definite_return:
                            if len(callee_flow.return_witnesses) == 1:
                                w = callee_flow.return_witnesses[0]
                                if w.program_id == target and w.file_path == callee_unit.file_path:
                                    self.supported_facts.append(
                                        SupportedSystemFact(
                                            fact=CallerContinuationConstraintFact(
                                                caller_program=caller,
                                                callee_program=target,
                                                constraint_type="RETURN_TO_CALLER",
                                            ),
                                            proposition_id=f"prop.continuation.{caller.lower()}_{target.lower()}",
                                            evidence_spans={
                                                "call_evidence": EvidenceSpan(
                                                    unit.file_path, stmt.line_start, stmt.line_end
                                                ),
                                                "callee_termination_evidence": EvidenceSpan(
                                                    callee_unit.file_path,
                                                    w.line_start,
                                                    w.line_end,
                                                ),
                                            },
                                        )
                                    )
                                    constraint_emitted = True

                        if not constraint_emitted:
                            for idx_s, s in enumerate(self.statements):
                                if (
                                    s.file_path == unit.file_path
                                    and s.line_start == stmt.line_start
                                ):
                                    self.statements[idx_s] = ClassifiedStatement(
                                        s.file_path,
                                        s.line_start,
                                        s.line_end,
                                        s.verb,
                                        s.raw_text,
                                        StatementClassification.UNSUPPORTED_RELEVANT,
                                        "Unproven or unrepresentable continuation outcome",
                                        has_terminal_period=s.has_terminal_period,
                                    )

        # 3. File Bindings
        for unit in self.compilation_units:
            caller = unit.program_id or "UNKNOWN"
            for fb in unit.file_bindings:
                self.supported_facts.append(
                    SupportedSystemFact(
                        fact=FileBindingFact(
                            program_id=caller,
                            internal_file_name=fb.internal_file_name,
                            external_file_name=fb.external_file_name,
                            organization=fb.organization,
                        ),
                        proposition_id=f"prop.binding.{caller.lower()}_{fb.internal_file_name.lower()}",
                        evidence_spans={
                            "evidence": EvidenceSpan(unit.file_path, fb.line_start, fb.line_end)
                        },
                    )
                )

        # 4. Termination Sites
        for unit in self.compilation_units:
            caller = unit.program_id or "UNKNOWN"
            for stmt in unit.statements:
                if isinstance(stmt, ASTTermination):
                    self.supported_facts.append(
                        SupportedSystemFact(
                            fact=TerminationSiteFact(
                                program_id=caller,
                                statement_type=stmt.verb,
                            ),
                            proposition_id=f"prop.term.{caller.lower()}_{stmt.verb.lower()}",
                            evidence_spans={
                                "evidence": EvidenceSpan(
                                    unit.file_path, stmt.line_start, stmt.line_end
                                )
                            },
                        )
                    )

        # 5. Record Layouts (distinct multi-field record layouts)
        all_records: list[tuple[ASTCompilationUnit, ASTRecordDeclaration]] = []
        for unit in self.compilation_units:
            prog_name = unit.program_id or Path(unit.file_path).stem
            for rec in unit.record_declarations:
                if not rec.fields:
                    continue
                has_unsupported_stmt = any(
                    s.file_path == unit.file_path
                    and s.classification == StatementClassification.UNSUPPORTED_RELEVANT
                    and rec.line_start <= s.line_start <= rec.line_end
                    for s in self.statements
                )
                if rec.is_unsupported or has_unsupported_stmt:
                    continue
                all_records.append((unit, rec))
                field_facts = tuple(
                    RecordFieldFact(
                        field_kind=f.field_kind,
                        level=f.level,
                        name=f.name,
                        picture=canonicalize_picture(f.picture) if f.picture is not None else None,
                        usage=f.usage if f.field_kind == "DATA_FIELD" else None,
                        condition_values=tuple(f.condition_values)
                        if f.field_kind == "CONDITION_NAME"
                        else (),
                    )
                    for f in rec.fields
                )
                rec_tag = rec.container_name.lower().replace("-", "_")
                self.supported_facts.append(
                    SupportedSystemFact(
                        fact=RecordLayoutFact(
                            program_id=prog_name,
                            record_name=rec.container_name,
                            fields=field_facts,
                        ),
                        proposition_id=f"prop.layout.{prog_name.lower()}_{rec_tag}",
                        evidence_spans={
                            "evidence": EvidenceSpan(unit.file_path, rec.line_start, rec.line_end)
                        },
                    )
                )

        # Binary Record Layout Comparisons
        self._build_record_layout_relations()

        # 6. Command Invocations, Platform Dependencies, and Operation Sequences
        for unit in self.compilation_units:
            caller = unit.program_id or "UNKNOWN"
            n_stmts = len(unit.statements)
            target_unit_file = self.bundle.get_file(unit.file_path)
            unit_raw_lines = target_unit_file.get_lines()
            commands_in_unit: list[tuple[ASTMove, ASTCall, int, int, MutationCommandResult]] = []

            for idx in range(n_stmts - 1):
                s1 = unit.statements[idx]
                s2 = unit.statements[idx + 1]

                if isinstance(s1, ASTMove) and s1.is_literal_source and isinstance(s2, ASTCall):
                    if (
                        s2.is_literal
                        and s2.target == "SYSTEM"
                        and s2.using_args == [s1.target_operand]
                    ):
                        # B-03: Strict procedural linearity and barrier check
                        # between MOVE and CALL SYSTEM
                        has_intervening_stmt = any(
                            s.file_path == unit.file_path
                            and s1.line_end < s.line_start < s2.line_start
                            for s in self.statements
                        )
                        has_barrier = has_intervening_stmt or has_procedural_barrier_between(
                            unit_raw_lines, s1.line_end, s2.line_start
                        )
                        if has_barrier:
                            continue

                        try:
                            if "\\" in s1.source_operand:
                                raise ValueError("Unsupported quoting in command source operand")
                            cmd_clean = exact_syntactic_unquote(s1.source_operand)
                            if s1.source_operand[0] in cmd_clean or not cmd_clean:
                                raise ValueError("Unconsumed quote or empty command literal")
                        except ValueError:
                            for idx_s, s in enumerate(self.statements):
                                if s.file_path == unit.file_path and s.line_start in (
                                    s1.line_start,
                                    s2.line_start,
                                ):
                                    self.statements[idx_s] = ClassifiedStatement(
                                        s.file_path,
                                        s.line_start,
                                        s.line_end,
                                        s.verb,
                                        s.raw_text,
                                        StatementClassification.UNSUPPORTED_RELEVANT,
                                        "Unsupported quoting or empty literal in command statement",
                                    )
                            continue

                        # Command invocation (opaque command fact is derivable)
                        cmd_idx = len(commands_in_unit) + 1
                        self.supported_facts.append(
                            SupportedSystemFact(
                                fact=CommandInvocationFact(
                                    program_id=caller,
                                    command_template=cmd_clean,
                                    target_operand=s1.target_operand,
                                ),
                                proposition_id=f"prop.command.{caller.lower()}_{cmd_idx}",
                                evidence_spans={
                                    "assignment_evidence": EvidenceSpan(
                                        unit.file_path, s1.line_start, s1.line_end
                                    ),
                                    "call_evidence": EvidenceSpan(
                                        unit.file_path, s2.line_start, s2.line_end
                                    ),
                                },
                            )
                        )

                        # Platform dependency (Contract 3.5.3 wire schema permits only WINDOWS)
                        dialect, unwrapped_cmd, dialect_reason = classify_command_dialect(cmd_clean)
                        if dialect != CommandDialect.SUPPORTED_WINDOWS_CMD:
                            fail_reason = (
                                dialect_reason
                                or f"Unsupported command dialect or shell wrapper: '{cmd_clean}'"
                            )
                            for idx_s, s in enumerate(self.statements):
                                if s.file_path == unit.file_path and s.line_start in (
                                    s1.line_start,
                                    s2.line_start,
                                ):
                                    self.statements[idx_s] = ClassifiedStatement(
                                        s.file_path,
                                        s.line_start,
                                        s.line_end,
                                        s.verb,
                                        s.raw_text,
                                        StatementClassification.UNSUPPORTED_RELEVANT,
                                        fail_reason,
                                    )
                            continue

                        self.supported_facts.append(
                            SupportedSystemFact(
                                fact=PlatformDependencyFact(
                                    program_id=caller,
                                    platform_family="WINDOWS",
                                    command_literal=cmd_clean,
                                ),
                                proposition_id=f"prop.platform.{caller.lower()}_{cmd_idx}",
                                evidence_spans={
                                    "evidence": EvidenceSpan(
                                        unit.file_path, s1.line_start, s1.line_end
                                    )
                                },
                            )
                        )

                        mut_res = classify_mutation_command(cmd_clean)
                        if mut_res.status == "MUTATION_UNSUPPORTED":
                            for idx_s, s in enumerate(self.statements):
                                if s.file_path == unit.file_path and s.line_start in (
                                    s1.line_start,
                                    s2.line_start,
                                ):
                                    self.statements[idx_s] = ClassifiedStatement(
                                        s.file_path,
                                        s.line_start,
                                        s.line_end,
                                        s.verb,
                                        s.raw_text,
                                        StatementClassification.UNSUPPORTED_RELEVANT,
                                        (
                                            "Unsupported or malformed mutation command syntax: "
                                            f"{mut_res.reason}"
                                        ),
                                    )
                            continue

                        if mut_res.status == "NOT_MUTATION":
                            clean_ctrl = classify_clean_control_command(unwrapped_cmd)
                            if not clean_ctrl.is_allowed:
                                for idx_s, s in enumerate(self.statements):
                                    if s.file_path == unit.file_path and s.line_start in (
                                        s1.line_start,
                                        s2.line_start,
                                    ):
                                        self.statements[idx_s] = ClassifiedStatement(
                                            s.file_path,
                                            s.line_start,
                                            s.line_end,
                                            s.verb,
                                            s.raw_text,
                                            StatementClassification.UNSUPPORTED_RELEVANT,
                                            (
                                                "Unsupported non-mutation command: "
                                                f"{clean_ctrl.reason}"
                                            ),
                                        )
                                continue

                        commands_in_unit.append((s1, s2, idx, idx + 1, mut_res))

            # Operation sequence and non-atomic risk: generic operand-aware
            if len(commands_in_unit) >= 2:
                for c_idx in range(len(commands_in_unit) - 1):
                    m1, c1, m1_idx, c1_idx, mut1 = commands_in_unit[c_idx]
                    m2, c2, m2_idx, c2_idx, mut2 = commands_in_unit[c_idx + 1]

                    # Sequences require adjacent command dispatches
                    # (no intervening procedural statements or barriers)
                    if m2_idx != c1_idx + 1:
                        continue
                    has_intervening = any(
                        s.file_path == unit.file_path and c1.line_end < s.line_start < m2.line_start
                        for s in self.statements
                    )
                    has_seq_barrier = has_intervening or has_procedural_barrier_between(
                        unit_raw_lines, c1.line_end, m2.line_start
                    )
                    if has_seq_barrier:
                        continue

                    if not self._are_statements_in_same_linear_cf_segment(m1, c1, unit):
                        continue
                    if not self._are_statements_in_same_linear_cf_segment(c1, m2, unit):
                        continue
                    if not self._are_statements_in_same_linear_cf_segment(m2, c2, unit):
                        continue

                    if mut1.status == "MUTATION_PARSED" and mut2.status == "MUTATION_PARSED":
                        if mut1.operation == "DELETE" and mut2.operation == "RENAME":
                            self.supported_facts.append(
                                SupportedSystemFact(
                                    fact=OperationSequenceFact(
                                        program_id=caller,
                                        first_operation="DELETE",
                                        second_operation="RENAME",
                                    ),
                                    proposition_id=f"prop.op_seq.{caller.lower()}_del_ren",
                                    evidence_spans={
                                        "first_assignment_evidence": EvidenceSpan(
                                            unit.file_path, m1.line_start, m1.line_end
                                        ),
                                        "first_call_evidence": EvidenceSpan(
                                            unit.file_path, c1.line_start, c1.line_end
                                        ),
                                        "second_assignment_evidence": EvidenceSpan(
                                            unit.file_path, m2.line_start, m2.line_end
                                        ),
                                        "second_call_evidence": EvidenceSpan(
                                            unit.file_path, c2.line_start, c2.line_end
                                        ),
                                    },
                                )
                            )
                            # Risk: non-atomic file update derived ONLY when delete target matches
                            # rename target
                            if (
                                mut1.target_operand
                                and mut2.target_operand
                                and mut1.target_operand.upper() == mut2.target_operand.upper()
                            ):
                                canonical_resource = mut2.target_operand.upper()
                                caller_tag = caller.lower().replace("-", "_")
                                prop_id = f"prop.risk.{caller_tag}_non_atomic_update"
                                self.supported_facts.append(
                                    SupportedSystemFact(
                                        fact=BehavioralRiskFact(
                                            program_id=caller,
                                            risk_category="DATA_INTEGRITY",
                                            risk_basis_kind="NON_ATOMIC_EXTERNAL_MUTATION",
                                            impact_category="DATA_INTEGRITY",
                                            resource_name=canonical_resource,
                                        ),
                                        proposition_id=prop_id,
                                        evidence_spans={
                                            "operation_evidence": EvidenceSpan(
                                                unit.file_path, c1.line_start, c2.line_end
                                            ),
                                            "affected_resource_evidence": EvidenceSpan(
                                                unit.file_path, m2.line_start, m2.line_end
                                            ),
                                        },
                                    )
                                )
                        else:
                            # F-06: Same proven linear segment + two known mutations + pair outside
                            # frozen representable OperationSequence domain -> UNSUPPORTED_RELEVANT
                            for s_target in (m1, c1, m2, c2):
                                for idx_s, s in enumerate(self.statements):
                                    if (
                                        s.file_path == unit.file_path
                                        and s.line_start == s_target.line_start
                                    ):
                                        self.statements[idx_s] = ClassifiedStatement(
                                            s.file_path,
                                            s.line_start,
                                            s.line_end,
                                            s.verb,
                                            s.raw_text,
                                            StatementClassification.UNSUPPORTED_RELEVANT,
                                            (
                                                f"Unrepresentable mutation sequence "
                                                f"{mut1.operation}->{mut2.operation} "
                                                "in Contract 3.5.3 frozen wire contract"
                                            ),
                                        )

        # 7. Record-to-Record Data Transfer Relations
        for unit in self.compilation_units:
            caller = unit.program_id or "UNKNOWN"
            declared_records = {r.container_name for r in unit.record_declarations}
            for stmt in unit.statements:
                if isinstance(stmt, ASTMove):
                    if (
                        stmt.source_operand in declared_records
                        and stmt.target_operand in declared_records
                    ):
                        self.supported_facts.append(
                            SupportedSystemFact(
                                fact=DataTransferRelationFact(
                                    program_id=caller,
                                    source_entity=stmt.source_operand,
                                    target_entity=stmt.target_operand,
                                    transfer_verb="MOVE",
                                ),
                                proposition_id=f"prop.transfer.{caller.lower()}_{stmt.source_operand.lower()}_{stmt.target_operand.lower()}",
                                evidence_spans={
                                    "evidence": EvidenceSpan(
                                        unit.file_path, stmt.line_start, stmt.line_end
                                    )
                                },
                            )
                        )

        # Build mapping of record name -> owning FD scoped per compilation unit
        unit_record_to_fd: dict[str, dict[str, str]] = {}
        for unit in self.compilation_units:
            unit_map: dict[str, str] = {}
            for rec in unit.record_declarations:
                if rec.owning_fd:
                    unit_map[rec.container_name.upper()] = rec.owning_fd.upper()
            unit_record_to_fd[unit.file_path] = unit_map

        # Build FileStatusCertificate
        binding_records: dict[tuple[str, str], FileBindingStatusRecord] = {}
        for unit in self.compilation_units:
            p_id = unit.program_id or Path(unit.file_path).stem
            rec_to_fd = unit_record_to_fd.get(unit.file_path, {})
            for fb in unit.file_bindings:
                f_name = fb.internal_file_name
                ops_in_file = [
                    s
                    for s in unit.statements
                    if isinstance(s, ASTFileOp)
                    and (
                        s.internal_file_name.upper() == f_name.upper()
                        or rec_to_fd.get(s.internal_file_name.upper()) == f_name.upper()
                    )
                ]
                res_span = EvidenceSpan(unit.file_path, fb.line_start, fb.line_end)
                if ops_in_file:
                    op_span = EvidenceSpan(
                        unit.file_path, ops_in_file[0].line_start, ops_in_file[-1].line_end
                    )
                else:
                    op_span = None
                status_rec = FileBindingStatusRecord(
                    program_id=p_id,
                    internal_file_name=f_name,
                    has_file_status=fb.has_file_status,
                    resource_span=res_span,
                    operations_span=op_span,
                )
                binding_records[(p_id.upper(), f_name.upper())] = status_rec
        self._file_status_certificate = FileStatusCertificate(binding_records)

        # 8. File Operations & Resource Lifecycles & Missing Status Risks
        for unit in self.compilation_units:
            caller = unit.program_id or "UNKNOWN"
            rec_to_fd = unit_record_to_fd.get(unit.file_path, {})
            # Emit discrete FileOperationFacts
            for op_idx, stmt in enumerate(unit.statements):
                if isinstance(stmt, ASTFileOp):
                    target_res = stmt.internal_file_name
                    if stmt.verb == "WRITE" and target_res.upper() in rec_to_fd:
                        target_res = rec_to_fd[target_res.upper()]
                    if stmt.verb == "OPEN":
                        if stmt.access_mode in ("INPUT", "OUTPUT", "IO", "EXTEND"):
                            op_verb = f"OPEN_{stmt.access_mode}"
                        else:
                            op_verb = "OPEN"
                    else:
                        op_verb = stmt.verb
                    f_tag = target_res.lower().replace("-", "_")
                    prop_op_id = f"prop.file_op.{caller.lower()}_{f_tag}_{op_idx}"
                    self.supported_facts.append(
                        SupportedSystemFact(
                            fact=FileOperationFact(
                                program_id=caller,
                                internal_file_name=target_res,
                                operation_verb=op_verb,
                            ),
                            proposition_id=prop_op_id,
                            evidence_spans={
                                "evidence": EvidenceSpan(
                                    unit.file_path, stmt.line_start, stmt.line_end
                                )
                            },
                        )
                    )

            # Resource Lifecycles per file binding
            for fb in unit.file_bindings:
                f_name = fb.internal_file_name
                ops_in_file = [
                    s
                    for s in unit.statements
                    if isinstance(s, ASTFileOp)
                    and (
                        s.internal_file_name.upper() == f_name.upper()
                        or rec_to_fd.get(s.internal_file_name.upper()) == f_name.upper()
                    )
                ]
                if ops_in_file:
                    span_start = ops_in_file[0].line_start
                    span_end = ops_in_file[-1].line_end
                    open_modes = set()
                    for op in ops_in_file:
                        if op.verb == "OPEN":
                            m = op.access_mode or "INPUT"
                            if m in ("I-O", "IO"):
                                m = "IO"
                            open_modes.add(m)

                    if len(open_modes) > 1:
                        # More than one distinct OPEN access mode in lifecycle:
                        # Under Contract 3.5.3:
                        # - preserve truthful individual FileOperation facts
                        # - DO NOT emit a fabricated ResourceLifecycleFact
                        # - mark lifecycle semantic interpretation UNSUPPORTED_RELEVANT
                        # - final coverage blocks evaluation
                        self.statements.append(
                            ClassifiedStatement(
                                unit.file_path,
                                ops_in_file[0].line_start,
                                ops_in_file[-1].line_end,
                                "FILE_LIFECYCLE",
                                f"Mixed OPEN access modes for {f_name}: {sorted(open_modes)}",
                                StatementClassification.UNSUPPORTED_RELEVANT,
                                (
                                    "Resource lifecycle contains mixed OPEN access modes "
                                    "unsupported by Contract 3.5.3"
                                ),
                            )
                        )
                    else:
                        mode = list(open_modes)[0] if open_modes else "INPUT"
                        verbs_list = []
                        for op in ops_in_file:
                            if op.verb == "OPEN":
                                op_m = op.access_mode or "INPUT"
                                if op_m in ("I-O", "IO"):
                                    op_m = "IO"
                                verbs_list.append("OPEN_IO" if op_m == "IO" else f"OPEN_{op_m}")
                            else:
                                verbs_list.append(op.verb)
                        verbs = tuple(verbs_list)
                        span_start = ops_in_file[0].line_start
                        span_end = ops_in_file[-1].line_end

                        f_tag = f_name.lower().replace("-", "_")
                        prop_lc_id = f"prop.lifecycle.{caller.lower()}_{f_tag}"
                        self.supported_facts.append(
                            SupportedSystemFact(
                                fact=ResourceLifecycleFact(
                                    program_id=caller,
                                    resource_name=f_name,
                                    access_mode=mode,
                                    ordered_operations=verbs,
                                ),
                                proposition_id=prop_lc_id,
                                evidence_spans={
                                    "evidence": EvidenceSpan(unit.file_path, span_start, span_end)
                                },
                            )
                        )

                    # Missing File Status Risk
                    if not fb.has_file_status:
                        caller_tag = caller.lower().replace("-", "_")
                        f_tag = f_name.lower().replace("-", "_")
                        prop_risk_id = (
                            f"prop.risk.{caller_tag}_missing_status"
                            if f_name == "ACCOUNT-FILE"
                            else f"prop.risk.{caller_tag}_{f_tag}_missing_status"
                        )
                        self.supported_facts.append(
                            SupportedSystemFact(
                                fact=BehavioralRiskFact(
                                    program_id=caller,
                                    risk_category="IO_ERROR_HANDLING",
                                    risk_basis_kind="MISSING_ERROR_STATUS",
                                    impact_category="ERROR_VISIBILITY",
                                    resource_name=f_name,
                                ),
                                proposition_id=prop_risk_id,
                                evidence_spans={
                                    "operation_evidence": EvidenceSpan(
                                        unit.file_path, span_start, span_end
                                    ),
                                    "affected_resource_evidence": EvidenceSpan(
                                        unit.file_path, fb.line_start, fb.line_end
                                    ),
                                },
                            )
                        )

        # 9. Computation Dataflow
        for unit in self.compilation_units:
            caller = unit.program_id or "UNKNOWN"
            for stmt in unit.statements:
                if isinstance(stmt, ASTArithmetic):
                    self.supported_facts.append(
                        SupportedSystemFact(
                            fact=ComputationDataflowFact(
                                program_id=caller,
                                source_field=stmt.operand,
                                target_field=stmt.target,
                                operation_verb=stmt.verb,
                            ),
                            proposition_id=f"prop.dataflow.{caller.lower()}_{stmt.operand.lower()}_{stmt.target.lower()}",
                            evidence_spans={
                                "evidence": EvidenceSpan(
                                    unit.file_path, stmt.line_start, stmt.line_end
                                )
                            },
                        )
                    )

        # 10. Data State Comparison (.DAT vs Initializer)
        self._extract_data_state_comparison(programs_by_id)

    def _compare_records_generically(
        self, rec_a: ASTRecordDeclaration, rec_b: ASTRecordDeclaration
    ) -> str | None:
        """Total structural comparison between two record layouts."""
        data_a = [f for f in rec_a.fields if f.field_kind == "DATA_FIELD"]
        data_b = [f for f in rec_b.fields if f.field_kind == "DATA_FIELD"]
        if not data_a or not data_b:
            return None

        if len(data_a) != len(data_b):
            return "REPRESENTATION_MISMATCH"

        pics_a = [f.picture for f in data_a]
        pics_b = [f.picture for f in data_b]
        if pics_a != pics_b:
            return "REPRESENTATION_MISMATCH"

        usages_a = [f.usage for f in data_a]
        usages_b = [f.usage for f in data_b]
        if usages_a != usages_b:
            return "REPRESENTATION_MISMATCH"

        if rec_a.container_name == rec_b.container_name:
            return "IDENTICAL"
        return "EQUIVALENT"

    def _build_record_layout_relations(self) -> None:
        """Total binary record layout comparisons and canonical endpoint construction."""
        all_records: list[tuple[ASTCompilationUnit, ASTRecordDeclaration]] = []
        for unit in self.compilation_units:
            for rec in unit.record_declarations:
                if not rec.fields:
                    continue
                has_unsupported_stmt = any(
                    s.file_path == unit.file_path
                    and s.classification == StatementClassification.UNSUPPORTED_RELEVANT
                    and rec.line_start <= s.line_start <= rec.line_end
                    for s in self.statements
                )
                if rec.is_unsupported or has_unsupported_stmt:
                    continue
                all_records.append((unit, rec))

        seen_pairs: set[tuple[str, str]] = set()
        for idx_a in range(len(all_records)):
            for idx_b in range(idx_a + 1, len(all_records)):
                unit_a, rec_a = all_records[idx_a]
                unit_b, rec_b = all_records[idx_b]

                if (
                    rec_a.container_name == rec_b.container_name
                    and unit_a.file_path == unit_b.file_path
                ):
                    continue

                # Compare layout equivalence generically
                rel = self._compare_records_generically(rec_a, rec_b)
                if rel:
                    name_a = (
                        f"{unit_a.program_id or Path(unit_a.file_path).stem}:{rec_a.container_name}"
                    )
                    name_b = (
                        f"{unit_b.program_id or Path(unit_b.file_path).stem}:{rec_b.container_name}"
                    )
                    span_a = EvidenceSpan(unit_a.file_path, rec_a.line_start, rec_a.line_end)
                    span_b = EvidenceSpan(unit_b.file_path, rec_b.line_start, rec_b.line_end)

                    # Canonicalize complete endpoints: (layout_name, evidence_span)
                    if (name_a, span_a.file_path, span_a.line_start, span_a.line_end) > (
                        name_b,
                        span_b.file_path,
                        span_b.line_start,
                        span_b.line_end,
                    ):
                        name_a, name_b = name_b, name_a
                        span_a, span_b = span_b, span_a

                    pair_key = (name_a, name_b)
                    if pair_key not in seen_pairs:
                        seen_pairs.add(pair_key)
                        tag_a = rec_a.container_name.lower().replace("-", "_")
                        tag_b = rec_b.container_name.lower().replace("-", "_")
                        prop_rel_id = f"prop.relation.{tag_a}_{tag_b}_{idx_a}_{idx_b}"
                        self.supported_facts.append(
                            SupportedSystemFact(
                                fact=RecordLayoutRelationFact(
                                    layout_a_name=name_a,
                                    layout_b_name=name_b,
                                    relation_type=rel,
                                ),
                                proposition_id=prop_rel_id,
                                evidence_spans={
                                    "evidence_a": span_a,
                                    "evidence_b": span_b,
                                },
                            )
                        )

    def _extract_data_state_comparison(self, programs_by_id: dict[str, ASTCompilationUnit]) -> None:
        """Extract discrepancies between DAT files and initialization code generically."""
        dat_file = next((f for p, f in self.bundle.files.items() if f.file_type == "DATA"), None)
        if not dat_file:
            return

        dat_lines = dat_file.get_lines()
        dat_stem = Path(dat_file.relative_path).stem.upper()

        for prog_id, unit in programs_by_id.items():
            # Find file binding targeting this DAT dataset
            matching_fb = next(
                (
                    fb
                    for fb in unit.file_bindings
                    if Path(fb.external_file_name).stem.upper() == dat_stem
                ),
                None,
            )
            if not matching_fb:
                continue

            # Verify that program performs WRITE operations
            if not any(isinstance(s, ASTFileOp) and s.verb == "WRITE" for s in unit.statements):
                continue

            # Identify record layout declared for this program
            if not unit.record_declarations:
                continue
            rec_decl = unit.record_declarations[0]
            has_unsupported_stmt = any(
                s.file_path == unit.file_path
                and s.classification == StatementClassification.UNSUPPORTED_RELEVANT
                and rec_decl.line_start <= s.line_start <= rec_decl.line_end
                for s in self.statements
            )
            if not rec_decl.fields or rec_decl.is_unsupported or has_unsupported_stmt:
                continue

            # Dynamically derive field character offsets and decimal places from layout
            field_offsets: dict[str, tuple[int, int, int]] = {}
            curr_offset = 0
            for f in rec_decl.fields:
                if f.field_kind != "DATA_FIELD":
                    continue
                f_width, f_decs = parse_cobol_picture(f.picture)
                field_offsets[f.name.upper()] = (curr_offset, curr_offset + f_width, f_decs)
                curr_offset += f_width

            if not field_offsets:
                continue

            key_field = next((f for f in rec_decl.fields if f.field_kind == "DATA_FIELD"), None)
            if not key_field:
                continue
            key_field_name = key_field.name.upper()
            key_start, key_end, _ = field_offsets[key_field_name]

            # Track procedural field moves leading up to each WRITE
            staged_moves: dict[str, tuple[str, ASTMove]] = {}
            for stmt in unit.statements:
                if isinstance(stmt, ASTMove):
                    t_name = stmt.target_operand.upper()
                    if t_name in field_offsets:
                        if stmt.is_literal_source:
                            try:
                                if "\\" in stmt.source_operand:
                                    raise ValueError(
                                        "Unsupported quoting in initializer move literal"
                                    )
                                source_val = exact_syntactic_unquote(stmt.source_operand)
                                if stmt.source_operand[0] in source_val:
                                    raise ValueError(
                                        "Unconsumed delimiter quote in initializer move literal"
                                    )
                            except ValueError:
                                for idx_s, s in enumerate(self.statements):
                                    if (
                                        s.file_path == unit.file_path
                                        and s.line_start == stmt.line_start
                                    ):
                                        self.statements[idx_s] = ClassifiedStatement(
                                            s.file_path,
                                            s.line_start,
                                            s.line_end,
                                            s.verb,
                                            s.raw_text,
                                            StatementClassification.UNSUPPORTED_RELEVANT,
                                            "Unsupported quoting in initializer move literal",
                                        )
                                continue
                        else:
                            source_val = stmt.source_operand
                        staged_moves[t_name] = (source_val, stmt)
                elif isinstance(stmt, ASTFileOp) and stmt.verb == "WRITE":
                    if key_field_name in staged_moves:
                        staged_id, _ = staged_moves[key_field_name]
                        # Locate corresponding line in DAT file by key field value
                        for line_idx, d_line in enumerate(dat_lines):
                            if not d_line.strip() or len(d_line) < key_end:
                                continue
                            dat_id = d_line[key_start:key_end].strip()
                            if dat_id == staged_id:
                                # Compare all other staged fields against DAT record
                                for f_name, (f_start, f_end, f_decs) in field_offsets.items():
                                    if f_name == key_field_name or f_name not in staged_moves:
                                        continue
                                    staged_val, move_stmt = staged_moves[f_name]
                                    if len(d_line) < f_end:
                                        continue
                                    dat_raw = d_line[f_start:f_end].strip()
                                    if f_decs > 0 and dat_raw.isdigit():
                                        int_p = dat_raw[:-f_decs] if len(dat_raw) > f_decs else "0"
                                        dec_p = dat_raw[-f_decs:]
                                        dat_fmt = f"{int(int_p)}.{dec_p}"
                                        try:
                                            if float(staged_val) != float(dat_fmt):
                                                self.supported_facts.append(
                                                    SupportedSystemFact(
                                                        fact=DataStateComparisonFact(
                                                            entity_id=staged_id,
                                                            dat_record_value=dat_fmt,
                                                            initializer_code_value=staged_val,
                                                            causal_provenance="UNKNOWN",
                                                        ),
                                                        proposition_id=f"prop.state_cmp.{staged_id.lower()}",
                                                        evidence_spans={
                                                            "dat_evidence": EvidenceSpan(
                                                                dat_file.relative_path,
                                                                line_idx + 1,
                                                                line_idx + 1,
                                                            ),
                                                            "initializer_evidence": EvidenceSpan(
                                                                unit.file_path,
                                                                move_stmt.line_start,
                                                                move_stmt.line_end,
                                                            ),
                                                        },
                                                    )
                                                )
                                        except ValueError:
                                            pass
                    staged_moves.clear()
