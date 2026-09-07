"""Deterministic evaluator for Gate 2 COBOL Reader assessments.

Calculates:
1. Deterministic evidence validation for every cited line range and snippet.
2. Atomic fact matching against the golden dataset (True Positives).
3. False Positive accounting across all predicted items (invented calls, fields, options, etc.).
4. Prohibited out-of-scope claim detection restricted strictly to affirmative fields
   (excluding explicit unsupported_assumptions).
5. Precision = TP / (TP + FP) and Recall = TP / (TP + FN).
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agents.legacy_analyzer.schemas.assessment_v1 import LegacyAssessment, SourceEvidence
from src.cobol.source_reader import prepare_source
from src.validation.evidence_validator import (
    EvidenceValidationResult,
    validate_evidence,
)


@dataclass
class FactMatchResult:
    """Evaluation result for a single expected fact."""

    fact_id: str
    category: str
    description: str
    matched: bool
    evidence_valid: bool = True
    evidence_found: str | None = None
    notes: str | None = None


@dataclass
class ProhibitedViolation:
    """Details of a detected prohibited/hallucinated claim."""

    rule_id: str
    pattern_matched: str
    context_found: str
    description: str


@dataclass
class EvaluationReport:
    """Complete evaluation report for a Gate 2 assessment."""

    evaluator_version: str = "1.1.0"
    golden_dataset_version: str = "1.0.0"
    schema_valid: bool = True
    scope_valid: bool = True
    source_sha256_match: bool = True
    evidence_valid: bool = True
    invalid_evidence_count: int = 0

    expected_fact_count: int = 0
    matched_fact_count: int = 0  # True Positives (TP)
    missing_fact_count: int = 0  # False Negatives (FN)
    false_positive_count: int = 0  # False Positives (FP)
    unsupported_fact_count: int = 0  # Total unsupported/invented claims

    precision: float = 0.0
    recall: float = 0.0
    gate_2_pass: bool = False

    matched_facts: list[FactMatchResult] = field(default_factory=list)
    missing_facts: list[FactMatchResult] = field(default_factory=list)
    unsupported_facts: list[str] = field(default_factory=list)
    invalid_evidences: list[dict[str, Any]] = field(default_factory=list)
    violations: list[ProhibitedViolation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary."""
        return asdict(self)


def load_golden_dataset(path: Path | str | None = None) -> dict[str, Any]:
    """Load the golden dataset JSON file."""
    if path is None:
        path = (
            Path(__file__).resolve().parent.parent.parent
            / "evals"
            / "expected"
            / "bank-main-single.json"
        )
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Golden dataset not found at: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def load_bank_main_lines(repo_root: Path | None = None) -> list[str]:
    """Load raw source lines of BANK-MAIN.CBL for evidence validation."""
    prep = prepare_source("legacy/core-banking-system/BANK-MAIN.CBL", repo_root=repo_root)
    return prep.raw_content.splitlines()


def validate_all_evidence(
    assessment: LegacyAssessment,
    source_lines: list[str],
) -> tuple[bool, list[EvidenceValidationResult]]:
    """Validate every SourceEvidence instance cited in the assessment."""
    results: list[EvidenceValidationResult] = []

    def check_item(ev: SourceEvidence, context: str):
        res = validate_evidence(ev, source_lines, context=context)
        if not res.is_valid:
            results.append(res)

    # Program
    check_item(assessment.program.evidence, "program.evidence")

    # Data fields
    for idx, df in enumerate(assessment.data_fields):
        check_item(df.evidence, f"data_fields[{idx}]({df.name})")

    # Call dependencies
    for idx, c in enumerate(assessment.call_dependencies):
        check_item(c.evidence, f"call_dependencies[{idx}]({c.target_program})")

    # Menu options
    for idx, mo in enumerate(assessment.menu_options):
        check_item(mo.evidence, f"menu_options[{idx}]({mo.option_key})")

    # Control flow
    for idx, cf in enumerate(assessment.control_flow):
        check_item(cf.evidence, f"control_flow[{idx}]({cf.construct_type})")

    # I/O operations
    for idx, io_op in enumerate(assessment.io_operations):
        check_item(io_op.evidence, f"io_operations[{idx}]({io_op.operation_type})")

    # Observations
    for idx, obs in enumerate(assessment.observations):
        check_item(obs.evidence, f"observations[{idx}]({obs.category})")

    is_all_valid = len(results) == 0
    return is_all_valid, results


