"""Canonical Atomic Fact representations for COBOL analysis (Version 2.1.0).

Separates:
1. Semantic Normalization: Category-aware normalization for identifiers, keywords,
   PIC clauses, conditions, and display/string literals.
2. AtomicFact: Pure semantic identity (normalized, immutable, hashable).
3. SupportedFactOccurrence: Ground-truth fact occurrence in source code with exact
   physical statement span [line_start, line_end] and required operands.
4. PredictedFact: Model assertion binding an AtomicFact to cited SourceEvidence.
5. Contradiction Semantics: Distinguishes multi-valued relations (CALL, DISPLAY, COPY)
   from single-valued properties (PROGRAM, MENU_OPTION branch, DATA_FIELD attributes).
"""

import re
from dataclasses import dataclass
from typing import Any


def normalize_identifier(text: str) -> str:
    """Normalize a COBOL identifier: uppercase, strip, collapse whitespace."""
    return " ".join(text.strip().split()).upper()


def normalize_keyword(text: str) -> str:
    """Normalize a COBOL keyword: uppercase, strip, collapse whitespace."""
    return " ".join(text.strip().split()).upper()


def normalize_string_literal(text: str) -> str:
    """Normalize a COBOL string literal: preserve case and internal spacing.

    Strips surrounding quotes (' or \") if present, but preserves exact casing,
    internal whitespace, and punctuation inside the literal.
    """
    s = text.strip()
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        s = s[1:-1]
    return s


def normalize_pic(raw_pic: str | None) -> str:
    """Canonicalize a COBOL PICTURE clause string.

    Examples:
    - None or '' or 'NONE' -> 'NONE'
    - 'X' -> 'X(1)'
    - 'X(1)' -> 'X(1)'
    - '9' -> '9(1)'
    - '999' -> '9(3)'
    - 'XXXXX' -> 'X(5)'
    - '9(12)' -> '9(12)'
    - 'PIC X' -> 'X(1)'
    """
    if not raw_pic or raw_pic.strip().upper() in ("NONE", ""):
        return "NONE"

    s = raw_pic.strip().upper()
    if s.startswith("PIC "):
        s = s[4:].strip()
    elif s.startswith("PICTURE "):
        s = s[8:].strip()
    s = s.rstrip(".")

    # Remove internal spaces
    s = "".join(s.split())

    # Check for repeated single characters: e.g. 999 -> 9(3), XXX -> X(3)
    m_repeat = re.fullmatch(r"([A-Z9])\1*", s)
    if m_repeat and len(s) > 1:
        char = m_repeat.group(1)
        count = len(s)
        return f"{char}({count})"

    # Check for single char without count: X -> X(1), 9 -> 9(1), A -> A(1)
    if re.fullmatch(r"[A-Z9]", s):
        return f"{s}(1)"

    return s


def normalize_condition(cond: str) -> str:
    """Normalize a COBOL condition expression without erasing operand values.

    Normalizes keyword/identifier casing and quote styles around string literals,
    while strictly preserving literal values and comparison operators.
    E.g. \"ws-choice = '4'\" -> \"WS-CHOICE = '4'\"
         'ws-choice = \"4\"' -> \"WS-CHOICE = '4'\"
    """
    s = cond.strip()
    # Match pattern: <identifier> <op> <literal or identifier>
    m = re.match(r"^([A-Za-z0-9-]+)\s*(=|NOT\s*=|<>|>|<|>=|<=)\s*(.+)$", s, re.IGNORECASE)
    if m:
        lhs = m.group(1).upper()
        op = " ".join(m.group(2).upper().split())
        rhs = m.group(3).strip()
        # If rhs is quoted literal, canonicalize to single quotes with preserved content
        if (rhs.startswith("'") and rhs.endswith("'")) or (
            rhs.startswith('"') and rhs.endswith('"')
        ):
            lit_val = rhs[1:-1]
            return f"{lhs} {op} '{lit_val}'"
        return f"{lhs} {op} {rhs.upper()}"

    return " ".join(s.split()).upper()


def normalize_token(text: str) -> str:
    """Universal token normalizer for generic tokens (fallback)."""
    return " ".join(text.strip().split()).upper()


