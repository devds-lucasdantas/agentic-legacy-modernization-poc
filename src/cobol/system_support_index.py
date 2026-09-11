"""Ground-truth AST support index for Gate 3 system evaluation.

Indexes all 54 canonical supported system facts across the 6-file legacy bundle.
Provides deterministic, AST-grounded fact matching and coordinate verification
with ZERO fuzzy or LLM evaluation.
"""

from src.cobol.multi_source_reader import MultiSourceBundle
from src.cobol.system_atomic_facts import SupportedSystemFact, SystemAtomicFact


class SystemSupportIndex:
    """Immutable ground-truth index for verified system facts and source spans."""

    def __init__(
        self, supported_facts: list[SupportedSystemFact], bundle: MultiSourceBundle
    ) -> None:
        self.bundle = bundle
        self._facts_by_prop_id: dict[str, SupportedSystemFact] = {}
        self._facts_by_semantic_key: dict[str, list[SupportedSystemFact]] = {}
        self._facts_by_file: dict[str, list[SupportedSystemFact]] = {}

        for sf in supported_facts:
            prop_id = sf.proposition_id
            self._facts_by_prop_id[prop_id] = sf

            key = sf.fact.get_semantic_key()
            self._facts_by_semantic_key.setdefault(key, []).append(sf)

            norm_path = sf.file_path.replace("\\", "/")
            self._facts_by_file.setdefault(norm_path, []).append(sf)

    @property
    def total_expected_facts(self) -> int:
        """Total count of canonical golden propositions."""
        return len(self._facts_by_prop_id)

    def get_all_facts(self) -> list[SupportedSystemFact]:
        """Return all supported system facts."""
        return list(self._facts_by_prop_id.values())

    def get_fact_by_id(self, proposition_id: str) -> SupportedSystemFact | None:
        """Look up a supported fact by its canonical golden proposition ID."""
        return self._facts_by_prop_id.get(proposition_id)

    def get_facts_for_file(self, file_path: str) -> list[SupportedSystemFact]:
        """Return all supported facts grounded in the specified file."""
        norm_path = file_path.replace("\\", "/")
        return self._facts_by_file.get(norm_path, [])

    def is_span_valid(self, file_path: str, line_start: int, line_end: int) -> bool:
        """Validate that physical line coordinates exist within the target file bounds."""
        norm_path = file_path.replace("\\", "/")
        try:
            target_file = self.bundle.get_file(norm_path)
            return 1 <= line_start <= line_end <= target_file.line_count
        except KeyError:
            return False

    def verify_assertion(
        self,
        candidate_fact: SystemAtomicFact,
        file_path: str,
        line_start: int,
        line_end: int,
        tolerance_lines: int = 5,
    ) -> tuple[bool, str, SupportedSystemFact | None]:
        """Verify candidate model assertion against ground-truth support index.

        Strictly deterministic:
        1. Checks exact semantic key match against grounded AST facts.
        2. Checks target file path match.
        3. Checks physical line span proximity within tolerance window.

        Returns:
            (is_supported, reason_message, matched_supported_fact)
        """
        norm_file = file_path.replace("\\", "/")
        if not self.is_span_valid(norm_file, line_start, line_end):
            return (
                False,
                f"Invalid line span [{line_start}, {line_end}] for '{file_path}'",
                None,
            )

        key = candidate_fact.get_semantic_key()
        grounded_candidates = self._facts_by_semantic_key.get(key, [])

        if not grounded_candidates:
            return (
                False,
                f"No ground-truth source fact supports semantic assertion '{key}'",
                None,
            )

        for sf in grounded_candidates:
            # Match file
            if (
                sf.file_path == norm_file
                or sf.file_path.endswith("/" + norm_file)
                or norm_file.endswith("/" + sf.file_path)
            ):
                # Check line coordinate overlap / tolerance
                if (
                    abs(sf.line_start - line_start) <= tolerance_lines
                    and abs(sf.line_end - line_end) <= tolerance_lines
                ):
                    return True, "Supported by ground-truth AST fact", sf

        return (
            False,
            f"Evidence span [{line_start}, {line_end}] in '{file_path}' does not match "
            f"ground-truth spans for '{key}'",
            None,
        )
