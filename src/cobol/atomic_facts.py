"""Canonical Atomic Fact representations for COBOL analysis (Version 2.2.0).

Separates:
1. Source Token Parsing: Strictly decodes quoted source literal tokens and WHEN branch tokens.
2. Semantic Normalization: Type-aware normalization for identifiers, keywords, PIC clauses,
   conditions, and menu keys. Model semantic values for literals and menu keys
   are preserved verbatim.
3. AtomicFact: Pure semantic identity (normalized, immutable, hashable).
4. SupportedFactOccurrence: Ground-truth fact occurrence in source code with exact
   physical statement span [line_start, line_end] and non-vacuous required operands.
5. PredictedFact: Model assertion binding an AtomicFact to cited SourceEvidence.
6. Contradiction Semantics: Distinguishes multi-valued relations (CALL, DISPLAY, COPY)
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


def parse_cobol_literal_token(token: str) -> str:
    """Decode a quoted COBOL source literal token.

    Requires matching quote delimiters (' or \") when a quoted source token is expected.
    Removes the matching outer delimiter exactly once.
    Preserves every character inside verbatim: case, leading/trailing/internal spaces,
    and punctuation.
    """
    s = token.strip()
    if len(s) < 2:
        raise ValueError(f"Invalid COBOL literal token: '{token}' (too short)")
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        return s[1:-1]
    raise ValueError(f"Invalid COBOL literal token: '{token}' (missing matching outer quotes)")


def parse_source_menu_key_token(token: str) -> str:
    """Parse a COBOL source WHEN branch condition token.

    Matches either:
    - Exact keyword OTHER (case-insensitive) -> 'OTHER'
    - Exact quoted literal token (e.g. \"'1'\" -> \"1\")
    """
    s = token.strip()
    if s.upper() == "OTHER":
        return "OTHER"
    if (s.startswith("'") and s.endswith("'") and len(s) >= 2) or (
        s.startswith('"') and s.endswith('"') and len(s) >= 2
    ):
        inner = s[1:-1]
        if "'" in inner or '"' in inner:
            raise ValueError(f"Malformed source menu key token with inner quotes: '{token}'")
        return inner
    raise ValueError(f"Invalid source menu key token: '{token}'")


def normalize_menu_key(key: str) -> str:
    """Normalize a model-produced semantic menu key.

    Model fields already contain semantic values (e.g. '1', '2', '3', '4', 'OTHER').
    Preserves semantic values as-is verbatim without trimming, quote-stripping, or repairs.
    Keyword case normalization is permitted ONLY when the complete original semantic
    value is exactly the keyword 'OTHER' (case-insensitive) without leading/trailing characters.
    Malformed or whitespace-padded values such as " 1 ", "1 ", "\\t1", "\\n1", "\\u00a01",
    "'1'", "O'THER", " other " are NEVER repaired into supported keys.
    """
    if key.upper() == "OTHER" and len(key) == 5:
        return "OTHER"
    return key


normalize_model_menu_key = normalize_menu_key


def normalize_semantic_literal(text: str) -> str:
    """Normalize a model-produced semantic string/display literal.

    The model schema value IS ALREADY the semantic literal content.
    Do NOT trim it.
    Do NOT strip quotes heuristically.
    Do NOT uppercase it.
    Do NOT decode it a second time.
    Strictly idempotent: normalize_semantic_literal(val) == val.
    """
    return text


def normalize_string_literal(text: str) -> str:
    """Legacy alias / fallback for string literals (preserved for compatibility)."""
    return normalize_semantic_literal(text)


def normalize_pic(raw_pic: str | None) -> str:
    """Canonicalize a COBOL PICTURE clause string using a narrow supported grammar.

    Only canonicalizes VALID supported syntax:
    - None or '' or 'NONE' -> 'NONE'
    - 'X' -> 'X(1)'
    - 'X(1)' -> 'X(1)'
    - '9' -> '9(1)'
    - '999' -> '9(3)'
    - 'XXXXX' -> 'X(5)'
    - '9(12)' -> '9(12)'
    - 'S9(4)' -> 'S9(4)'
    - 'PIC X' -> 'X(1)'

    Does NOT use broad punctuation removal (no arbitrary rstrip('.')).
    Malformed values (e.g. 'X....', 'X(', '9(abc)') remain un-normalized distinct claims
    and will not match valid source PIC clauses.
    """
    if not raw_pic or raw_pic.strip().upper() in ("NONE", ""):
        return "NONE"

    s = raw_pic.strip()
    if s.upper().startswith("PIC "):
        s = s[4:].strip()
    elif s.upper().startswith("PICTURE "):
        s = s[8:].strip()

    # Narrow grammar for supported Gate 2 PIC clauses
    m_single = re.fullmatch(r"([X9AS])", s, re.IGNORECASE)
    if m_single:
        return f"{m_single.group(1).upper()}(1)"

    m_repeat = re.fullmatch(r"([X9AS])\1+", s, re.IGNORECASE)
    if m_repeat:
        char = m_repeat.group(1).upper()
        return f"{char}({len(s)})"

    m_paren = re.fullmatch(r"([X9AS])\((\d+)\)", s, re.IGNORECASE)
    if m_paren:
        char = m_paren.group(1).upper()
        count = int(m_paren.group(2))
        return f"{char}({count})"

    m_signed_paren = re.fullmatch(r"S(9)\((\d+)\)", s, re.IGNORECASE)
    if m_signed_paren:
        return f"S9({int(m_signed_paren.group(2))})"

    m_signed_repeat = re.fullmatch(r"S(9)+", s, re.IGNORECASE)
    if m_signed_repeat:
        return f"S9({len(s) - 1})"

    # Malformed or unsupported PIC: return as-is, never normalize into valid PIC
    return s


def normalize_condition(cond: str) -> str:
    """Normalize a COBOL condition expression without erasing operand values.

    Normalizes keyword/identifier casing and quote styles around string literals,
    while strictly preserving literal values and comparison operators.
    E.g. \"ws-choice = '4'\" -> \"WS-CHOICE = '4'\"
         'ws-choice = \"4\"' -> \"WS-CHOICE = '4'\"
    """
    s = cond.strip()
    m = re.match(r"^([A-Za-z0-9-]+)\s*(=|NOT\s*=|<>|>|<|>=|<=)\s*(.+)$", s, re.IGNORECASE)
    if m:
        lhs = m.group(1).upper()
        op = " ".join(m.group(2).upper().split())
        rhs = m.group(3).strip()
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
            norm_subject = normalize_menu_key(self.subject)
            if norm_predicate == "CALLS":
                norm_object = normalize_identifier(self.object)
            elif norm_predicate == "DISPLAYS":
                norm_object = normalize_semantic_literal(self.object)
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
                norm_object = normalize_semantic_literal(self.object)
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
