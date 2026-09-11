"""Deterministic offline test suite for Gate 2 COBOL Reader.

These tests run completely offline without requiring any Azure credentials or network access.
"""

from pathlib import Path

import pytest

from agents.legacy_analyzer.schemas.assessment import (
    LegacyAssessment as LegacyAssessmentV2,
)
from agents.legacy_analyzer.schemas.assessment_v1 import (
    CallDependency,
    DataField,
    MenuOption,
    SourceEvidence,
)
from agents.legacy_analyzer.schemas.export import get_assessment_json_schema
from evals.fixtures.synthetic_assessments import (
    make_hallucinating_assessment,
    make_perfect_assessment_v2,
)
from evals.fixtures.synthetic_assessments import (
    make_perfect_assessment_v1 as make_perfect_assessment,
)
from src.cobol.source_reader import (
    EXPECTED_BANK_MAIN_SHA256,
    ScopeViolationError,
    format_numbered_source,
    prepare_source,
    validate_source_path,
)
from src.cobol.static_extractor import extract_static_facts
from src.validation.evaluator import (
    evaluate_assessment,
    load_bank_main_lines,
    load_golden_dataset,
)
from src.validation.evidence_validator import validate_evidence

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestScopeAndSourcePreparation:
    """Validate source reader and strict scope boundaries."""

    def test_allowlisted_path_accepted(self):
        resolved = validate_source_path(
            "legacy/core-banking-system/BANK-MAIN.CBL", repo_root=REPO_ROOT
        )
        assert resolved.is_file()
        assert resolved.name == "BANK-MAIN.CBL"

    def test_unauthorized_callee_path_rejected(self):
        with pytest.raises(ScopeViolationError):
            validate_source_path("legacy/core-banking-system/TRANS-PROC.CBL", repo_root=REPO_ROOT)

        with pytest.raises(ScopeViolationError):
            validate_source_path("legacy/core-banking-system/INIT-DB.CBL", repo_root=REPO_ROOT)

        with pytest.raises(ScopeViolationError):
            validate_source_path("legacy/core-banking-system/REPORT-GEN.CBL", repo_root=REPO_ROOT)

        with pytest.raises(ScopeViolationError):
            validate_source_path("legacy/core-banking-system/ACCOUNTS.CPY", repo_root=REPO_ROOT)

    def test_outside_repo_path_rejected(self):
        with pytest.raises(ScopeViolationError):
            validate_source_path("../../etc/passwd", repo_root=REPO_ROOT)

    def test_sha256_provenance_match(self):
        prep = prepare_source("legacy/core-banking-system/BANK-MAIN.CBL", repo_root=REPO_ROOT)
        assert prep.sha256.lower() == EXPECTED_BANK_MAIN_SHA256.lower()
        assert prep.line_count == 36

    def test_deterministic_line_numbering(self):
        raw = "IDENTIFICATION DIVISION.\nPROGRAM-ID. BANK-MAIN."
        numbered = format_numbered_source(raw)
        lines = numbered.splitlines()
        assert lines[0] == "0001 | IDENTIFICATION DIVISION."
        assert lines[1] == "0002 | PROGRAM-ID. BANK-MAIN."


class TestStaticExtractor:
    """Validate deterministic static extraction on BANK-MAIN.CBL."""

    def test_extract_facts_from_bank_main(self):
        prep = prepare_source("legacy/core-banking-system/BANK-MAIN.CBL", repo_root=REPO_ROOT)
        facts = extract_static_facts(prep.raw_content)

        assert facts.program_id == "BANK-MAIN"
        assert facts.call_targets == ["INIT-DB", "TRANS-PROC", "REPORT-GEN"]
        assert len(facts.copy_statements) == 0
        assert 36 in facts.stop_run_lines
        assert len(facts.accept_statements) == 1
        assert facts.accept_statements[0]["target"] == "WS-CHOICE"
        assert len(facts.perform_loops) == 1
        assert "WS-CHOICE = '4'" in facts.perform_loops[0]["condition"]
        assert len(facts.working_storage_fields) == 1
        assert facts.working_storage_fields[0]["name"] == "WS-CHOICE"
        assert facts.working_storage_fields[0]["picture"] == "X"

        conditions = [b["condition"] for b in facts.evaluate_branches]
        assert "1" in conditions
        assert "2" in conditions
        assert "3" in conditions
        assert "4" in conditions
        assert "OTHER" in conditions


