"""Deterministic source reader and scope validator for Gate 2.

Enforces scope isolation: only explicitly allowlisted COBOL sources may be read.
Adds deterministic 1-indexed 4-digit line numbers to source text for model context.
Computes SHA256 for execution provenance without modifying the source file.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

# Strictly allowlisted source files for Gate 2
ALLOWED_SOURCES: set[str] = {
    "legacy/core-banking-system/BANK-MAIN.CBL",
}

EXPECTED_BANK_MAIN_SHA256 = "b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028"


class ScopeViolationError(ValueError):
    """Raised when an unauthorized source file is requested."""

    pass


@dataclass(frozen=True)
class PreparedSource:
    """Prepared source code representation for model analysis."""

    relative_path: str
    absolute_path: Path
    raw_content: str
    numbered_content: str
    sha256: str
    line_count: int


def validate_source_path(requested_path: str | Path, repo_root: Path | None = None) -> Path:
    """Validate that the requested path is within the Gate 2 scope allowlist.

    Args:
        requested_path: Relative or absolute path to the target source file.
        repo_root: Optional repository root path. If not provided, computed from this file.

    Returns:
        The resolved Path to the verified source file.

    Raises:
        ScopeViolationError: If the requested path is not in the allowlist.
        FileNotFoundError: If the allowlisted file does not exist on disk.
    """
    if repo_root is None:
        # Assuming src/cobol/source_reader.py -> repo_root is two levels up from src
        repo_root = Path(__file__).resolve().parent.parent.parent

    target_path = Path(requested_path)
    if not target_path.is_absolute():
        target_path = (repo_root / target_path).resolve()
    else:
        target_path = target_path.resolve()

    try:
        rel_path = target_path.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        raise ScopeViolationError(
            f"Path '{requested_path}' is outside repository root '{repo_root}'"
        ) from None

    if rel_path not in ALLOWED_SOURCES:
        raise ScopeViolationError(
            f"Source '{rel_path}' is not in Gate 2 allowlist: {sorted(ALLOWED_SOURCES)}"
        )

    if not target_path.is_file():
        raise FileNotFoundError(f"Allowlisted file not found on disk: {target_path}")

    return target_path


def format_numbered_source(raw_content: str) -> str:
    """Format raw source code with deterministic 4-digit line numbers (1-indexed).

    Example:
        0001 |        IDENTIFICATION DIVISION.
        0002 |        PROGRAM-ID. BANK-MAIN.
    """
    lines = raw_content.splitlines()
    formatted_lines = [f"{i:04d} | {line}" for i, line in enumerate(lines, start=1)]
    return "\n".join(formatted_lines)


def prepare_source(
    requested_path: str | Path = "legacy/core-banking-system/BANK-MAIN.CBL",
    repo_root: Path | None = None,
) -> PreparedSource:
    """Read, hash, validate, and format the requested source file.

    Does NOT modify the underlying file on disk.
    """
    resolved_path = validate_source_path(requested_path, repo_root=repo_root)

    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent.parent
    rel_path = resolved_path.relative_to(repo_root.resolve()).as_posix()

    raw_content = resolved_path.read_text(encoding="utf-8")
    raw_bytes = resolved_path.read_bytes()
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    numbered_content = format_numbered_source(raw_content)
    lines = raw_content.splitlines()

    return PreparedSource(
        relative_path=rel_path,
        absolute_path=resolved_path,
        raw_content=raw_content,
        numbered_content=numbered_content,
        sha256=sha256,
        line_count=len(lines),
    )
