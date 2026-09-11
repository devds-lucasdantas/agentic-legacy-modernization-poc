"""Deterministic Evaluator for Gate 2 V2.1 COBOL Reader assessments.

Converts LegacyAssessment (Schema V2.1 with discriminated variants) losslessly
into canonical PredictedFact representations without answer repairing or fuzzy heuristics.
Delegates core metrics calculation to unified evaluator_core.
"""

import json
import re
from pathlib import Path
from typing import Any

from agents.legacy_analyzer.schemas.assessment import (
    AcceptIO,
    CallMenuOption,
    DisplayIO,
    DisplayMenuOption,
    EvaluateConstruct,
    LegacyAssessment,
    PerformUntilConstruct,
    StopRunConstruct,
)
from src.cobol.atomic_facts import AtomicFact, PredictedFact
from src.cobol.evidence_enricher import derive_snippet_from_source
from src.cobol.source_reader import prepare_source
from src.cobol.support_index import SourceSupportIndex
from src.validation.evaluator_core import (
    CoreEvaluationReport,
    HostVerificationReport,
    evaluate_predicted_facts,
)

# Export for backward compatibility
EvaluationReportV2 = CoreEvaluationReport


def load_golden_dataset_v2(path: Path | str | None = None) -> dict[str, Any]:
    """Load the Gate 2 V2.1 golden dataset."""
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


