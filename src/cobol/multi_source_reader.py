"""Multi-source bundle reader and scope validator for Gate 3.

Enforces strict scope isolation: only explicitly allowlisted COBOL system sources
may be read and analyzed.
Computes SHA256 hashes for execution provenance and formats multi-source bundle
for prompt transport with deterministic line numbering.
Supports synthetic overlays for offline testing and counterfactual analysis.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# Allowlisted source files for Gate 3 Core Banking System
ALLOWED_SYSTEM_FILES: dict[str, str] = {
    "legacy/core-banking-system/ACCOUNTS.CPY": (
        "8be563740b435cbe89775659a302dac70362e7aa9de227632326d0d85f3e36bf"
    ),
    "legacy/core-banking-system/ACCOUNTS.DAT": (
        "f1d10d416848db31ef8d33b7735acab6d482ab6d83b28350e16a708fbc353d2d"
    ),
    "legacy/core-banking-system/BANK-MAIN.CBL": (
        "b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028"
    ),
    "legacy/core-banking-system/INIT-DB.CBL": (
        "4732bea13b5ec6ed5dc4b1d63f70d5e69fb76e8f65270da9f365fcc1ed88a4b1"
    ),
    "legacy/core-banking-system/REPORT-GEN.CBL": (
        "568b514089efb24b9d3855e3562601c2da506213c72eb5f5464542acb14c0993"
    ),
    "legacy/core-banking-system/TRANS-PROC.CBL": (
        "2dbb4fe4d0208271ffb1e2c26fe67dfde8b99163ed0046091bee96db8e3c1267"
    ),
}

EXPECTED_TOTAL_PHYSICAL_LINES = 247


class ScopeViolationError(ValueError):
    """Raised when an unauthorized source file is requested or outside allowlist."""

    pass


@dataclass(frozen=True)
class TargetFile:
    """Represents a single verified source file in the legacy bundle."""

    relative_path: str
    file_type: str  # 'PROGRAM', 'COPYBOOK', 'DATA'
    raw_content: str
    numbered_content: str
    sha256: str
    line_count: int

    def get_lines(self) -> list[str]:
        """Return raw lines (splitlines)."""
        return self.raw_content.splitlines()


@dataclass(frozen=True)
class MultiSourceBundle:
    """Represents the complete multi-source legacy banking bundle."""

    files: dict[str, TargetFile]
    total_physical_lines: int
    bundle_sha256: str
    formatted_prompt_payload: str

    def resolve_canonical_file_path(self, path: str) -> str:
        """Resolve a caller-provided path or alias to a unique canonical bundle path.

        Rules:
        - normalize backslashes to "/";
        - strip leading/trailing whitespace;
        - exact repository-relative path -> itself (if present in self.files);
        - if path contains "/" and is not an exact match -> reject with KeyError;
        - pure basename (no directory separators) -> resolve to its unique canonical bundle path;
        - ambiguous basename -> reject with ValueError;
        - unknown path -> reject with KeyError.
        """
        if not path or not isinstance(path, str):
            raise KeyError(f"Invalid path argument: {path!r}")
        norm_path = path.replace("\\", "/").strip()
        if norm_path in self.files:
            return norm_path

        # Frozen contract permits ONLY exact canonical path or pure basename
        if "/" in norm_path:
            raise KeyError(
                f"Path '{path}' contains directory separators "
                "but is not an exact canonical bundle path."
            )

        # Pure basename alias resolution
        matches = [k for k in self.files if Path(k).name == norm_path]
        if len(matches) == 1:
            return matches[0]
        elif len(matches) > 1:
            raise ValueError(
                f"Ambiguous file alias '{path}' matches multiple bundle files: {sorted(matches)}"
            )
        raise KeyError(f"File path '{path}' not found in bundle: {sorted(self.files.keys())}")

    def get_file(self, relative_path: str) -> TargetFile:
        """Retrieve target file by exact relative path or basename."""
        canon_path = self.resolve_canonical_file_path(relative_path)
        return self.files[canon_path]


def format_numbered_source(raw_content: str) -> str:
    """Format raw source code with deterministic 4-digit line numbers (1-indexed)."""
    lines = raw_content.splitlines()
    formatted = [f"{i:04d} | {line}" for i, line in enumerate(lines, start=1)]
    return "\n".join(formatted)


def classify_file_type(relative_path: str) -> str:
    """Classify file type based on extension."""
    norm = relative_path.upper()
    if norm.endswith(".CBL") or norm.endswith(".COB"):
        return "PROGRAM"
    if norm.endswith(".CPY"):
        return "COPYBOOK"
    if norm.endswith(".DAT") or norm.endswith(".TXT"):
        return "DATA"
    return "UNKNOWN"


def read_system_bundle(
    repo_root: Path | None = None,
    overlays: Mapping[str, str] | None = None,
) -> MultiSourceBundle:
    """Read, hash, and format all allowlisted files in the legacy system bundle.

    Args:
        repo_root: Optional repository root path.
        overlays: Optional dict mapping relative paths to synthetic in-memory contents
                  (used for counterfactual mutations and AST testing).

    Returns:
        MultiSourceBundle containing all 6 files and prompt payload.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent.parent

    bundle_files: dict[str, TargetFile] = {}
    combined_hash = hashlib.sha256()
    prompt_sections: list[str] = []
    total_lines = 0

    for rel_path in sorted(ALLOWED_SYSTEM_FILES.keys()):
        expected_sha = ALLOWED_SYSTEM_FILES[rel_path]
        abs_path = (repo_root / rel_path).resolve()

        if overlays and rel_path in overlays:
            raw_content = overlays[rel_path]
        else:
            if not abs_path.is_file():
                raise FileNotFoundError(f"Allowlisted system file not found on disk: {abs_path}")
            raw_content = abs_path.read_text(encoding="utf-8")

        file_sha = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
        # If not an overlay, verify expected hash
        if not overlays and file_sha != expected_sha:
            raise ValueError(
                f"Hash mismatch for allowlisted file '{rel_path}': "
                f"expected {expected_sha}, got {file_sha}"
            )

        lines = raw_content.splitlines()
        line_count = len(lines)
        total_lines += line_count
        combined_hash.update(f"{rel_path}:{file_sha}:".encode())

        numbered = format_numbered_source(raw_content)
        file_type = classify_file_type(rel_path)

        target_file = TargetFile(
            relative_path=rel_path,
            file_type=file_type,
            raw_content=raw_content,
            numbered_content=numbered,
            sha256=file_sha,
            line_count=line_count,
        )
        bundle_files[rel_path] = target_file

        prompt_sections.append(
            f"=== FILE: {rel_path} ({file_type}, {line_count} lines) ===\n{numbered}\n"
        )

    formatted_payload = "\n".join(prompt_sections)
    bundle_sha = combined_hash.hexdigest()

    return MultiSourceBundle(
        files=bundle_files,
        total_physical_lines=total_lines,
        bundle_sha256=bundle_sha,
        formatted_prompt_payload=formatted_payload,
    )
