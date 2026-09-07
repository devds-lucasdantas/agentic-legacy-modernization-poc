"""Deterministic static analysis extractor for COBOL sources.

Provides an independent ground-truth baseline mechanism using regex and syntax pattern
matching to verify against model predictions.
"""

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StaticExtractedFacts:
    """Facts extracted deterministically from COBOL source text."""

    program_id: str | None
    call_targets: list[str] = field(default_factory=list)
    copy_statements: list[str] = field(default_factory=list)
    stop_run_lines: list[int] = field(default_factory=list)
    accept_statements: list[dict[str, Any]] = field(default_factory=list)
    perform_loops: list[dict[str, Any]] = field(default_factory=list)
    evaluate_branches: list[dict[str, Any]] = field(default_factory=list)
    working_storage_fields: list[dict[str, Any]] = field(default_factory=list)


def extract_static_facts(source_text: str) -> StaticExtractedFacts:
    """Extract structural facts from COBOL source text deterministically.

    Args:
        source_text: Raw COBOL source code (without line numbers).

    Returns:
        StaticExtractedFacts dataclass with extracted elements and line references.
    """
    lines = source_text.splitlines()

    # 1. PROGRAM-ID
    program_id = None
    for line in lines:
        m = re.search(r"PROGRAM-ID\.\s+([A-Za-z0-9-]+)\.", line, re.IGNORECASE)
        if m:
            program_id = m.group(1).upper()
            break

    # 2. CALL statements
    call_targets: list[str] = []
    for line in lines:
        m = re.search(r"CALL\s+['\"]([A-Za-z0-9-]+)['\"]", line, re.IGNORECASE)
        if m:
            target = m.group(1).upper()
            if target not in call_targets:
                call_targets.append(target)

    # 3. COPY statements
    copy_statements: list[str] = []
    for line in lines:
        m = re.search(r"^\s*COPY\s+([A-Za-z0-9_.-]+)", line, re.IGNORECASE)
        if m:
            copy_statements.append(m.group(1))

    # 4. STOP RUN line numbers (1-indexed)
    stop_run_lines: list[int] = []
    for idx, line in enumerate(lines, start=1):
        if re.search(r"\bSTOP\s+RUN\b", line, re.IGNORECASE):
            stop_run_lines.append(idx)

    # 5. ACCEPT statements
    accept_statements: list[dict[str, Any]] = []
    for idx, line in enumerate(lines, start=1):
        m = re.search(r"\bACCEPT\s+([A-Za-z0-9-]+)", line, re.IGNORECASE)
        if m:
            accept_statements.append({
                "line": idx,
                "target": m.group(1).upper(),
                "snippet": line.strip(),
            })

    # 6. PERFORM UNTIL loops
    perform_loops: list[dict[str, Any]] = []
    for idx, line in enumerate(lines, start=1):
        m = re.search(r"PERFORM\s+UNTIL\s+(.+)", line, re.IGNORECASE)
        if m:
            perform_loops.append({
                "line": idx,
                "condition": m.group(1).strip(),
                "snippet": line.strip(),
            })

    # 7. EVALUATE branches
    evaluate_branches: list[dict[str, Any]] = []
    for idx, line in enumerate(lines, start=1):
        m_when = re.search(r"WHEN\s+['\"]([^'\"]+)['\"]", line, re.IGNORECASE)
        if m_when:
            evaluate_branches.append({
                "line": idx,
                "condition": m_when.group(1),
                "snippet": line.strip(),
            })
        elif re.search(r"WHEN\s+OTHER\b", line, re.IGNORECASE):
            evaluate_branches.append({
                "line": idx,
                "condition": "OTHER",
                "snippet": line.strip(),
            })

    # 8. WORKING-STORAGE fields
    working_storage_fields: list[dict[str, Any]] = []
    in_ws = False
    for idx, line in enumerate(lines, start=1):
        if re.search(r"WORKING-STORAGE\s+SECTION\.", line, re.IGNORECASE):
            in_ws = True
            continue
        if in_ws and re.search(r"PROCEDURE\s+DIVISION\.", line, re.IGNORECASE):
            in_ws = False
            break
        if in_ws:
            m_field = re.search(
                r"^\s*([0-9]{2})\s+([A-Za-z0-9-]+)\s+(?:PIC\s+([A-Za-z0-9()]+))?",
                line,
                re.IGNORECASE,
            )
            if m_field:
                working_storage_fields.append({
                    "line": idx,
                    "level": m_field.group(1),
                    "name": m_field.group(2).upper(),
                    "picture": m_field.group(3).upper() if m_field.group(3) else None,
                    "snippet": line.strip(),
                })

    return StaticExtractedFacts(
        program_id=program_id,
        call_targets=call_targets,
        copy_statements=copy_statements,
        stop_run_lines=stop_run_lines,
        accept_statements=accept_statements,
        perform_loops=perform_loops,
        evaluate_branches=evaluate_branches,
        working_storage_fields=working_storage_fields,
    )