class TestPydanticSchema:
    """Validate Pydantic v2 schemas and JSON Schema export."""

    def test_schema_export_properties(self):
        schema = get_assessment_json_schema()
        assert schema.get("title") == "LegacyAssessment"
        props = schema.get("properties", {})
        assert "program" in props
        assert "call_dependencies" in props
        assert "menu_options" in props
        assert "control_flow" in props
        assert "io_operations" in props
        assert "copybook_dependencies" in props

    def test_assessment_roundtrip_serialization(self):
        assessment = make_perfect_assessment_v2()
        json_str = assessment.model_dump_json()
        restored = LegacyAssessmentV2.model_validate_json(json_str)
        assert restored.program.program_id == "BANK-MAIN"
        assert len(restored.call_dependencies) == 3


class TestEvidenceValidation:
    """Validate source evidence verification mechanics."""

    @pytest.fixture
    def source_lines(self):
        return load_bank_main_lines(repo_root=REPO_ROOT)

    def test_correct_evidence(self, source_lines):
        ev = SourceEvidence(
            source_file="BANK-MAIN.CBL",
            line_start=24,
            line_end=24,
            snippet="CALL 'INIT-DB'",
        )
        res = validate_evidence(ev, source_lines)
        assert res.is_valid is True

    def test_wrong_line_number(self, source_lines):
        # Citing line 30 ('DISPLAY Bye.') but claiming snippet is CALL 'INIT-DB'
        ev = SourceEvidence(
            source_file="BANK-MAIN.CBL",
            line_start=30,
            line_end=30,
            snippet="CALL 'INIT-DB'",
        )
        res = validate_evidence(ev, source_lines)
        assert res.is_valid is False
        assert "does not match actual source" in (res.error_message or "")

    def test_wrong_snippet(self, source_lines):
        # Correct line 24, but fabricated snippet
        ev = SourceEvidence(
            source_file="BANK-MAIN.CBL",
            line_start=24,
            line_end=24,
            snippet="CALL 'FABRICATED-TARGET'",
        )
        res = validate_evidence(ev, source_lines)
        assert res.is_valid is False
        assert "does not match" in (res.error_message or "")

    def test_wrong_source_file(self, source_lines):
        ev = SourceEvidence(
            source_file="TRANS-PROC.CBL",
            line_start=24,
            line_end=24,
            snippet="CALL 'INIT-DB'",
        )
        res = validate_evidence(ev, source_lines)
        assert res.is_valid is False
        assert "outside file" in (res.error_message or "")

    def test_out_of_range_lines(self, source_lines):
        ev_high = SourceEvidence(
            source_file="BANK-MAIN.CBL",
            line_start=99,
            line_end=100,
            snippet="STOP RUN.",
        )
        assert validate_evidence(ev_high, source_lines).is_valid is False

        ev_inverted = SourceEvidence(
            source_file="BANK-MAIN.CBL",
            line_start=20,
            line_end=10,
            snippet="ACCEPT WS-CHOICE",
        )
        assert validate_evidence(ev_inverted, source_lines).is_valid is False

    def test_evaluator_rejects_fact_with_invalid_evidence(self):
        golden = load_golden_dataset(REPO_ROOT / "evals" / "expected" / "bank-main-single.json")
        assessment = make_perfect_assessment()
        # Corrupt evidence for INIT-DB: cite wrong snippet
        assessment.call_dependencies[0].evidence = SourceEvidence(
            source_file="BANK-MAIN.CBL",
            line_start=24,
            line_end=24,
            snippet="WRONG SNIPPET CONTENT",
        )
        report = evaluate_assessment(assessment, golden_data=golden)

        assert report.evidence_valid is False
        assert report.invalid_evidence_count == 1
        # INIT-DB should NOT match because evidence is invalid
        assert any(mf.fact_id == "call.init_db" and not mf.matched for mf in report.missing_facts)
        assert report.gate_2_pass is False


