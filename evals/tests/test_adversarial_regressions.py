"""Adversarial Regression Test Suite for Gate 2 V2.

Verifies that all 23 vulnerabilities identified in the adversarial review
are deterministically rejected or appropriately scored by Evaluator V2.
100% offline — zero Azure calls.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from agents.legacy_analyzer.agent import ReasoningEffort
from agents.legacy_analyzer.schemas.assessment import (
    ControlFlowConstruct,
    IOOperation,
    LegacyAssessment,
    MenuOption,
    SourceEvidence,
)
from agents.legacy_analyzer.schemas.export import get_assessment_json_schema
from evals.fixtures.synthetic_assessments import make_perfect_assessment_v2
from src.cobol.atomic_facts import AtomicFact, PredictedFact
from src.cobol.oracle import SourceSupportOracle
from src.validation.evaluator_v2 import (
    evaluate_assessment_v2,
    load_golden_dataset_v2,
    load_source_lines,
)
from src.validation.evidence_validator import (
    validate_claim_evidence,
    validate_evidence,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def get_run_gate_2_module():
    spec = importlib.util.spec_from_file_location(
        "run_gate_2_module", REPO_ROOT / "scripts" / "run-gate-2.py"
    )
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    raise ImportError("Failed to load scripts/run-gate-2.py")


@pytest.fixture
def source_lines():
    return load_source_lines(repo_root=REPO_ROOT)


@pytest.fixture
def oracle(source_lines):
    return SourceSupportOracle(source_lines)


@pytest.fixture
def golden_v2():
    return load_golden_dataset_v2()


class TestEvidenceVulnerabilities:
    """Tests 1, 2, 17: Lexical evidence verification hardening."""

    def test_1_fabricated_snippet_on_blank_line_rejected(self, source_lines):
        # Line 9 in BANK-MAIN.CBL is completely blank
        ev = SourceEvidence(
            source_file="BANK-MAIN.CBL",
            line_start=9,
            line_end=9,
            snippet="CALL 'FABRICATED-TARGET'",
        )
        res = validate_evidence(ev, source_lines)
        assert res.is_valid is False
        assert "blank source lines" in (res.error_message or "")

    def test_2_real_snippet_plus_fabricated_appended_text_rejected(self, source_lines):
        # Line 24 is "CALL 'INIT-DB'"
        ev = SourceEvidence(
            source_file="BANK-MAIN.CBL",
            line_start=24,
            line_end=24,
            snippet="CALL 'INIT-DB' AND DROP TABLE USERS",
        )
        res = validate_evidence(ev, source_lines)
        assert res.is_valid is False
        assert "does not match actual source" in (res.error_message or "")

    def test_17_unrelated_real_evidence_cannot_support_another_fact(self, source_lines, oracle):
        # Fact is CALL INIT-DB, but evidence cites lines 1..2 (PROGRAM-ID)
        pred = PredictedFact(
            fact=AtomicFact(
                kind="CALL",
                subject="BANK-MAIN",
                predicate="INVOKES",
                object="INIT-DB",
            ),
            source_file="BANK-MAIN.CBL",
            line_start=1,
            line_end=2,
            snippet="PROGRAM-ID. BANK-MAIN.",
        )
        supp = oracle.get_supported_fact(pred.fact)
        assert supp is not None
        res = validate_claim_evidence(pred, supp, source_lines)
        assert res.is_valid is False
        assert "does not overlap" in (res.error_message or "")


class TestFactPrecisionVulnerabilities:
    """Tests 3, 4, 5, 6, 7, 8: Exact attribute matching."""

    def test_3_wrong_ws_choice_level_rejected(self, golden_v2, source_lines):
        assessment = make_perfect_assessment_v2()
        # Change level from 01 to 77
        assessment.data_fields[0].level = "77"
        report = evaluate_assessment_v2(
            assessment, golden_data=golden_v2, source_lines=source_lines
        )

        assert report.unsupported_predicted_count >= 1
        assert any(
            mf.fact_id == "data.ws_choice" and not mf.matched
            for mf in report.missing_expected_facts
        )
        assert report.gate_2_pass is False

    def test_4_wrong_ws_choice_pic_rejected(self, golden_v2, source_lines):
        assessment = make_perfect_assessment_v2()
        # Change PIC from X to 9(12)
        assessment.data_fields[0].picture = "9(12)"
        report = evaluate_assessment_v2(
            assessment, golden_data=golden_v2, source_lines=source_lines
        )

        assert report.unsupported_predicted_count >= 1
        assert any(
            mf.fact_id == "data.ws_choice" and not mf.matched
            for mf in report.missing_expected_facts
        )
        assert report.gate_2_pass is False

    def test_5_wrong_ws_choice_section_rejected(self, golden_v2, source_lines):
        assessment = make_perfect_assessment_v2()
        assessment.data_fields[0].section = "FILE-SECTION"
        report = evaluate_assessment_v2(
            assessment, golden_data=golden_v2, source_lines=source_lines
        )

        assert report.unsupported_predicted_count >= 1
        assert any(
            mf.fact_id == "data.ws_choice" and not mf.matched
            for mf in report.missing_expected_facts
        )
        assert report.gate_2_pass is False

    def test_6_menu_option_1_pointing_to_wrong_target_rejected(self, golden_v2, source_lines):
        assessment = make_perfect_assessment_v2()
        assessment.menu_options[0].action_target = "PAYROLL-PROC"
        report = evaluate_assessment_v2(
            assessment, golden_data=golden_v2, source_lines=source_lines
        )

        assert report.unsupported_predicted_count >= 1
        assert any(
            mf.fact_id == "menu.option_1" and not mf.matched for mf in report.missing_expected_facts
        )
        assert report.gate_2_pass is False

    def test_7_wrong_loop_condition_rejected(self, golden_v2, source_lines):
        assessment = make_perfect_assessment_v2()
        assessment.control_flow[0].condition_or_target = "WS-CHOICE = '9'"
        report = evaluate_assessment_v2(
            assessment, golden_data=golden_v2, source_lines=source_lines
        )

        assert report.unsupported_predicted_count >= 1
        assert any(
            mf.fact_id == "control.perform_loop" and not mf.matched
            for mf in report.missing_expected_facts
        )
        assert report.gate_2_pass is False

    def test_8_missing_evaluate_cannot_be_satisfied_by_perform(self, golden_v2, source_lines):
        assessment = make_perfect_assessment_v2()
        # Remove EVALUATE construct
        assessment.control_flow = [
            cf for cf in assessment.control_flow if "EVALUATE" not in cf.construct_type
        ]
        report = evaluate_assessment_v2(
            assessment, golden_data=golden_v2, source_lines=source_lines
        )

        assert any(
            mf.fact_id == "control.evaluate_choice" and not mf.matched
            for mf in report.missing_expected_facts
        )
        assert report.recall < 1.0


class TestFalsePositiveAccounting:
    """Tests 9, 10, 11, 12, 15: Incomplete FP accounting and escape hatches."""

    def test_9_invented_io_operation_with_valid_evidence_penalized(self, golden_v2, source_lines):
        assessment = make_perfect_assessment_v2()
        # Invent WRITE operation citing line 36 (STOP RUN)
        assessment.io_operations.append(
            IOOperation(
                operation_type="WRITE",
                target_or_content="SECRET-ACCOUNT-RECORD",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=36,
                    line_end=36,
                    snippet="STOP RUN.",
                ),
            )
        )
        report = evaluate_assessment_v2(
            assessment, golden_data=golden_v2, source_lines=source_lines
        )
        assert report.unsupported_predicted_count >= 1
        assert report.precision < 1.0
        assert report.gate_2_pass is False

    def test_10_invented_control_flow_with_valid_evidence_penalized(self, golden_v2, source_lines):
        assessment = make_perfect_assessment_v2()
        assessment.control_flow.append(
            ControlFlowConstruct(
                construct_type="IF",
                condition_or_target="USER-IS-ADMIN",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=36,
                    line_end=36,
                    snippet="STOP RUN.",
                ),
            )
        )
        report = evaluate_assessment_v2(
            assessment, golden_data=golden_v2, source_lines=source_lines
        )
        assert report.unsupported_predicted_count >= 1
        assert report.precision < 1.0
        assert report.gate_2_pass is False

    def test_11_unrestricted_observation_eliminated_from_schema_v2(self):
        # In Schema V2, 'observations' is not a permitted field
        with pytest.raises(ValidationError):
            LegacyAssessment.model_validate(
                {
                    "schema_version": "2.0.0",
                    "program": {
                        "program_id": "BANK-MAIN",
                        "evidence": {
                            "source_file": "BANK-MAIN.CBL",
                            "line_start": 2,
                            "line_end": 2,
                            "snippet": "PROGRAM-ID. BANK-MAIN.",
                        },
                    },
                    "data_fields": [],
                    "call_dependencies": [],
                    "menu_options": [],
                    "control_flow": [],
                    "io_operations": [],
                    "copybook_dependencies": [],
                    "observations": [{"category": "ARCHITECTURE", "observation": "Hallucination"}],
                }
            )

    def test_12_unsupported_assumptions_eliminated_from_schema_v2(self):
        # In Schema V2, 'unsupported_assumptions' is rejected by extra="forbid"
        with pytest.raises(ValidationError):
            LegacyAssessment.model_validate(
                {
                    "schema_version": "2.0.0",
                    "program": {
                        "program_id": "BANK-MAIN",
                        "evidence": {
                            "source_file": "BANK-MAIN.CBL",
                            "line_start": 2,
                            "line_end": 2,
                            "snippet": "PROGRAM-ID. BANK-MAIN.",
                        },
                    },
                    "data_fields": [],
                    "call_dependencies": [],
                    "menu_options": [],
                    "control_flow": [],
                    "io_operations": [],
                    "copybook_dependencies": [],
                    "unsupported_assumptions": ["TRANS-PROC probably performs deposits."],
                }
            )

    def test_15_invented_copybook_penalized(self, golden_v2, source_lines):
        assessment = make_perfect_assessment_v2()
        assessment.copybook_dependencies = ["INVENTED.CPY"]
        report = evaluate_assessment_v2(
            assessment, golden_data=golden_v2, source_lines=source_lines
        )
        assert report.unsupported_predicted_count >= 1
        assert report.gate_2_pass is False


class TestDuplicatesAndContradictions:
    """Tests 13, 14, 16: Duplicate, contradiction, and omission invariants."""

    def test_13_duplicate_supported_prediction_prevents_pass(self, golden_v2, source_lines):
        assessment = make_perfect_assessment_v2()
        # Duplicate the INIT-DB call dependency
        assessment.call_dependencies.append(assessment.call_dependencies[0])
        report = evaluate_assessment_v2(
            assessment, golden_data=golden_v2, source_lines=source_lines
        )

        assert report.raw_predicted_count > report.unique_predicted_count
        assert report.duplicate_prediction_count == 1
        assert len(report.duplicates) == 1
        assert report.gate_2_pass is False

    def test_14_contradictory_prediction_detected_and_penalized(self, golden_v2, source_lines):
        assessment = make_perfect_assessment_v2()
        # Add contradictory option 1
        assessment.menu_options.append(
            MenuOption(
                option_key="1",
                description="Payroll Processing",
                action_type="CALL",
                action_target="PAYROLL-PROC",
                evidence=SourceEvidence(
                    source_file="BANK-MAIN.CBL",
                    line_start=23,
                    line_end=24,
                    snippet="WHEN '1'\n     CALL 'INIT-DB'",
                ),
            )
        )
        report = evaluate_assessment_v2(
            assessment, golden_data=golden_v2, source_lines=source_lines
        )
        assert report.contradiction_count >= 1
        assert report.gate_2_pass is False

    def test_16_omitted_required_copybook_list_fails_validation(self):
        # copybook_dependencies has no default_factory; omitting it must raise ValidationError
        raw = {
            "schema_version": "2.0.0",
            "program": {
                "program_id": "BANK-MAIN",
                "evidence": {
                    "source_file": "BANK-MAIN.CBL",
                    "line_start": 2,
                    "line_end": 2,
                    "snippet": "PROGRAM-ID. BANK-MAIN.",
                },
            },
            "data_fields": [],
            "call_dependencies": [],
            "menu_options": [],
            "control_flow": [],
            "io_operations": [],
            # copybook_dependencies missing
        }
        with pytest.raises(ValidationError):
            LegacyAssessment.model_validate(raw)


class TestRunnerAndEnvironmentHygiene:
    """Tests 18, 19, 20, 21, 22, 23: Runner, git provenance, schema hints, reasoning typing."""

    def test_18_runner_refuses_existing_run_directory(self):
        existing_dir = REPO_ROOT / "artifacts" / "gate-2" / "test-existing-run"
        existing_dir.mkdir(parents=True, exist_ok=True)
        try:
            import os

            env = dict(
                os.environ,
                GATE2_ALLOW_DIRTY_WORKTREE="1",
                FOUNDRY_PROJECT_ENDPOINT="https://test.services.ai.azure.com/api/projects/test",
                FOUNDRY_MODEL="gpt-4o",
            )
            cmd = [
                sys.executable,
                str(REPO_ROOT / "scripts" / "run-gate-2.py"),
                "--run-label",
                "test-existing-run",
                "--dry-run",
            ]
            res = subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True)
            assert res.returncode == 1
            assert "Run directory already exists" in res.stdout
        finally:
            if existing_dir.exists():
                existing_dir.rmdir()

    def test_19_runner_refuses_dirty_worktree(self, monkeypatch):
        mod = get_run_gate_2_module()
        fake_result = subprocess.CompletedProcess(
            args=["git", "status", "--porcelain"],
            returncode=0,
            stdout=" M agents/legacy_analyzer/agent.py\n",
            stderr="",
        )
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: fake_result)
        with pytest.raises(RuntimeError, match="Git working tree is dirty"):
            mod.verify_clean_worktree()

    def test_20_runner_refuses_unknown_git_sha(self, monkeypatch):
        mod = get_run_gate_2_module()

        def fail_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, ["git", "rev-parse", "HEAD"])

        monkeypatch.setattr(subprocess, "run", fail_run)
        with pytest.raises(subprocess.CalledProcessError):
            mod.get_git_commit_sha()

    def test_21_runner_refuses_mismatched_expected_git_sha(self):
        import os

        env = dict(
            os.environ,
            GATE2_ALLOW_DIRTY_WORKTREE="1",
            FOUNDRY_PROJECT_ENDPOINT="https://test.services.ai.azure.com/api/projects/test",
            FOUNDRY_MODEL="gpt-4o",
        )
        cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run-gate-2.py"),
            "--run-label",
            "baseline-v2-test",
            "--expected-git-sha",
            "0000000000000000000000000000000000000000",
            "--dry-run",
        ]
        res = subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True)
        assert res.returncode == 1
        assert "HEAD SHA mismatch" in res.stdout

    def test_22_schema_and_prompt_contain_no_bank_main_specific_hints(self):
        schema_json = get_assessment_json_schema()
        schema_str = str(schema_json)
        prompt_path = REPO_ROOT / "agents" / "legacy_analyzer" / "prompts" / "system.md"
        prompt_str = prompt_path.read_text(encoding="utf-8")

        forbidden_tokens = ["INIT-DB", "TRANS-PROC", "REPORT-GEN", "WS-CHOICE"]
        for tok in forbidden_tokens:
            assert tok not in schema_str, f"Token '{tok}' leaked in Schema V2 JSON descriptions!"
            assert tok not in prompt_str, f"Token '{tok}' leaked in System Prompt V2!"

    def test_23_reasoning_effort_matches_installed_sdk_typing(self):
        valid_efforts = get_args(ReasoningEffort)
        assert set(valid_efforts) == {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
