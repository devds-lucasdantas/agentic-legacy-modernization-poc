"""Deterministic JSON Schema and OpenAI wire schema exporter for Gate 3 SystemAssessment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from agents.legacy_analyzer.schemas.system_assessment import SystemAssessment


def get_system_assessment_json_schema() -> dict[str, Any]:
    """Return the local Pydantic JSON schema dictionary for SystemAssessment."""
    return SystemAssessment.model_json_schema()


def get_system_responses_text_format() -> dict[str, Any]:
    """Return the exact OpenAI Responses API text.format configuration for SystemAssessment."""
    from openai.lib._parsing import type_to_response_format_param

    chat_format = cast(dict[str, Any], type_to_response_format_param(SystemAssessment))
    js = chat_format["json_schema"]
    return {
        "type": "json_schema",
        "name": js["name"],
        "strict": js.get("strict", True),
        "schema": js["schema"],
    }


def get_system_openai_wire_schema() -> dict[str, Any]:
    """Return the exact OpenAI Responses API wire schema for Structured Outputs."""
    return get_system_responses_text_format()


def export_system_schema_to_file(destination_path: Path | str) -> Path:
    """Export the JSON schema for SystemAssessment to a file deterministically."""
    dest = Path(destination_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    schema = get_system_assessment_json_schema()
    dest.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
    return dest


def export_system_wire_schema_to_file(destination_path: Path | str) -> Path:
    """Export the OpenAI wire schema to a file deterministically."""
    dest = Path(destination_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    wire_schema = get_system_openai_wire_schema()
    dest.write_text(json.dumps(wire_schema, indent=2, sort_keys=True), encoding="utf-8")
    return dest