class TestGoldenDatasetAndEvaluator:
    """Validate evaluator behavior against golden dataset and false-positive accounting."""

    def test_load_golden_dataset(self):
        golden = load_golden_dataset(REPO_ROOT / "evals" / "expected" / "bank-main-single.json")
        assert golden.get("dataset_version") == "1.0.0"
        assert len(golden.get("facts", [])) == 15
        assert len(golden.get("prohibited_facts", [])) == 6

    def test_evaluator_on_perfect_assessment(self):
        golden = load_golden_dataset(REPO_ROOT / "evals" / "expected" / "bank-main-single.json")
        assessment = make_perfect_assessment()
        report = evaluate_assessment(assessment, golden_data=golden)

        assert report.schema_valid is True
        assert report.scope_valid is True
        assert report.source_sha256_match is True
        assert report.evidence_valid is True
        assert report.invalid_evidence_count == 0
        assert report.expected_fact_count == 15
        assert report.matched_fact_count == 15
        assert report.missing_fact_count == 0
        assert report.false_positive_count == 0
        assert report.unsupported_fact_count == 0
        assert report.recall == 1.0
        assert report.precision == 1.0
        assert report.gate_2_pass is True

    def test_evaluator_on_missing_call_dependency(self):
        golden = load_golden_dataset(REPO_ROOT / "evals" / "expected" / "bank-main-single.json")
        assessment = make_perfect_assessment()
        # Remove TRANS-PROC call
        assessment.call_dependencies = [
            c for c in assessment.call_dependencies if c.target_program != "TRANS-PROC"
        ]
        report = evaluate_assessment(assessment, golden_data=golden)

        assert report.matched_fact_count == 14
        assert report.missing_fact_count == 1
        assert any(mf.fact_id == "call.trans_proc" for mf in report.missing_facts)
        assert report.recall == round(14 / 15, 4)

    def test_invented_call_target_decreases_precision(self):
        golden = load_golden_dataset(REPO_ROOT / "evals" / "expected" / "bank-main-single.json")
        assessment = make_perfect_assessment()
        assessment.call_dependencies.append(
            CallDependency(
                target_program="FOO",
                call_type="DYNAMIC",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=24,
                    line_end=24,
                    snippet="CALL 'INIT-DB'",
                ),
            )
        )
        report = evaluate_assessment(assessment, golden_data=golden)

        assert report.matched_fact_count == 15
        assert report.false_positive_count >= 1
        assert any("FOO" in uf for uf in report.unsupported_facts)
        assert report.precision < 1.0
        assert report.gate_2_pass is False

    def test_invented_data_field_decreases_precision(self):
        golden = load_golden_dataset(REPO_ROOT / "evals" / "expected" / "bank-main-single.json")
        assessment = make_perfect_assessment()
        assessment.data_fields.append(
            DataField(
                name="WS-INVENTED-FIELD",
                level="01",
                picture="9(5)",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=8,
                    line_end=8,
                    snippet="01 WS-CHOICE PIC X.",
                ),
            )
        )
        report = evaluate_assessment(assessment, golden_data=golden)

        assert report.false_positive_count >= 1
        assert any("WS-INVENTED-FIELD" in uf for uf in report.unsupported_facts)
        assert report.precision < 1.0
        assert report.gate_2_pass is False

    def test_invented_menu_option_decreases_precision(self):
        golden = load_golden_dataset(REPO_ROOT / "evals" / "expected" / "bank-main-single.json")
        assessment = make_perfect_assessment()
        assessment.menu_options.append(
            MenuOption(
                option_key="9",
                description="Invented Admin Menu",
                action_type="CALL",
                action_target="ADMIN-PROC",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=23,
                    line_end=24,
                    snippet="WHEN '1' CALL 'INIT-DB'",
                ),
            )
        )
        report = evaluate_assessment(assessment, golden_data=golden)

        assert report.false_positive_count >= 1
        assert any("9" in uf for uf in report.unsupported_facts)
        assert report.precision < 1.0
        assert report.gate_2_pass is False

    def test_evaluator_on_hallucinating_assessment(self):
        golden = load_golden_dataset(REPO_ROOT / "evals" / "expected" / "bank-main-single.json")
        assessment = make_hallucinating_assessment()
        report = evaluate_assessment(assessment, golden_data=golden)

        assert report.unsupported_fact_count > 0
        assert len(report.violations) >= 2  # matches deposits/withdrawals and cmd /c
        assert report.precision < 1.0
        assert report.gate_2_pass is False

    def test_unsupported_assumptions_does_not_trigger_hallucination(self):
        """Verify explicit unknown statements in unsupported_assumptions
        do NOT generate false positives.
        """
        golden = load_golden_dataset(REPO_ROOT / "evals" / "expected" / "bank-main-single.json")
        assessment = make_perfect_assessment()
        # Include keywords that would match prohibited rules if scanned indiscriminately
        assessment.unsupported_assumptions = [
            "Cannot determine whether TRANS-PROC performs deposits or withdrawal logic.",
            "Cannot determine whether TRANS-PROC executes Windows cmd /c commands.",
            "Cannot verify if INIT-DB creates 3 accounts or seed accounts.",
            "Cannot calculate total bank balance without REPORT-GEN.",
            "Cannot verify if subprograms use STOP RUN.",
            "Cannot determine if ACCOUNTS.CPY is dead code across the repository.",
        ]
        report = evaluate_assessment(assessment, golden_data=golden)

        assert len(report.violations) == 0
        assert report.false_positive_count == 0
        assert report.precision == 1.0
        assert report.gate_2_pass is True

    def test_evaluator_on_scope_breach(self):
        golden = load_golden_dataset(REPO_ROOT / "evals" / "expected" / "bank-main-single.json")
        assessment = make_perfect_assessment()
        assessment.scope.has_external_callees_analyzed = True
        report = evaluate_assessment(assessment, golden_data=golden)

        assert report.scope_valid is False
        assert report.gate_2_pass is False
