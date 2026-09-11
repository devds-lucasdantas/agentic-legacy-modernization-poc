"""Deterministic JSON Schema exporter for LegacyAssessment (Version 2.2.0)."""

import json
from pathlib import Path
from typing import Any, cast

from agents.legacy_analyzer.schemas.assessment import LegacyAssessment


def get_assessment_json_schema() -> dict[str, Any]:
    """Return the local Pydantic JSON schema dictionary for LegacyAssessment."""
    return LegacyAssessment.model_json_schema()


def get_openai_wire_schema() -> dict[str, Any]:
    """Return the exact OpenAI 3.8.0 transformed wire schema for Structured Outputs."""
    from openai.lib._parsing import type_to_response_format_param

    return cast(dict[str, Any], type_to_response_format_param(LegacyAssessment))


def export_schema_to_file(destination_path: Path | str) -> Path:
    """Export the JSON schema for LegacyAssessment to a file deterministically.

    Args:
        destination_path: Path where the JSON schema will be saved.

    Returns:
        The Path to the saved file.
    """
    dest = Path(destination_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    schema = get_assessment_json_schema()
    dest.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
    return dest


def export_wire_schema_to_file(destination_path: Path | str) -> Path:
    """Export the exact OpenAI 3.8.0 SDK-transformed wire schema to a file deterministically.

    Args:
        destination_path: Path where the wire schema will be saved.

    Returns:
        The Path to the saved file.
    """
    dest = Path(destination_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    wire_schema = get_openai_wire_schema()
    dest.write_text(json.dumps(wire_schema, indent=2, sort_keys=True), encoding="utf-8")
    return dest


if __name__ == "__main__":
    import sys

    out_path = Path("artifacts/assessment-schema.json") if len(sys.argv) < 2 else Path(sys.argv[1])
    saved = export_schema_to_file(out_path)
    print(f"Exported schema to: {saved}")
