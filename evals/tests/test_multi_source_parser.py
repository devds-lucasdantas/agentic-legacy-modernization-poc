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
from src.cobol.system_atomic_facts import ComponentTopologyFact
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
    assert cert.logical_statement_count == 203
    assert cert.parsed_and_scored_count == 106
    assert cert.recognized_but_unscored_count == 97
    assert cert.unsupported_relevant_count == 0
    assert (
        cert.parsed_and_scored_count + cert.recognized_but_unscored_count
        == cert.logical_statement_count
    )
    assert len(cert.certificate_sha256) == 64
    assert (
        cert.certificate_sha256
        == "541d0120455a15b42f562aca539eeb2be02fe21e302ea5ca1b65302b47804d79"
    )


def test_all_54_supported_facts_extracted_across_14_groups():
    """Verify that parser extracts exactly 54 canonical propositions across all 14 groups."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    facts = parser.get_supported_facts()

    assert len(facts) == 54

    categories = {sf.fact.fact_category for sf in facts}
    expected_categories = {
        "ARCHITECTURE",
        "CROSS_PROGRAM_CALL",
        "MENU_DISPATCH",
        "COPYBOOK_INCLUSION",
        "FIELD_LAYOUT",
        "DATA_TRANSFER",
        "RESOURCE_LIFECYCLE",
        "CONTROL_FLOW_LOOP",
        "EVALUATE_BRANCHING",
        "ARITHMETIC_OPERATION",
        "CONDITIONAL_BRANCH",
        "INTERACTIVE_IO",
        "TERMINATION",
        "BEHAVIORAL_RISK",
        "ARCHITECTURAL_RISK",
        "WORKING_STORAGE_STATE",
        "TRANSACTION_PROTOCOL",
    }
    assert categories == expected_categories


def test_system_support_index_exact_verification():
    """Verify that SystemSupportIndex deterministically verifies valid and invalid assertions."""
    bundle = read_system_bundle(repo_root=REPO_ROOT)
    parser = SystemCobolParser(bundle)
    index = SystemSupportIndex(parser.get_supported_facts(), bundle)

    assert index.total_expected_facts == 54

    # Positive test: Root orchestrator proposition
    valid_fact = ComponentTopologyFact(
        fact_category="ARCHITECTURE",
        program_id="BANK-MAIN",
        component_role="ROOT_ORCHESTRATOR",
    )
    is_supp, reason, matched = index.verify_assertion(
        valid_fact,
        file_path="legacy/core-banking-system/BANK-MAIN.CBL",
        line_start=1,
        line_end=2,
    )
    assert is_supp is True
    assert matched is not None
    assert matched.proposition_id == "prop.arch.bank_main"

    # Negative test: Out of bounds line coordinates
    is_supp, reason, matched = index.verify_assertion(
        valid_fact,
        file_path="legacy/core-banking-system/BANK-MAIN.CBL",
        line_start=100,
        line_end=105,
    )
    assert is_supp is False

    # Negative test: Unsupported fact
    fake_fact = ComponentTopologyFact(
        fact_category="ARCHITECTURE",
        program_id="NON-EXISTENT",
        component_role="UNKNOWN",
    )
    is_supp, reason, matched = index.verify_assertion(
        fake_fact,
        file_path="legacy/core-banking-system/BANK-MAIN.CBL",
        line_start=1,
        line_end=2,
    )
    assert is_supp is False


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
