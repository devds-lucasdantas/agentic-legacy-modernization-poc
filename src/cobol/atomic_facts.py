"""Canonical Atomic Fact representations for COBOL analysis.

Separates:
1. AtomicFact: Pure semantic identity (normalized, immutable, hashable).
2. PredictedFact: Model assertion binding an AtomicFact to cited SourceEvidence.
3. SupportedFact: Oracle ground-truth fact binding an AtomicFact to a deterministic
   support span [line_start, line_end] and required evidence text fragments.
"""

from dataclasses import dataclass
from typing import Any


def normalize_token(text: str) -> str:
    """Normalize a token by stripping, collapsing whitespace, and converting to uppercase."""
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
        object.__setattr__(self, "kind", normalize_token(self.kind))
        object.__setattr__(self, "subject", normalize_token(self.subject))
        object.__setattr__(self, "predicate", normalize_token(self.predicate))
        object.__setattr__(self, "object", normalize_token(self.object))
        norm_attrs = tuple(
            sorted((normalize_token(k), normalize_token(v)) for k, v in self.attributes)
        )
        object.__setattr__(self, "attributes", norm_attrs)

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
    def contradiction_key(self) -> tuple[str, str]:
        """Key used to group assertions for contradiction detection.

        If multiple assertions have the same contradiction key but different
        predicates, objects, or attributes, they are in contradiction.
        """
        if self.kind == "DATA_FIELD":
            return ("DATA_FIELD", self.subject)
        if self.kind == "MENU_OPTION":
            return ("MENU_OPTION", self.subject)
        if self.kind == "PROGRAM":
            return ("PROGRAM", "PROGRAM-ID")
        if self.kind == "DEPENDENCY_SCAN":
            return ("DEPENDENCY_SCAN", self.subject)
        return (self.kind, f"{self.subject}:{self.predicate}")


@dataclass(frozen=True)
class SupportedFact:
    """Ground-truth fact supported by source code with span and required fragments."""

    fact: AtomicFact
    line_start: int
    line_end: int
    required_evidence_fragments: tuple[str, ...]

    def __post_init__(self) -> None:
        norm_frags = tuple(
            normalize_token(f) for f in self.required_evidence_fragments if normalize_token(f)
        )
        object.__setattr__(self, "required_evidence_fragments", norm_frags)


@dataclass(frozen=True)
class PredictedFact:
    """Model assertion predicting a fact backed by a cited SourceEvidence."""

    fact: AtomicFact
    source_file: str
    line_start: int
    line_end: int
    snippet: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_file", self.source_file.strip())
        object.__setattr__(self, "snippet", self.snippet.strip())
