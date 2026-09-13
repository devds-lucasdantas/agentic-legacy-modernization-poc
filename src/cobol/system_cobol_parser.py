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
class ASTArithmetic(ASTStatement):
    operand: str
    target: str


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
# Generic Quote-Aware Tokenizer
# ---------------------------------------------------------------------------


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
    WINDOWS_CMD = "WINDOWS_CMD"
    POSIX_SHELL = "POSIX_SHELL"
    BARE_OR_OTHER = "BARE_OR_OTHER"


def classify_command_dialect(cmd_text: str) -> tuple[CommandDialect, str]:
    """Classify the command dialect and return (dialect, unwrapped_command)."""
    clean = cmd_text.strip()
    m_win = re.match(r"^cmd(?:\.exe)?\s+/c\s+", clean, flags=re.IGNORECASE)
    if m_win:
        return CommandDialect.WINDOWS_CMD, clean[m_win.end() :].strip()

    m_posix = re.match(
        r"^(?:/(?:usr/)?bin/(?:ba)?sh|(?:ba)?sh)\s+-c\s+",
        clean,
        flags=re.IGNORECASE,
    )
    if m_posix:
        return CommandDialect.POSIX_SHELL, clean[m_posix.end() :].strip()

    return CommandDialect.BARE_OR_OTHER, clean


SHELL_METACHARACTERS: frozenset[str] = frozenset(
    {">", "<", "|", "&", "^", "%", "!", "*", "?", "(", ")"}
)


def tokenize_windows_mutation_operands(text: str) -> tuple[bool, list[str], str | None]:
    """Tokenize Windows mutation command operands.

    Supports unquoted operands and double-quote grouped operands ("...").
    Does NOT treat single quotes as Windows grouping quotes.
    Rejects shell metacharacters and wildcards (><|&^%!*?()).
    Rejects lossy whitespace (consecutive spaces, boundary spaces).
    Returns (True, operands, None) on success.
    Returns (False, [], reason) on malformed quoting, invalid syntax, or metacharacters.
    """
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
                # Unclosed double quote
                return False, [], "Unclosed double quote in mutation operand"
            # Closing double quote at i
            i += 1
            # Check trailing character after closing quote
            if i < n and not text[i].isspace():
                # Attached unseparated characters, e.g. "file"xyz
                return False, [], "Attached character after closing quote in mutation operand"
            raw = text[start:i]
            semantic = raw[1:-1]
            if not semantic:
                # Empty filename operand
                return False, [], "Empty filename operand in mutation command"
            if re.search(r"\s{2,}", semantic):
                return False, [], "Lossy whitespace in mutation operand: consecutive whitespace"
            if semantic != semantic.strip():
                return False, [], "Lossy whitespace in mutation operand: boundary whitespace"
            operands.append(semantic)
        elif char == "'":
            # Single quote in Windows cmd is not grouping syntax;
            # Reject as unsupported mutation operand syntax
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
                    # Stray quote inside word
                    return False, [], "Stray quote inside unquoted mutation operand"
                i += 1
            raw = text[start:i]
            operands.append(raw)
    return True, operands, None


