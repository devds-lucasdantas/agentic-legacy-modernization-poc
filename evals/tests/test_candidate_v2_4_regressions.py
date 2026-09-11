"""Candidate V2.4 Comprehensive Regression Test Suite.

Verifies all 13 planned architectural requirements + 7 additional invariant checks:
1. Model-visible schema contains line_start and line_end only.
2. Raw snippet host-derived from verified source bytes.
3. Exact single-line span produces exact raw source line.
4. Exact multi-line span produces exact raw source lines.
5. Invalid/out-of-range spans fail closed.
6. Reversed spans fail closed.
7. Valid line range not supporting fact remains unsupported.
8. Semantically false fact cannot become supported merely because line span is valid.
9. Historical baseline-v2 assessment can be diagnostic-rescored without altering semantic fields.
10. Official baseline-v2 artifacts remain byte-for-byte unchanged.
11. Golden expected facts remain unchanged (2.2.0).
12. Perfect synthetic assessment remains PASS under new evidence contract.
13. Adversarial false semantic claims remain FAIL.
14. OpenAI wire schema has no "snippet" property anywhere in SourceEvidence.
15. Raw bank-main-assessment serialization has line_start/line_end but no host-derived snippet.
16. Host-enriched evidence is a distinct artifact marked host-derived.
17. Evaluation source citations are deterministically derived from verified raw source.
18. Diagnostic semantic hash identical before/after transport conversion.
20. Candidate V2.4 rejects historical model-generated snippet fields (extra="forbid").
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agents.legacy_analyzer.agent import LegacyAnalyzerAgent
from agents.legacy_analyzer.config import FoundryConfig
from agents.legacy_analyzer.schemas.assessment import (
    LegacyAssessment,
    SourceEvidence,
)
from agents.legacy_analyzer.schemas.export import (
    get_assessment_json_schema,
    get_openai_wire_schema,
)
from evals.fixtures.synthetic_assessments import make_perfect_assessment_v2
from evals.scripts.rescore_baseline_v2_diagnostic import (
    compute_semantic_hash as compute_diagnostic_semantic_hash,
)
from evals.scripts.rescore_baseline_v2_diagnostic import (
    structurally_verify_and_convert_evidence,
)
from src.cobol.atomic_facts import AtomicFact, PredictedFact
from src.cobol.evidence_enricher import (
    build_enriched_assessment_dict,
    derive_snippet_from_source,
)
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


@pytest.fixture
def source_lines() -> list[str]:
    return load_source_lines(repo_root=REPO_ROOT)


@pytest.fixture
def golden_v2() -> dict[str, Any]:
    return load_golden_dataset_v2()


@pytest.fixture
def oracle(source_lines: list[str]) -> SourceSupportOracle:
    return SourceSupportOracle(source_lines)


# 1. Model-visible schema contains line_start and line_end only
def test_01_model_visible_schema_contains_line_start_and_line_end_only():
    fields = set(SourceEvidence.model_fields.keys())
    assert fields == {"line_start", "line_end"}
    assert SourceEvidence.model_config.get("extra") == "forbid"

    local_schema = get_assessment_json_schema()
    defs = local_schema.get("$defs", {})
    source_ev_def = defs.get("SourceEvidence", {})
    props = set(source_ev_def.get("properties", {}).keys())
    assert props == {"line_start", "line_end"}
    assert source_ev_def.get("additionalProperties") is False


# 2. OpenAI wire schema has no snippet property anywhere in SourceEvidence
def test_02_openai_wire_schema_has_no_snippet_anywhere_in_source_evidence():
    wire_schema = get_openai_wire_schema()

    # Locate SourceEvidence definition in $defs
    defs = wire_schema.get("json_schema", {}).get("schema", {}).get("$defs", {})
    assert "SourceEvidence" in defs
    ev_def = defs["SourceEvidence"]
    props = ev_def.get("properties", {})
    assert "snippet" not in props
    assert set(props.keys()) == {"line_start", "line_end"}
    assert ev_def.get("additionalProperties") is False

    # Check that "snippet" is not a property in any object schema across wire definition
    def check_no_snippet_prop(node: Any) -> None:
        if isinstance(node, dict):
            if "properties" in node:
                assert "snippet" not in node["properties"]
            for v in node.values():
                check_no_snippet_prop(v)
        elif isinstance(node, list):
            for item in node:
                check_no_snippet_prop(item)

    check_no_snippet_prop(wire_schema)


# 3. Exact single-line span produces exact raw source line
def test_03_exact_single_line_span_produces_exact_raw_source_line(source_lines: list[str]):
    # Line 2 is PROGRAM-ID. BANK-MAIN.
    snippet = derive_snippet_from_source(2, 2, source_lines)
    assert snippet == source_lines[1]
    assert "PROGRAM-ID. BANK-MAIN." in snippet


# 4. Exact multi-line span produces exact raw source lines
def test_04_exact_multi_line_span_produces_exact_raw_source_lines(source_lines: list[str]):
    # Lines 23..24: WHEN '1' / CALL 'INIT-DB'
    snippet = derive_snippet_from_source(23, 24, source_lines)
    expected = "\n".join(source_lines[22:24])
    assert snippet == expected
    assert "WHEN '1'" in snippet
    assert "CALL 'INIT-DB'" in snippet


# 5. Invalid / out-of-range spans fail closed
def test_05_invalid_out_of_range_spans_fail_closed(source_lines: list[str]):
    assert derive_snippet_from_source(0, 5, source_lines) == ""
    assert derive_snippet_from_source(1, len(source_lines) + 10, source_lines) == ""
    assert derive_snippet_from_source(-5, -1, source_lines) == ""

    ev_out = SourceEvidence(line_start=1, line_end=999)
    res = validate_evidence(ev_out, source_lines)
    assert res.is_valid is False
    assert "out of bounds" in (res.error_message or "").lower()


# 6. Reversed spans fail closed
def test_06_reversed_spans_fail_closed(source_lines: list[str]):
    assert derive_snippet_from_source(24, 23, source_lines) == ""

    ev_rev = SourceEvidence(line_start=24, line_end=23)
    res = validate_evidence(ev_rev, source_lines)
    assert res.is_valid is False
    assert "exceeds" in (res.error_message or "").lower()


# 7. Valid line range not supporting fact remains unsupported
def test_07_valid_line_range_not_supporting_fact_remains_unsupported(
    source_lines: list[str], oracle: SourceSupportOracle
):
    # Fact is CALL INIT-DB, but cited line span is 1..2 (PROGRAM-ID)
    pred = PredictedFact(
        fact=AtomicFact(
            kind="CALL",
            subject="BANK-MAIN",
            predicate="INVOKES",
            object="INIT-DB",
        ),
        line_start=1,
        line_end=2,
        snippet=derive_snippet_from_source(1, 2, source_lines),
    )
    supp = oracle.get_supported_fact(pred.fact)
    assert supp is not None
    res = validate_claim_evidence(pred, supp, source_lines)
    assert res.is_valid is False
    assert "does not overlap" in (res.error_message or "")


# 8. Semantically false fact cannot become supported merely because line span is valid
def test_08_semantically_false_fact_cannot_become_supported_merely_because_line_span_is_valid(
    golden_v2: dict[str, Any], source_lines: list[str]
):
    assessment = make_perfect_assessment_v2()
    # Mutate option 1 to point to nonexistent target with valid span 23..24
    assessment.menu_options[0].target_program = "UNSUPPORTED-TARGET"  # type: ignore[union-attr]

    report = evaluate_assessment_v2(assessment, golden_data=golden_v2, source_lines=source_lines)
    assert report.gate_2_pass is False
    assert report.unsupported_predicted_count >= 1
    assert any(p["fact"]["object"] == "UNSUPPORTED-TARGET" for p in report.unsupported_predictions)


# 9. Historical baseline-v2 assessment can be diagnostic-rescored without altering semantic fields
def test_09_historical_baseline_v2_assessment_can_be_diagnostic_rescored(source_lines: list[str]):
    raw_path = REPO_ROOT / "evals" / "observed" / "baseline-v2" / "bank-main-assessment.json"
    raw_data = json.loads(raw_path.read_text(encoding="utf-8"))

    hash_before = compute_diagnostic_semantic_hash(raw_data)
    converted_data, count = structurally_verify_and_convert_evidence(raw_data, source_lines)
    hash_after = compute_diagnostic_semantic_hash(converted_data)

    assert count == 21
    assert hash_before == hash_after
    assert hash_before == "a2a41674058dbb8a20d962300c276e62ec617aab08f9b5641bc174b0bed74ce3"


# 10. Official baseline-v2 artifacts remain byte-for-byte unchanged
def test_10_official_baseline_v2_artifacts_remain_byte_for_byte_unchanged():
    manifest_path = REPO_ROOT / "evals" / "observed" / "baseline-v2-manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    for item in manifest["artifacts"]:
        fn = item["filename"]
        expected_sha = item["sha256"]
        expected_bytes = item["bytes"]

        # Check in artifacts/gate-2/baseline-v2/
        p1 = REPO_ROOT / "artifacts" / "gate-2" / "baseline-v2" / fn
        assert p1.is_file(), f"Missing original artifact: {p1}"
        raw1 = p1.read_bytes()
        assert len(raw1) == expected_bytes, f"Byte size mismatch on {p1}"
        assert hashlib.sha256(raw1).hexdigest() == expected_sha, f"SHA mismatch on {p1}"

        # Check in evals/observed/baseline-v2/
        p2 = REPO_ROOT / "evals" / "observed" / "baseline-v2" / fn
        assert p2.is_file(), f"Missing preserved artifact: {p2}"
        raw2 = p2.read_bytes()
        assert len(raw2) == expected_bytes, f"Byte size mismatch on {p2}"
        assert hashlib.sha256(raw2).hexdigest() == expected_sha, f"SHA mismatch on {p2}"


# 11. Golden expected facts remain unchanged (2.2.0)
def test_11_golden_expected_facts_remain_unchanged_v2_2_0(golden_v2: dict[str, Any]):
    assert golden_v2["dataset_version"] == "2.2.0"
    facts = golden_v2["expected_facts"]
    assert len(facts) == 15

    # Check key expected facts
    fact_ids = {f["id"] for f in facts}
    assert "program.id" in fact_ids
    assert "data.ws_choice" in fact_ids
    assert "call.init_db" in fact_ids
    assert "call.trans_proc" in fact_ids
    assert "call.report_gen" in fact_ids
    assert "menu.option_1" in fact_ids
    assert "menu.option_2" in fact_ids
    assert "menu.option_3" in fact_ids
    assert "menu.option_4" in fact_ids
    assert "menu.option_other" in fact_ids
    assert "control.perform_loop" in fact_ids
    assert "control.evaluate_choice" in fact_ids
    assert "control.stop_run" in fact_ids
    assert "io.accept_choice" in fact_ids
    assert "dependency.no_copybooks" in fact_ids


# 12. Perfect synthetic assessment remains PASS under new evidence contract
def test_12_perfect_synthetic_assessment_remains_pass_under_v2_4(
    golden_v2: dict[str, Any], source_lines: list[str]
):
    assessment = make_perfect_assessment_v2()
    report = evaluate_assessment_v2(assessment, golden_data=golden_v2, source_lines=source_lines)

    assert report.gate_2_pass is True
    assert report.precision == 1.0
    assert report.recall == 1.0
    assert report.supported_predicted_count == 15
    assert report.unsupported_predicted_count == 0
    assert report.invalid_evidence_count == 0
    assert report.duplicate_prediction_count == 0
    assert report.contradiction_count == 0


# 13. Adversarial false semantic claims remain FAIL
def test_13_adversarial_false_semantic_claims_remain_fail(
    golden_v2: dict[str, Any], source_lines: list[str]
):
    assessment = make_perfect_assessment_v2()
    # Change program identity
    assessment.program.program_id = "MALICIOUS-PROGRAM"

    report = evaluate_assessment_v2(assessment, golden_data=golden_v2, source_lines=source_lines)
    assert report.gate_2_pass is False
    assert report.unsupported_predicted_count >= 1
    assert report.precision < 1.0


# 14. Raw bank-main-assessment serialization has line_start/line_end but no host-derived snippet
def test_14_raw_bank_main_assessment_serialization_has_no_snippet():
    assessment = make_perfect_assessment_v2()
    dumped_json = assessment.model_dump_json(indent=2)
    data = json.loads(dumped_json)

    def verify_no_snippet(node: Any) -> None:
        if isinstance(node, dict):
            if "line_start" in node and "line_end" in node:
                assert "snippet" not in node
                assert set(node.keys()) == {"line_start", "line_end"}
            for v in node.values():
                verify_no_snippet(v)
        elif isinstance(node, list):
            for item in node:
                verify_no_snippet(item)

    verify_no_snippet(data)


# 15. Host-enriched evidence is a distinct artifact marked host-derived
def test_15_host_enriched_evidence_is_distinct_and_marked_host_derived(source_lines: list[str]):
    assessment = make_perfect_assessment_v2()
    enriched = build_enriched_assessment_dict(assessment, source_lines)

    # Output is clearly tagged as host-derived
    assert enriched.get("_host_enrichment", {}).get("status") == "HOST_DERIVED"

    # Enriched output has snippets
    assert "snippet" in enriched["program"]["evidence"]
    assert "PROGRAM-ID. BANK-MAIN." in enriched["program"]["evidence"]["snippet"]

    # Original model assessment was NOT mutated
    assert not hasattr(assessment.program.evidence, "snippet")
    dumped = json.loads(assessment.model_dump_json())
    assert "snippet" not in dumped["program"]["evidence"]


# 16. Evaluation source citations are deterministically derived from verified raw source
def test_16_evaluation_source_citations_derived_from_verified_source(
    golden_v2: dict[str, Any], source_lines: list[str]
):
    assessment = make_perfect_assessment_v2()
    report = evaluate_assessment_v2(assessment, golden_data=golden_v2, source_lines=source_lines)

    for matched in report.matched_expected_facts:
        assert matched.matched_prediction is not None
        cit = matched.matched_prediction["citation"]
        l_start = cit["line_start"]
        l_end = cit["line_end"]
        if matched.fact_id == "dependency.no_copybooks":
            # Negative absence claim has empty snippet by design
            assert cit["snippet"] == ""
        else:
            expected_snippet = derive_snippet_from_source(l_start, l_end, source_lines)
            assert cit["snippet"] == expected_snippet.strip()


# 17. Candidate V2.4 rejects historical model-generated snippet fields
def test_17_candidate_v2_4_rejects_snippet_extra_fields():
    with pytest.raises(ValidationError):
        SourceEvidence(line_start=1, line_end=2, snippet="PROGRAM-ID. BANK-MAIN.")  # type: ignore[call-arg]

    with pytest.raises(ValidationError):
        LegacyAssessment.model_validate(
            {
                "program": {
                    "program_id": "BANK-MAIN",
                    "evidence": {
                        "line_start": 1,
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
            }
        )


# 18. Baseline V3 authorization spec integrity
def test_18_baseline_v3_authorization_spec_integrity():
    spec_path = REPO_ROOT / "evals" / "baselines" / "gate-2-baseline-v3.json"
    assert spec_path.is_file()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    assert spec["spec_version"] == "1.1.0"
    assert spec["run_label"] == "baseline-v3"
    assert spec["schema_version"] == "2.3.0"
    assert spec["prompt_version"] == "gate2-baseline-v2.3"
    assert spec["evaluator_version"] == "2.4.0"
    assert spec["golden_dataset_version"] == "2.2.0"
    expected_sha = "b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028"
    assert spec["source_sha256"] == expected_sha
    assert spec["requested_model"] == "gpt-5-mini"


# 19. Diagnostic rescore committed artifact metrics
def test_19_diagnostic_rescore_committed_artifact_metrics():
    diag_name = "gate-2-baseline-v2-evidence-contract-diagnostic.json"
    diag_path = REPO_ROOT / "evals" / "results" / diag_name
    assert diag_path.is_file()
    diag = json.loads(diag_path.read_text(encoding="utf-8"))

    assert diag["status"] == "NOT_A_BASELINE_RESULT"
    metrics = diag["diagnostic_metrics"]
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["supported_predicted_count"] == 22
    assert metrics["invalid_evidence_count"] == 0
    assert metrics["matched_expected_count"] == 15
    assert diag["converted_evidence_objects_count"] == 21
    assert diag["semantic_hash_identical"] is True


# 20. System prompt instructs line numbers only and no snippets
def test_20_system_prompt_instructs_line_numbers_only_no_snippets():
    cfg = FoundryConfig(
        foundry_project_endpoint="https://example.services.ai.azure.com/api/projects/test-proj",
        foundry_model="gpt-5-mini",
    )
    agent = LegacyAnalyzerAgent(config=cfg)
    prompt = agent.system_prompt

    assert "line_start" in prompt
    assert "line_end" in prompt
    assert "snippet" not in prompt.lower()
