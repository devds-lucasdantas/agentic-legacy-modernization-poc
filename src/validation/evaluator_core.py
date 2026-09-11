"""Unified Evaluation Core for Gate 2.

Evaluates faithful PredictedFacts against a SourceSupportIndex, Golden Dataset,
and HostVerifications.

Both the V2.1 evaluation pipeline and the historical V1 rescoring adapter feed into
this identical core.
"""

from dataclasses import asdict, dataclass, field
from typing import Any

from src.cobol.atomic_facts import AtomicFact, PredictedFact
from src.cobol.support_index import SourceSupportIndex
from src.validation.evidence_validator import validate_claim_evidence


@dataclass
class HostVerificationReport:
    """Host-executed deterministic verifications outside of model line citations."""

    copy_statements_found_count: int = 0
    scanned_line_count: int = 0
    source_sha256: str = ""
    verification_method: str = "WHOLE_FILE_SCAN"


@dataclass
class ExpectedFactMatch:
    """Result of matching a golden expected fact against predictions."""

    fact_id: str
    description: str
    expected_fact: dict[str, Any]
    matched: bool
    matched_prediction: dict[str, Any] | None = None
    evidence_valid: bool = True
    notes: str | None = None


@dataclass
class CoreEvaluationReport:
    """Detailed evaluation report produced by the unified evaluation core."""

    evaluator_version: str = "2.2.0"
    golden_dataset_version: str = "2.2.0"

    schema_valid: bool = True
    source_sha256_match: bool = True
    parse_complete: bool = True
    evidence_valid: bool = True
    invalid_evidence_count: int = 0

    # Prediction metrics
    raw_predicted_count: int = 0
    unique_predicted_count: int = 0
    duplicate_prediction_count: int = 0
    supported_predicted_count: int = 0
    unsupported_predicted_count: int = 0
    contradiction_count: int = 0

    # Recall metrics
    expected_fact_count: int = 0
    matched_expected_count: int = 0
    missing_expected_count: int = 0

    # High-level scores
    precision: float = 0.0
    recall: float = 0.0
    gate_2_pass: bool = False

    # Detailed listings
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    unsupported_predictions: list[dict[str, Any]] = field(default_factory=list)
    invalid_evidences: list[dict[str, Any]] = field(default_factory=list)
    matched_expected_facts: list[ExpectedFactMatch] = field(default_factory=list)
    missing_expected_facts: list[ExpectedFactMatch] = field(default_factory=list)
    host_verifications: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to serializable dictionary."""
        return asdict(self)


def evaluate_predicted_facts(
    predictions: list[PredictedFact],
    support_index: SourceSupportIndex,
    golden_data: dict[str, Any],
    source_lines: list[str],
    host_verifications: HostVerificationReport | None = None,
    source_sha256_actual: str | None = None,
    expected_sha256: str = "b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028",
    schema_valid: bool = True,
) -> CoreEvaluationReport:
    """Evaluate a collection of PredictedFacts deterministically.

    Args:
        predictions: List of model predictions mapped faithfully to PredictedFact.
        support_index: SourceSupportIndex derived dynamically from the source text.
        golden_data: Golden expected facts dataset dictionary.
        source_lines: Raw source lines of the analyzed file.
        host_verifications: Host-owned verification report (e.g. whole-file COPY scan).
        source_sha256_actual: Actual SHA256 of the analyzed source file.
        expected_sha256: Expected SHA256 hash.
        schema_valid: Whether schema validation succeeded prior to evaluation.

    Returns:
        CoreEvaluationReport with precision, recall, and PASS decision.
    """
    report = CoreEvaluationReport()
    report.schema_valid = schema_valid

    if source_sha256_actual is not None:
        report.source_sha256_match = source_sha256_actual.lower() == expected_sha256.lower()

    report.parse_complete = support_index.parse_complete
    report.raw_predicted_count = len(predictions)

    if host_verifications is not None:
        report.host_verifications = asdict(host_verifications)

    # 1. Duplicate Detection
    seen_facts: dict[AtomicFact, PredictedFact] = {}
    duplicates: list[dict[str, Any]] = []
    unique_predictions: list[PredictedFact] = []

    for pred in predictions:
        if pred.fact in seen_facts:
            duplicates.append(
                {
                    "fact": pred.fact.to_dict(),
                    "canonical_id": pred.fact.canonical_id,
                    "first_citation": {
                        "line_start": seen_facts[pred.fact].line_start,
                        "line_end": seen_facts[pred.fact].line_end,
                        "snippet": seen_facts[pred.fact].snippet,
                    },
                    "duplicate_citation": {
                        "line_start": pred.line_start,
                        "line_end": pred.line_end,
                        "snippet": pred.snippet,
                    },
                }
            )
        else:
            seen_facts[pred.fact] = pred
            unique_predictions.append(pred)

    report.unique_predicted_count = len(unique_predictions)
    report.duplicate_prediction_count = len(duplicates)
    report.duplicates = duplicates

    # 2. Contradiction Detection (Single-Valued Properties ONLY)
    # Multi-valued relations return None for contradiction_group_key and are NOT grouped
    contradiction_groups: dict[tuple[str, ...], list[PredictedFact]] = {}
    for pred in unique_predictions:
        ckey = pred.fact.contradiction_group_key
        if ckey is not None:
            contradiction_groups.setdefault(ckey, []).append(pred)

    contradictions: list[dict[str, Any]] = []
    for ckey, group in contradiction_groups.items():
        if len(group) > 1:
            canonical_ids = {p.fact.canonical_id for p in group}
            if len(canonical_ids) > 1:
                contradictions.append(
                    {
                        "contradiction_key": list(ckey),
                        "conflicting_facts": [p.fact.to_dict() for p in group],
                        "details": (
                            f"Multiple contradictory predictions for key {ckey}: "
                            f"{sorted(canonical_ids)}"
                        ),
                    }
                )

    report.contradiction_count = len(contradictions)
    report.contradictions = contradictions

    # 3. Support & Evidence Evaluation on Unique Predicted Facts
    supported_preds: list[PredictedFact] = []
    unsupported_preds: list[dict[str, Any]] = []
    invalid_evidences: list[dict[str, Any]] = []

    for pred in unique_predictions:
        # Special case: Negative COPY assertion (absence verification is host-owned)
        if (
            pred.fact.kind == "DEPENDENCY_SCAN"
            and pred.fact.predicate == "DEPENDENCY_COUNT"
            and pred.fact.object == "0"
        ):
            if (
                host_verifications is not None
                and host_verifications.copy_statements_found_count == 0
                and support_index.parse_complete
            ):
                supported_preds.append(pred)
            else:
                unsupported_preds.append(
                    {
                        "fact": pred.fact.to_dict(),
                        "canonical_id": pred.fact.canonical_id,
                        "reason": (
                            "Host whole-file scan detected COPY statements or scan incomplete"
                        ),
                        "citation": {
                            "line_start": pred.line_start,
                            "line_end": pred.line_end,
                            "snippet": pred.snippet,
                        },
                    }
                )
            continue

        # Standard fact support check against SourceSupportIndex
        if not support_index.is_supported(pred.fact):
            unsupported_preds.append(
                {
                    "fact": pred.fact.to_dict(),
                    "canonical_id": pred.fact.canonical_id,
                    "reason": "Not supported by source code statements",
                    "citation": {
                        "line_start": pred.line_start,
                        "line_end": pred.line_end,
                        "snippet": pred.snippet,
                    },
                }
            )
            continue

        # Find best matching occurrence for evidence binding
        matching_occ = support_index.find_matching_occurrence(
            pred.fact, pred.line_start, pred.line_end
        )
        if matching_occ is None:
            unsupported_preds.append(
                {
                    "fact": pred.fact.to_dict(),
                    "canonical_id": pred.fact.canonical_id,
                    "reason": "No matching source occurrence found",
                    "citation": {
                        "line_start": pred.line_start,
                        "line_end": pred.line_end,
                        "snippet": pred.snippet,
                    },
                }
            )
            continue

        # Validate claim evidence against the occurrence
        ev_res = validate_claim_evidence(
            pred,
            matching_occ,
            source_lines,
            context=pred.fact.canonical_id,
        )

        if not ev_res.is_valid:
            invalid_evidences.append(
                {
                    "fact": pred.fact.to_dict(),
                    "canonical_id": pred.fact.canonical_id,
                    "error": ev_res.error_message,
                    "citation": {
                        "line_start": pred.line_start,
                        "line_end": pred.line_end,
                        "snippet": pred.snippet,
                    },
                }
            )
            unsupported_preds.append(
                {
                    "fact": pred.fact.to_dict(),
                    "canonical_id": pred.fact.canonical_id,
                    "reason": f"Invalid evidence citation: {ev_res.error_message}",
                    "citation": {
                        "line_start": pred.line_start,
                        "line_end": pred.line_end,
                        "snippet": pred.snippet,
                    },
                }
            )
        else:
            supported_preds.append(pred)

    report.supported_predicted_count = len(supported_preds)
    report.unsupported_predicted_count = len(unsupported_preds)
    report.unsupported_predictions = unsupported_preds
    report.invalid_evidence_count = len(invalid_evidences)
    report.invalid_evidences = invalid_evidences
    report.evidence_valid = len(invalid_evidences) == 0

    # 4. Golden Expected Facts Matching (1-to-1)
    expected_list = golden_data.get("expected_facts", [])
    report.expected_fact_count = len(expected_list)

    matched_facts: list[ExpectedFactMatch] = []
    missing_facts: list[ExpectedFactMatch] = []
    available_preds = list(supported_preds)

    for exp in expected_list:
        f_id = exp["id"]
        f_desc = exp["description"]
        exp_atomic = AtomicFact(
            kind=exp["kind"],
            subject=exp["subject"],
            predicate=exp["predicate"],
            object=exp["object"],
            attributes=tuple(exp.get("attributes", {}).items()),
        )

        matched_pred = None
        for p in available_preds:
            if p.fact == exp_atomic:
                matched_pred = p
                available_preds.remove(p)
                break

        if matched_pred is not None:
            matched_facts.append(
                ExpectedFactMatch(
                    fact_id=f_id,
                    description=f_desc,
                    expected_fact=exp_atomic.to_dict(),
                    matched=True,
                    matched_prediction={
                        "fact": matched_pred.fact.to_dict(),
                        "citation": {
                            "line_start": matched_pred.line_start,
                            "line_end": matched_pred.line_end,
                            "snippet": matched_pred.snippet,
                        },
                    },
                    evidence_valid=True,
                )
            )
        else:
            missing_facts.append(
                ExpectedFactMatch(
                    fact_id=f_id,
                    description=f_desc,
                    expected_fact=exp_atomic.to_dict(),
                    matched=False,
                    notes="Expected fact not found among supported predictions with valid evidence",
                )
            )

    report.matched_expected_count = len(matched_facts)
    report.missing_expected_count = len(missing_facts)
    report.matched_expected_facts = matched_facts
    report.missing_expected_facts = missing_facts

    # 5. Scores
    if report.unique_predicted_count > 0:
        report.precision = round(
            report.supported_predicted_count / report.unique_predicted_count, 4
        )
    else:
        report.precision = 0.0

    if report.expected_fact_count > 0:
        report.recall = round(report.matched_expected_count / report.expected_fact_count, 4)
    else:
        report.recall = 0.0

    # 6. PASS Criteria
    report.gate_2_pass = (
        report.schema_valid
        and report.source_sha256_match
        and report.parse_complete
        and report.evidence_valid
        and report.invalid_evidence_count == 0
        and report.duplicate_prediction_count == 0
        and report.contradiction_count == 0
        and report.unsupported_predicted_count == 0
        and report.recall >= 0.90
        and report.precision >= 0.95
    )

    return report