def assessment_to_predicted_facts(
    assessment: LegacyAssessment,
    total_lines: int = 36,
    source_lines: list[str] | None = None,
) -> list[PredictedFact]:
    """Convert a LegacyAssessment instance into a list of PredictedFact items.

    In Candidate V2.4, evidence snippets are host-derived from verified source_lines.
    """
    preds: list[PredictedFact] = []

    def get_snippet(ev: Any) -> str:
        if source_lines is not None:
            return derive_snippet_from_source(ev.line_start, ev.line_end, source_lines)
        return getattr(ev, "snippet", "")

    # 1. Program Identity
    prog = assessment.program
    caller_name = prog.program_id
    preds.append(
        PredictedFact(
            fact=AtomicFact(
                kind="PROGRAM",
                subject=prog.program_id,
                predicate="DECLARES",
                object="PROGRAM-ID",
            ),
            line_start=prog.evidence.line_start,
            line_end=prog.evidence.line_end,
            snippet=get_snippet(prog.evidence),
        )
    )

    # 2. Data Fields
    for df in assessment.data_fields:
        preds.append(
            PredictedFact(
                fact=AtomicFact(
                    kind="DATA_FIELD",
                    subject=df.name,
                    predicate="DECLARES",
                    object="VARIABLE",
                    attributes=(
                        ("LEVEL", df.level),
                        ("PICTURE", df.picture or "NONE"),
                        ("SECTION", df.section),
                    ),
                ),
                line_start=df.evidence.line_start,
                line_end=df.evidence.line_end,
                snippet=get_snippet(df.evidence),
            )
        )

    # 3. Call Dependencies
    for c in assessment.call_dependencies:
        preds.append(
            PredictedFact(
                fact=AtomicFact(
                    kind="CALL",
                    subject=caller_name,
                    predicate="INVOKES",
                    object=c.target_program,
                ),
                line_start=c.evidence.line_start,
                line_end=c.evidence.line_end,
                snippet=get_snippet(c.evidence),
            )
        )

    # 4. Menu Options (Discriminated variants)
    for mo in assessment.menu_options:
        if isinstance(mo, CallMenuOption) or getattr(mo, "action_type", "") == "CALL":
            target = getattr(mo, "target_program", "")
            preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="MENU_OPTION",
                        subject=mo.option_key,
                        predicate="CALLS",
                        object=target,
                    ),
                    line_start=mo.evidence.line_start,
                    line_end=mo.evidence.line_end,
                    snippet=get_snippet(mo.evidence),
                )
            )
        elif isinstance(mo, DisplayMenuOption) or getattr(mo, "action_type", "") == "DISPLAY":
            literal = getattr(mo, "display_literal", "")
            preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="MENU_OPTION",
                        subject=mo.option_key,
                        predicate="DISPLAYS",
                        object=literal,
                    ),
                    line_start=mo.evidence.line_start,
                    line_end=mo.evidence.line_end,
                    snippet=get_snippet(mo.evidence),
                )
            )

    # 5. Control Flow (Discriminated variants)
    for cf in assessment.control_flow:
        if (
            isinstance(cf, PerformUntilConstruct)
            or getattr(cf, "construct_type", "") == "PERFORM_UNTIL"
        ):
            preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="CONTROL_FLOW",
                        subject="PERFORM_UNTIL",
                        predicate="CONDITION",
                        object=getattr(cf, "condition", ""),
                    ),
                    line_start=cf.evidence.line_start,
                    line_end=cf.evidence.line_end,
                    snippet=get_snippet(cf.evidence),
                )
            )
        elif isinstance(cf, EvaluateConstruct) or getattr(cf, "construct_type", "") == "EVALUATE":
            preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="CONTROL_FLOW",
                        subject="EVALUATE",
                        predicate="DISPATCHES",
                        object=getattr(cf, "subject", ""),
                    ),
                    line_start=cf.evidence.line_start,
                    line_end=cf.evidence.line_end,
                    snippet=get_snippet(cf.evidence),
                )
            )
        elif isinstance(cf, StopRunConstruct) or getattr(cf, "construct_type", "") == "STOP_RUN":
            preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="CONTROL_FLOW",
                        subject="STOP_RUN",
                        predicate="TERMINATES",
                        object="STOP RUN",
                    ),
                    line_start=cf.evidence.line_start,
                    line_end=cf.evidence.line_end,
                    snippet=get_snippet(cf.evidence),
                )
            )

    # 6. I/O Operations (Discriminated variants)
    for io_op in assessment.io_operations:
        if isinstance(io_op, AcceptIO) or getattr(io_op, "operation_type", "") == "ACCEPT":
            preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="IO_OPERATION",
                        subject="ACCEPT",
                        predicate="READS",
                        object=getattr(io_op, "target_identifier", ""),
                    ),
                    line_start=io_op.evidence.line_start,
                    line_end=io_op.evidence.line_end,
                    snippet=get_snippet(io_op.evidence),
                )
            )
        elif isinstance(io_op, DisplayIO) or getattr(io_op, "operation_type", "") == "DISPLAY":
            preds.append(
                PredictedFact(
                    fact=AtomicFact(
                        kind="IO_OPERATION",
                        subject="DISPLAY",
                        predicate="WRITES",
                        object=getattr(io_op, "literal", ""),
                    ),
                    line_start=io_op.evidence.line_start,
                    line_end=io_op.evidence.line_end,
                    snippet=get_snippet(io_op.evidence),
                )
            )

    # 7. Dependency Scan
    if not assessment.copybook_dependencies:
        # Negative absence claim: host-owned verification without fabricated snippets
        preds.append(
            PredictedFact(
                fact=AtomicFact(
                    kind="DEPENDENCY_SCAN",
                    subject="COPY",
                    predicate="DEPENDENCY_COUNT",
                    object="0",
                ),
                line_start=1,
                line_end=total_lines,
                snippet="",
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
                    line_start=1,
                    line_end=total_lines,
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
    evaluator_version: str = "2.4.0",
) -> CoreEvaluationReport:
    """Evaluate a LegacyAssessment instance deterministically under Gate 2 V2.4 rules."""
    if golden_data is None:
        golden_data = load_golden_dataset_v2()
    if source_lines is None:
        source_lines = load_source_lines()

    support_index = SourceSupportIndex.from_source_lines(source_lines)

    # Deterministic whole-file scan for COPY statements
    copy_re = re.compile(r"\bCOPY\s+[A-Za-z0-9-]+\b", re.IGNORECASE)
    copy_matches = sum(1 for line in source_lines if copy_re.search(line))
    host_verif = HostVerificationReport(
        copy_statements_found_count=copy_matches,
        scanned_line_count=len(source_lines),
        source_sha256=source_sha256_actual or "",
        verification_method="WHOLE_FILE_SCAN",
    )

    predictions = assessment_to_predicted_facts(
        assessment,
        total_lines=len(source_lines),
        source_lines=source_lines,
    )

    return evaluate_predicted_facts(
        predictions=predictions,
        support_index=support_index,
        golden_data=golden_data,
        source_lines=source_lines,
        host_verifications=host_verif,
        source_sha256_actual=source_sha256_actual,
        expected_sha256=expected_sha256,
        schema_valid=True,
        evaluator_version=evaluator_version,
    )
