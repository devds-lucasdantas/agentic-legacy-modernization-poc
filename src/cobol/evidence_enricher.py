"""Deterministic host evidence derivation and enrichment for Gate 2 Candidate V2.4.

Separates raw model output (line coordinates only) from host-derived evidence.
Derives exact raw source code snippets deterministically from verified source bytes.
"""

import copy
from typing import Any

from agents.legacy_analyzer.schemas.assessment import LegacyAssessment


def derive_snippet_from_source(
    line_start: int,
    line_end: int,
    source_lines: list[str],
) -> str:
    """Deterministically derive exact raw snippet from source lines using 1-indexed coordinates.

    Fails closed:
    - Out-of-bounds (line_start < 1 or line_end > len(source_lines)) -> ""
    - Reversed bounds (line_start > line_end) -> ""
    - Otherwise -> "\\n".join(source_lines[line_start - 1 : line_end])
    """
    if line_start < 1 or line_end > len(source_lines) or line_start > line_end:
        return ""
    return "\n".join(source_lines[line_start - 1 : line_end])


def build_enriched_assessment_dict(
    assessment: LegacyAssessment | dict[str, Any],
    source_lines: list[str],
) -> dict[str, Any]:
    """Build a distinct enriched assessment dictionary with host-derived evidence snippets.

    Does NOT mutate the raw model assessment object.
    Explicitly tags the output as host-derived.
    """
    if hasattr(assessment, "model_dump"):
        data = copy.deepcopy(assessment.model_dump())
    elif isinstance(assessment, dict):
        data = copy.deepcopy(assessment)
    else:
        raise TypeError(f"Unsupported assessment type: {type(assessment)}")

    def process_evidence(ev: dict[str, Any]) -> None:
        l_start = ev.get("line_start")
        l_end = ev.get("line_end")
        if isinstance(l_start, int) and isinstance(l_end, int):
            ev["snippet"] = derive_snippet_from_source(l_start, l_end, source_lines)

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if "line_start" in obj and "line_end" in obj:
                process_evidence(obj)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    data["_host_enrichment"] = {
        "status": "HOST_DERIVED",
        "method": "EXACT_SOURCE_BYTE_SLICE",
        "source_line_count": len(source_lines),
    }
    return data
