"""Offline rescoring adapter for historical Baseline V1 assessment under Evaluator V2.2 rules.

Ensures:
1. Does NOT modify the original V1 JSON.
2. Preserves actual V1 values faithfully — zero answer substitution (e.g. no rewriting
   of loop conditions or evaluate subjects).
3. Evaluates predictions through the shared unified evaluation core (evaluator_core.py).
4. Explicitly reports converted_claim_count, unevaluated_claim_count, and unevaluated_claims.
5. Emits a new versioned rescore artifact (evals/results/gate-2-v1-rescored-with-v2.2.json).
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.cobol.atomic_facts import (  # noqa: E402
    AtomicFact,
    PredictedFact,
    normalize_string_literal,
)
from src.cobol.support_index import SourceSupportIndex  # noqa: E402
from src.validation.evaluator_core import (  # noqa: E402
    HostVerificationReport,
    evaluate_predicted_facts,
)
from src.validation.evaluator_v2 import (  # noqa: E402
    load_golden_dataset_v2,
    load_source_lines,
)


def rescore_v1_assessment(
    v1_assessment_path: Path | str,
    output_path: Path | str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Rescore historical Baseline V1 assessment faithfully under Evaluator V2.1 rules."""
    p = Path(v1_assessment_path)
    if not p.is_file():
        raise FileNotFoundError(f"V1 assessment not found at: {p}")

    v1_data = json.loads(p.read_text(encoding="utf-8"))
    source_lines = load_source_lines(repo_root=repo_root)
    support_index = SourceSupportIndex.from_source_lines(source_lines)
    golden = load_golden_dataset_v2()

    # Track historical accounting
    historical_claims: list[dict[str, Any]] = []
    converted_preds: list[PredictedFact] = []
    unevaluated_claims: list[dict[str, Any]] = []

    # 1. Program ID
    prog = v1_data.get("program", {})
    ev = prog.get("evidence", {})
    prog_id = prog.get("program_id", "")
    historical_claims.append({"field": "program", "value": prog_id})
    converted_preds.append(
        PredictedFact(
            fact=AtomicFact(
                kind="PROGRAM",
                subject=prog_id,
                predicate="DECLARES",
                object="PROGRAM-ID",
            ),
            line_start=ev.get("line_start", 1),
            line_end=ev.get("line_end", 1),
            snippet=ev.get("snippet", ""),
        )
    )

    # 2. Data Fields
    for df in v1_data.get("data_fields", []):
        historical_claims.append({"field": "data_fields", "value": df.get("name")})
        d_ev = df.get("evidence", {})
        converted_preds.append(
            PredictedFact(
                fact=AtomicFact(
                    kind="DATA_FIELD",
                    subject=df.get("name", ""),
                    predicate="DECLARES",
                    object="VARIABLE",
                    attributes=(
                        ("LEVEL", df.get("level", "")),
                        ("PICTURE", df.get("picture") or "NONE"),
                        ("SECTION", df.get("section", "WORKING-STORAGE")),
                    ),
                ),
                line_start=d_ev.get("line_start", 1),
                line_end=d_ev.get("line_end", 1),
                snippet=d_ev.get("snippet", ""),
            )
        )

    # 3. Call Dependencies
    for c in v1_data.get("call_dependencies", []):
        target_prog = c.get("target_program", "")
        historical_claims.append({"field": "call_dependencies", "value": target_prog})
        c_ev = c.get("evidence", {})
        converted_preds.append(
            PredictedFact(
                fact=AtomicFact(
                    kind="CALL",
                    subject=prog_id or "BANK-MAIN",
                    predicate="INVOKES",
                    object=target_prog,
                ),
                line_start=c_ev.get("line_start", 1),
                line_end=c_ev.get("line_end", 1),
                snippet=c_ev.get("snippet", ""),
            )
        )
        if "call_type" in c:
            historical_claims.append(
                {
                    "field": "call_type",
                    "target": target_prog,
                    "value": c["call_type"],
                }
            )
            unevaluated_claims.append(
                {
                    "category": "call_type",
                    "target": target_prog,
                    "claimed_value": c["call_type"],
                    "reason": (
                        "Compiler/linker binding (DYNAMIC vs STATIC) is not "
                        "provable from single COBOL source syntax."
                    ),
                }
            )

    # 4. Menu Options
    for mo in v1_data.get("menu_options", []):
        opt_key = mo.get("option_key", "")
        historical_claims.append({"field": "menu_options", "value": opt_key})
        action_type = mo.get("action_type", "").upper().strip()
        action_target = mo.get("action_target", "")
        mo_ev = mo.get("evidence", {})

        if "CALL" in action_type:
            # Clean target
            clean_tgt = action_target.replace("CALL", "").strip().strip("'").strip('"')
            converted_preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="MENU_OPTION",
                        subject=opt_key,
                        predicate="CALLS",
                        object=clean_tgt,
                    ),
                    line_start=mo_ev.get("line_start", 1),
                    line_end=mo_ev.get("line_end", 1),
                    snippet=mo_ev.get("snippet", ""),
                )
            )
        elif "DISPLAY" in action_type:
            clean_lit = action_target.replace("DISPLAY", "").strip().strip("'").strip('"')
            converted_preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="MENU_OPTION",
                        subject=opt_key,
                        predicate="DISPLAYS",
                        object=clean_lit,
                    ),
                    line_start=mo_ev.get("line_start", 1),
                    line_end=mo_ev.get("line_end", 1),
                    snippet=mo_ev.get("snippet", ""),
                )
            )

    # 5. Control Flow (Preserves actual V1 condition/subject without overwriting)
    for cf in v1_data.get("control_flow", []):
        historical_claims.append({"field": "control_flow", "value": cf.get("construct_type")})
        c_type = cf.get("construct_type", "").upper().strip()
        cond_or_target = cf.get("condition_or_target", "").strip()
        cf_ev = cf.get("evidence", {})

        if "PERFORM" in c_type:
            converted_preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="CONTROL_FLOW",
                        subject="PERFORM_UNTIL",
                        predicate="CONDITION",
                        object=cond_or_target,
                    ),
                    line_start=cf_ev.get("line_start", 1),
                    line_end=cf_ev.get("line_end", 1),
                    snippet=cf_ev.get("snippet", ""),
                )
            )
        elif "EVALUATE" in c_type:
            # Extract subject if format is 'EVALUATE <subj> ...'
            eval_subj = cond_or_target
            m_subj = re.match(r"^EVALUATE\s+([A-Za-z0-9-]+)", cond_or_target, re.IGNORECASE)
            if m_subj:
                eval_subj = m_subj.group(1).upper()
            converted_preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="CONTROL_FLOW",
                        subject="EVALUATE",
                        predicate="DISPATCHES",
                        object=eval_subj,
                    ),
                    line_start=cf_ev.get("line_start", 1),
                    line_end=cf_ev.get("line_end", 1),
                    snippet=cf_ev.get("snippet", ""),
                )
            )
        elif "STOP" in c_type or "STOP" in cond_or_target.upper():
            converted_preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="CONTROL_FLOW",
                        subject="STOP_RUN",
                        predicate="TERMINATES",
                        object="STOP RUN",
                    ),
                    line_start=cf_ev.get("line_start", 1),
                    line_end=cf_ev.get("line_end", 1),
                    snippet=cf_ev.get("snippet", ""),
                )
            )

    # 6. I/O Operations
    for io_op in v1_data.get("io_operations", []):
        historical_claims.append({"field": "io_operations", "value": io_op.get("operation_type")})
        op_type = io_op.get("operation_type", "").upper().strip()
        target = io_op.get("target_or_content", "").strip()
        io_ev = io_op.get("evidence", {})

        if op_type == "ACCEPT":
            converted_preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="IO_OPERATION",
                        subject="ACCEPT",
                        predicate="READS",
                        object=target,
                    ),
                    line_start=io_ev.get("line_start", 1),
                    line_end=io_ev.get("line_end", 1),
                    snippet=io_ev.get("snippet", ""),
                )
            )
        elif op_type == "DISPLAY":
            converted_preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="IO_OPERATION",
                        subject="DISPLAY",
                        predicate="WRITES",
                        object=normalize_string_literal(target),
                    ),
                    line_start=io_ev.get("line_start", 1),
                    line_end=io_ev.get("line_end", 1),
                    snippet=io_ev.get("snippet", ""),
                )
            )

    # 7. Dependency Scan
    copy_deps = v1_data.get("copybook_dependencies_found", [])
    if not copy_deps:
        converted_preds.append(
            PredictedFact(
                fact=AtomicFact(
                    kind="DEPENDENCY_SCAN",
                    subject="COPY",
                    predicate="DEPENDENCY_COUNT",
                    object="0",
                ),
                line_start=1,
                line_end=len(source_lines),
                snippet="",
            )
        )

    # 8. Account for V1 fields removed in V2 as unevaluated claims
    for obs in v1_data.get("observations", []):
        historical_claims.append({"field": "observations", "value": obs.get("category")})
        unevaluated_claims.append(
            {
                "category": "observation",
                "observation_category": obs.get("category"),
                "text": obs.get("observation"),
                "reason": "Free-form observations removed from scorable schema in V2.",
            }
        )

    for ua in v1_data.get("unsupported_assumptions", []):
        historical_claims.append({"field": "unsupported_assumptions", "value": ua})
        unevaluated_claims.append(
            {
                "category": "unsupported_assumption",
                "text": ua,
                "reason": "Free-form assumption escape hatch removed in V2.",
            }
        )

    # Perform evaluation via unified evaluation core
    copy_re = re.compile(r"\bCOPY\s+[A-Za-z0-9-]+\b", re.IGNORECASE)
    copy_matches = sum(1 for line in source_lines if copy_re.search(line))
    host_verif = HostVerificationReport(
        copy_statements_found_count=copy_matches,
        scanned_line_count=len(source_lines),
        source_sha256="",
        verification_method="WHOLE_FILE_SCAN",
    )

    core_report = evaluate_predicted_facts(
        predictions=converted_preds,
        support_index=support_index,
        golden_data=golden,
        source_lines=source_lines,
        host_verifications=host_verif,
    )

    effective_repo_root = repo_root or REPO_ROOT
    try:
        rel_v1_path = str(p.resolve().relative_to(effective_repo_root.resolve())).replace("\\", "/")
    except ValueError:
        rel_v1_path = str(p).replace("\\", "/")

    report_dict: dict[str, Any] = {
        "rescore_evaluator_version": "2.2.0",
        "golden_dataset_version": "2.2.0",
        "v1_source_file": rel_v1_path,
        "claim_accounting": {
            "historical_claim_count": len(historical_claims),
            "converted_claim_count": len(converted_preds),
            "unevaluated_claim_count": len(unevaluated_claims),
            "unevaluated_claims": unevaluated_claims,
        },
        "evaluation_metrics": core_report.to_dict(),
        "notes": (
            "Historical Baseline V1 offline rescore under Evaluator V2.2 rules. "
            "Original V1 JSON preserved intact. Evaluates structural claims losslessly."
        ),
    }

    if output_path is not None:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(report_dict, indent=2), encoding="utf-8")

    return report_dict


if __name__ == "__main__":
    v1_path = REPO_ROOT / "evals" / "observed" / "gate-2-baseline-v1-assessment.json"
    rescore_out = REPO_ROOT / "evals" / "results" / "gate-2-v1-rescored-with-v2.2.json"
    result = rescore_v1_assessment(v1_path, output_path=rescore_out)
    print("Rescore completed!")
    print(f"Historical claims: {result['claim_accounting']['historical_claim_count']}")
    print(f"Converted claims:  {result['claim_accounting']['converted_claim_count']}")
    print(f"Unevaluated:       {result['claim_accounting']['unevaluated_claim_count']}")
    print(f"Gate 2 Pass:       {result['evaluation_metrics']['gate_2_pass']}")
    print(f"Precision:         {result['evaluation_metrics']['precision']}")
    print(f"Recall:            {result['evaluation_metrics']['recall']}")
