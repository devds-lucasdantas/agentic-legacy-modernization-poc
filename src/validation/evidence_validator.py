"""Deterministic validator for SourceEvidence in Gate 2 V2.1.

Verifies:
1. Basic syntactic validity: line bounds within source length, line_start <= line_end,
   non-empty snippet.
2. Snippet containment: cited snippet must strictly appear in the actual source slice.
   Arbitrary fabricated text or blank-line citations are strictly rejected.
3. Ellipsis snippets: must match non-empty fragments in strict forward source order.
4. Occurrence-specific evidence binding:
   - Binds the predicted fact citation directly to a specific SupportedFactOccurrence.
   - Citation span must overlap/cover the occurrence's statement span.
   - Span bounds are derived dynamically from the occurrence's parsed span
     (occurrence span length + 2 lines tolerance for surrounding boundary tokens),
     eliminating magic formatting constants.
   - Required semantic operand fragments must all be present in the snippet and source slice.
"""

import re
from dataclasses import dataclass
from typing import Any

from agents.legacy_analyzer.schemas.assessment import SourceEvidence
from agents.legacy_analyzer.schemas.assessment_v1 import SourceEvidence as SourceEvidenceV1
from src.cobol.atomic_facts import PredictedFact, SupportedFactOccurrence


@dataclass
class EvidenceValidationResult:
    """Result of validating a SourceEvidence item."""

    is_valid: bool
    error_message: str | None = None
    field_context: str = ""
    evidence: dict[str, Any] | None = None


def normalize_snippet(text: str) -> str:
    """Normalize text for evidence comparison: collapse whitespace, uppercase."""
    return " ".join(text.strip().split()).upper()


def validate_evidence(
    evidence: SourceEvidence | SourceEvidenceV1,
    source_lines: list[str],
    context: str = "",
    allowed_filename: str = "BANK-MAIN.CBL",
) -> EvidenceValidationResult:
    """Validate a SourceEvidence instance deterministically against source text lines.

    Args:
        evidence: The SourceEvidence instance to validate.
        source_lines: List of raw source lines (1-indexed via index 0 = line 1).
        context: Contextual label (e.g. 'call_dependencies[0]').
        allowed_filename: Allowed base filename (for schemas that include source_file).

    Returns:
        EvidenceValidationResult indicating validity and details if invalid.
    """
    evidence_dict = evidence.model_dump()
    max_line = len(source_lines)

    # 1. Source file check (only if present in evidence schema, e.g. V1)
    if hasattr(evidence, "source_file") and getattr(evidence, "source_file", None):
        sf = getattr(evidence, "source_file").replace("\\", "/")
        # Reject traversal attempts
        if ".." in sf or sf.startswith("/"):
            return EvidenceValidationResult(
                is_valid=False,
                error_message=f"Disallowed path format in source_file: '{sf}'",
                field_context=context,
                evidence=evidence_dict,
            )
        sf_name = sf.split("/")[-1].upper()
        if sf_name != allowed_filename.upper():
            return EvidenceValidationResult(
                is_valid=False,
                error_message=(
                    f"Evidence references outside file '{sf}'; expected '{allowed_filename}'"
                ),
                field_context=context,
                evidence=evidence_dict,
            )

    # 2. Line range check
    if evidence.line_start < 1 or evidence.line_end > max_line:
        return EvidenceValidationResult(
            is_valid=False,
            error_message=(
                f"Line range [{evidence.line_start}, {evidence.line_end}] is out of bounds "
                f"(valid: [1, {max_line}])"
            ),
            field_context=context,
            evidence=evidence_dict,
        )

    if evidence.line_start > evidence.line_end:
        return EvidenceValidationResult(
            is_valid=False,
            error_message=(
                f"line_start ({evidence.line_start}) exceeds line_end ({evidence.line_end})"
            ),
            field_context=context,
            evidence=evidence_dict,
        )

    # 3. Snippet match check
    norm_snippet = normalize_snippet(evidence.snippet)
    if not norm_snippet:
        return EvidenceValidationResult(
            is_valid=False,
            error_message="Snippet is empty",
            field_context=context,
            evidence=evidence_dict,
        )

    # Slice actual lines (line_start and line_end are 1-indexed)
    actual_slice_lines = source_lines[evidence.line_start - 1 : evidence.line_end]
    actual_slice_text = " ".join(actual_slice_lines)
    norm_actual = normalize_snippet(actual_slice_text)

    # Reject non-empty snippets against completely blank source slices
    if not norm_actual:
        return EvidenceValidationResult(
            is_valid=False,
            error_message=(
                f"Snippet '{evidence.snippet}' cited for blank source lines "
                f"[{evidence.line_start}..{evidence.line_end}]"
            ),
            field_context=context,
            evidence=evidence_dict,
        )

    # Ellipsis support: requires all nonempty fragments in strict forward order
    if "..." in evidence.snippet or "…" in evidence.snippet:
        raw_parts = [p.strip() for p in re.split(r"\.{3}|…", evidence.snippet) if p.strip()]
        if not raw_parts:
            return EvidenceValidationResult(
                is_valid=False,
                error_message=f"Ellipsis snippet '{evidence.snippet}' has no textual content",
                field_context=context,
                evidence=evidence_dict,
            )

        current_idx = 0
        for part in raw_parts:
            norm_part = normalize_snippet(part)
            if not norm_part:
                continue
            found_idx = norm_actual.find(norm_part, current_idx)
            if found_idx == -1:
                return EvidenceValidationResult(
                    is_valid=False,
                    error_message=(
                        f"Ellipsis snippet fragment '{part}' not found in source slice in order"
                    ),
                    field_context=context,
                    evidence=evidence_dict,
                )
            current_idx = found_idx + len(norm_part)

        return EvidenceValidationResult(
            is_valid=True,
            field_context=context,
            evidence=evidence_dict,
        )

    # Standard contiguous snippet: must be strictly contained in actual slice
    if norm_snippet not in norm_actual:
        return EvidenceValidationResult(
            is_valid=False,
            error_message=(
                f"Evidence snippet '{evidence.snippet}' does not match actual source text "
                f"in lines [{evidence.line_start}..{evidence.line_end}]"
            ),
            field_context=context,
            evidence=evidence_dict,
        )

    return EvidenceValidationResult(
        is_valid=True,
        field_context=context,
        evidence=evidence_dict,
    )


