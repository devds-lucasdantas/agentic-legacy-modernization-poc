"""Deterministic AST-grounded Evaluator V3 for Gate 3 System Understanding.

Evaluates structured SystemAssessment output against the 54-unit golden dataset
and the ground-truth SystemSupportIndex.
Adheres strictly to:
- Guardrail A: ZERO fuzzy/NLP/LLM semantic comparison.
- Guardrail B: Explicit lifecycle and transfer verification.
- Dynamic recall denominator derived from loaded golden dataset.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agents.legacy_analyzer.schemas.system_assessment import SystemAssessment
from src.cobol.system_atomic_facts import (
    ArchitecturalRiskFact,
    ArithmeticOperationFact,
    BehavioralRiskFact,
    ComponentTopologyFact,
    ConditionalBranchFact,
    ControlFlowLoopFact,
    CopybookInclusionFact,
    CrossProgramCallFact,
    DataTransferFact,
    EvaluateBranchingFact,
    FieldLayoutFact,
    InteractiveIOFact,
    MenuDispatchFact,
    ResourceLifecycleFact,
    SystemAtomicFact,
    TerminationFact,
    TransactionProtocolFact,
    WorkingStorageStateFact,
)
from src.cobol.system_support_index import SystemSupportIndex


@dataclass(frozen=True)
class EvaluationMetricSummary:
    """Official summary metrics for Gate 3 evaluation."""

    raw_predicted_count: int
    unique_predicted_count: int
    supported_predicted_count: int
    unsupported_predicted_count: int
    invalid_evidence_count: int
    duplicate_prediction_count: int
    contradiction_count: int
    matched_expected_count: int
    missing_expected_count: int
    expected_fact_count: int
    precision: float
    recall: float
    gate_3_pass: bool

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class EvaluatedPrediction:
    """Evaluation result for an individual model assertion."""

    fact_category: str
    semantic_key: str
    file_path: str
    line_start: int
    line_end: int
    is_supported: bool
    is_duplicate: bool
    is_contradiction: bool
    rejection_reason: str | None
    matched_proposition_id: str | None


class SystemEvaluatorV3:
    """Deterministic system evaluator for Gate 3."""

    def __init__(
        self,
        support_index: SystemSupportIndex,
        golden_dataset_path: Path | None = None,
    ) -> None:
        self.support_index = support_index
        if golden_dataset_path is None:
            golden_dataset_path = (
                Path(__file__).resolve().parent.parent.parent
                / "evals"
                / "expected"
                / "system-understanding-v3.json"
            )
        self.golden_dataset_path = golden_dataset_path
        self._load_golden_dataset()

    def _load_golden_dataset(self) -> None:
        """Load golden dataset and dynamically derive total expected facts."""
        data = json.loads(self.golden_dataset_path.read_text(encoding="utf-8"))
        self.golden_propositions = data["propositions"]
        self.expected_fact_count = len(self.golden_propositions)
        self.golden_by_id = {p["id"]: p for p in self.golden_propositions}
        self.golden_by_semantic_key = {p["semantic_key"]: p for p in self.golden_propositions}

    def evaluate_assessment(
        self,
        assessment: SystemAssessment | dict[str, Any],
    ) -> tuple[EvaluationMetricSummary, list[EvaluatedPrediction]]:
        """Evaluate a model assessment against the support index and golden dataset."""
        if isinstance(assessment, dict):
            assessment_obj = SystemAssessment.model_validate(assessment)
        else:
            assessment_obj = assessment

        candidate_facts: list[tuple[SystemAtomicFact, str, int, int]] = []

        # 1. Extract all candidate predictions from assessment
        for c in assessment_obj.components:
            f = ComponentTopologyFact(
                fact_category="ARCHITECTURE",
                program_id=c.program_id,
                component_role=c.component_role,
            )
            candidate_facts.append(
                (f, c.evidence.file_path, c.evidence.line_start, c.evidence.line_end)
            )

        for call in assessment_obj.cross_program_calls:
            f_call = CrossProgramCallFact(
                fact_category="CROSS_PROGRAM_CALL",
                caller_program=call.caller_program,
                callee_program=call.callee_program,
                call_mechanism=call.call_mechanism,
            )
            candidate_facts.append(
                (f_call, call.evidence.file_path, call.evidence.line_start, call.evidence.line_end)
            )

        for menu in assessment_obj.menu_dispatches:
            f_menu = MenuDispatchFact(
                fact_category="MENU_DISPATCH",
                program_id=menu.program_id,
                menu_key=menu.menu_key,
                target_action=menu.target_action,
            )
            candidate_facts.append(
                (f_menu, menu.evidence.file_path, menu.evidence.line_start, menu.evidence.line_end)
            )

        for copy in assessment_obj.copybook_references:
            f_copy = CopybookInclusionFact(
                fact_category="COPYBOOK_INCLUSION",
                program_id=copy.program_id,
                copybook_name=copy.copybook_name,
            )
            candidate_facts.append(
                (f_copy, copy.evidence.file_path, copy.evidence.line_start, copy.evidence.line_end)
            )

        for field in assessment_obj.record_fields:
            f_field = FieldLayoutFact(
                fact_category="FIELD_LAYOUT",
                container_name=field.container_name,
                field_name=field.field_name,
                picture_clause=field.picture_clause,
                storage_format=field.storage_format,
            )
            candidate_facts.append(
                (
                    f_field,
                    field.evidence.file_path,
                    field.evidence.line_start,
                    field.evidence.line_end,
                )
            )

        for trans in assessment_obj.data_transfers:
            f_trans = DataTransferFact(
                fact_category="DATA_TRANSFER",
                program_id=trans.program_id,
                source_entity=trans.source_entity,
                target_entity=trans.target_entity,
                transfer_verb=trans.transfer_verb,
            )
            candidate_facts.append(
                (
                    f_trans,
                    trans.evidence.file_path,
                    trans.evidence.line_start,
                    trans.evidence.line_end,
                )
            )

        for r_life in assessment_obj.resource_lifecycles:
            f_life = ResourceLifecycleFact(
                fact_category="RESOURCE_LIFECYCLE",
                program_id=r_life.program_id,
                resource_name=r_life.resource_name,
                access_mode=r_life.access_mode,
                operations=tuple(r_life.operations),
            )
            candidate_facts.append(
                (
                    f_life,
                    r_life.evidence.file_path,
                    r_life.evidence.line_start,
                    r_life.evidence.line_end,
                )
            )

        for loop in assessment_obj.control_flow_loops:
            f_loop = ControlFlowLoopFact(
                fact_category="CONTROL_FLOW_LOOP",
                program_id=loop.program_id,
                loop_predicate=loop.loop_predicate,
            )
            candidate_facts.append(
                (f_loop, loop.evidence.file_path, loop.evidence.line_start, loop.evidence.line_end)
            )

        for eval_s in assessment_obj.evaluate_selections:
            f_eval = EvaluateBranchingFact(
                fact_category="EVALUATE_BRANCHING",
                program_id=eval_s.program_id,
                selection_subject=eval_s.selection_subject,
            )
            candidate_facts.append(
                (
                    f_eval,
                    eval_s.evidence.file_path,
                    eval_s.evidence.line_start,
                    eval_s.evidence.line_end,
                )
            )

        for arith in assessment_obj.arithmetic_computations:
            f_arith = ArithmeticOperationFact(
                fact_category="ARITHMETIC_OPERATION",
                program_id=arith.program_id,
                verb=arith.verb,
                operand=arith.operand,
                target_field=arith.target_field,
            )
            candidate_facts.append(
                (
                    f_arith,
                    arith.evidence.file_path,
                    arith.evidence.line_start,
                    arith.evidence.line_end,
                )
            )

        for branch in assessment_obj.conditional_branches:
            f_branch = ConditionalBranchFact(
                fact_category="CONDITIONAL_BRANCH",
                program_id=branch.program_id,
                condition_kind=branch.condition_kind,
                predicate=branch.predicate,
            )
            candidate_facts.append(
                (
                    f_branch,
                    branch.evidence.file_path,
                    branch.evidence.line_start,
                    branch.evidence.line_end,
                )
            )

        for io in assessment_obj.interactive_io_operations:
            f_io = InteractiveIOFact(
                fact_category="INTERACTIVE_IO",
                program_id=io.program_id,
                io_verb=io.io_verb,
                target_identifier=io.target_identifier,
            )
            candidate_facts.append(
                (f_io, io.evidence.file_path, io.evidence.line_start, io.evidence.line_end)
            )

        for term in assessment_obj.terminations:
            f_term = TerminationFact(
                fact_category="TERMINATION",
                program_id=term.program_id,
                termination_verb=term.termination_verb,
            )
            candidate_facts.append(
                (f_term, term.evidence.file_path, term.evidence.line_start, term.evidence.line_end)
            )

        for b_risk in assessment_obj.behavioral_risks:
            f_b_risk = BehavioralRiskFact(
                fact_category="BEHAVIORAL_RISK",
                program_id=b_risk.program_id,
                risk_category=b_risk.risk_category,
                precondition=b_risk.precondition,
                ordered_operations=tuple(b_risk.ordered_operations),
                possible_consequence=b_risk.possible_consequence,
                severity=b_risk.severity,
            )
            candidate_facts.append(
                (
                    f_b_risk,
                    b_risk.evidence.file_path,
                    b_risk.evidence.line_start,
                    b_risk.evidence.line_end,
                )
            )

        for a_risk in assessment_obj.architectural_risks:
            f_a_risk = ArchitecturalRiskFact(
                fact_category="ARCHITECTURAL_RISK",
                risk_id=a_risk.risk_id,
                risk_type=a_risk.risk_type,
                affected_components=tuple(a_risk.affected_components),
                architectural_consequence=a_risk.architectural_consequence,
                severity=a_risk.severity,
            )
            candidate_facts.append(
                (
                    f_a_risk,
                    a_risk.evidence.file_path,
                    a_risk.evidence.line_start,
                    a_risk.evidence.line_end,
                )
            )

        for ws in assessment_obj.working_storage_states:
            f_ws = WorkingStorageStateFact(
                fact_category="WORKING_STORAGE_STATE",
                program_id=ws.program_id,
                variable_name=ws.variable_name,
                picture_clause=ws.picture_clause,
                state_role=ws.state_role,
            )
            candidate_facts.append(
                (f_ws, ws.evidence.file_path, ws.evidence.line_start, ws.evidence.line_end)
            )

        for proto in assessment_obj.system_protocols:
            f_proto = TransactionProtocolFact(
                fact_category="TRANSACTION_PROTOCOL",
                protocol_name=proto.protocol_name,
                ordered_phases=tuple(proto.ordered_phases),
            )
            candidate_facts.append(
                (
                    f_proto,
                    proto.evidence.file_path,
                    proto.evidence.line_start,
                    proto.evidence.line_end,
                )
            )

        raw_count = len(candidate_facts)

        # 2. Duplicate Detection
        seen_assertions: set[tuple[str, str, int, int]] = set()
        evaluated: list[EvaluatedPrediction] = []
        duplicate_count = 0
        invalid_evidence_count = 0
        unsupported_count = 0
        contradiction_count = 0
        matched_golden_ids: set[str] = set()

        for fact, f_path, l_start, l_end in candidate_facts:
            sem_key = fact.get_semantic_key()
            assertion_tuple = (sem_key, f_path, l_start, l_end)

            # Check invalid evidence line bounds
            if not self.support_index.is_span_valid(f_path, l_start, l_end):
                invalid_evidence_count += 1
                evaluated.append(
                    EvaluatedPrediction(
                        fact_category=fact.fact_category,
                        semantic_key=sem_key,
                        file_path=f_path,
                        line_start=l_start,
                        line_end=l_end,
                        is_supported=False,
                        is_duplicate=False,
                        is_contradiction=False,
                        rejection_reason="Invalid line span coordinates",
                        matched_proposition_id=None,
                    )
                )
                continue

            if assertion_tuple in seen_assertions:
                duplicate_count += 1
                evaluated.append(
                    EvaluatedPrediction(
                        fact_category=fact.fact_category,
                        semantic_key=sem_key,
                        file_path=f_path,
                        line_start=l_start,
                        line_end=l_end,
                        is_supported=False,
                        is_duplicate=True,
                        is_contradiction=False,
                        rejection_reason="Duplicate assertion",
                        matched_proposition_id=None,
                    )
                )
                continue
            seen_assertions.add(assertion_tuple)

            # Verify against ground-truth index
            is_supp, reason, matched_fact = self.support_index.verify_assertion(
                fact, f_path, l_start, l_end
            )

            matched_id: str | None = None
            if is_supp and matched_fact:
                matched_id = matched_fact.proposition_id
                matched_golden_ids.add(matched_id)
            else:
                unsupported_count += 1

            evaluated.append(
                EvaluatedPrediction(
                    fact_category=fact.fact_category,
                    semantic_key=sem_key,
                    file_path=f_path,
                    line_start=l_start,
                    line_end=l_end,
                    is_supported=is_supp,
                    is_duplicate=False,
                    is_contradiction=False,
                    rejection_reason=None if is_supp else reason,
                    matched_proposition_id=matched_id,
                )
            )

        unique_count = raw_count - duplicate_count
        supported_count = sum(1 for e in evaluated if e.is_supported and not e.is_duplicate)
        matched_expected = len(matched_golden_ids)
        missing_expected = self.expected_fact_count - matched_expected

        precision = (supported_count / unique_count) if unique_count > 0 else 0.0
        recall = (
            (matched_expected / self.expected_fact_count) if self.expected_fact_count > 0 else 0.0
        )

        gate_pass = (
            precision >= 0.80
            and recall >= 0.80
            and unsupported_count == 0
            and invalid_evidence_count == 0
            and contradiction_count == 0
        )

        metrics = EvaluationMetricSummary(
            raw_predicted_count=raw_count,
            unique_predicted_count=unique_count,
            supported_predicted_count=supported_count,
            unsupported_predicted_count=unsupported_count,
            invalid_evidence_count=invalid_evidence_count,
            duplicate_prediction_count=duplicate_count,
            contradiction_count=contradiction_count,
            matched_expected_count=matched_expected,
            missing_expected_count=missing_expected,
            expected_fact_count=self.expected_fact_count,
            precision=round(precision, 4),
            recall=round(recall, 4),
            gate_3_pass=gate_pass,
        )

        return metrics, evaluated