def evaluate_assessment(
    assessment: LegacyAssessment,
    golden_data: dict[str, Any] | None = None,
    source_lines: list[str] | None = None,
    expected_sha256: str = "b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028",
) -> EvaluationReport:
    """Evaluate a LegacyAssessment instance deterministically against the golden dataset.

    Args:
        assessment: The populated LegacyAssessment object.
        golden_data: Optional pre-loaded golden dataset.
        source_lines: Optional list of raw lines from BANK-MAIN.CBL.
        expected_sha256: Expected SHA256 of BANK-MAIN.CBL.

    Returns:
        EvaluationReport with precision, recall, evidence checks, and fact breakdown.
    """
    if golden_data is None:
        golden_data = load_golden_dataset()
    if source_lines is None:
        source_lines = load_bank_main_lines()

    report = EvaluationReport(
        evaluator_version="1.1.0",
        golden_dataset_version=golden_data.get("dataset_version", "1.0.0"),
    )

    # 1. Scope and SHA256 validation
    analyzed_file = assessment.scope.analyzed_file.replace("\\", "/").upper()
    report.scope_valid = (
        "BANK-MAIN.CBL" in analyzed_file and not assessment.scope.has_external_callees_analyzed
    )
    report.source_sha256_match = assessment.scope.source_sha256.lower() == expected_sha256.lower()

    # 2. Evidence validation across all cited evidence
    evidence_ok, invalid_ev_list = validate_all_evidence(assessment, source_lines)
    report.evidence_valid = evidence_ok
    report.invalid_evidence_count = len(invalid_ev_list)
    report.invalid_evidences = [asdict(r) for r in invalid_ev_list]

    invalid_contexts = {r.field_context for r in invalid_ev_list}

    # 3. Expected Fact Matching (True Positives)
    facts = golden_data.get("facts", [])
    report.expected_fact_count = len(facts)

    for fact in facts:
        f_id = fact["id"]
        cat = fact["category"]
        desc = fact["description"]
        matched = False
        ev_valid = True
        evidence_found = None
        notes = None

        if f_id == "program.id":
            prog_id = assessment.program.program_id.strip().upper()
            if prog_id == "BANK-MAIN":
                if "program.evidence" in invalid_contexts:
                    ev_valid = False
                    notes = "Program ID value matched but evidence is invalid"
                else:
                    matched = True
                    evidence_found = (
                        f"program_id={prog_id}, snippet={assessment.program.evidence.snippet}"
                    )

        elif f_id == "data.ws_choice":
            for idx, df in enumerate(assessment.data_fields):
                if df.name.strip().upper() == "WS-CHOICE":
                    ctx = f"data_fields[{idx}]({df.name})"
                    if ctx in invalid_contexts:
                        ev_valid = False
                        notes = f"Field {df.name} matched but evidence is invalid"
                    else:
                        matched = True
                        evidence_found = (
                            f"name={df.name}, level={df.level}, pic={df.picture}, "
                            f"snippet={df.evidence.snippet}"
                        )
                    break

        elif f_id == "control.perform_loop":
            for idx, cf in enumerate(assessment.control_flow):
                c_type = cf.construct_type.strip().upper()
                c_cond = cf.condition_or_target.strip()
                if "PERFORM" in c_type and ("4" in c_cond or "WS-CHOICE" in c_cond.upper()):
                    ctx = f"control_flow[{idx}]({cf.construct_type})"
                    if ctx in invalid_contexts:
                        ev_valid = False
                        notes = "PERFORM loop matched but evidence is invalid"
                    else:
                        matched = True
                        evidence_found = (
                            f"type={cf.construct_type}, cond={cf.condition_or_target}, "
                            f"snippet={cf.evidence.snippet}"
                        )
                    break

        elif f_id == "io.accept_choice":
            for idx, io_op in enumerate(assessment.io_operations):
                op_type = io_op.operation_type.strip().upper()
                target = io_op.target_or_content.strip().upper()
                if op_type == "ACCEPT" and "WS-CHOICE" in target:
                    ctx = f"io_operations[{idx}]({io_op.operation_type})"
                    if ctx in invalid_contexts:
                        ev_valid = False
                        notes = "ACCEPT matched but evidence is invalid"
                    else:
                        matched = True
                        evidence_found = (
                            f"op={io_op.operation_type}, target={io_op.target_or_content}, "
                            f"snippet={io_op.evidence.snippet}"
                        )
                    break

        elif f_id == "control.evaluate_choice":
            for idx, cf in enumerate(assessment.control_flow):
                c_type = cf.construct_type.strip().upper()
                c_cond = cf.condition_or_target.strip().upper()
                if "EVALUATE" in c_type or "WS-CHOICE" in c_cond:
                    ctx = f"control_flow[{idx}]({cf.construct_type})"
                    if ctx in invalid_contexts:
                        ev_valid = False
                        notes = "EVALUATE matched but evidence is invalid"
                    else:
                        matched = True
                        evidence_found = (
                            f"type={cf.construct_type}, cond={cf.condition_or_target}, "
                            f"snippet={cf.evidence.snippet}"
                        )
                    break

        elif f_id == "call.init_db":
            for idx, c in enumerate(assessment.call_dependencies):
                if c.target_program.strip().upper() == "INIT-DB":
                    ctx = f"call_dependencies[{idx}]({c.target_program})"
                    if ctx in invalid_contexts:
                        ev_valid = False
                        notes = "CALL INIT-DB matched but evidence is invalid"
                    else:
                        matched = True
                        evidence_found = f"target={c.target_program}, snippet={c.evidence.snippet}"
                    break

        elif f_id == "call.trans_proc":
            for idx, c in enumerate(assessment.call_dependencies):
                if c.target_program.strip().upper() == "TRANS-PROC":
                    ctx = f"call_dependencies[{idx}]({c.target_program})"
                    if ctx in invalid_contexts:
                        ev_valid = False
                        notes = "CALL TRANS-PROC matched but evidence is invalid"
                    else:
                        matched = True
                        evidence_found = f"target={c.target_program}, snippet={c.evidence.snippet}"
                    break

        elif f_id == "call.report_gen":
            for idx, c in enumerate(assessment.call_dependencies):
                if c.target_program.strip().upper() == "REPORT-GEN":
                    ctx = f"call_dependencies[{idx}]({c.target_program})"
                    if ctx in invalid_contexts:
                        ev_valid = False
                        notes = "CALL REPORT-GEN matched but evidence is invalid"
                    else:
                        matched = True
                        evidence_found = f"target={c.target_program}, snippet={c.evidence.snippet}"
                    break

        elif f_id == "menu.option_1":
            for idx, mo in enumerate(assessment.menu_options):
                target_str = (mo.action_target or "").upper()
                desc_str = mo.description.upper()
                action_str = mo.action_type.upper()
                if mo.option_key.strip() == "1" and (
                    "INIT-DB" in target_str or "INIT" in desc_str or "CALL" in action_str
                ):
                    ctx = f"menu_options[{idx}]({mo.option_key})"
                    if ctx in invalid_contexts:
                        ev_valid = False
                        notes = "Menu option 1 matched but evidence is invalid"
                    else:
                        matched = True
                        evidence_found = (
                            f"key={mo.option_key}, target={mo.action_target}, desc={mo.description}"
                        )
                    break

        elif f_id == "menu.option_2":
            for idx, mo in enumerate(assessment.menu_options):
                target_str = (mo.action_target or "").upper()
                desc_str = mo.description.upper()
                action_str = mo.action_type.upper()
                if mo.option_key.strip() == "2" and (
                    "TRANS-PROC" in target_str or "TRANSACTION" in desc_str or "CALL" in action_str
                ):
                    ctx = f"menu_options[{idx}]({mo.option_key})"
                    if ctx in invalid_contexts:
                        ev_valid = False
                        notes = "Menu option 2 matched but evidence is invalid"
                    else:
                        matched = True
                        evidence_found = (
                            f"key={mo.option_key}, target={mo.action_target}, desc={mo.description}"
                        )
                    break

        elif f_id == "menu.option_3":
            for idx, mo in enumerate(assessment.menu_options):
                target_str = (mo.action_target or "").upper()
                desc_str = mo.description.upper()
                action_str = mo.action_type.upper()
                if mo.option_key.strip() == "3" and (
                    "REPORT-GEN" in target_str or "REPORT" in desc_str or "CALL" in action_str
                ):
                    ctx = f"menu_options[{idx}]({mo.option_key})"
                    if ctx in invalid_contexts:
                        ev_valid = False
                        notes = "Menu option 3 matched but evidence is invalid"
                    else:
                        matched = True
                        evidence_found = (
                            f"key={mo.option_key}, target={mo.action_target}, desc={mo.description}"
                        )
                    break

        elif f_id == "menu.option_4":
            for idx, mo in enumerate(assessment.menu_options):
                target_str = (mo.action_target or "").upper()
                desc_str = mo.description.upper()
                action_str = mo.action_type.upper()
                if mo.option_key.strip() == "4" and (
                    "BYE" in target_str
                    or "EXIT" in desc_str
                    or "BYE" in desc_str
                    or "EXIT" in action_str
                ):
                    ctx = f"menu_options[{idx}]({mo.option_key})"
                    if ctx in invalid_contexts:
                        ev_valid = False
                        notes = "Menu option 4 matched but evidence is invalid"
                    else:
                        matched = True
                        evidence_found = (
                            f"key={mo.option_key}, target={mo.action_target}, desc={mo.description}"
                        )
                    break

        elif f_id == "menu.option_other":
            for idx, mo in enumerate(assessment.menu_options):
                key_str = mo.option_key.strip().upper()
                target_str = (mo.action_target or "").upper()
                desc_str = mo.description.upper()
                action_str = mo.action_type.upper()
                if ("OTHER" in key_str or "DEFAULT" in key_str or key_str == "*") and (
                    "INVALID" in target_str or "INVALID" in desc_str or "ERROR" in action_str
                ):
                    ctx = f"menu_options[{idx}]({mo.option_key})"
                    if ctx in invalid_contexts:
                        ev_valid = False
                        notes = "Menu option OTHER matched but evidence is invalid"
                    else:
                        matched = True
                        evidence_found = (
                            f"key={mo.option_key}, target={mo.action_target}, desc={mo.description}"
                        )
                    break

        elif f_id == "control.stop_run":
            for idx, cf in enumerate(assessment.control_flow):
                c_type = cf.construct_type.strip().upper()
                c_cond = cf.condition_or_target.strip().upper()
                if "STOP" in c_type or "STOP" in c_cond:
                    ctx = f"control_flow[{idx}]({cf.construct_type})"
                    if ctx in invalid_contexts:
                        ev_valid = False
                        notes = "STOP RUN matched but evidence is invalid"
                    else:
                        matched = True
                        evidence_found = (
                            f"type={cf.construct_type}, target={cf.condition_or_target}, "
                            f"snippet={cf.evidence.snippet}"
                        )
                    break

        elif f_id == "dependency.no_copybooks":
            if len(assessment.scope.copybook_dependencies_found) == 0:
                matched = True
                evidence_found = "copybook_dependencies_found=[] (0 copybooks confirmed)"
            else:
                notes = (
                    f"Found unexpected copybooks: {assessment.scope.copybook_dependencies_found}"
                )

        match_res = FactMatchResult(
            fact_id=f_id,
            category=cat,
            description=desc,
            matched=matched,
            evidence_valid=ev_valid,
            evidence_found=evidence_found,
            notes=notes,
        )

        if matched:
            report.matched_facts.append(match_res)
        else:
            report.missing_facts.append(match_res)

    report.matched_fact_count = len(report.matched_facts)
    report.missing_fact_count = len(report.missing_facts)

    # 4. False Positive Accounting across Normalized Predicted Facts
    # Any predicted item that is NOT supported by BANK-MAIN.CBL is counted as a False Positive.
    supported_calls = {"INIT-DB", "TRANS-PROC", "REPORT-GEN"}
    supported_fields = {"WS-CHOICE"}
    supported_menu_keys = {"1", "2", "3", "4", "OTHER", "DEFAULT", "*"}

    for idx, c in enumerate(assessment.call_dependencies):
        target = c.target_program.strip().upper()
        ctx = f"call_dependencies[{idx}]({c.target_program})"
        if target not in supported_calls:
            report.unsupported_facts.append(f"Invented CALL target: '{c.target_program}'")
        elif ctx in invalid_contexts:
            report.unsupported_facts.append(f"CALL '{c.target_program}' with invalid evidence")

    for idx, df in enumerate(assessment.data_fields):
        name = df.name.strip().upper()
        ctx = f"data_fields[{idx}]({df.name})"
        if name not in supported_fields:
            report.unsupported_facts.append(f"Invented data field: '{df.name}'")
        elif ctx in invalid_contexts:
            report.unsupported_facts.append(f"Field '{df.name}' with invalid evidence")

    for idx, mo in enumerate(assessment.menu_options):
        key = mo.option_key.strip().upper()
        ctx = f"menu_options[{idx}]({mo.option_key})"
        if key not in supported_menu_keys:
            report.unsupported_facts.append(f"Invented menu option key: '{mo.option_key}'")
        elif ctx in invalid_contexts:
            report.unsupported_facts.append(f"Menu option '{mo.option_key}' with invalid evidence")

    # Invented copybook dependencies
    for cpy in assessment.scope.copybook_dependencies_found:
        report.unsupported_facts.append(f"Invented COPY dependency: '{cpy}'")

    # Invented Program ID
    if assessment.program.program_id.strip().upper() != "BANK-MAIN":
        report.unsupported_facts.append(f"Invented Program ID: '{assessment.program.program_id}'")
    elif "program.evidence" in invalid_contexts:
        report.unsupported_facts.append("Program ID with invalid evidence")

    # Invalid evidence on control_flow or io_operations
    for idx, cf in enumerate(assessment.control_flow):
        ctx = f"control_flow[{idx}]({cf.construct_type})"
        if ctx in invalid_contexts:
            report.unsupported_facts.append(
                f"Control flow '{cf.construct_type}' with invalid evidence"
            )

    for idx, io_op in enumerate(assessment.io_operations):
        ctx = f"io_operations[{idx}]({io_op.operation_type})"
        if ctx in invalid_contexts:
            report.unsupported_facts.append(
                f"IO operation '{io_op.operation_type}' with invalid evidence"
            )

    # 5. Prohibited / Out-of-Scope Checks (Hallucination Detection)
    # CRITICAL: Only scan affirmative factual fields (observations, menu_options, etc.).
    # Do NOT scan unsupported_assumptions!
    affirmative_text_blobs: list[str] = []

    for obs in assessment.observations:
        affirmative_text_blobs.append(f"observation({obs.category}): {obs.observation}")

    for mo in assessment.menu_options:
        affirmative_text_blobs.append(
            f"menu_option({mo.option_key}): {mo.description} -> {mo.action_target}"
        )

    for cf in assessment.control_flow:
        affirmative_text_blobs.append(
            f"control_flow({cf.construct_type}): {cf.condition_or_target}"
        )

    for c in assessment.call_dependencies:
        affirmative_text_blobs.append(f"call({c.target_program}): {c.call_type}")

    prohibited_rules = golden_data.get("prohibited_facts", [])
    for rule in prohibited_rules:
        r_id = rule["id"]
        patterns = rule["forbidden_patterns"]
        r_desc = rule["description"]

        for blob in affirmative_text_blobs:
            blob_lower = blob.lower()
            for pat in patterns:
                if pat.lower() in blob_lower:
                    report.violations.append(
                        ProhibitedViolation(
                            rule_id=r_id,
                            pattern_matched=pat,
                            context_found=blob,
                            description=r_desc,
                        )
                    )
                    report.unsupported_facts.append(
                        f"Prohibited callee claim ({r_id}): matched '{pat}' in {blob}"
                    )
                    break

    if assessment.scope.has_external_callees_analyzed:
        report.violations.append(
            ProhibitedViolation(
                rule_id="prohibit.scope.callees_analyzed",
                pattern_matched="has_external_callees_analyzed=True",
                context_found="ScopeDeclaration",
                description="Model claimed external callees analyzed, violating scope isolation.",
            )
        )
        report.unsupported_facts.append("Scope claim: has_external_callees_analyzed=True")

    # 6. False Positives & Precision / Recall Metrics
    # FP is the total count of unsupported/invented claims and invalid-evidence claims
    report.false_positive_count = len(report.unsupported_facts)
    report.unsupported_fact_count = report.false_positive_count

    tp = report.matched_fact_count
    fp = report.false_positive_count
    fn = report.missing_fact_count

    report.recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
    report.precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0

    report.gate_2_pass = (
        report.schema_valid
        and report.scope_valid
        and report.source_sha256_match
        and report.evidence_valid
        and report.invalid_evidence_count == 0
        and report.recall >= 0.90
        and report.false_positive_count == 0
        and len(report.violations) == 0
    )

    return report
