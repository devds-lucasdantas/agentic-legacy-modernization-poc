"""Source support oracle compatibility layer backed by SourceSupportIndex.

DEPRECATED: Use SourceFactExtractor and SourceSupportIndex directly.
This wrapper provides backward compatibility while delegating 100% of extraction
and lookup to the deterministic SourceSupportIndex without any hardcoded answers.
"""

from src.cobol.atomic_facts import AtomicFact, SupportedFactOccurrence
from src.cobol.support_index import SourceSupportIndex


class SourceSupportOracle:
    """Ground-truth support oracle deterministically backed by SourceSupportIndex."""

    def __init__(self, source_lines: list[str]) -> None:
        self.source_lines = source_lines
        self.total_lines = len(source_lines)
        self._index = SourceSupportIndex.from_source_lines(source_lines)

    @property
    def index(self) -> SourceSupportIndex:
        """Return the underlying SourceSupportIndex."""
        return self._index

    @property
    def supported_facts(self) -> list[SupportedFactOccurrence]:
        """Return all supported ground-truth fact occurrences."""
        return self._index.occurrences

    def is_fact_supported(self, fact: AtomicFact) -> bool:
        """Check if an AtomicFact is supported by the source code."""
        return self._index.is_supported(fact)

    def get_supported_fact(self, fact: AtomicFact) -> SupportedFactOccurrence | None:
        """Get the primary SupportedFactOccurrence entry for an AtomicFact, if supported."""
        occs = self._index.get_occurrences(fact)
        return occs[0] if occs else None

    def find_matching_occurrence(
        self, fact: AtomicFact, line_start: int, line_end: int
    ) -> SupportedFactOccurrence | None:
        """Find the occurrence that best matches the cited span."""
        return self._index.find_matching_occurrence(fact, line_start, line_end)
