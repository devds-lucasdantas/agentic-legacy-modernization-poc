"""Neutral COBOL identifier domain validation for Gate 3 Contract 3.5.3.

Provides canonical predicate and validation helpers importable by both
src/cobol parser admission and Pydantic schemas.
"""

from __future__ import annotations

import re

# Domain regex for canonical COBOL identifiers:
# - already uppercase
# - at least one A-Z letter
# - only A-Z, 0-9, and single internal hyphens
# - no leading or trailing hyphen
# - no consecutive hyphens
# - no whitespace
_CANONICAL_COBOL_ID_PATTERN = re.compile(r"^(?=.*[A-Z])[A-Z0-9]+(?:-[A-Z0-9]+)*$")

# Domain regex for exact numeric literals:
_NUMERIC_LITERAL_PATTERN = re.compile(r"^[+-]?[0-9]+(?:\.[0-9]+)?$")


def is_canonical_cobol_identifier(value: str) -> bool:
    """Return True if value is a canonical COBOL identifier under Contract 3.5.3.

    Requirements:
    - String type
    - Already uppercase
    - Contains at least one A-Z letter
    - A-Z, 0-9, and internal single hyphens only
    - No leading/trailing whitespace
    - No internal whitespace
    - No leading/trailing hyphen
    - No doubled hyphen
    - Reject rather than normalize or strip
    """
    if not isinstance(value, str):
        return False
    if not value or value != value.strip() or value != value.upper():
        return False
    if any(c.isspace() for c in value):
        return False
    return bool(_CANONICAL_COBOL_ID_PATTERN.match(value))


def validate_canonical_cobol_identifier(name: str, value: str) -> str:
    """Validate that a field is a canonical COBOL identifier.

    Raises ValueError on invalid identifier. Never silently transforms or repairs.
    """
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string, got {type(value).__name__}")
    if not is_canonical_cobol_identifier(value):
        raise ValueError(
            f"{name} must be a canonical COBOL identifier matching "
            f"^(?=.*[A-Z])[A-Z0-9]+(?:-[A-Z0-9]+)*$, got '{value}'"
        )
    return value


def is_numeric_literal(value: str) -> bool:
    """Return True if value is an exact numeric literal."""
    if not isinstance(value, str):
        return False
    if not value or value != value.strip():
        return False
    return bool(_NUMERIC_LITERAL_PATTERN.match(value))


def is_computation_operand(value: str) -> bool:
    """Return True if value is a canonical COBOL identifier or an exact numeric literal."""
    return is_canonical_cobol_identifier(value) or is_numeric_literal(value)


def validate_computation_operand(name: str, value: str) -> str:
    """Validate that a field is a canonical COBOL identifier or numeric literal."""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string, got {type(value).__name__}")
    if not is_computation_operand(value):
        raise ValueError(
            f"{name} must be a canonical COBOL identifier or numeric literal, got '{value}'"
        )
    return value
