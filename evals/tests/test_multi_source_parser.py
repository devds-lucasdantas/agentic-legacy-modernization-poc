"""Unit and architectural tests for Gate 3 isolated multi-source parser and support index."""

from pathlib import Path

import pytest

from src.cobol.multi_evidence_enricher import (
    build_enriched_system_assessment_dict,
    derive_snippet_from_bundle,
)
from src.cobol.multi_source_reader import (
    ALLOWED_SYSTEM_FILES,
    EXPECTED_TOTAL_PHYSICAL_LINES,
    read_system_bundle,
)
from src.cobol.system_atomic_facts import (
    EvidenceSpan,
    InternalCallResolutionFact,
    ProgramDeclarationFact,
)
from src.cobol.system_cobol_parser import SystemCobolParser
from src.cobol.system_support_index import SystemSupportIndex

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_system_bundle_reader_loads_all_six_files_and_hashes():
    """Verify that multi_source_reader loads all 6 allowlisted files with exact hashes."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    assert len(bundle.files) == 6
    assert bundle.total_physical_lines == EXPECTED_TOTAL_PHYSICAL_LINES
    assert bundle.total_physical_lines == 247

    for rel_path, expected_sha in ALLOWED_SYSTEM_FILES.items():
        tf = bundle.get_file(rel_path)
        assert tf.sha256 == expected_sha
        assert len(tf.get_lines()) == tf.line_count


def test_parser_coverage_certificate_zero_unsupported():
    """Verify that SystemCobolParser produces 100% statement coverage with zero unsupported."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    cert = parser.parse_system()

    assert cert.physical_line_count == 247
    assert cert.blank_line_count == 31
    assert cert.comment_line_count == 1
    assert cert.data_fixture_line_count == 3
    assert cert.logical_statement_count == 207
    assert cert.parsed_and_scored_count == 118
    assert cert.recognized_but_unscored_count == 89
    assert cert.unsupported_relevant_count == 0
    assert (
        cert.parsed_and_scored_count + cert.recognized_but_unscored_count
        == cert.logical_statement_count
    )
    assert len(cert.certificate_sha256) == 64
    assert (
        cert.certificate_sha256
        == "e5900cba53db046c80e0e5f64618b549e894631a0eebfe42f8c502fe0ae948be"
    )


def test_all_approved_concept_facts_extracted():
    """Verify that parser extracts all required approved concepts from AST."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()

    categories = {sf.fact.fact_category for sf in facts}
    expected_categories = {
        "PROGRAM_DECLARATION",
        "CALL_OCCURRENCE",
        "CALL_EDGE",
        "INTERNAL_CALL_RESOLUTION",
        "FILE_BINDING",
        "RECORD_LAYOUT",
        "RECORD_LAYOUT_RELATION",
        "TERMINATION_SITE",
        "CALLER_CONTINUATION_CONSTRAINT",
        "COMMAND_INVOCATION",
        "PLATFORM_DEPENDENCY",
        "OPERATION_SEQUENCE",
        "DATA_TRANSFER_RELATION",
        "RESOURCE_LIFECYCLE",
        "COMPUTATION_DATAFLOW",
        "BEHAVIORAL_RISK",
        "DATA_STATE_COMPARISON",
    }
    assert expected_categories.issubset(categories)


def test_system_support_index_exact_verification():
    """Verify that SystemSupportIndex deterministically verifies valid and invalid assertions."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    index = SystemSupportIndex(
        parser.get_supported_facts(),
        bundle,
        file_status_certificate=parser.file_status_certificate,
    )

    # Positive test: Program declaration
    valid_decl = ProgramDeclarationFact(
        program_id="BANK-MAIN",
    )
    is_supp, reason, matched = index.verify_assertion(
        valid_decl,
        file_path="legacy/core-banking-system/BANK-MAIN.CBL",
        line_start=2,
        line_end=2,
    )
    assert is_supp is True
    assert matched is not None
    assert matched.proposition_id == "prop.program.bank_main"

    # Positive test: Role-bound multi-evidence assertion (InternalCallResolution)
    valid_call_res = InternalCallResolutionFact(
        caller_program="BANK-MAIN",
        callee_program="INIT-DB",
    )
    spans = {
        "call_evidence": EvidenceSpan("legacy/core-banking-system/BANK-MAIN.CBL", 24, 24),
        "target_declaration_evidence": EvidenceSpan("legacy/core-banking-system/INIT-DB.CBL", 2, 2),
    }
    is_supp, reason, matched = index.verify_role_bound_assertion(valid_call_res, spans)
    assert is_supp is True
    assert matched is not None

    # Negative test: Out of bounds line coordinates
    is_supp, reason, matched = index.verify_assertion(
        valid_decl,
        file_path="legacy/core-banking-system/BANK-MAIN.CBL",
        line_start=100,
        line_end=105,
    )
    assert is_supp is False

    # Negative test: Wrong role coordinates
    wrong_spans = {
        "call_evidence": EvidenceSpan("legacy/core-banking-system/BANK-MAIN.CBL", 25, 25),
        "target_declaration_evidence": EvidenceSpan("legacy/core-banking-system/INIT-DB.CBL", 2, 2),
    }
    is_supp, reason, matched = index.verify_role_bound_assertion(valid_call_res, wrong_spans)
    assert is_supp is False

    # Negative test: Unsupported fact
    fake_fact = ProgramDeclarationFact(
        program_id="NON-EXISTENT",
    )
    is_supp, reason, matched = index.verify_assertion(
        fake_fact,
        file_path="legacy/core-banking-system/BANK-MAIN.CBL",
        line_start=2,
        line_end=2,
    )
    assert is_supp is False


