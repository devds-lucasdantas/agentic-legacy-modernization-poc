"""Deterministic Source Support Index for COBOL analysis.

Indexes SupportedFactOccurrence items by canonical AtomicFact.
Supports:
1. Deterministic support lookup for AtomicFacts
2. Preserving distinct occurrence identities
3. Matching predictions to specific statement occurrences
4. Tracking parse completeness and unsupported syntax
"""

from collections import defaultdict
from typing import Any

from src.cobol.atomic_facts import AtomicFact, SupportedFactOccurrence
from src.cobol.fact_extractor import ExtractionResult, SourceFactExtractor


class SourceSupportIndex:
    """Index of ground-truth supported facts derived from source code."""

    def __init__(self, extraction_result: ExtractionResult) -> None:
        self._result = extraction_result
        self._occurrences: list[SupportedFactOccurrence] = list(extraction_result.occurrences)
        self._fact_to_occurrences: dict[AtomicFact, list[SupportedFactOccurrence]] = defaultdict(
            list
        )
        for occ in self._occurrences:
            self._fact_to_occurrences[occ.fact].append(occ)

    @classmethod
    def from_source_lines(cls, source_lines: list[str]) -> "SourceSupportIndex":
        """Build support index directly from source lines using SourceFactExtractor."""
        extractor = SourceFactExtractor(source_lines)
        result = extractor.extract()
        return cls(result)

    @property
    def occurrences(self) -> list[SupportedFactOccurrence]:
        """Return all supported fact occurrences."""
        return list(self._occurrences)

    @property
    def supported_facts(self) -> set[AtomicFact]:
        """Return the set of unique supported AtomicFacts."""
        return set(self._fact_to_occurrences.keys())

    @property
    def parse_complete(self) -> bool:
        """Whether source parsing was complete and free of ambiguous syntax."""
        return self._result.parse_complete

    @property
    def unsupported_statements(self) -> list[str]:
        """List of unsupported or ambiguous statements encountered during parsing."""
        return list(self._result.unsupported_statements)

    def is_supported(self, fact: AtomicFact) -> bool:
        """Check if an AtomicFact is supported by at least one occurrence in source."""
        return fact in self._fact_to_occurrences

    def get_occurrences(self, fact: AtomicFact) -> list[SupportedFactOccurrence]:
        """Return all occurrences supporting a given AtomicFact."""
        return list(self._fact_to_occurrences.get(fact, []))

    def find_matching_occurrence(
        self,
        fact: AtomicFact,
        line_start: int,
        line_end: int,
    ) -> SupportedFactOccurrence | None:
        """Find the occurrence of fact that best aligns with the cited line range.

        Prioritizes:
        1. Overlapping line ranges
        2. Nearest distance if multiple occurrences exist
        """
        occs = self._fact_to_occurrences.get(fact, [])
        if not occs:
            return None

        # Check for overlapping occurrences first
        overlapping: list[tuple[float, SupportedFactOccurrence]] = []
        for occ in occs:
            has_overlap = not (line_end < occ.line_start or line_start > occ.line_end)
            if has_overlap:
                # Calculate distance between centers for tie-breaking
                cite_center = (line_start + line_end) / 2.0
                occ_center = (occ.line_start + occ.line_end) / 2.0
                dist = abs(cite_center - occ_center)
                overlapping.append((dist, occ))

        if overlapping:
            overlapping.sort(key=lambda x: x[0])
            return overlapping[0][1]

        # If no overlap, return the closest occurrence by line proximity
        def distance_to_span(occ: SupportedFactOccurrence) -> int:
            if line_end < occ.line_start:
                return occ.line_start - line_end
            return line_start - occ.line_end

        sorted_by_dist = sorted(occs, key=distance_to_span)
        return sorted_by_dist[0]

    def to_summary_dict(self) -> dict[str, Any]:
        """Produce a diagnostic summary dictionary."""
        return {
            "total_occurrences": len(self._occurrences),
            "unique_supported_facts": len(self._fact_to_occurrences),
            "parse_complete": self.parse_complete,
            "unsupported_statements": self.unsupported_statements,
        }
