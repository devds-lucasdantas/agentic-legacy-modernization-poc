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
                    if self.file_status_certificate is None:
                        raise RuntimeError(
                            "Whole-scope FileStatusCertificate is required to evaluate "
                            "MISSING_ERROR_STATUS behavioral risk."
                        )

                    cand_res_span = candidate_spans.get("affected_resource_evidence")
                    cand_op_span = candidate_spans.get("operation_evidence")
                    if cand_res_span is None or cand_op_span is None:
                        return (
                            False,
                            "MISSING_ERROR_STATUS requires both affected_resource_evidence "
                            "and operation_evidence",
                            None,
                        )

                    # 1. Structurally identify the file binding from affected_resource_evidence
                    target_record = None
                    for (
                        p_id,
                        _f_name,
                    ), rec in self.file_status_certificate.bindings.items():
                        if p_id.upper() == candidate_fact.program_id.upper():
                            res_file = rec.resource_span.file_path.replace("\\", "/")
                            cand_res_file = cand_res_span.file_path.replace("\\", "/")
                            path_match = (
                                res_file == cand_res_file
                                or res_file.endswith("/" + cand_res_file)
                                or cand_res_file.endswith("/" + res_file)
                            )
                            if (
                                path_match
                                and cand_res_span.line_start == rec.resource_span.line_start
                                and cand_res_span.line_end == rec.resource_span.line_end
                            ):
                                target_record = rec
                                break

                    if target_record is None:
                        return (
                            False,
                            "Affected resource evidence does not match any known file binding in "
                            f"{candidate_fact.program_id}",
                            None,
                        )

                    # 2. Certificate must contain that exact binding
                    if not self.file_status_certificate.binding_exists(
                        candidate_fact.program_id, target_record.internal_file_name
                    ):
                        return (
                            False,
                            f"Binding {target_record.internal_file_name} in "
                            f"{candidate_fact.program_id} missing from host certificate",
                            None,
                        )

                    # 3. Certificate must prove has_file_status == False
                    if target_record.has_file_status:
                        return (
                            False,
                            "Whole-scope certificate proves FILE STATUS is declared for "
                            f"{target_record.internal_file_name} in {candidate_fact.program_id}",
                            None,
                        )

                    # 4. Grounded file operation evidence must match that same binding
                    if target_record.operations_span is None:
                        return (
                            False,
                            f"No grounded file operations exist for "
                            f"{target_record.internal_file_name} in {candidate_fact.program_id}",
                            None,
                        )

                    op_file = target_record.operations_span.file_path.replace("\\", "/")
                    cand_op_file = cand_op_span.file_path.replace("\\", "/")
                    op_path_match = (
                        op_file == cand_op_file
                        or op_file.endswith("/" + cand_op_file)
                        or cand_op_file.endswith("/" + op_file)
                    )
                    if (
                        not op_path_match
                        or cand_op_span.line_start != target_record.operations_span.line_start
                        or cand_op_span.line_end != target_record.operations_span.line_end
                    ):
                        return (
                            False,
                            f"Operation evidence does not match operations on "
                            f"{target_record.internal_file_name} in {candidate_fact.program_id}",
                            None,
                        )

                    return (
                        True,
                        "Supported by exact role-bound ground-truth AST fact and host "
                        "file status certificate",
                        sf,
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
