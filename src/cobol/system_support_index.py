"""Ground-truth AST support index for Gate 3 system evaluation (Candidate V3.1).

Indexes all supported system facts across the multi-source legacy bundle.
Provides exact role-bound evidence verification adhering strictly to:
- Blocker 5: ZERO evidence line tolerance; exact role-bound verification.
- Guardrail A: Exact semantic key match against AST-grounded facts.
- Host verifier reasons over exact AST relations and does not supply omitted relationships.
"""

from typing import Any

from src.cobol.multi_source_reader import MultiSourceBundle
from src.cobol.system_atomic_facts import (
    BehavioralRiskFact,
    EvidenceSpan,
    SupportedSystemFact,
    SystemAtomicFact,
)


class SystemSupportIndex:
    """Immutable ground-truth index for verified system facts and source spans."""

    def __init__(
        self,
        supported_facts: list[SupportedSystemFact],
        bundle: MultiSourceBundle,
        file_status_certificate: Any | None = None,
    ) -> None:
        self.bundle = bundle
        self.file_status_certificate = file_status_certificate
        self._facts_by_prop_id: dict[str, SupportedSystemFact] = {}
        self._facts_by_semantic_key: dict[str, list[SupportedSystemFact]] = {}
        self._facts_by_file: dict[str, list[SupportedSystemFact]] = {}

        for sf in supported_facts:
            prop_id = sf.proposition_id
            self._facts_by_prop_id[prop_id] = sf

            key = sf.fact.get_semantic_key()
            self._facts_by_semantic_key.setdefault(key, []).append(sf)

            for span in sf.evidence_spans.values():
                norm_path = span.file_path.replace("\\", "/")
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

    def verify_role_bound_assertion(
        self,
        candidate_fact: SystemAtomicFact,
        candidate_spans: dict[str, EvidenceSpan],
    ) -> tuple[bool, str, SupportedSystemFact | None]:
        """Verify candidate model assertion against ground-truth support index with exact roles.

        Strictly deterministic:
        1. Validates coordinate bounds of all candidate spans.
        2. Matches exact semantic key against grounded AST facts.
        3. Enforces exact role-bound evidence match without tolerance windows.

        Returns:
            (is_supported, reason_message, matched_supported_fact)
        """
        # Validate span bounds
        for role_name, span in candidate_spans.items():
            if not self.is_span_valid(span.file_path, span.line_start, span.line_end):
                return (
                    False,
                    f"Invalid coordinates for role '{role_name}': "
                    f"[{span.line_start}, {span.line_end}] in '{span.file_path}'",
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

        # Match exact role spans
        for sf in grounded_candidates:
            # Check if all required roles match
            roles_match = True
            for role_name, expected_span in sf.evidence_spans.items():
                cand_span = candidate_spans.get(role_name)
                if not cand_span:
                    roles_match = False
                    break

                # Normalize paths
                expected_norm = expected_span.file_path.replace("\\", "/")
                cand_norm = cand_span.file_path.replace("\\", "/")

                path_matches = (
                    expected_norm == cand_norm
                    or expected_norm.endswith("/" + cand_norm)
                    or cand_norm.endswith("/" + expected_norm)
                )
                if not path_matches:
                    roles_match = False
                    break

                # Exact line match
                if (
                    cand_span.line_start != expected_span.line_start
                    or cand_span.line_end != expected_span.line_end
                ):
                    roles_match = False
                    break

            if roles_match:
                if (
                    isinstance(candidate_fact, BehavioralRiskFact)
                    and candidate_fact.risk_basis_kind == "MISSING_ERROR_STATUS"
                ):
                    if self.file_status_certificate is not None:
                        is_proven = False
                        for (
                            p_id,
                            f_name,
                        ), has_status in self.file_status_certificate.bindings_file_status.items():
                            if p_id == candidate_fact.program_id and not has_status:
                                if f_name.lower().replace("-", "_") in sf.proposition_id.lower():
                                    is_proven = True
                                    break
                        if not is_proven:
                            return (
                                False,
                                "Whole-scope certificate does not prove absence of FILE STATUS "
                                f"for {candidate_fact.program_id}",
                                None,
                            )
                return True, "Supported by exact role-bound ground-truth AST fact", sf

        return (
            False,
            f"Evidence spans for '{key}' do not match exact ground-truth coordinates",
            None,
        )

    def verify_assertion(
        self,
        candidate_fact: SystemAtomicFact,
        file_path: str,
        line_start: int,
        line_end: int,
    ) -> tuple[bool, str, SupportedSystemFact | None]:
        """Convenience single-span verification method for 1-evidence facts."""
        spans = {"evidence": EvidenceSpan(file_path, line_start, line_end)}
        return self.verify_role_bound_assertion(candidate_fact, spans)
