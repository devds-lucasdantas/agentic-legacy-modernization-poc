"""Deterministic Evaluator for Gate 2 V2 COBOL Reader assessments.

Decouples:
1. Precision / Support:
   - Measures how many of the model's unique predicted facts are actually supported
     by BANK-MAIN.CBL according to the SourceSupportOracle with valid claim-specific evidence.
   - Evaluates: supported_predicted_count / unique_predicted_count.
   - Zero denominator policy: returns 0.0 if unique_predicted_count == 0.
2. Recall / Coverage:
   - Measures how many manually curated golden expected facts were identified.
   - Strict 1-to-1 matching: one prediction cannot satisfy multiple expected facts;
     one expected fact cannot be matched twice.
   - Evaluates: matched_expected_count / expected_fact_count.
3. Soundness & Invariants:
   - Duplicate prediction detection (must be 0 for PASS).
   - Contradiction detection across identity keys (must be 0 for PASS).
   - Unsupported prediction count (must be 0 for PASS on this deterministic fixture).
   - Claim-specific evidence validation with support span bounding.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agents.legacy_analyzer.schemas.assessment import LegacyAssessment
from src.cobol.atomic_facts import (
    AtomicFact,
    PredictedFact,
    normalize_token,
)
from src.cobol.oracle import SourceSupportOracle
from src.cobol.source_reader import prepare_source
from src.validation.evidence_validator import (
    validate_claim_evidence,
)


@dataclass
class ExpectedFactMatch:
    """Result of matching a golden expected fact against predictions."""

    fact_id: str
    description: str
    expected_fact: dict[str, Any]
    matched: bool
    matched_prediction: dict[str, Any] | None = None
    evidence_valid: bool = True
    notes: str | None = None


@dataclass
class EvaluationReportV2:
    """Complete evaluation report for Gate 2 V2."""

    evaluator_version: str = "2.0.0"
    golden_dataset_version: str = "2.0.0"

    schema_valid: bool = True
    source_sha256_match: bool = True
    evidence_valid: bool = True
    invalid_evidence_count: int = 0

    # Prediction metrics
    raw_predicted_count: int = 0
    unique_predicted_count: int = 0
    duplicate_prediction_count: int = 0
    supported_predicted_count: int = 0
    unsupported_predicted_count: int = 0
    contradiction_count: int = 0

    # Recall metrics
    expected_fact_count: int = 0
    matched_expected_count: int = 0
    missing_expected_count: int = 0

    # High-level scores
    precision: float = 0.0
    recall: float = 0.0
    gate_2_pass: bool = False

    # Detailed listings
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    unsupported_predictions: list[dict[str, Any]] = field(default_factory=list)
    invalid_evidences: list[dict[str, Any]] = field(default_factory=list)
    matched_expected_facts: list[ExpectedFactMatch] = field(default_factory=list)
    missing_expected_facts: list[ExpectedFactMatch] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to serializable dictionary."""
        return asdict(self)


def load_golden_dataset_v2(path: Path | str | None = None) -> dict[str, Any]:
    """Load the Gate 2 V2 golden dataset."""
    if path is None:
        path = (
            Path(__file__).resolve().parent.parent.parent
            / "evals"
            / "expected"
            / "bank-main-single-v2.json"
        )
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"V2 Golden dataset not found at: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def load_source_lines(
    source_path: str = "legacy/core-banking-system/BANK-MAIN.CBL",
    repo_root: Path | None = None,
) -> list[str]:
    """Load raw source lines of allowlisted file."""
    prep = prepare_source(source_path, repo_root=repo_root)
    return prep.raw_content.splitlines()


