"""Adversarial Regression Test Suite for Gate 2 V2.1.

Verifies that all 23 vulnerabilities identified in the review (R1-R14) and the
5 Required Amendments are deterministically rejected or appropriately scored by Evaluator V2.1.
100% offline — zero Azure calls.
"""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from agents.legacy_analyzer.agent import ReasoningEffort
from agents.legacy_analyzer.schemas.assessment import (
    CallMenuOption,
    DisplayIO,
    DisplayMenuOption,
    LegacyAssessment,
    PerformUntilConstruct,
    SourceEvidence,
)
from agents.legacy_analyzer.schemas.export import get_assessment_json_schema
from evals.fixtures.synthetic_assessments import make_perfect_assessment_v2
from src.cobol.atomic_facts import AtomicFact, PredictedFact
from src.cobol.fact_extractor import SourceFactExtractor
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
            line_start=9,
            line_end=9,
        )
        res = validate_evidence(ev, source_lines)
        assert res.is_valid is False
        assert "blank source lines" in (res.error_message or "")

        # Candidate V2.4 SourceEvidence strictly forbids extra snippet property
        with pytest.raises(ValidationError):
            SourceEvidence(line_start=9, line_end=9, snippet="CALL 'FABRICATED-TARGET'")  # type: ignore[call-arg]

    def test_2_real_snippet_plus_fabricated_appended_text_rejected(self, source_lines):
        # Line 24 is "CALL 'INIT-DB'"
        from agents.legacy_analyzer.schemas.assessment_v1 import SourceEvidence as SourceEvidenceV1

        ev = SourceEvidenceV1(
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
        # In V2.1 discriminated schema, menu_options[0] is CallMenuOption
        assert isinstance(assessment.menu_options[0], CallMenuOption)
        assessment.menu_options[0].target_program = "PAYROLL-PROC"
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
        # In V2.1 discriminated schema, control_flow[0] is PerformUntilConstruct
        assert isinstance(assessment.control_flow[0], PerformUntilConstruct)
        assessment.control_flow[0].condition = "WS-CHOICE = '9'"
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
            cf for cf in assessment.control_flow if cf.construct_type != "EVALUATE"
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
        # Add an extra DisplayIO operation citing line 36 (STOP RUN)
        assessment.io_operations.append(
            DisplayIO(
                operation_type="DISPLAY",
                literal="SECRET-ACCOUNT-RECORD",
                evidence=SourceEvidence(
                    line_start=36,
                    line_end=36,
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
            PerformUntilConstruct(
                construct_type="PERFORM_UNTIL",
                condition="USER-IS-ADMIN = 'Y'",
                evidence=SourceEvidence(
                    line_start=36,
                    line_end=36,
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
        # In Schema V2.1, 'observations' is not a permitted field
        with pytest.raises(ValidationError):
            LegacyAssessment.model_validate(
                {
                    "program": {
                        "program_id": "BANK-MAIN",
                        "evidence": {
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
        # In Schema V2.1, 'unsupported_assumptions' is rejected by extra="forbid"
        with pytest.raises(ValidationError):
            LegacyAssessment.model_validate(
                {
                    "program": {
                        "program_id": "BANK-MAIN",
                        "evidence": {
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
        # Add contradictory option 1 pointing to PAYROLL-PROC
        assessment.menu_options.append(
            CallMenuOption(
                option_key="1",
                action_type="CALL",
                target_program="PAYROLL-PROC",
                evidence=SourceEvidence(
                    line_start=23,
                    line_end=24,
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
            "program": {
                "program_id": "BANK-MAIN",
                "evidence": {
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
            mod.verify_clean_worktree(is_baseline_run=False)

    def test_20_runner_refuses_unknown_git_sha(self, monkeypatch):
        mod = get_run_gate_2_module()

        def fail_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, ["git", "rev-parse", "HEAD"])

        monkeypatch.setattr(subprocess, "run", fail_run)
        with pytest.raises(subprocess.CalledProcessError):
            mod.get_git_commit_sha()

    def test_21_runner_refuses_mismatched_expected_git_sha(self):
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
            "trial-test",
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


class TestAmendmentsRegressions:
    """Explicit tests for the 5 Required Amendments and R1-R14 remediation."""

    def test_amendment_1_discriminated_union_structural_invariants(self):
        """Amendment 1: CALL without target / DISPLAY with CALL target is invalid."""
        # A CALL without target_program must fail validation
        with pytest.raises(ValidationError):
            CallMenuOption.model_validate(
                {
                    "option_key": "1",
                    "action_type": "CALL",
                    "evidence": {
                        "line_start": 23,
                        "line_end": 24,
                        "snippet": "WHEN '1' CALL 'FOO'",
                    },
                }
            )

        # A DISPLAY without literal must fail validation
        with pytest.raises(ValidationError):
            DisplayMenuOption.model_validate(
                {
                    "option_key": "4",
                    "action_type": "DISPLAY",
                    "evidence": {
                        "line_start": 29,
                        "line_end": 30,
                        "snippet": "WHEN '4' DISPLAY 'BYE'",
                    },
                }
            )

        # A CALL passed into DisplayMenuOption must fail validation
        with pytest.raises(ValidationError):
            DisplayMenuOption.model_validate(
                {
                    "option_key": "1",
                    "action_type": "CALL",
                    "literal": "HELLO",
                    "evidence": {"line_start": 23, "line_end": 24, "snippet": "WHEN '1'"},
                }
            )

        # Control flow explicit variants
        with pytest.raises(ValidationError):
            PerformUntilConstruct.model_validate(
                {
                    "construct_type": "PERFORM_UNTIL",
                    "evidence": {"line_start": 17, "line_end": 17, "snippet": "PERFORM"},
                    # missing condition
                }
            )

    def test_amendment_2_parser_fails_closed_on_unrecognized_syntax(self):
        """Amendment 2: Unrecognized syntax fails closed and omits authoritative negative COPY."""
        malformed_cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-FAIL-CLOSED.
       DATA DIVISION.
       PROCEDURE DIVISION.
           COPY +++ MALFORMED SYNTAX @@@
           STOP RUN.
"""
        extractor = SourceFactExtractor(malformed_cobol.splitlines())
        res = extractor.extract()
        assert res.parse_complete is False
        assert res.unsupported_statement_count > 0
        assert any("COPY" in s for s in res.unsupported_statements)

        # Authoritative negative fact must NOT be emitted
        assert not any(
            occ.fact.kind == "DEPENDENCY_SCAN" and occ.fact.predicate == "DEPENDENCY_COUNT"
            for occ in res.occurrences
        )

    def test_amendment_3_baseline_provenance_rejects_dirty_and_env_bypasses(self, monkeypatch):
        """Amendment 3: Baseline runs reject PYTHONPATH, PYTHONHOME, and dirty worktree bypass."""
        mod = get_run_gate_2_module()

        # Reject dirty bypass on baseline
        monkeypatch.setenv("GATE2_ALLOW_DIRTY_WORKTREE", "1")
        with pytest.raises(RuntimeError, match="GATE2_ALLOW_DIRTY_WORKTREE is strictly prohibited"):
            mod.verify_environment_variables(is_baseline_run=True)
        monkeypatch.delenv("GATE2_ALLOW_DIRTY_WORKTREE", raising=False)

        # Reject PYTHONPATH
        monkeypatch.setenv("PYTHONPATH", "/custom/lib")
        with pytest.raises(RuntimeError, match="Disallowed non-empty PYTHONPATH"):
            mod.verify_environment_variables(is_baseline_run=True)
        monkeypatch.delenv("PYTHONPATH", raising=False)

        # Reject PYTHONHOME
        monkeypatch.setenv("PYTHONHOME", "/custom/python")
        with pytest.raises(RuntimeError, match="Disallowed non-empty PYTHONHOME"):
            mod.verify_environment_variables(is_baseline_run=True)
        monkeypatch.delenv("PYTHONHOME", raising=False)

    def test_amendment_4_error_artifacts_allowlist_based(self, tmp_path):
        """Amendment 4: Run-state failure uses allowlist and never leaks raw exceptions."""
        mod = get_run_gate_2_module()

        # Adversarial exception containing sensitive API keys and raw HTTP headers
        adversarial_err = ValueError(
            "Connection failed: Authorization: Bearer sk-proj-SECRETKEY1234567890 "
            "Endpoint: https://my-sensitive-host.azure.com/keys?key=SECRET_TOKEN_999"
        )

        state_file = tmp_path / "run-state.json"
        mod.write_failure_run_state(
            run_state_file=state_file,
            failed_phase="MODEL_INVOCATION",
            exc=adversarial_err,
            git_sha="abcdef1234567890",
        )

        assert state_file.exists()
        state_data = json.loads(state_file.read_text(encoding="utf-8"))

        # Verify only allowlisted fields exist
        allowed_fields = {
            "status",
            "failed_phase",
            "error_type",
            "safe_message",
            "timestamp",
            "git_sha",
        }
        assert set(state_data.keys()).issubset(allowed_fields)

        raw_content = state_file.read_text(encoding="utf-8")
        assert "SECRETKEY" not in raw_content
        assert "SECRET_TOKEN" not in raw_content
        assert "Authorization" not in raw_content
        assert "https://" not in raw_content
        assert state_data["error_type"] == "ValueError"
        assert state_data["safe_message"] == "Execution failed during MODEL_INVOCATION: ValueError"

    def test_amendment_5_environment_manifest_exists_and_reconstructable(self):
        """Amendment 5: Exact frozen requirements-lock.txt exists and contains required packages."""
        lock_file = REPO_ROOT / "requirements-lock.txt"
        assert lock_file.exists(), "requirements-lock.txt must exist"
        content = lock_file.read_text(encoding="utf-8")

        required_pkgs = [
            "openai==",
            "azure-ai-projects==",
            "azure-identity==",
            "pydantic==",
            "pydantic-settings==",
        ]
        for pkg in required_pkgs:
            assert pkg in content, f"Required package constraint {pkg} missing from lockfile"

        # Verify hash can be deterministically computed
        lock_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert len(lock_sha) == 64

    def test_r1_multiplicity_contradiction_eliminated(self, golden_v2, source_lines):
        """R1: Multiple distinct CALLs must coexist without triggering contradiction."""
        assessment = make_perfect_assessment_v2()
        # Verify initial assessment has 3 CALL dependencies
        assert len(assessment.call_dependencies) == 3

        report = evaluate_assessment_v2(
            assessment, golden_data=golden_v2, source_lines=source_lines
        )
        assert report.contradiction_count == 0
        assert report.gate_2_pass is True

    def test_r2_evaluator_never_rewrites_predictions(self):
        """R2: Evaluator must never rewrite or modify input prediction models."""
        assessment = make_perfect_assessment_v2()
        orig_dump = assessment.model_dump_json()

        golden = load_golden_dataset_v2()
        source_lines = load_source_lines(repo_root=REPO_ROOT)
        _ = evaluate_assessment_v2(assessment, golden_data=golden, source_lines=source_lines)

        assert assessment.model_dump_json() == orig_dump, "Evaluator mutated input assessment!"