def classify_mutation_command(cmd_text: str) -> MutationCommandResult:
    """Classify a shell command for mutation sequence and risk analysis.

    Returns:
    - NOT_MUTATION: command does not enter the mutation verb family (e.g. echo, dir).
    - MUTATION_PARSED: command successfully tokenized into deterministic operation and operands.
    - MUTATION_UNSUPPORTED: command belongs to mutation family but has malformed/unsupported syntax.
    """
    dialect, unwrapped = classify_command_dialect(cmd_text)
    if dialect == CommandDialect.POSIX_SHELL:
        inner = unwrapped
        if (inner.startswith("'") and inner.endswith("'")) or (
            inner.startswith('"') and inner.endswith('"')
        ):
            inner = inner[1:-1].strip()
        words = inner.split()
    else:
        words = unwrapped.split()
    if not words:
        return MutationCommandResult(status="NOT_MUTATION")

    verb = words[0].lower()
    mutation_verbs = {
        "del": "DELETE",
        "delete": "DELETE",
        "erase": "DELETE",
        "rm": "DELETE",
        "ren": "RENAME",
        "rename": "RENAME",
        "mv": "RENAME",
        "move": "RENAME",
        "copy": "COPY",
        "cp": "COPY",
    }
    if verb not in mutation_verbs:
        return MutationCommandResult(status="NOT_MUTATION")

    op_type = mutation_verbs[verb]

    # B-04: POSIX -c shell wrappers are outside Contract 3.5.3 mutation interpretation
    if dialect == CommandDialect.POSIX_SHELL:
        return MutationCommandResult(
            status="MUTATION_UNSUPPORTED",
            operation=op_type,
            reason=(
                "POSIX shell mutation wrappers are unsupported for deterministic "
                "resource mutation analysis"
            ),
        )

    # B-04 / B-03: Bare mutation commands without supported shell wrapper
    if dialect == CommandDialect.BARE_OR_OTHER:
        return MutationCommandResult(
            status="MUTATION_UNSUPPORTED",
            operation=op_type,
            reason=(
                "Bare mutation commands without explicit supported Windows shell "
                "wrapper are unsupported"
            ),
        )

    rem_text = unwrapped[len(words[0]) :].strip()

    valid, operands, err_reason = tokenize_windows_mutation_operands(rem_text)
    if not valid:
        return MutationCommandResult(
            status="MUTATION_UNSUPPORTED",
            operation=op_type,
            reason=err_reason or f"Malformed or unsupported operand syntax for {op_type}",
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
    elif op_type == "COPY":
        if len(operands) != 2:
            return MutationCommandResult(
                status="MUTATION_UNSUPPORTED",
                operation=op_type,
                reason=f"COPY expects exactly 2 operands (source, target), got {len(operands)}",
            )
        return MutationCommandResult(
            status="MUTATION_PARSED",
            operation="COPY",
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
                tokens = [t for t in tokenize_cobol_line(raw_line) if t != "."]
                if not tokens:
                    i += 1
                    continue
                first = tokens[0].upper()
                line_is_terminated = False
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
                prog_name = tokens[1].rstrip(".") if len(tokens) > 1 else ""
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
                internal_name = tokens[1] if len(tokens) > 1 else ""
                start_l = line_num
                clause_text = raw_line
                assign_target = ""
                org_val = "SEQUENTIAL"
                has_status = False

                # Slurp continuation lines until period
                while not clause_text.rstrip().endswith(".") and (i + 1) < n:
                    i += 1
                    clause_text += " " + lines[i].strip()

                end_l = i + 1

                if not is_canonical_cobol_identifier(internal_name):
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            start_l,
                            end_l,
                            "SELECT",
                            clause_text,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            f"Invalid internal file identifier in SELECT: {internal_name}",
                        )
                    )
                    i += 1
                    continue

                # Check for unsupported file organizations: INDEXED, RELATIVE
                if re.search(
                    r"\bORGANIZATION\s+(?:IS\s+)?(?:INDEXED|RELATIVE)\b", clause_text, re.I
                ):
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            start_l,
                            end_l,
                            "SELECT",
                            clause_text,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            "Unsupported file organization (INDEXED/RELATIVE)",
                        )
                    )
                    i += 1
                    continue

                # Robust quote-aware parsing of ASSIGN target with fail-closed semantics
                # on unsupported quoting
                m_kw = re.search(r"\bASSIGN(?:\s+TO)?\b", clause_text, re.I)
                assign_target = ""
                assign_valid = False
                if m_kw:
                    rem = clause_text[m_kw.end() :].lstrip()
                    if rem:
                        if rem[0] in ("'", '"'):
                            q_char = rem[0]
                            # Check for unsupported doubled-quote escapes or backslashes
                            if (q_char * 2) in rem or "\\" in rem:
                                assign_valid = False
                            else:
                                close_idx = rem.find(q_char, 1)
                                if close_idx == -1:
                                    # Unclosed quote
                                    assign_valid = False
                                else:
                                    raw_target = rem[: close_idx + 1]
                                    char_after = (
                                        rem[close_idx + 1] if close_idx + 1 < len(rem) else ""
                                    )
                                    after_target = rem[close_idx + 1 :].strip()
                                    if char_after and not (
                                        char_after.isspace() or char_after == "."
                                    ):
                                        # e.g. 'accounts.dat'xyz
                                        assign_valid = False
                                    elif "'" in after_target or '"' in after_target:
                                        # Stray unconsumed quotes in remaining clause
                                        assign_valid = False
                                    else:
                                        try:
                                            unquoted = exact_syntactic_unquote(raw_target)
                                            if q_char in unquoted:
                                                assign_valid = False
                                            elif not unquoted:
                                                # Empty file name is domain-invalid
                                                assign_valid = False
                                            else:
                                                assign_target = unquoted
                                                assign_valid = True
                                        except ValueError:
                                            assign_valid = False
                        else:
                            # Unquoted identifier
                            toks = rem.split()
                            first_tok = toks[0].rstrip(".")
                            if "'" in first_tok or '"' in first_tok or not first_tok:
                                assign_valid = False
                            else:
                                assign_target = first_tok
                                assign_valid = True

                if not assign_valid or not assign_target:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            start_l,
                            end_l,
                            "SELECT",
                            clause_text,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            f"Unsupported or malformed file assignment syntax in SELECT: "
                            f"{clause_text}",
                        )
                    )
                    i += 1
                    continue

                if re.search(r"LINE\s+SEQUENTIAL", clause_text, re.I):
                    org_val = "LINE_SEQUENTIAL"

                if re.search(r"FILE\s+STATUS", clause_text, re.I):
                    has_status = True

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
                        "File binding clause",
                    )
                )
                i += 1
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
                rec_name = tokens[1].rstrip(".") if len(tokens) > 1 else ""
                if not is_canonical_cobol_identifier(rec_name):
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            "RECORD_01",
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            f"Invalid 01 record identifier: {rec_name}",
                        )
                    )
                    i += 1
                    continue
                current_record = ASTRecordDeclaration(
                    container_name=rec_name,
                    line_start=line_num,
                    line_end=line_num,
                    owning_fd=current_fd,
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
                    i += 1
                    continue
                pic_val = None
                usage_val = "DISPLAY"
                for pic_kw in ("PIC", "PICTURE"):
                    if pic_kw in [t.upper() for t in tokens]:
                        idx = [t.upper() for t in tokens].index(pic_kw)
                        if idx + 1 < len(tokens):
                            pic_val = canonicalize_picture(tokens[idx + 1])
                        break
                if "COMP-3" in [t.upper() for t in tokens]:
                    usage_val = "COMP-3"
                elif "COMP" in [t.upper() for t in tokens] or "BINARY" in [
                    t.upper() for t in tokens
                ]:
                    usage_val = "BINARY"

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
                    # Check if next line is an obvious structural boundary
                    if is_cobol_structural_boundary(next_line):
                        break
                    # Slurp continuation line
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
                    no_dot_tokens = [t for t in c_tokens if t != "."]
                    if len(no_dot_tokens) > 1 and no_dot_tokens[0] == "88":
                        cond_name = no_dot_tokens[1]
                        if not is_canonical_cobol_identifier(cond_name):
                            is_supported = False
                    else:
                        is_supported = False

                    val_tokens_upper = [t.upper() for t in no_dot_tokens]
                    start_idx = -1
                    for v_key in ("VALUE", "VALUES"):
                        if v_key in val_tokens_upper:
                            start_idx = val_tokens_upper.index(v_key) + 1
                            if start_idx < len(no_dot_tokens) and val_tokens_upper[start_idx] in (
                                "IS",
                                "ARE",
                            ):
                                start_idx += 1
                            break

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
                            "Unsupported condition level 88 syntax",
                        )
                    )
                i = curr_i + 1
                continue

            # PROCEDURE DIVISION / PARAGRAPHS
            if first == "PROCEDURE" and len(tokens) > 1 and tokens[1].upper().startswith("DIV"):
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
                    )
                )
                i += 1
                continue

            if len(tokens) == 2 and tokens[1].upper() == "SECTION":
                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        line_num,
                        line_num,
                        "SECTION_HEADER",
                        raw_line,
                        StatementClassification.RECOGNIZED_BUT_UNSCORED,
                        "Section header",
                    )
                )
                i += 1
                continue

            if stripped.endswith(".") and len(tokens) == 1:
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
                    )
                )
                i += 1
                continue

            if first in ("COMPUTE", "MULTIPLY", "DIVIDE"):
                arith_valid = True
                op = ""
                tgt = ""
                if any(is_unquoted_procedural_starter(t) for t in tokens[1:]):
                    arith_valid = False
                elif first == "COMPUTE":
                    if len(tokens) == 4 and tokens[2] == "=":
                        tgt = tokens[1]
                        op = tokens[3]
                        if not is_canonical_cobol_identifier(tgt) or not is_computation_operand(op):
                            arith_valid = False
                    else:
                        arith_valid = False
                elif first == "MULTIPLY":
                    if len(tokens) == 4 and tokens[2].upper() == "BY":
                        op = tokens[1]
                        tgt = tokens[3]
                        if not is_canonical_cobol_identifier(tgt) or not is_computation_operand(op):
                            arith_valid = False
                    else:
                        arith_valid = False
                elif first == "DIVIDE":
                    if len(tokens) == 4 and tokens[2].upper() == "INTO":
                        op = tokens[1]
                        tgt = tokens[3]
                        if not is_canonical_cobol_identifier(tgt) or not is_computation_operand(op):
                            arith_valid = False
                    else:
                        arith_valid = False

                if not arith_valid:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            first,
                            raw_line,
                            StatementClassification.UNSUPPORTED_RELEVANT,
                            f"Unsupported or compound {first} statement",
                        )
                    )
                    i += 1
                    continue

                arith_node = ASTArithmetic(
                    verb=first,
                    operand=op,
                    target=tgt,
                    line_start=line_num,
                    line_end=line_num,
                )
                unit.statements.append(arith_node)
                self.statements.append(
                    ClassifiedStatement(
                        target_file.relative_path,
                        line_num,
                        line_num,
                        first,
                        raw_line,
                        StatementClassification.PARSED_AND_SCORED,
                        f"Arithmetic {first} statement",
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
                    )
                )
                i += 1
                continue

            if first == "PERFORM":
                perf_valid = False
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
                        )
                    )
                else:
                    self.statements.append(
                        ClassifiedStatement(
                            target_file.relative_path,
                            line_num,
                            line_num,
                            "PERFORM",
                            raw_line,
                            StatementClassification.PARSED_AND_SCORED,
                            "Procedural loop PERFORM",
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
                )
            )
            i += 1

        return unit

    def _prove_callee_continuation(self, callee_unit: ASTCompilationUnit) -> ASTTermination | None:
        """Structural proof of unavoidable callee continuation outcome.

        Establishes that:
        - no UNSUPPORTED_RELEVANT statements exist in the callee;
        - no GO/GOTO statements exist;
        - all ASTTermination nodes agree on their termination verb;
        - control block nesting is balanced and depth is 0 at termination;
        - the proving termination occurs at top-level and is the final
          reachable executable procedural outcome.
        """
        callee_stmts = [s for s in self.statements if s.file_path == callee_unit.file_path]
        if any(
            s.classification == StatementClassification.UNSUPPORTED_RELEVANT for s in callee_stmts
        ):
            return None

        if any(s.verb in ("GO", "GOTO") for s in callee_stmts):
            return None

        term_stmts = [s for s in callee_unit.statements if isinstance(s, ASTTermination)]
        if not term_stmts:
            return None

        first_verb = term_stmts[0].verb
        if any(t.verb != first_verb for t in term_stmts):
            return None

        # Track structural control depth
        depth = 0
        proving_term: ASTTermination | None = None
        for s in callee_stmts:
            if s.verb in ("IF", "EVALUATE"):
                depth += 1
            elif s.verb == "PERFORM" and "UNTIL" in s.raw_text.upper():
                depth += 1
            elif s.verb in ("END-IF", "END-EVALUATE", "END-PERFORM"):
                depth -= 1
                if depth < 0:
                    return None
            elif s.verb in ("STOP_RUN", "GOBACK", "EXIT_PROGRAM"):
                if depth == 0:
                    ast_t = next(
                        (t for t in term_stmts if t.line_start == s.line_start),
                        None,
                    )
                    if ast_t:
                        proving_term = ast_t

        if depth != 0 or proving_term is None:
            return None

        # Must be the final reachable executable outcome
        exec_classes = (ASTCall, ASTMove, ASTFileOp, ASTArithmetic)
        try:
            proving_idx = callee_unit.statements.index(proving_term)
            remaining_stmts = callee_unit.statements[proving_idx + 1 :]
            if any(isinstance(r, exec_classes) for r in remaining_stmts):
                return None
        except ValueError:
            return None

        procedural_verbs = {
            "DISPLAY",
            "ACCEPT",
            "PERFORM",
            "IF",
            "EVALUATE",
            "WHEN",
            "MOVE",
            "CALL",
            "OPEN",
            "READ",
            "WRITE",
            "CLOSE",
            "ADD",
            "SUBTRACT",
            "COMPUTE",
            "MULTIPLY",
            "DIVIDE",
            "GO",
            "GOTO",
        }
        after_stmts = [
            s
            for s in callee_stmts
            if s.line_start > proving_term.line_end and s.verb in procedural_verbs
        ]
        if after_stmts:
            return None

        return proving_term

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
                        callee_term = self._prove_callee_continuation(callee_unit)
                        if callee_term:
                            constraint_effect = (
                                "PROCESS_TERMINATION_ON_CALL"
                                if callee_term.verb == "STOP_RUN"
                                else "RETURN_TO_CALLER"
                            )
                            self.supported_facts.append(
                                SupportedSystemFact(
                                    fact=CallerContinuationConstraintFact(
                                        caller_program=caller,
                                        callee_program=target,
                                        constraint_type=constraint_effect,
                                    ),
                                    proposition_id=f"prop.continuation.{caller.lower()}_{target.lower()}",
                                    evidence_spans={
                                        "call_evidence": EvidenceSpan(
                                            unit.file_path, stmt.line_start, stmt.line_end
                                        ),
                                        "callee_termination_evidence": EvidenceSpan(
                                            callee_unit.file_path,
                                            callee_term.line_start,
                                            callee_term.line_end,
                                        ),
                                    },
                                )
                            )
                        else:
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
                                        "Unproven callee continuation outcome",
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

                        # Platform dependency
                        dialect, _ = classify_command_dialect(cmd_clean)
                        if dialect == CommandDialect.WINDOWS_CMD:
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
                        elif dialect == CommandDialect.POSIX_SHELL:
                            self.supported_facts.append(
                                SupportedSystemFact(
                                    fact=PlatformDependencyFact(
                                        program_id=caller,
                                        platform_family="POSIX",
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
                if rec.fields:
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
            if not rec_decl.fields:
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
