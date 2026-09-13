"""Deterministic AST-grounded Evaluator V3 for Gate 3 System Understanding.

Evaluates structured SystemAssessment output against the independently authored
golden dataset and the ground-truth SystemSupportIndex.
Adheres strictly to:
- Blocker 1: Restores all 18 approved model-visible concepts.
- Blocker 5: ZERO evidence line tolerance; exact role-bound verification.
- Blocker 7: Independent positive oracle test, no circular generation.
- Blocker 8: Categorical completeness semantics
  (REQUIRED COMPLETE, OPTIONAL SUPPLEMENTARY, NOT SCORED).
- Blocker 9: Role-bound multi-evidence coordinates for relational facts.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agents.legacy_analyzer.schemas.system_assessment import SystemAssessment
from src.cobol.system_atomic_facts import (
    BehavioralRiskFact,
    CallEdgeFact,
    CallerContinuationConstraintFact,
    CallOccurrenceFact,
    CommandInvocationFact,
    ComputationDataflowFact,
    DataStateComparisonFact,
    DataTransferRelationFact,
    EvidenceSpan,
    FileBindingFact,
    FileOperationFact,
    InternalCallResolutionFact,
    OperationSequenceFact,
    PlatformDependencyFact,
    ProgramDeclarationFact,
    RecordFieldFact,
    RecordLayoutFact,
    RecordLayoutRelationFact,
    ResourceLifecycleFact,
    SystemAtomicFact,
    TerminationSiteFact,
)
from src.cobol.system_support_index import SystemSupportIndex

EVALUATOR_VERSION: str = "3.5.2"


def _single_span(ev: Any) -> dict[str, EvidenceSpan]:
    return {"evidence": EvidenceSpan(ev.file_path, ev.line_start, ev.line_end)}


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

    def to_dict(self) -> dict[str, Any]:
        """Convert prediction evaluation to dictionary."""
        return {
            "fact_category": self.fact_category,
            "semantic_key": self.semantic_key,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "is_supported": self.is_supported,
            "is_duplicate": self.is_duplicate,
            "is_contradiction": self.is_contradiction,
            "rejection_reason": self.rejection_reason,
            "matched_proposition_id": self.matched_proposition_id,
        }


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

    def _canonicalize_path(self, path: str) -> str:
        """Resolve path to its canonical bundle path if possible, else normalized path."""
        try:
            return self.support_index.bundle.resolve_canonical_file_path(path)
        except (KeyError, ValueError):
            return path.replace("\\", "/").strip()

    def _load_golden_dataset(self) -> None:
        """Load golden dataset and dynamically derive total expected facts."""
        data = json.loads(self.golden_dataset_path.read_text(encoding="utf-8"))
        self.category_policies = data.get("category_policies", {})
        self.golden_propositions = data["propositions"]
        self.required_golden_propositions = [
            p
            for p in self.golden_propositions
            if self.category_policies.get(p["category"]) != "OPTIONAL_SUPPLEMENTARY"
        ]
        self.expected_fact_count = len(self.required_golden_propositions)
        self.golden_by_id = {p["id"]: p for p in self.golden_propositions}
        self.golden_by_semantic_key = {p["semantic_key"]: p for p in self.golden_propositions}
        self.golden_by_key_and_spans: dict[
            tuple[str, tuple[tuple[str, str, int, int], ...]], str
        ] = {}
        for p in self.golden_propositions:
            sig = tuple(
                sorted(
                    (
                        r,
                        self._canonicalize_path(sp["file_path"]),
                        sp["line_start"],
                        sp["line_end"],
                    )
                    for r, sp in p["evidence_spans"].items()
                )
            )
            self.golden_by_key_and_spans[(p["semantic_key"], sig)] = p["id"]

    def evaluate_assessment(
        self,
        assessment: SystemAssessment | dict[str, Any],
    ) -> tuple[EvaluationMetricSummary, list[EvaluatedPrediction]]:
        """Evaluate a model assessment against the support index and golden dataset."""
        if isinstance(assessment, dict):
            assessment_obj = SystemAssessment.model_validate(assessment)
        else:
            assessment_obj = assessment

        candidate_items: list[tuple[SystemAtomicFact, dict[str, EvidenceSpan]]] = []

        def _assert_canonical(model_val: Any, fact_val: Any, field_name: str) -> None:
            if model_val != fact_val:
                raise ValueError(
                    f"Model value for {field_name} '{model_val}' was non-canonical "
                    f"and would be repaired to '{fact_val}'. "
                    f"Strict anti-repair rejects non-canonical input."
                )

        # 1. Program Declarations
        for d in assessment_obj.program_declarations:
            f = ProgramDeclarationFact(program_id=d.program_id)
            _assert_canonical(d.program_id, f.program_id, "program_id")
            candidate_items.append((f, _single_span(d.evidence)))

        # 2. Call Occurrences
        for c in assessment_obj.call_occurrences:
            f_call = CallOccurrenceFact(
                caller_program=c.caller_program,
                target_program=c.target_program,
                call_mechanism=c.call_mechanism,
                argument_identifier=c.argument_identifier,
            )
            _assert_canonical(c.caller_program, f_call.caller_program, "caller_program")
            _assert_canonical(c.target_program, f_call.target_program, "target_program")
            _assert_canonical(c.call_mechanism, f_call.call_mechanism, "call_mechanism")
            if c.argument_identifier is not None:
                _assert_canonical(
                    c.argument_identifier, f_call.argument_identifier, "argument_identifier"
                )
            candidate_items.append((f_call, _single_span(c.evidence)))

        # 3. Call Edges
        for e in assessment_obj.call_edges:
            f_edge = CallEdgeFact(
                caller_program=e.caller_program,
                target_program=e.target_program,
                call_mechanism=e.call_mechanism,
            )
            _assert_canonical(e.caller_program, f_edge.caller_program, "caller_program")
            _assert_canonical(e.target_program, f_edge.target_program, "target_program")
            _assert_canonical(e.call_mechanism, f_edge.call_mechanism, "call_mechanism")
            candidate_items.append((f_edge, _single_span(e.evidence)))

        # 4. Internal Call Resolutions
        for r in assessment_obj.internal_call_resolutions:
            f_res = InternalCallResolutionFact(
                caller_program=r.caller_program,
                callee_program=r.callee_program,
            )
            _assert_canonical(r.caller_program, f_res.caller_program, "caller_program")
            _assert_canonical(r.callee_program, f_res.callee_program, "callee_program")
            spans = {
                "call_evidence": EvidenceSpan(
                    r.call_evidence.file_path, r.call_evidence.line_start, r.call_evidence.line_end
                ),
                "target_declaration_evidence": EvidenceSpan(
                    r.target_declaration_evidence.file_path,
                    r.target_declaration_evidence.line_start,
                    r.target_declaration_evidence.line_end,
                ),
            }
            candidate_items.append((f_res, spans))

        # 5. File Bindings
        for b in assessment_obj.file_bindings:
            f_bind = FileBindingFact(
                program_id=b.program_id,
                internal_file_name=b.internal_file_name,
                external_file_name=b.external_file_name,
                organization=b.organization,
            )
            _assert_canonical(b.program_id, f_bind.program_id, "program_id")
            _assert_canonical(b.internal_file_name, f_bind.internal_file_name, "internal_file_name")
            _assert_canonical(b.external_file_name, f_bind.external_file_name, "external_file_name")
            _assert_canonical(b.organization, f_bind.organization, "organization")
            candidate_items.append((f_bind, _single_span(b.evidence)))

        # 6. Record Layouts
        for lay in assessment_obj.record_layouts:
            fields = []
            for fld in lay.fields:
                rf = RecordFieldFact(
                    field_kind=fld.field_kind,
                    level=fld.level,
                    name=fld.name,
                    picture=fld.picture,
                    usage=fld.usage,
                    condition_values=tuple(fld.condition_values),
                )
                _assert_canonical(fld.name, rf.name, "field.name")
                if fld.picture is not None:
                    _assert_canonical(fld.picture, rf.picture, "field.picture")
                if fld.usage is not None:
                    _assert_canonical(fld.usage, rf.usage, "field.usage")
                _assert_canonical(
                    tuple(fld.condition_values), rf.condition_values, "field.condition_values"
                )
                fields.append(rf)
            f_lay = RecordLayoutFact(
                program_id=lay.program_id,
                record_name=lay.record_name,
                fields=tuple(fields),
            )
            _assert_canonical(lay.program_id, f_lay.program_id, "program_id")
            _assert_canonical(lay.record_name, f_lay.record_name, "record_name")
            candidate_items.append((f_lay, _single_span(lay.evidence)))

        # File Operations (OPTIONAL_SUPPLEMENTARY)
        for fo in assessment_obj.file_operations:
            f_fo = FileOperationFact(
                program_id=fo.program_id,
                internal_file_name=fo.internal_file_name,
                operation_verb=fo.operation_verb,
            )
            _assert_canonical(fo.program_id, f_fo.program_id, "program_id")
            _assert_canonical(fo.internal_file_name, f_fo.internal_file_name, "internal_file_name")
            _assert_canonical(fo.operation_verb, f_fo.operation_verb, "operation_verb")
            candidate_items.append((f_fo, _single_span(fo.evidence)))

        # 7. Record Layout Relations
        for rel in assessment_obj.record_layout_relations:
            name_a = rel.layout_a_name
            name_b = rel.layout_b_name
            span_a = EvidenceSpan(
                rel.evidence_a.file_path, rel.evidence_a.line_start, rel.evidence_a.line_end
            )
            span_b = EvidenceSpan(
                rel.evidence_b.file_path, rel.evidence_b.line_start, rel.evidence_b.line_end
            )
            # Canonicalize complete endpoints: (layout_name, evidence_span)
            if (name_a, span_a.file_path, span_a.line_start, span_a.line_end) > (
                name_b,
                span_b.file_path,
                span_b.line_start,
                span_b.line_end,
            ):
                name_a, name_b = name_b, name_a
                span_a, span_b = span_b, span_a

            f_rel = RecordLayoutRelationFact(
                layout_a_name=name_a,
                layout_b_name=name_b,
                relation_type=rel.relation_type,
            )
            _assert_canonical(name_a, f_rel.layout_a_name, "layout_a_name")
            _assert_canonical(name_b, f_rel.layout_b_name, "layout_b_name")
            _assert_canonical(rel.relation_type, f_rel.relation_type, "relation_type")
            spans = {
                "evidence_a": span_a,
                "evidence_b": span_b,
            }
            candidate_items.append((f_rel, spans))

        # 8. Termination Sites
        for t in assessment_obj.termination_sites:
            f_term = TerminationSiteFact(
                program_id=t.program_id,
                statement_type=t.statement_type,
            )
            _assert_canonical(t.program_id, f_term.program_id, "program_id")
            _assert_canonical(t.statement_type, f_term.statement_type, "statement_type")
            candidate_items.append((f_term, _single_span(t.evidence)))

        # 9. Caller Continuation Constraints
        for c_con in assessment_obj.caller_continuation_constraints:
            f_ccc = CallerContinuationConstraintFact(
                caller_program=c_con.caller_program,
                callee_program=c_con.callee_program,
                constraint_type=c_con.constraint_type,
            )
            _assert_canonical(c_con.caller_program, f_ccc.caller_program, "caller_program")
            _assert_canonical(c_con.callee_program, f_ccc.callee_program, "callee_program")
            _assert_canonical(c_con.constraint_type, f_ccc.constraint_type, "constraint_type")
            spans = {
                "call_evidence": EvidenceSpan(
                    c_con.call_evidence.file_path,
                    c_con.call_evidence.line_start,
                    c_con.call_evidence.line_end,
                ),
                "callee_termination_evidence": EvidenceSpan(
                    c_con.callee_termination_evidence.file_path,
                    c_con.callee_termination_evidence.line_start,
                    c_con.callee_termination_evidence.line_end,
                ),
            }
            candidate_items.append((f_ccc, spans))

        # 10. Command Invocations
        for cmd in assessment_obj.command_invocations:
            f_cmd = CommandInvocationFact(
                program_id=cmd.program_id,
                command_template=cmd.command_template,
                target_operand=cmd.target_operand,
            )
            _assert_canonical(cmd.program_id, f_cmd.program_id, "program_id")
            _assert_canonical(cmd.command_template, f_cmd.command_template, "command_template")
            _assert_canonical(cmd.target_operand, f_cmd.target_operand, "target_operand")
            spans = {
                "assignment_evidence": EvidenceSpan(
                    cmd.assignment_evidence.file_path,
                    cmd.assignment_evidence.line_start,
                    cmd.assignment_evidence.line_end,
                ),
                "call_evidence": EvidenceSpan(
                    cmd.call_evidence.file_path,
                    cmd.call_evidence.line_start,
                    cmd.call_evidence.line_end,
                ),
            }
            candidate_items.append((f_cmd, spans))

        # 11. Data Transfer Relations
        for dt in assessment_obj.data_transfer_relations:
            f_dt = DataTransferRelationFact(
                program_id=dt.program_id,
                source_entity=dt.source_entity,
                target_entity=dt.target_entity,
                transfer_verb=dt.transfer_verb,
            )
            _assert_canonical(dt.program_id, f_dt.program_id, "program_id")
            _assert_canonical(dt.source_entity, f_dt.source_entity, "source_entity")
            _assert_canonical(dt.target_entity, f_dt.target_entity, "target_entity")
            _assert_canonical(dt.transfer_verb, f_dt.transfer_verb, "transfer_verb")
            candidate_items.append((f_dt, _single_span(dt.evidence)))

        # 12. Resource Lifecycles
        for rl in assessment_obj.resource_lifecycles:
            f_rl = ResourceLifecycleFact(
                program_id=rl.program_id,
                resource_name=rl.resource_name,
                access_mode=rl.access_mode,
                ordered_operations=tuple(rl.ordered_operations),
            )
            _assert_canonical(rl.program_id, f_rl.program_id, "program_id")
            _assert_canonical(rl.resource_name, f_rl.resource_name, "resource_name")
            _assert_canonical(rl.access_mode, f_rl.access_mode, "access_mode")
            _assert_canonical(
                tuple(rl.ordered_operations), f_rl.ordered_operations, "ordered_operations"
            )
            candidate_items.append((f_rl, _single_span(rl.evidence)))

        # 13. Operation Sequences
        for op in assessment_obj.operation_sequences:
            f_op = OperationSequenceFact(
                program_id=op.program_id,
                first_operation=op.first_operation,
                second_operation=op.second_operation,
            )
            _assert_canonical(op.program_id, f_op.program_id, "program_id")
            _assert_canonical(op.first_operation, f_op.first_operation, "first_operation")
            _assert_canonical(op.second_operation, f_op.second_operation, "second_operation")
            spans = {
                "first_assignment_evidence": EvidenceSpan(
                    op.first_assignment_evidence.file_path,
                    op.first_assignment_evidence.line_start,
                    op.first_assignment_evidence.line_end,
                ),
                "first_call_evidence": EvidenceSpan(
                    op.first_call_evidence.file_path,
                    op.first_call_evidence.line_start,
                    op.first_call_evidence.line_end,
                ),
                "second_assignment_evidence": EvidenceSpan(
                    op.second_assignment_evidence.file_path,
                    op.second_assignment_evidence.line_start,
                    op.second_assignment_evidence.line_end,
                ),
                "second_call_evidence": EvidenceSpan(
                    op.second_call_evidence.file_path,
                    op.second_call_evidence.line_start,
                    op.second_call_evidence.line_end,
                ),
            }
            candidate_items.append((f_op, spans))

        # 14. Computation Dataflows
        for cd in assessment_obj.computation_dataflows:
            f_cd = ComputationDataflowFact(
                program_id=cd.program_id,
                source_field=cd.source_field,
                target_field=cd.target_field,
                operation_verb=cd.operation_verb,
            )
            _assert_canonical(cd.program_id, f_cd.program_id, "program_id")
            _assert_canonical(cd.source_field, f_cd.source_field, "source_field")
            _assert_canonical(cd.target_field, f_cd.target_field, "target_field")
            _assert_canonical(cd.operation_verb, f_cd.operation_verb, "operation_verb")
            candidate_items.append((f_cd, _single_span(cd.evidence)))

        # 15. Platform Dependencies
        for pd in assessment_obj.platform_dependencies:
            f_pd = PlatformDependencyFact(
                program_id=pd.program_id,
                platform_family=pd.platform_family,
                command_literal=pd.command_literal,
            )
            _assert_canonical(pd.program_id, f_pd.program_id, "program_id")
            _assert_canonical(pd.platform_family, f_pd.platform_family, "platform_family")
            _assert_canonical(pd.command_literal, f_pd.command_literal, "command_literal")
            candidate_items.append((f_pd, _single_span(pd.evidence)))

        # 16. Behavioral Risks
        for br in assessment_obj.behavioral_risks:
            f_br = BehavioralRiskFact(
                program_id=br.program_id,
                risk_category=br.risk_category,
                risk_basis_kind=br.risk_basis_kind,
                impact_category=br.impact_category,
                resource_name=br.resource_name,
            )
            _assert_canonical(br.program_id, f_br.program_id, "program_id")
            _assert_canonical(br.risk_category, f_br.risk_category, "risk_category")
            _assert_canonical(br.risk_basis_kind, f_br.risk_basis_kind, "risk_basis_kind")
            _assert_canonical(br.impact_category, f_br.impact_category, "impact_category")
            if br.resource_name is not None:
                _assert_canonical(br.resource_name, f_br.resource_name, "resource_name")
            spans = {
                "operation_evidence": EvidenceSpan(
                    br.operation_evidence.file_path,
                    br.operation_evidence.line_start,
                    br.operation_evidence.line_end,
                ),
                "affected_resource_evidence": EvidenceSpan(
                    br.affected_resource_evidence.file_path,
                    br.affected_resource_evidence.line_start,
                    br.affected_resource_evidence.line_end,
                ),
            }
            candidate_items.append((f_br, spans))

        # 17. Data State Comparisons
        for dsc in assessment_obj.data_state_comparisons:
            f_dsc = DataStateComparisonFact(
                entity_id=dsc.entity_id,
                dat_record_value=dsc.dat_record_value,
                initializer_code_value=dsc.initializer_code_value,
                causal_provenance=dsc.causal_provenance,
            )
            _assert_canonical(dsc.entity_id, f_dsc.entity_id, "entity_id")
            _assert_canonical(dsc.dat_record_value, f_dsc.dat_record_value, "dat_record_value")
            _assert_canonical(
                dsc.initializer_code_value, f_dsc.initializer_code_value, "initializer_code_value"
            )
            _assert_canonical(dsc.causal_provenance, f_dsc.causal_provenance, "causal_provenance")
            spans = {
                "dat_evidence": EvidenceSpan(
                    dsc.dat_evidence.file_path,
                    dsc.dat_evidence.line_start,
                    dsc.dat_evidence.line_end,
                ),
                "initializer_evidence": EvidenceSpan(
                    dsc.initializer_evidence.file_path,
                    dsc.initializer_evidence.line_start,
                    dsc.initializer_evidence.line_end,
                ),
            }
            candidate_items.append((f_dsc, spans))

        # Evaluation counters
        evaluated_predictions: list[EvaluatedPrediction] = []
        seen_assertions: set[str] = set()
        seen_supported_assertions: set[str] = set()
        matched_golden_ids: set[str] = set()
        supported_count = 0
        unsupported_count = 0
        invalid_evidence_count = 0
        duplicate_count = 0
        contradiction_count = 0

        raw_predicted_count = len(candidate_items)

        for fact, spans in candidate_items:
            key = fact.semantic_key()

            # Attempt to resolve canonical paths for all role spans
            canon_spans: dict[str, EvidenceSpan] = {}
            path_error: str | None = None

            for role_name, span in spans.items():
                try:
                    canon_file = self.support_index.bundle.resolve_canonical_file_path(
                        span.file_path
                    )
                    canon_spans[role_name] = EvidenceSpan(
                        canon_file, span.line_start, span.line_end
                    )
                except ValueError as ve:
                    path_error = f"Ambiguous file alias in role '{role_name}': {ve}"
                    canon_spans[role_name] = EvidenceSpan(
                        span.file_path.replace("\\", "/"), span.line_start, span.line_end
                    )
                except KeyError as ke:
                    path_error = f"Unknown file path in role '{role_name}': {ke}"
                    canon_spans[role_name] = EvidenceSpan(
                        span.file_path.replace("\\", "/"), span.line_start, span.line_end
                    )

            # Duplicate signature MUST be built from canonical span coordinates
            span_sig = f"{key}|" + "|".join(
                f"{r}:{s.file_path}:{s.line_start}-{s.line_end}"
                for r, s in sorted(canon_spans.items())
            )
            is_dup = span_sig in seen_assertions
            if is_dup:
                duplicate_count += 1
            seen_assertions.add(span_sig)

            primary_span = next(iter(canon_spans.values()))

            # If alias was unknown or ambiguous, fail deterministically without crashing
            if path_error is not None:
                invalid_evidence_count += 1
                unsupported_count += 1
                evaluated_predictions.append(
                    EvaluatedPrediction(
                        fact_category=fact.fact_category,
                        semantic_key=key,
                        file_path=primary_span.file_path,
                        line_start=primary_span.line_start,
                        line_end=primary_span.line_end,
                        is_supported=False,
                        is_duplicate=is_dup,
                        is_contradiction=False,
                        rejection_reason=path_error,
                        matched_proposition_id=None,
                    )
                )
                continue

            # Verify coordinate bounds
            has_invalid_bounds = any(
                s.line_start > s.line_end or s.line_start <= 0 for s in canon_spans.values()
            )
            if has_invalid_bounds:
                invalid_evidence_count += 1
                unsupported_count += 1
                evaluated_predictions.append(
                    EvaluatedPrediction(
                        fact_category=fact.fact_category,
                        semantic_key=key,
                        file_path=primary_span.file_path,
                        line_start=primary_span.line_start,
                        line_end=primary_span.line_end,
                        is_supported=False,
                        is_duplicate=is_dup,
                        is_contradiction=False,
                        rejection_reason="Invalid coordinate bounds",
                        matched_proposition_id=None,
                    )
                )
                continue

            # Verify against support index using canonical spans
            is_supp, reason, matched_sf = self.support_index.verify_role_bound_assertion(
                fact, canon_spans
            )

            if is_supp and matched_sf:
                supported_count += 1
                seen_supported_assertions.add(span_sig)
                matched_id = matched_sf.proposition_id
                cand_sig = tuple(
                    sorted(
                        (r, s.file_path, s.line_start, s.line_end) for r, s in canon_spans.items()
                    )
                )
                if (key, cand_sig) in self.golden_by_key_and_spans:
                    matched_id = self.golden_by_key_and_spans[(key, cand_sig)]
                    matched_golden_ids.add(matched_id)
                elif matched_id in self.golden_by_id:
                    matched_golden_ids.add(matched_id)

                evaluated_predictions.append(
                    EvaluatedPrediction(
                        fact_category=fact.fact_category,
                        semantic_key=key,
                        file_path=primary_span.file_path,
                        line_start=primary_span.line_start,
                        line_end=primary_span.line_end,
                        is_supported=True,
                        is_duplicate=is_dup,
                        is_contradiction=False,
                        rejection_reason=None,
                        matched_proposition_id=matched_id,
                    )
                )
            else:
                unsupported_count += 1
                evaluated_predictions.append(
                    EvaluatedPrediction(
                        fact_category=fact.fact_category,
                        semantic_key=key,
                        file_path=primary_span.file_path,
                        line_start=primary_span.line_start,
                        line_end=primary_span.line_end,
                        is_supported=False,
                        is_duplicate=is_dup,
                        is_contradiction=False,
                        rejection_reason=reason,
                        matched_proposition_id=None,
                    )
                )

        unique_predicted_count = len(seen_assertions)
        supported_unique_count = len(seen_supported_assertions)
        required_golden_ids = {p["id"] for p in self.required_golden_propositions}
        matched_required_golden_ids = matched_golden_ids & required_golden_ids
        matched_expected_count = len(matched_required_golden_ids)
        missing_expected_count = self.expected_fact_count - matched_expected_count

        precision = (
            supported_unique_count / unique_predicted_count if unique_predicted_count > 0 else 1.0
        )
        recall = (
            matched_expected_count / self.expected_fact_count
            if self.expected_fact_count > 0
            else 1.0
        )

        gate_3_pass = (
            precision == 1.0
            and recall == 1.0
            and unsupported_count == 0
            and invalid_evidence_count == 0
            and contradiction_count == 0
            and duplicate_count == 0
        )

        metrics = EvaluationMetricSummary(
            raw_predicted_count=raw_predicted_count,
            unique_predicted_count=unique_predicted_count,
            supported_predicted_count=supported_unique_count,
            unsupported_predicted_count=unsupported_count,
            invalid_evidence_count=invalid_evidence_count,
            duplicate_prediction_count=duplicate_count,
            contradiction_count=contradiction_count,
            matched_expected_count=matched_expected_count,
            missing_expected_count=missing_expected_count,
            expected_fact_count=self.expected_fact_count,
            precision=precision,
            recall=recall,
            gate_3_pass=gate_3_pass,
        )

        return metrics, evaluated_predictions


def load_golden_assessment(golden_dataset_path: Path | None = None) -> SystemAssessment:
    """Load the independently authored frozen golden dataset as a SystemAssessment object."""
    from agents.legacy_analyzer.schemas.system_assessment import (
        BehavioralRisk,
        CallEdge,
        CallerContinuationConstraint,
        CallOccurrence,
        CommandInvocation,
        ComputationDataflow,
        DataStateComparison,
        DataTransferRelation,
        FileBinding,
        FileOperation,
        InternalCallResolution,
        OperationSequence,
        PlatformDependency,
        ProgramDeclaration,
        RecordField,
        RecordLayout,
        RecordLayoutRelation,
        ResourceLifecycle,
        SourceEvidence,
        TerminationSite,
    )

    if golden_dataset_path is None:
        golden_dataset_path = (
            Path(__file__).resolve().parent.parent.parent
            / "evals"
            / "expected"
            / "system-understanding-v3.json"
        )
    data = json.loads(golden_dataset_path.read_text(encoding="utf-8"))

    def make_ev(d: dict[str, Any]) -> SourceEvidence:
        return SourceEvidence(
            file_path=d["file_path"], line_start=d["line_start"], line_end=d["line_end"]
        )

    assessment = SystemAssessment(system_name="Core Banking System")

    for p in data["propositions"]:
        cat = p["category"]
        key = p["semantic_key"]
        spans = p["evidence_spans"]

        if cat == "PROGRAM_DECLARATION":
            prog = key.split(":", 1)[1]
            assessment.program_declarations.append(
                ProgramDeclaration(program_id=prog, evidence=make_ev(spans["evidence"]))
            )
        elif cat == "CALL_OCCURRENCE":
            parts = key.split(":")
            caller, target = parts[1].split("->")
            mech = parts[2]
            arg = parts[3] if len(parts) > 3 else None
            assessment.call_occurrences.append(
                CallOccurrence(
                    caller_program=caller,
                    target_program=target,
                    call_mechanism=mech,
                    argument_identifier=arg,
                    evidence=make_ev(spans["evidence"]),
                )
            )
        elif cat == "CALL_EDGE":
            parts = key.split(":")
            caller, target = parts[1].split("->")
            mech = parts[2]
            assessment.call_edges.append(
                CallEdge(
                    caller_program=caller,
                    target_program=target,
                    call_mechanism=mech,
                    evidence=make_ev(spans["evidence"]),
                )
            )
        elif cat == "INTERNAL_CALL_RESOLUTION":
            caller, callee = key.split(":", 1)[1].split("->")
            assessment.internal_call_resolutions.append(
                InternalCallResolution(
                    caller_program=caller,
                    callee_program=callee,
                    call_evidence=make_ev(spans["call_evidence"]),
                    target_declaration_evidence=make_ev(spans["target_declaration_evidence"]),
                )
            )
        elif cat == "FILE_BINDING":
            parts = key.split(":")
            prog = parts[1]
            internal_file = parts[2]
            external_file = parts[3]
            org = parts[4]
            assessment.file_bindings.append(
                FileBinding(
                    program_id=prog,
                    internal_file_name=internal_file,
                    external_file_name=external_file,
                    organization=org,
                    evidence=make_ev(spans["evidence"]),
                )
            )
        elif cat == "RECORD_LAYOUT":
            parts = key.split(":")
            raw_fields = p.get("fields", [])
            field_objs = []
            for rf in raw_fields:
                field_objs.append(
                    RecordField(
                        field_kind=rf.get("field_kind", "DATA_FIELD"),
                        level=rf["level"],
                        name=rf["name"],
                        picture=rf.get("picture"),
                        usage=rf.get("usage"),
                        condition_values=rf.get("condition_values", []),
                    )
                )
            assessment.record_layouts.append(
                RecordLayout(
                    program_id=parts[1],
                    record_name=parts[2],
                    fields=field_objs,
                    evidence=make_ev(spans["evidence"]),
                )
            )
        elif cat == "FILE_OPERATION":
            parts = key.split(":")
            prog = parts[1]
            internal_f = parts[2]
            verb = parts[3]
            assessment.file_operations.append(
                FileOperation(
                    program_id=prog,
                    internal_file_name=internal_f,
                    operation_verb=verb,
                    evidence=make_ev(spans["evidence"]),
                )
            )
        elif cat == "RECORD_LAYOUT_RELATION":
            parts = key.split(":")
            layout_a = f"{parts[1]}:{parts[2]}"
            layout_b = f"{parts[3]}:{parts[4]}"
            rel_type = parts[5]
            assessment.record_layout_relations.append(
                RecordLayoutRelation(
                    layout_a_name=layout_a,
                    layout_b_name=layout_b,
                    relation_type=rel_type,
                    evidence_a=make_ev(spans["evidence_a"]),
                    evidence_b=make_ev(spans["evidence_b"]),
                )
            )
        elif cat == "TERMINATION_SITE":
            parts = key.split(":")
            assessment.termination_sites.append(
                TerminationSite(
                    program_id=parts[1],
                    statement_type=parts[2],
                    evidence=make_ev(spans["evidence"]),
                )
            )
        elif cat == "CALLER_CONTINUATION_CONSTRAINT":
            parts = key.split(":")
            caller, callee = parts[1].split("->")
            assessment.caller_continuation_constraints.append(
                CallerContinuationConstraint(
                    caller_program=caller,
                    callee_program=callee,
                    constraint_type=parts[2],
                    call_evidence=make_ev(spans["call_evidence"]),
                    callee_termination_evidence=make_ev(spans["callee_termination_evidence"]),
                )
            )
        elif cat == "COMMAND_INVOCATION":
            parts = key.split(":")
            assessment.command_invocations.append(
                CommandInvocation(
                    program_id=parts[1],
                    command_template=parts[2],
                    target_operand=parts[3],
                    assignment_evidence=make_ev(spans["assignment_evidence"]),
                    call_evidence=make_ev(spans["call_evidence"]),
                )
            )
        elif cat == "DATA_TRANSFER_RELATION":
            parts = key.split(":")
            prog = parts[1]
            src, tgt = parts[2].split("->")
            verb = parts[3]
            assessment.data_transfer_relations.append(
                DataTransferRelation(
                    program_id=prog,
                    source_entity=src,
                    target_entity=tgt,
                    transfer_verb=verb,
                    evidence=make_ev(spans["evidence"]),
                )
            )
        elif cat == "RESOURCE_LIFECYCLE":
            parts = key.split(":")
            prog = parts[1]
            res = parts[2]
            mode = parts[3]
            ops = parts[4].strip("()").split("->")
            assessment.resource_lifecycles.append(
                ResourceLifecycle(
                    program_id=prog,
                    resource_name=res,
                    access_mode=mode,
                    ordered_operations=ops,
                    evidence=make_ev(spans["evidence"]),
                )
            )
        elif cat == "OPERATION_SEQUENCE":
            parts = key.split(":")
            prog = parts[1]
            op1, op2 = parts[2].split("->")
            assessment.operation_sequences.append(
                OperationSequence(
                    program_id=prog,
                    first_operation=op1,
                    second_operation=op2,
                    first_assignment_evidence=make_ev(spans["first_assignment_evidence"]),
                    first_call_evidence=make_ev(spans["first_call_evidence"]),
                    second_assignment_evidence=make_ev(spans["second_assignment_evidence"]),
                    second_call_evidence=make_ev(spans["second_call_evidence"]),
                )
            )
        elif cat == "COMPUTATION_DATAFLOW":
            parts = key.split(":")
            prog = parts[1]
            src, tgt = parts[2].split("->")
            verb = parts[3]
            assessment.computation_dataflows.append(
                ComputationDataflow(
                    program_id=prog,
                    source_field=src,
                    target_field=tgt,
                    operation_verb=verb,
                    evidence=make_ev(spans["evidence"]),
                )
            )
        elif cat == "PLATFORM_DEPENDENCY":
            parts = key.split(":")
            prog = parts[1]
            fam = parts[2]
            cmd = ":".join(parts[3:])
            assessment.platform_dependencies.append(
                PlatformDependency(
                    program_id=prog,
                    platform_family=fam,
                    command_literal=cmd,
                    evidence=make_ev(spans["evidence"]),
                )
            )
        elif cat == "BEHAVIORAL_RISK":
            parts = key.split(":")
            prog = parts[1]
            cat_risk = parts[2]
            basis_kind = parts[3]
            impact = parts[4]
            res_name = parts[5] if len(parts) > 5 else None
            assessment.behavioral_risks.append(
                BehavioralRisk(
                    program_id=prog,
                    risk_category=cat_risk,
                    risk_basis_kind=basis_kind,
                    impact_category=impact,
                    resource_name=res_name,
                    operation_evidence=make_ev(spans["operation_evidence"]),
                    affected_resource_evidence=make_ev(spans["affected_resource_evidence"]),
                )
            )
        elif cat == "DATA_STATE_COMPARISON":
            parts = key.split(":")
            ent = parts[1]
            dat_val = parts[2]
            init_val = parts[3]
            prov = parts[4]
            assessment.data_state_comparisons.append(
                DataStateComparison(
                    entity_id=ent,
                    dat_record_value=dat_val,
                    initializer_code_value=init_val,
                    causal_provenance=prov,
                    dat_evidence=make_ev(spans["dat_evidence"]),
                    initializer_evidence=make_ev(spans["initializer_evidence"]),
                )
            )

    return assessment