@dataclass(frozen=True)
class AtomicFact:
    """Immutable, hashable, canonical representation of a COBOL structural fact."""

    kind: str
    subject: str
    predicate: str
    object: str
    attributes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        norm_kind = normalize_keyword(self.kind)
        norm_predicate = normalize_keyword(self.predicate)

        # Category-aware normalization for subject and object
        if norm_kind == "PROGRAM":
            norm_subject = normalize_identifier(self.subject)
            norm_object = normalize_keyword(self.object)
        elif norm_kind == "DATA_FIELD":
            norm_subject = normalize_identifier(self.subject)
            norm_object = normalize_keyword(self.object)
        elif norm_kind == "CALL":
            norm_subject = normalize_identifier(self.subject)
            norm_object = normalize_identifier(self.object)
        elif norm_kind == "MENU_OPTION":
            # Subject is menu option key (e.g. '1', '4', 'OTHER')
            norm_subject = self.subject.strip().replace("'", "").replace('"', "").upper()
            if norm_predicate == "CALLS":
                norm_object = normalize_identifier(self.object)
            elif norm_predicate == "DISPLAYS":
                norm_object = normalize_string_literal(self.object)
            else:
                norm_object = normalize_token(self.object)
        elif norm_kind == "CONTROL_FLOW":
            norm_subject = normalize_keyword(self.subject)
            if norm_subject == "PERFORM_UNTIL":
                norm_object = normalize_condition(self.object)
            elif norm_subject == "EVALUATE":
                norm_object = normalize_identifier(self.object)
            elif norm_subject == "STOP_RUN":
                norm_object = normalize_keyword(self.object)
            else:
                norm_object = normalize_token(self.object)
        elif norm_kind == "IO_OPERATION":
            norm_subject = normalize_keyword(self.subject)
            if norm_subject == "ACCEPT":
                norm_object = normalize_identifier(self.object)
            elif norm_subject == "DISPLAY":
                norm_object = normalize_string_literal(self.object)
            else:
                norm_object = normalize_token(self.object)
        elif norm_kind == "DEPENDENCY_SCAN":
            norm_subject = normalize_keyword(self.subject)
            norm_object = normalize_token(self.object)
        else:
            norm_subject = normalize_token(self.subject)
            norm_object = normalize_token(self.object)

        # Attribute normalization
        norm_attrs_list: list[tuple[str, str]] = []
        for k, v in self.attributes:
            k_norm = normalize_keyword(k)
            if k_norm == "PICTURE":
                v_norm = normalize_pic(v)
            elif k_norm in ("SECTION", "LEVEL"):
                v_norm = normalize_keyword(v)
            else:
                v_norm = normalize_token(v)
            norm_attrs_list.append((k_norm, v_norm))

        object.__setattr__(self, "kind", norm_kind)
        object.__setattr__(self, "subject", norm_subject)
        object.__setattr__(self, "predicate", norm_predicate)
        object.__setattr__(self, "object", norm_object)
        object.__setattr__(self, "attributes", tuple(sorted(norm_attrs_list)))

    def to_dict(self) -> dict[str, Any]:
        """Convert atomic fact to dictionary."""
        return {
            "kind": self.kind,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "attributes": dict(self.attributes),
        }

    @property
    def canonical_id(self) -> str:
        """Produce a canonical readable identifier."""
        attr_str = ",".join(f"{k}={v}" for k, v in self.attributes)
        if attr_str:
            return f"{self.kind}:{self.subject}:{self.predicate}:{self.object}[{attr_str}]"
        return f"{self.kind}:{self.subject}:{self.predicate}:{self.object}"

    @property
    def contradiction_group_key(self) -> tuple[str, ...] | None:
        """Return the group key for contradiction detection if this fact is single-valued.

        Returns None for multi-valued relations (CALL, DISPLAY, positive COPY)
        where multiple distinct facts legitimately coexist.

        Returns a non-None grouping tuple only for single-valued semantic properties:
        - PROGRAM identity: exactly one PROGRAM-ID per module.
        - MENU_OPTION: for a specific option_key, only one branch action can exist.
        - DATA_FIELD: for a given variable name and section, declarations must not conflict.
        - DEPENDENCY_SCAN: cannot assert both dependency_count=0 and positive dependency.
        - CONTROL_FLOW PERFORM_UNTIL / EVALUATE: unique loop/eval construct for this single module.
        """
        if self.kind == "PROGRAM":
            return ("PROGRAM", "PROGRAM-ID")
        if self.kind == "MENU_OPTION":
            # For a given option key (e.g. '1'), there is only one menu action
            return ("MENU_OPTION", self.subject)
        if self.kind == "DATA_FIELD":
            # For a given variable name, cannot have conflicting level/pic/section
            sec = dict(self.attributes).get("SECTION", "")
            return ("DATA_FIELD", self.subject, sec)
        if self.kind == "DEPENDENCY_SCAN":
            # Dependency scan for a given dependency type
            return ("DEPENDENCY_SCAN", self.subject)

        # Multi-valued relations: multiple CALLs, multiple DISPLAYs, multiple COPYs
        # are completely legitimate and must NEVER trigger contradiction grouping.
        return None


@dataclass(frozen=True)
class SupportedFactOccurrence:
    """A specific occurrence of a ground-truth fact in source code."""

    fact: AtomicFact
    occurrence_id: str
    line_start: int
    line_end: int
    required_evidence_fragments: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "occurrence_id", self.occurrence_id.strip())


@dataclass(frozen=True)
class PredictedFact:
    """Model assertion predicting a fact backed by a cited SourceEvidence."""

    fact: AtomicFact
    line_start: int
    line_end: int
    snippet: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "snippet", self.snippet.strip())
