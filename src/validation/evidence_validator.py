"""Deterministic validator for SourceEvidence in Gate 2 V2.

Verifies:
1. Source file is strictly allowed (e.g. BANK-MAIN.CBL).
3. Snippet strictly matches or is contained within actual source lines
   (norm_snippet in norm_actual).
   Arbitrary fabricated text or blank-line citations are strictly rejected.
4. Ellipsis snippets must match non-empty fragments in strict source order.
5. Claim-specific evidence binding ensures the citation overlaps the oracle support span,
   is not excessively broad, and contains all required evidence fragments for that claim.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.legacy_analyzer.schemas.assessment import SourceEvidence
from agents.legacy_analyzer.schemas.assessment_v1 import SourceEvidence as SourceEvidenceV1
from src.cobol.atomic_facts import PredictedFact, SupportedFact


@dataclass
class EvidenceValidationResult:
    """Result of validating a SourceEvidence item."""

    is_valid: bool
    error_message: str | None = None
    field_context: str = ""
    evidence: dict[str, Any] | None = None


def normalize_snippet(text: str) -> str:
    """Normalize text for evidence comparison: collapse whitespace, uppercase.

    Normalization policy:
    - Strips leading and trailing whitespace.
    - Collapses consecutive whitespace characters (including newlines) into a single space.
    - Converts to uppercase for case-insensitive COBOL comparison.
    """
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
        allowed_filename: Allowed base filename (default 'BANK-MAIN.CBL').

    Returns:
        EvidenceValidationResult indicating validity and details if invalid.
    """
    evidence_dict = evidence.model_dump()
    max_line = len(source_lines)

    # 1. Source file check
    source_path = Path(evidence.source_file.replace("\\", "/"))
    if source_path.name.upper() != allowed_filename.upper():
        return EvidenceValidationResult(
            is_valid=False,
            error_message=(
                f"Evidence references outside file '{evidence.source_file}'; "
                f"expected '{allowed_filename}'"
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
        all_matched = True
        for part in raw_parts:
            norm_part = normalize_snippet(part)
            found_idx = norm_actual.find(norm_part, current_idx)
            if found_idx == -1:
                all_matched = False
                break
            current_idx = found_idx + len(norm_part)

        if all_matched:
            return EvidenceValidationResult(
                is_valid=True,
                field_context=context,
                evidence=evidence_dict,
            )

        return EvidenceValidationResult(
            is_valid=False,
            error_message=(
                f"Ellipsis snippet '{evidence.snippet}' fragments not found in sequence "
                f"in source lines {evidence.line_start}..{evidence.line_end}: "
                f"'{actual_slice_text.strip()}'"
            ),
            field_context=context,
            evidence=evidence_dict,
        )

    # Non-ellipsis: snippet MUST be contained in the actual slice.
    # NEVER allow norm_actual in norm_snippet (prevents fabricated suffix/prefix text)
    if norm_snippet in norm_actual:
        return EvidenceValidationResult(
            is_valid=True,
            field_context=context,
            evidence=evidence_dict,
        )

    return EvidenceValidationResult(
        is_valid=False,
        error_message=(
            f"Snippet '{evidence.snippet}' does not match actual source at lines "
            f"{evidence.line_start}..{evidence.line_end}: '{actual_slice_text.strip()}'"
        ),
        field_context=context,
        evidence=evidence_dict,
    )


def validate_claim_evidence(
    predicted: PredictedFact,
    supported_oracle_entry: SupportedFact,
    source_lines: list[str],
    context: str = "",
) -> EvidenceValidationResult:
    """Validate that a predicted fact's evidence actually supports that specific claim.

    Rules:
    1. Base syntactic validation (source file, line bounds, snippet containment).
    2. Overlap constraint: cited line range must overlap with oracle support span.
    3. Span length constraint: cited line span must not be excessively large.
    4. Fragment constraint: required key tokens for this claim must be present.
    """
    ev_obj = SourceEvidence(
        source_file=predicted.source_file,
        line_start=predicted.line_start,
        line_end=predicted.line_end,
        snippet=predicted.snippet,
    )

    # 1. Base validation
    base_res = validate_evidence(ev_obj, source_lines, context=context)
    if not base_res.is_valid:
        return base_res

    # 2. Overlap constraint with oracle support span
    o_start = supported_oracle_entry.line_start
    o_end = supported_oracle_entry.line_end

    has_overlap = not (predicted.line_end < o_start or predicted.line_start > o_end)
    if not has_overlap:
        return EvidenceValidationResult(
            is_valid=False,
            error_message=(
                f"Cited line span [{predicted.line_start}, {predicted.line_end}] does not "
                f"overlap with source support span [{o_start}, {o_end}] for fact "
                f"'{predicted.fact.canonical_id}'"
            ),
            field_context=context,
            evidence=ev_obj.model_dump(),
        )

    # 3. Maximum allowed span length per category
    span_len = predicted.line_end - predicted.line_start + 1
    kind = predicted.fact.kind

    if kind in ("PROGRAM", "DATA_FIELD", "MENU_OPTION"):
        max_allowed = 4
    elif kind in ("CALL", "CONTROL_FLOW", "IO_OPERATION"):
        max_allowed = 6
    else:
        max_allowed = 15

    if span_len > max_allowed:
        return EvidenceValidationResult(
            is_valid=False,
            error_message=(
                f"Cited line span [{predicted.line_start}, {predicted.line_end}] "
                f"(length {span_len}) exceeds maximum allowed span length ({max_allowed}) "
                f"for fact category '{kind}'"
            ),
            field_context=context,
            evidence=ev_obj.model_dump(),
        )

    # 4. Required evidence fragments check
    norm_snippet = normalize_snippet(predicted.snippet)
    actual_slice_lines = source_lines[predicted.line_start - 1 : predicted.line_end]
    norm_actual = normalize_snippet(" ".join(actual_slice_lines))

    for frag in supported_oracle_entry.required_evidence_fragments:
        if frag not in norm_snippet:
            return EvidenceValidationResult(
                is_valid=False,
                error_message=(
                    f"Evidence snippet missing required fragment '{frag}' for fact "
                    f"'{predicted.fact.canonical_id}'"
                ),
                field_context=context,
                evidence=ev_obj.model_dump(),
            )
        if frag not in norm_actual:
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