def assessment_to_predicted_facts(assessment: LegacyAssessment) -> list[PredictedFact]:
    """Convert a LegacyAssessment instance into a list of PredictedFact items."""
    preds: list[PredictedFact] = []

    # 1. Program Identity
    prog = assessment.program
    preds.append(
        PredictedFact(
            fact=AtomicFact(
                kind="PROGRAM",
                subject=prog.program_id,
                predicate="DECLARES",
                object="PROGRAM-ID",
            ),
            source_file=prog.evidence.source_file,
            line_start=prog.evidence.line_start,
            line_end=prog.evidence.line_end,
            snippet=prog.evidence.snippet,
        )
    )

    # 2. Data Fields
    for df in assessment.data_fields:
        raw_pic = df.picture or ""
        norm_pic = normalize_token(raw_pic.replace("PIC", "").strip()) if raw_pic else "NONE"
        preds.append(
            PredictedFact(
                fact=AtomicFact(
                    kind="DATA_FIELD",
                    subject=df.name,
                    predicate="DECLARES",
                    object="VARIABLE",
                    attributes=(
                        ("level", df.level),
                        ("picture", norm_pic),
                        ("section", df.section or "WORKING-STORAGE"),
                    ),
                ),
                source_file=df.evidence.source_file,
                line_start=df.evidence.line_start,
                line_end=df.evidence.line_end,
                snippet=df.evidence.snippet,
            )
        )

    # 3. Call Dependencies
    for c in assessment.call_dependencies:
        preds.append(
            PredictedFact(
                fact=AtomicFact(
                    kind="CALL",
                    subject="BANK-MAIN",
                    predicate="INVOKES",
                    object=c.target_program,
                ),
                source_file=c.evidence.source_file,
                line_start=c.evidence.line_start,
                line_end=c.evidence.line_end,
                snippet=c.evidence.snippet,
            )
        )

    # 4. Menu Options
    for mo in assessment.menu_options:
        action_type = mo.action_type.upper().strip()
        target = (mo.action_target or "").upper().strip()
        if "CALL" in action_type:
            clean_tgt = target.replace("CALL", "").replace("'", "").replace('"', "").strip()
            action_obj = f"CALL:{clean_tgt}"
        elif "DISPLAY" in action_type:
            clean_tgt = target.replace("DISPLAY", "").replace("'", "").replace('"', "").strip()
            action_obj = f"DISPLAY:{clean_tgt}"
        else:
            action_obj = f"{action_type}:{target}"

        desc_norm = normalize_token(mo.description)
        # Normalize common descriptions for equivalence
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

        preds.append(
            PredictedFact(
                fact=AtomicFact(
                    kind="MENU_OPTION",
                    subject=mo.option_key,
                    predicate="ACTION",
                    object=action_obj,
                    attributes=(("description", desc_norm),),
                ),
                source_file=mo.evidence.source_file,
                line_start=mo.evidence.line_start,
                line_end=mo.evidence.line_end,
                snippet=mo.evidence.snippet,
            )
        )

    # 5. Control Flow
    for cf in assessment.control_flow:
        c_type = cf.construct_type.upper().strip()
        cond = cf.condition_or_target.upper().strip()
        if "PERFORM" in c_type:
            preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="CONTROL_FLOW",
                        subject="PERFORM_UNTIL",
                        predicate="CONDITION",
                        object=cond,
                    ),
                    source_file=cf.evidence.source_file,
                    line_start=cf.evidence.line_start,
                    line_end=cf.evidence.line_end,
                    snippet=cf.evidence.snippet,
                )
            )
        elif "EVALUATE" in c_type:
            eval_subj = "WS-CHOICE" if "WS-CHOICE" in cond else cond
            preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="CONTROL_FLOW",
                        subject="EVALUATE",
                        predicate="DISPATCHES",
                        object=eval_subj,
                    ),
                    source_file=cf.evidence.source_file,
                    line_start=cf.evidence.line_start,
                    line_end=cf.evidence.line_end,
                    snippet=cf.evidence.snippet,
                )
            )
        elif "STOP" in c_type or "STOP" in cond:
            preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="CONTROL_FLOW",
                        subject="STOP_RUN",
                        predicate="TERMINATES",
                        object="STOP RUN",
                    ),
                    source_file=cf.evidence.source_file,
                    line_start=cf.evidence.line_start,
                    line_end=cf.evidence.line_end,
                    snippet=cf.evidence.snippet,
                )
            )
        else:
            preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="CONTROL_FLOW",
                        subject=c_type,
                        predicate="CONDITION",
                        object=cond,
                    ),
                    source_file=cf.evidence.source_file,
                    line_start=cf.evidence.line_start,
                    line_end=cf.evidence.line_end,
                    snippet=cf.evidence.snippet,
                )
            )

    # 6. I/O Operations
    for io_op in assessment.io_operations:
        op_type = io_op.operation_type.upper().strip()
        target = io_op.target_or_content.upper().strip()
        preds.append(
            PredictedFact(
                fact=AtomicFact(
                    kind="IO_OPERATION",
                    subject=op_type,
                    predicate="READS" if op_type == "ACCEPT" else "WRITES",
                    object=target,
                ),
                source_file=io_op.evidence.source_file,
                line_start=io_op.evidence.line_start,
                line_end=io_op.evidence.line_end,
                snippet=io_op.evidence.snippet,
            )
        )

    # 7. Dependency Scan (Explicit Negative COPY Fact)
    if not assessment.copybook_dependencies:
        preds.append(
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
    else:
        for cpy in assessment.copybook_dependencies:
            preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="DEPENDENCY_SCAN",
                        subject="COPY",
                        predicate="DEPENDENCY_FOUND",
                        object=cpy,
                    ),
                    source_file="BANK-MAIN.CBL",
                    line_start=1,
                    line_end=37,
                    snippet=f"COPY {cpy}",
                )
            )

    return preds


