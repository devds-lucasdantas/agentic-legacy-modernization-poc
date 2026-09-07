"""Deterministic validator for SourceEvidence in Gate 2.

Verifies:
1. Source file is strictly BANK-MAIN.CBL (no callee or outside references).
2. Line numbers are in valid range [1, total_lines] with line_start <= line_end.
3. Snippet matches actual source lines under a documented normalization policy.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.legacy_analyzer.schemas.assessment import SourceEvidence


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
    evidence: SourceEvidence,
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

    # Snippet must match or be contained in the actual slice,
    # or actual slice must be contained in snippet (for multi-line variations)
    if norm_snippet in norm_actual or norm_actual in norm_snippet:
        return EvidenceValidationResult(
            is_valid=True,
            field_context=context,
            evidence=evidence_dict,
        )

    # Support ellipsis abbreviation across line spans (e.g. 'PERFORM UNTIL ... STOP RUN.')
    if "..." in evidence.snippet or "…" in evidence.snippet:
        import re
        raw_parts = [p.strip() for p in re.split(r"\.{3}|…", evidence.snippet) if p.strip()]
        current_idx = 0
        all_matched = True
        for part in raw_parts:
            norm_part = normalize_snippet(part)
            found_idx = norm_actual.find(norm_part, current_idx)
            if found_idx == -1:
                all_matched = False
                break
            current_idx = found_idx + len(norm_part)
        if all_matched and len(raw_parts) > 0:
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
