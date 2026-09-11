"""Deterministic multi-file evidence derivation and enrichment for Gate 3.

Separates raw model output (line coordinates only) from host-derived evidence.
Derives exact raw source code snippets deterministically from verified source bytes
across all files in the multi-source legacy bundle.
"""

import copy
from typing import Any

from src.cobol.multi_source_reader import MultiSourceBundle


def derive_snippet_from_bundle(
    file_path: str,
    line_start: int,
    line_end: int,
    bundle: MultiSourceBundle,
) -> str:
    """Deterministically derive exact raw snippet from bundle file using 1-indexed coordinates.

    Fails closed:
    - Unknown file -> ""
    - Out-of-bounds (line_start < 1 or line_end > line_count) -> ""
    - Reversed bounds (line_start > line_end) -> ""
    - Otherwise -> "\\n".join(target_file.get_lines()[line_start - 1 : line_end])
    """
    try:
        target_file = bundle.get_file(file_path)
    except KeyError:
        return ""

    source_lines = target_file.get_lines()
    if line_start < 1 or line_end > len(source_lines) or line_start > line_end:
        return ""

    return "\n".join(source_lines[line_start - 1 : line_end])


def build_enriched_system_assessment_dict(
    assessment: Any,
    bundle: MultiSourceBundle,
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
        f_path = ev.get("file_path")
        l_start = ev.get("line_start")
        l_end = ev.get("line_end")
        if isinstance(f_path, str) and isinstance(l_start, int) and isinstance(l_end, int):
            ev["snippet"] = derive_snippet_from_bundle(f_path, l_start, l_end, bundle)

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            # Check if this dict represents SourceEvidence
            if "file_path" in obj and "line_start" in obj and "line_end" in obj:
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
        "total_bundle_files": len(bundle.files),
        "total_physical_lines": bundle.total_physical_lines,
    }
    return data