def evaluate_assessment_v2(
    assessment: LegacyAssessment,
    golden_data: dict[str, Any] | None = None,
    source_lines: list[str] | None = None,
    expected_sha256: str = "b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028",
    source_sha256_actual: str | None = None,
) -> EvaluationReportV2:
    """Evaluate a LegacyAssessment instance deterministically under Gate 2 V2 rules."""
    if golden_data is None:
        golden_data = load_golden_dataset_v2()
    if source_lines is None:
        source_lines = load_source_lines()

    oracle = SourceSupportOracle(source_lines)
    report = EvaluationReportV2()

    # 1. SHA256 check
    if source_sha256_actual is not None:
        report.source_sha256_match = source_sha256_actual.lower() == expected_sha256.lower()

    # 2. Extract predicted facts
    all_predictions = assessment_to_predicted_facts(assessment)
    report.raw_predicted_count = len(all_predictions)

    # 3. Duplicate Detection
    seen_facts: dict[AtomicFact, PredictedFact] = {}
    duplicates: list[dict[str, Any]] = []
    unique_predictions: list[PredictedFact] = []

    for pred in all_predictions:
        if pred.fact in seen_facts:
            duplicates.append(
                {
                    "fact": pred.fact.to_dict(),
                    "canonical_id": pred.fact.canonical_id,
                    "first_citation": {
                        "line_start": seen_facts[pred.fact].line_start,
                        "line_end": seen_facts[pred.fact].line_end,
                        "snippet": seen_facts[pred.fact].snippet,
                    },
                    "duplicate_citation": {
                        "line_start": pred.line_start,
                        "line_end": pred.line_end,
                        "snippet": pred.snippet,
                    },
                }
            )
        else:
            seen_facts[pred.fact] = pred
            unique_predictions.append(pred)

    report.unique_predicted_count = len(unique_predictions)
    report.duplicate_prediction_count = len(duplicates)
    report.duplicates = duplicates

    # 4. Contradiction Detection
    # Group unique facts by contradiction_key
    contradiction_groups: dict[tuple[str, str], list[PredictedFact]] = {}
    for pred in unique_predictions:
        ckey = pred.fact.contradiction_key
        contradiction_groups.setdefault(ckey, []).append(pred)

    contradictions: list[dict[str, Any]] = []
    for ckey, group in contradiction_groups.items():
        if len(group) > 1:
            # Check if they are semantically conflicting
            # If they share the same key but have different objects/predicates/attributes,
            # that's a contradiction.
            canonical_ids = {p.fact.canonical_id for p in group}
            if len(canonical_ids) > 1:
                contradictions.append(
                    {
                        "contradiction_key": list(ckey),
                        "conflicting_facts": [p.fact.to_dict() for p in group],
                        "details": (
                            f"Multiple contradictory predictions for key {ckey}: "
                            f"{canonical_ids}"
                        ),
                    }
                )

    report.contradiction_count = len(contradictions)
    report.contradictions = contradictions

    # 5. Support & Evidence Evaluation on Unique Predicted Facts
    supported_preds: list[PredictedFact] = []
    unsupported_preds: list[dict[str, Any]] = []
    invalid_evidences: list[dict[str, Any]] = []

    for pred in unique_predictions:
        supported_oracle_entry = oracle.get_supported_fact(pred.fact)
        if supported_oracle_entry is None:
            unsupported_preds.append(
                {
                    "fact": pred.fact.to_dict(),
                    "canonical_id": pred.fact.canonical_id,
                    "reason": "Not supported by source code statements",
                    "citation": {
                        "line_start": pred.line_start,
                        "line_end": pred.line_end,
                        "snippet": pred.snippet,
                    },
                }
            )
            continue

        # Check claim-specific evidence binding (support span + fragments + lexical)
        # Skip special negative dependency scan snippet check since snippet is a
        # synthetic confirmation
        if pred.fact.kind == "DEPENDENCY_SCAN" and pred.fact.object == "0":
            ev_ok = True
            ev_err = None
        else:
            ev_res = validate_claim_evidence(
                pred,
                supported_oracle_entry,
                source_lines,
                context=pred.fact.canonical_id,
            )
            ev_ok = ev_res.is_valid
            ev_err = ev_res.error_message

        if not ev_ok:
            invalid_evidences.append(
                {
                    "fact": pred.fact.to_dict(),
                    "canonical_id": pred.fact.canonical_id,
                    "error": ev_err,
                    "citation": {
                        "line_start": pred.line_start,
                        "line_end": pred.line_end,
                        "snippet": pred.snippet,
                    },
                }
            )
            unsupported_preds.append(
                {
                    "fact": pred.fact.to_dict(),
                    "canonical_id": pred.fact.canonical_id,
                    "reason": f"Invalid evidence: {ev_err}",
                    "citation": {
                        "line_start": pred.line_start,
                        "line_end": pred.line_end,
                        "snippet": pred.snippet,
                    },
                }
            )
        else:
            supported_preds.append(pred)

    report.supported_predicted_count = len(supported_preds)
    report.unsupported_predicted_count = len(unsupported_preds)
    report.unsupported_predictions = unsupported_preds
    report.invalid_evidence_count = len(invalid_evidences)
    report.invalid_evidences = invalid_evidences
    report.evidence_valid = report.invalid_evidence_count == 0

    # 6. Recall / Expected Coverage (1-to-1 matching against golden expected facts)
    expected_list = golden_data.get("expected_facts", [])
    report.expected_fact_count = len(expected_list)

    matched_facts: list[ExpectedFactMatch] = []
    missing_facts: list[ExpectedFactMatch] = []
    used_predictions: set[AtomicFact] = set()

    for item in expected_list:
        f_id = item["id"]
        f_desc = item["description"]
        exp_dict = item["fact"]

        raw_attrs = exp_dict.get("attributes", {})
        attr_tuple = tuple((k, v) for k, v in raw_attrs.items())
        expected_atomic = AtomicFact(
            kind=exp_dict["kind"],
            subject=exp_dict["subject"],
            predicate=exp_dict["predicate"],
            object=exp_dict["object"],
            attributes=attr_tuple,
        )

        # Look for matching supported prediction that hasn't been claimed yet
        matched_pred = None
        for sp in supported_preds:
            if sp.fact == expected_atomic and sp.fact not in used_predictions:
                matched_pred = sp
                used_predictions.add(sp.fact)
                break

        if matched_pred is not None:
            matched_facts.append(
                ExpectedFactMatch(
                    fact_id=f_id,
                    description=f_desc,
                    expected_fact=expected_atomic.to_dict(),
                    matched=True,
                    matched_prediction={
                        "canonical_id": matched_pred.fact.canonical_id,
                        "line_start": matched_pred.line_start,
                        "line_end": matched_pred.line_end,
                        "snippet": matched_pred.snippet,
                    },
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
                    notes=(
                        "Expected fact not found among supported model "
                        "predictions with valid evidence"
                    ),
                )
            )

    report.matched_expected_count = len(matched_facts)
    report.missing_expected_count = len(missing_facts)
    report.matched_expected_facts = matched_facts
    report.missing_expected_facts = missing_facts

    # 7. Compute Scores
    # Precision over unique predictions:
    if report.unique_predicted_count > 0:
        report.precision = round(
            report.supported_predicted_count / report.unique_predicted_count, 4
        )
    else:
        report.precision = 0.0  # Explicit zero denominator policy

    if report.expected_fact_count > 0:
        report.recall = round(report.matched_expected_count / report.expected_fact_count, 4)
    else:
        report.recall = 0.0

    # 8. PASS Criteria
    report.gate_2_pass = (
        report.schema_valid
        and report.source_sha256_match
        and report.evidence_valid
        and report.invalid_evidence_count == 0
        and report.duplicate_prediction_count == 0
        and report.contradiction_count == 0
        and report.unsupported_predicted_count == 0
        and report.recall >= 0.90
        and report.precision >= 0.95
    )

    return report