def validate_claim_evidence(
    predicted: PredictedFact,
    supported_occurrence: SupportedFactOccurrence,
    source_lines: list[str],
    context: str = "",
) -> EvidenceValidationResult:
    """Validate that a predicted fact's evidence specifically supports that fact occurrence.

    Rules:
    1. Base syntactic validation (line bounds, snippet containment).
    2. Overlap constraint: cited line range must overlap with occurrence statement span.
    3. Span length constraint: derived dynamically from occurrence span length + 2 lines tolerance.
    4. Required semantic operands: all required fragments for this occurrence must be present.
    """
    ev_obj = SourceEvidence(
        line_start=predicted.line_start,
        line_end=predicted.line_end,
        snippet=predicted.snippet,
    )

    # 1. Base validation
    base_res = validate_evidence(ev_obj, source_lines, context=context)
    if not base_res.is_valid:
        return base_res

    # 2. Overlap constraint with occurrence statement span
    o_start = supported_occurrence.line_start
    o_end = supported_occurrence.line_end

    has_overlap = not (predicted.line_end < o_start or predicted.line_start > o_end)
    if not has_overlap:
        return EvidenceValidationResult(
            is_valid=False,
            error_message=(
                f"Cited line span [{predicted.line_start}, {predicted.line_end}] does not "
                f"overlap with statement support span [{o_start}, {o_end}] for fact "
                f"'{predicted.fact.canonical_id}'"
            ),
            field_context=context,
            evidence=ev_obj.model_dump(),
        )

    # 3. Dynamic span bound: occurrence span length + 2 lines tolerance (eliminates magic constants)
    occ_len = o_end - o_start + 1
    max_allowed = max(occ_len + 2, 4)
    span_len = predicted.line_end - predicted.line_start + 1

    if span_len > max_allowed:
        return EvidenceValidationResult(
            is_valid=False,
            error_message=(
                f"Cited line span [{predicted.line_start}, {predicted.line_end}] "
                f"(length {span_len}) exceeds allowed span bound ({max_allowed}) "
                f"for statement span [{o_start}..{o_end}]"
            ),
            field_context=context,
            evidence=ev_obj.model_dump(),
        )

    # 4. Required evidence fragments check
    norm_snippet = normalize_snippet(predicted.snippet)
    actual_slice_lines = source_lines[predicted.line_start - 1 : predicted.line_end]
    norm_actual = normalize_snippet(" ".join(actual_slice_lines))

    for frag in supported_occurrence.required_evidence_fragments:
        if not frag or not frag.strip():
            return EvidenceValidationResult(
                is_valid=False,
                error_message=(
                    f"Occurrence has vacuous required fragment '{frag}' for fact "
                    f"'{predicted.fact.canonical_id}'"
                ),
                field_context=context,
                evidence=ev_obj.model_dump(),
            )
        norm_frag = normalize_snippet(frag)
        if not norm_frag:
            return EvidenceValidationResult(
                is_valid=False,
                error_message=(
                    f"Occurrence has vacuous normalized required fragment '{frag}' for fact "
                    f"'{predicted.fact.canonical_id}'"
                ),
                field_context=context,
                evidence=ev_obj.model_dump(),
            )
        if norm_frag not in norm_snippet:
            return EvidenceValidationResult(
                is_valid=False,
                error_message=(
                    f"Evidence snippet missing required fragment '{frag}' for fact "
                    f"'{predicted.fact.canonical_id}'"
                ),
                field_context=context,
                evidence=ev_obj.model_dump(),
            )
        if norm_frag not in norm_actual:
            return EvidenceValidationResult(
                is_valid=False,
                error_message=(
                    f"Actual source slice missing required fragment '{frag}' for fact "
                    f"'{predicted.fact.canonical_id}'"
                ),
                field_context=context,
                evidence=ev_obj.model_dump(),
            )

    return EvidenceValidationResult(
        is_valid=True,
        field_context=context,
        evidence=ev_obj.model_dump(),
    )