def test_zero_fixture_identifiers_in_parser():
    """Verify that SystemCobolParser contains zero hardcoded fixture variable/program names."""
    parser_file = REPO_ROOT / "src" / "cobol" / "system_cobol_parser.py"
    with open(parser_file, encoding="utf-8") as f:
        content = f.read()

    forbidden_identifiers = [
        "BANK-MAIN",
        "INIT-DB",
        "TRANS-PROC",
        "REPORT-GEN",
        "WS-CHOICE",
        "WS-EOF-FLAG",
        "WS-TOTAL-BAL",
        "ACC-BALANCE",
        "WS-TRANS-TYPE",
        "REC-ACC-BALANCE",
    ]
    for ident in forbidden_identifiers:
        # Check non-comment lines
        for line_idx, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert ident not in line, (
                f"Forbidden fixture identifier '{ident}' found at {parser_file}:{line_idx}: {line}"
            )


def test_multi_evidence_enricher_derives_correct_snippets():
    """Verify deterministic source snippet extraction across bundle files."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)

    # In BANK-MAIN.CBL
    snippet = derive_snippet_from_bundle("legacy/core-banking-system/BANK-MAIN.CBL", 1, 2, bundle)
    assert "IDENTIFICATION DIVISION." in snippet
    assert "PROGRAM-ID. BANK-MAIN." in snippet

    # In TRANS-PROC.CBL
    snippet_trans = derive_snippet_from_bundle(
        "legacy/core-banking-system/TRANS-PROC.CBL", 1, 2, bundle
    )
    assert "PROGRAM-ID. TRANS-PROC." in snippet_trans

    # Out-of-bounds fails closed
    assert (
        derive_snippet_from_bundle("legacy/core-banking-system/BANK-MAIN.CBL", 0, 5, bundle) == ""
    )
    assert (
        derive_snippet_from_bundle("legacy/core-banking-system/BANK-MAIN.CBL", 1, 999, bundle) == ""
    )

    # Full structure enrichment
    raw_output = {
        "summary": "Core banking system",
        "evidence": {
            "file_path": "legacy/core-banking-system/INIT-DB.CBL",
            "line_start": 24,
            "line_end": 24,
        },
    }
    enriched = build_enriched_system_assessment_dict(raw_output, bundle)
    assert enriched["_host_enrichment"]["status"] == "HOST_DERIVED"
    assert "OPEN OUTPUT ACCOUNT-FILE." in enriched["evidence"]["snippet"]


def test_scope_isolation_rejects_unauthorized_files():
    """Verify that reading bundle rejects un-allowlisted files."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    with pytest.raises(KeyError):
        bundle.get_file("unauthorized/FILE.CBL")
