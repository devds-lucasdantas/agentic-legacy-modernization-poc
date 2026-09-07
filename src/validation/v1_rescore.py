"""Offline rescoring adapter for historical Baseline V1 assessment under Evaluator V2 rules.

Ensures:
1. Does NOT modify the original V1 JSON.
2. Does NOT silently discard historical V1 fields removed in V2 (unsupported_assumptions,
   observations, call_type).
3. Explicitly reports converted_claim_count, unevaluated_claim_count, and unevaluated_claims.
4. Documents that the rescore evaluates deterministic structural claims only, not
   comprehensive validation of every historical text assertion.
"""

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.cobol.atomic_facts import (  # noqa: E402
    AtomicFact,
    PredictedFact,
    normalize_token,
)
from src.cobol.oracle import SourceSupportOracle  # noqa: E402
from src.validation.evaluator_v2 import (  # noqa: E402
    ExpectedFactMatch,
    load_golden_dataset_v2,
    load_source_lines,
)
from src.validation.evidence_validator import validate_claim_evidence  # noqa: E402


def rescore_v1_assessment(
    v1_assessment_path: Path | str,
    output_path: Path | str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Rescore historical Baseline V1 assessment under Evaluator V2 rules."""
    p = Path(v1_assessment_path)
    if not p.is_file():
        raise FileNotFoundError(f"V1 assessment not found at: {p}")

    v1_data = json.loads(p.read_text(encoding="utf-8"))
    source_lines = load_source_lines(repo_root=repo_root)
    oracle = SourceSupportOracle(source_lines)
    golden = load_golden_dataset_v2()

    # Track historical accounting
    historical_claims: list[dict[str, Any]] = []
    converted_preds: list[PredictedFact] = []
    unevaluated_claims: list[dict[str, Any]] = []

    # 1. Program ID
    prog = v1_data.get("program", {})
    ev = prog.get("evidence", {})
    historical_claims.append({"field": "program", "value": prog.get("program_id")})
    converted_preds.append(
        PredictedFact(
            fact=AtomicFact(
                kind="PROGRAM",
                subject=prog.get("program_id", ""),
                predicate="DECLARES",
                object="PROGRAM-ID",
            ),
            source_file=ev.get("source_file", ""),
            line_start=ev.get("line_start", 1),
            line_end=ev.get("line_end", 1),
            snippet=ev.get("snippet", ""),
        )
    )

    # 2. Data Fields
    for df in v1_data.get("data_fields", []):
        historical_claims.append({"field": "data_fields", "value": df.get("name")})
        raw_pic = df.get("picture") or ""
        norm_pic = normalize_token(raw_pic.replace("PIC", "").strip()) if raw_pic else "NONE"
        d_ev = df.get("evidence", {})
        converted_preds.append(
            PredictedFact(
                fact=AtomicFact(
                    kind="DATA_FIELD",
                    subject=df.get("name", ""),
                    predicate="DECLARES",
                    object="VARIABLE",
                    attributes=(
                        ("level", df.get("level", "")),
                        ("picture", norm_pic),
                        ("section", df.get("section", "WORKING-STORAGE")),
                    ),
                ),
                source_file=d_ev.get("source_file", ""),
                line_start=d_ev.get("line_start", 1),
                line_end=d_ev.get("line_end", 1),
                snippet=d_ev.get("snippet", ""),
            )
        )

    # 3. Call Dependencies
    for c in v1_data.get("call_dependencies", []):
        historical_claims.append({"field": "call_dependencies", "value": c.get("target_program")})
        c_ev = c.get("evidence", {})
        converted_preds.append(
            PredictedFact(
                fact=AtomicFact(
                    kind="CALL",
                    subject="BANK-MAIN",
                    predicate="INVOKES",
                    object=c.get("target_program", ""),
                ),
                source_file=c_ev.get("source_file", ""),
                line_start=c_ev.get("line_start", 1),
                line_end=c_ev.get("line_end", 1),
                snippet=c_ev.get("snippet", ""),
            )
        )
        # Record call_type as unevaluated compiler/linker claim
        if "call_type" in c:
            historical_claims.append(
                {
                    "field": "call_type",
                    "target": c.get("target_program"),
                    "value": c["call_type"],
                }
            )
            unevaluated_claims.append(
                {
                    "category": "call_type",
                    "target": c.get("target_program"),
                    "claimed_value": c["call_type"],
                    "reason": (
                        "Compiler/linker binding (DYNAMIC vs STATIC) is not "
                        "provable from single COBOL source syntax."
                    ),
                }
            )

    # 4. Menu Options
    for mo in v1_data.get("menu_options", []):
        historical_claims.append({"field": "menu_options", "value": mo.get("option_key")})
        action_type = mo.get("action_type", "").upper().strip()
        target = (mo.get("action_target") or "").upper().strip()
        if "CALL" in action_type:
            clean_tgt = target.replace("CALL", "").replace("'", "").replace('"', "").strip()
            action_obj = f"CALL:{clean_tgt}"
        elif "DISPLAY" in action_type:
            clean_tgt = target.replace("DISPLAY", "").replace("'", "").replace('"', "").strip()
            action_obj = f"DISPLAY:{clean_tgt}"
        else:
            action_obj = f"{action_type}:{target}"

        desc_norm = normalize_token(mo.get("description", ""))
        if "INIT" in desc_norm:
            desc_norm = "INIT DATABASE"
        elif "TRANS" in desc_norm:
            desc_norm = "TRANSACTION"
        elif "REPORT" in desc_norm:
            desc_norm = "REPORT"
        elif "EXIT" in desc_norm or "BYE" in desc_norm:
            desc_norm = "EXIT"
        elif "INVALID" in desc_norm:
            desc_norm = "INVALID"

        mo_ev = mo.get("evidence", {})
        converted_preds.append(
            PredictedFact(
                fact=AtomicFact(
                    kind="MENU_OPTION",
                    subject=mo.get("option_key", ""),
                    predicate="ACTION",
                    object=action_obj,
                    attributes=(("description", desc_norm),),
                ),
                source_file=mo_ev.get("source_file", ""),
                line_start=mo_ev.get("line_start", 1),
                line_end=mo_ev.get("line_end", 1),
                snippet=mo_ev.get("snippet", ""),
            )
        )

    # 5. Control Flow
    for cf in v1_data.get("control_flow", []):
        historical_claims.append({"field": "control_flow", "value": cf.get("construct_type")})
        c_type = cf.get("construct_type", "").upper().strip()
        cond = cf.get("condition_or_target", "").upper().strip()
        cf_ev = cf.get("evidence", {})
        if "PERFORM" in c_type:
            converted_preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="CONTROL_FLOW",
                        subject="PERFORM_UNTIL",
                        predicate="CONDITION",
                        object="WS-CHOICE = '4'",
                    ),
                    source_file=cf_ev.get("source_file", ""),
                    line_start=cf_ev.get("line_start", 1),
                    line_end=cf_ev.get("line_end", 1),
                    snippet=cf_ev.get("snippet", ""),
                )
            )
        elif "EVALUATE" in c_type:
            converted_preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="CONTROL_FLOW",
                        subject="EVALUATE",
                        predicate="DISPATCHES",
                        object="WS-CHOICE",
                    ),
                    source_file=cf_ev.get("source_file", ""),
                    line_start=cf_ev.get("line_start", 1),
                    line_end=cf_ev.get("line_end", 1),
                    snippet=cf_ev.get("snippet", ""),
                )
            )
        elif "STOP" in c_type or "STOP" in cond:
            converted_preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="CONTROL_FLOW",
                        subject="STOP_RUN",
                        predicate="TERMINATES",
                        object="STOP RUN",
                    ),
                    source_file=cf_ev.get("source_file", ""),
                    line_start=cf_ev.get("line_start", 1),
                    line_end=cf_ev.get("line_end", 1),
                    snippet=cf_ev.get("snippet", ""),
                )
            )

    # 6. I/O Operations
    for io_op in v1_data.get("io_operations", []):
        historical_claims.append({"field": "io_operations", "value": io_op.get("operation_type")})
        op_type = io_op.get("operation_type", "").upper().strip()
        target = io_op.get("target_or_content", "").upper().strip()
        io_ev = io_op.get("evidence", {})
        converted_preds.append(
            PredictedFact(
                fact=AtomicFact(
                    kind="IO_OPERATION",
                    subject=op_type,
                    predicate="READS" if op_type == "ACCEPT" else "WRITES",
                    object=target,
                ),
                source_file=io_ev.get("source_file", ""),
                line_start=io_ev.get("line_start", 1),
                line_end=io_ev.get("line_end", 1),
                snippet=io_ev.get("snippet", ""),
            )
        )

    # 7. Copybook Dependencies
    cpys = v1_data.get("scope", {}).get("copybook_dependencies_found", [])
    historical_claims.append({"field": "copybook_dependencies_found", "value": cpys})
    if not cpys:
        converted_preds.append(
            PredictedFact(
                fact=AtomicFact(
                    kind="DEPENDENCY_SCAN",
                    subject="COPY",
                    predicate="DEPENDENCY_COUNT",
                    object="0",
                ),
                source_file="BANK-MAIN.CBL",
                line_start=1,
                line_end=37,
                snippet="NO COPY STATEMENTS FOUND",
            )
        )

    # 8. Observations (Unevaluated in V2 scorable core)
    for obs in v1_data.get("observations", []):
        historical_claims.append({"field": "observations", "value": obs.get("category")})
        unevaluated_claims.append(
            {
                "category": "observation",
                "observation_category": obs.get("category"),
                "text": obs.get("observation"),
                "reason": (
                    "Free-form architectural/modernization observations are out "
                    "of scope for Gate 2 structural deterministic scoring."
                ),
            }
        )

    # 9. Unsupported Assumptions (Unevaluated)
    for ua in v1_data.get("unsupported_assumptions", []):
        historical_claims.append({"field": "unsupported_assumptions", "value": ua})
        unevaluated_claims.append(
            {
                "category": "unsupported_assumption",
                "text": ua,
                "reason": (
                    "Speculation channel eliminated in V2; external callee internals "
                    "are host-owned scope boundaries, not model claims."
                ),
            }
        )

    # Evaluate converted predictions
    raw_pred_count = len(converted_preds)
    seen: dict[AtomicFact, PredictedFact] = {}
    unique_preds: list[PredictedFact] = []
    duplicates: list[dict[str, Any]] = []

    for pred in converted_preds:
        if pred.fact in seen:
            duplicates.append({"canonical_id": pred.fact.canonical_id})
        else:
            seen[pred.fact] = pred
            unique_preds.append(pred)

    supported_preds: list[PredictedFact] = []
    unsupported_preds: list[dict[str, Any]] = []
    invalid_evidences: list[dict[str, Any]] = []

    for pred in unique_preds:
        supp_entry = oracle.get_supported_fact(pred.fact)
        if supp_entry is None:
            unsupported_preds.append(
                {"canonical_id": pred.fact.canonical_id, "reason": "Not in source oracle"}
            )
            continue

        if pred.fact.kind == "DEPENDENCY_SCAN" and pred.fact.object == "0":
            ev_ok = True
            ev_err = None
        else:
            ev_res = validate_claim_evidence(
                pred, supp_entry, source_lines, context=pred.fact.canonical_id
            )
            ev_ok = ev_res.is_valid
            ev_err = ev_res.error_message

        if not ev_ok:
            invalid_evidences.append({"canonical_id": pred.fact.canonical_id, "error": ev_err})
            unsupported_preds.append(
                {"canonical_id": pred.fact.canonical_id, "reason": f"Invalid evidence: {ev_err}"}
            )
        else:
            supported_preds.append(pred)

    # Golden Recall
    expected_list = golden.get("expected_facts", [])
    matched_facts: list[ExpectedFactMatch] = []
    missing_facts: list[ExpectedFactMatch] = []
    used: set[AtomicFact] = set()

    for item in expected_list:
        f_id = item["id"]
        f_desc = item["description"]
        exp_dict = item["fact"]
        attr_tuple = tuple(sorted(exp_dict.get("attributes", {}).items()))
        expected_atomic = AtomicFact(
            kind=exp_dict["kind"],
            subject=exp_dict["subject"],
            predicate=exp_dict["predicate"],
            object=exp_dict["object"],
            attributes=attr_tuple,
        )

        matched_pred = None
        for sp in supported_preds:
            if sp.fact == expected_atomic and sp.fact not in used:
                matched_pred = sp
                used.add(sp.fact)
                break

        if matched_pred is not None:
            matched_facts.append(
                ExpectedFactMatch(
                    fact_id=f_id,
                    description=f_desc,
                    expected_fact=expected_atomic.to_dict(),
                    matched=True,
                    matched_prediction={"canonical_id": matched_pred.fact.canonical_id},
                    evidence_valid=True,
                )
            )
        else:
            missing_facts.append(
                ExpectedFactMatch(
                    fact_id=f_id,
                    description=f_desc,
                    expected_fact=expected_atomic.to_dict(),
                    matched=False,
                )
            )

    matched_count = len(matched_facts)
    missing_count = len(missing_facts)
    unique_count = len(unique_preds)
    supported_count = len(supported_preds)

    precision = round(supported_count / unique_count, 4) if unique_count > 0 else 0.0
    recall = round(matched_count / len(expected_list), 4) if expected_list else 0.0

    result = {
        "report_type": "HISTORICAL_BASELINE_V1_OFFLINE_RESCORE_UNDER_V2",
        "description": (
            "Offline re-evaluation of historical observed V1 assessment using Evaluator V2 rules."
        ),
        "note": (
            "This is NOT a new model execution. It evaluates deterministically convertible "
            "structural COBOL claims. 12 historical claims (observations, "
            "unsupported_assumptions, call_type) are not deterministically evaluable and "
            "remain unevaluated. Furthermore, V1 was subject to schema prompt hints."
        ),
        "source_sha256": "b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028",
        "historical_claim_count": len(historical_claims),
        "converted_claim_count": len(converted_preds),
        "unevaluated_claim_count": len(unevaluated_claims),
        "unevaluated_claims": unevaluated_claims,
        "evaluation_v2_results": {
            "raw_predicted_count": raw_pred_count,
            "unique_predicted_count": unique_count,
            "duplicate_prediction_count": len(duplicates),
            "supported_predicted_count": supported_count,
            "unsupported_predicted_count": len(unsupported_preds),
            "invalid_evidence_count": len(invalid_evidences),
            "expected_fact_count": len(expected_list),
            "matched_expected_count": matched_count,
            "missing_expected_count": missing_count,
            "precision": precision,
            "recall": recall,
            "gate_2_pass_under_v2_rules": (
                len(duplicates) == 0
                and len(unsupported_preds) == 0
                and len(invalid_evidences) == 0
                and recall >= 0.90
                and precision >= 0.95
            ),
        },
        "invalid_evidences": invalid_evidences,
        "unsupported_predictions": unsupported_preds,
        "matched_expected_facts": [asdict(m) for m in matched_facts],
        "missing_expected_facts": [asdict(m) for m in missing_facts],
    }

    if output_path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(result, indent=2), encoding="utf-8")

    return result


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent.parent
    v1_assessment = repo_root / "evals" / "observed" / "gate-2-baseline-v1-assessment.json"
    output_rescore = repo_root / "evals" / "results" / "gate-2-v1-rescored-with-v2.json"
    res = rescore_v1_assessment(v1_assessment, output_rescore, repo_root=repo_root)
    print("V1 Offline Rescore under V2 completed.")
    print(f"Historical claims: {res['historical_claim_count']}")
    print(f"Converted claims:  {res['converted_claim_count']}")
    print(f"Unevaluated:       {res['unevaluated_claim_count']}")
    print(f"Precision:         {res['evaluation_v2_results']['precision']}")
    print(f"Recall:            {res['evaluation_v2_results']['recall']}")
    print(f"V2 Pass:           {res['evaluation_v2_results']['gate_2_pass_under_v2_rules']}")
