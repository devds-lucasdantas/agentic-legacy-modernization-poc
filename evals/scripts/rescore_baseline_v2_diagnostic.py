"""Non-authoritative, structurally verified offline diagnostic rescore for Gate 2 Baseline-V2.

DOES NOT modify official baseline-v2 artifacts.
DOES NOT execute any model calls.
Applies ONLY structural transport-prefix removal (NNNN | ) and evaluates offline
with Evaluator V2.3.
"""

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.legacy_analyzer.schemas.assessment import LegacyAssessment  # noqa: E402
from src.cobol.source_reader import prepare_source  # noqa: E402
from src.validation.evaluator_v2 import (  # noqa: E402
    evaluate_assessment_v2,
    load_golden_dataset_v2,
)


def compute_semantic_hash(data: dict[str, Any]) -> str:
    """Compute deterministic SHA256 of assessment excluding evidence snippet fields."""

    def strip_snippets(obj: Any) -> Any:
        if isinstance(obj, dict):
            new_obj = {}
            for k, v in obj.items():
                if k == "snippet":
                    continue
                new_obj[k] = strip_snippets(v)
            return new_obj
        if isinstance(obj, list):
            return [strip_snippets(item) for item in obj]
        return obj

    stripped = strip_snippets(data)
    canonical_json = json.dumps(stripped, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def structurally_verify_and_convert_evidence(
    raw_data: dict[str, Any],
    source_lines: list[str],
) -> tuple[dict[str, Any], int]:
    """Verify transport format line-by-line and remove exact NNNN | prefixes.

    Invariants enforced:
    1. For every evidence object with snippet:
       - line_start <= line_end
       - snippet line count == (line_end - line_start + 1)
       - each line i starts with exact prefix f"{(line_start + i):04d} | "
    2. Once prefix is removed, line matches corresponding raw source line exactly.
    3. Exactly 21 evidence objects are converted.
    """
    converted_count = 0
    data = copy.deepcopy(raw_data)

    def process_evidence(ev: dict[str, Any], path: str) -> None:
        nonlocal converted_count
        l_start = ev.get("line_start")
        l_end = ev.get("line_end")
        snippet = ev.get("snippet")

        if not isinstance(l_start, int) or not isinstance(l_end, int):
            raise ValueError(f"Evidence at {path} missing valid integer line range")

        if l_start > l_end:
            raise ValueError(f"Evidence at {path} has reversed span: {l_start} > {l_end}")

        if snippet is None:
            return

        span_len = l_end - l_start + 1
        lines = snippet.split("\n")
        if len(lines) != span_len:
            raise ValueError(
                f"Evidence at {path} line count mismatch: expected {span_len} lines for span "
                f"[{l_start}..{l_end}], found {len(lines)} lines in snippet: {snippet!r}"
            )

        stripped_lines: list[str] = []
        for i, line in enumerate(lines):
            expected_line_num = l_start + i
            expected_prefix = f"{expected_line_num:04d} | "
            if not line.startswith(expected_prefix):
                raise ValueError(
                    f"Evidence at {path} line {i} does not start with expected prefix "
                    f"'{expected_prefix}': line was {line!r}"
                )
            stripped_line = line[len(expected_prefix) :]
            actual_source_line = source_lines[expected_line_num - 1]
            if stripped_line != actual_source_line:
                raise ValueError(
                    f"Evidence at {path} line {expected_line_num} does not match raw source:\n"
                    f"  Stripped:   {stripped_line!r}\n"
                    f"  Raw Source: {actual_source_line!r}"
                )
            stripped_lines.append(stripped_line)

        ev["snippet"] = "\n".join(stripped_lines)
        converted_count += 1

    def walk(obj: Any, path: str = "root") -> None:
        if isinstance(obj, dict):
            if "line_start" in obj and "line_end" in obj and "snippet" in obj:
                process_evidence(obj, path)
            for k, v in obj.items():
                walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                walk(item, f"{path}[{i}]")

    walk(data)
    return data, converted_count


def run_diagnostic_rescore() -> dict[str, Any]:
    """Execute the complete offline diagnostic rescore protocol."""
    assessment_path = REPO_ROOT / "evals" / "observed" / "baseline-v2" / "bank-main-assessment.json"
    if not assessment_path.is_file():
        assessment_path = (
            REPO_ROOT / "artifacts" / "gate-2" / "baseline-v2" / "bank-main-assessment.json"
        )
    raw_json = json.loads(assessment_path.read_text(encoding="utf-8"))

    # Load verified source lines
    prep = prepare_source("legacy/core-banking-system/BANK-MAIN.CBL", repo_root=REPO_ROOT)
    source_lines = prep.raw_content.splitlines()

    # Invariant 1: Semantic hash before transformation
    hash_before = compute_semantic_hash(raw_json)

    # Invariant 2: Structural verification and conversion
    transformed_json, converted_count = structurally_verify_and_convert_evidence(
        raw_json, source_lines
    )

    if converted_count != 21:
        raise ValueError(
            f"Expected exactly 21 evidence objects to require conversion, found {converted_count}"
        )

    # Invariant 3: Semantic hash equality after transformation (zero semantic drift)
    hash_after = compute_semantic_hash(transformed_json)
    if hash_before != hash_after:
        raise ValueError(
            f"Semantic hash mismatch before and after diagnostic conversion!\n"
            f"  Before: {hash_before}\n"
            f"  After:  {hash_after}"
        )

    # Validate transformed JSON against Schema V2.2 Pydantic model
    rescored_assessment = LegacyAssessment.model_validate(transformed_json)

    # Run Evaluator V2.3 offline
    golden = load_golden_dataset_v2()
    report = evaluate_assessment_v2(
        rescored_assessment,
        golden_data=golden,
        source_lines=source_lines,
        source_sha256_actual=prep.sha256,
    )

    # Invariant 4: Verify expected diagnostic claims
    assert report.invalid_evidence_count == 0, f"Invalid evidence: {report.invalid_evidence_count}"
    assert report.matched_expected_count == 15, f"Matched expected: {report.matched_expected_count}"
    assert report.missing_expected_count == 0, f"Missing expected: {report.missing_expected_count}"
    assert report.supported_predicted_count == 22, f"Supported: {report.supported_predicted_count}"
    assert report.unsupported_predicted_count == 0, (
        f"Unsupported: {report.unsupported_predicted_count}"
    )
    assert report.precision == 1.0, f"Precision: {report.precision}"
    assert report.recall == 1.0, f"Recall: {report.recall}"
    assert report.gate_2_pass is True, f"Gate 2 Pass: {report.gate_2_pass}"

    official_metrics = {
        "raw_predicted_count": 22,
        "unique_predicted_count": 22,
        "supported_predicted_count": 1,
        "unsupported_predicted_count": 21,
        "invalid_evidence_count": 21,
        "matched_expected_count": 1,
        "missing_expected_count": 14,
        "precision": 0.0455,
        "recall": 0.0667,
        "gate_2_pass": False,
    }

    diagnostic_metrics = {
        "raw_predicted_count": report.raw_predicted_count,
        "unique_predicted_count": report.unique_predicted_count,
        "supported_predicted_count": report.supported_predicted_count,
        "unsupported_predicted_count": report.unsupported_predicted_count,
        "invalid_evidence_count": report.invalid_evidence_count,
        "matched_expected_count": report.matched_expected_count,
        "missing_expected_count": report.missing_expected_count,
        "precision": report.precision,
        "recall": report.recall,
        "gate_2_pass": report.gate_2_pass,
    }

    result_payload = {
        "disclaimer": "NON_AUTHORITATIVE_POST_HOC_DIAGNOSTIC",
        "status": "NOT_A_BASELINE_RESULT",
        "model_call": "NO_MODEL_CALL",
        "target_run_label": "baseline-v2",
        "git_commit_sha": "9390377b410917e3e9c62883346b299b628a0000",
        "target_file": "legacy/core-banking-system/BANK-MAIN.CBL",
        "source_sha256": prep.sha256,
        "semantic_hash_before_conversion": hash_before,
        "semantic_hash_after_conversion": hash_after,
        "semantic_hash_identical": True,
        "converted_evidence_objects_count": converted_count,
        "structural_prefix_verification": "PASSED (all 21 spans verified line-by-line)",
        "exact_raw_source_match_verification": (
            "PASSED (all 21 transformed snippets match source bytes)"
        ),
        "official_baseline_v2_metrics": official_metrics,
        "diagnostic_metrics": diagnostic_metrics,
        "delta": {
            "invalid_evidence": "21 -> 0 (-21)",
            "supported_predictions": "1 -> 22 (+21)",
            "matched_expected_facts": "1/15 -> 15/15 (+14)",
            "precision": "0.0455 -> 1.0 (+0.9545)",
            "recall": "0.0667 -> 1.0 (+0.9333)",
            "gate_2_pass": "False -> True",
        },
        "evaluation_report": report.to_dict(),
    }

    out_file = (
        REPO_ROOT / "evals" / "results" / "gate-2-baseline-v2-evidence-contract-diagnostic.json"
    )
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(result_payload, indent=2), encoding="utf-8")
    print(f"Wrote diagnostic rescore to {out_file}")
    return result_payload


if __name__ == "__main__":
    res = run_diagnostic_rescore()
    print("Structural verification and offline diagnostic rescore completed successfully.")
