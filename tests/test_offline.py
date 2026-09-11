"""General offline integration tests for legacy analyzer agent components."""

from typing import get_args

from agents.legacy_analyzer.agent import LegacyAnalyzerAgent, ReasoningEffort
from agents.legacy_analyzer.config import FoundryConfig
from evals.fixtures.synthetic_assessments import (
    make_perfect_assessment_v1,
    make_perfect_assessment_v2,
)


def test_agent_initialization():
    cfg = FoundryConfig(
        foundry_project_endpoint="https://example.services.ai.azure.com/api/projects/test-proj",
        foundry_model="gpt-5-mini",
    )
    agent = LegacyAnalyzerAgent(config=cfg, reasoning_effort="low")
    assert agent.config.foundry_model == "gpt-5-mini"
    assert agent.reasoning_effort == "low"
    assert len(agent.system_prompt) > 0


def test_schema_v2_field_presence():
    from agents.legacy_analyzer.agent import ExecutionMetadata

    meta = ExecutionMetadata()
    assert meta.schema_version == "2.2.0"
    assert meta.prompt_version == "gate2-baseline-v2.2"
    assert meta.evaluator_version == "2.3.0"
    assert hasattr(meta, "foundry_project_fingerprint")
    assert not hasattr(meta, "endpoint") or "endpoint" not in meta.__dict__

    assessment = make_perfect_assessment_v2()
    assert assessment.program.program_id == "BANK-MAIN"
    assert len(assessment.call_dependencies) == 3
    assert len(assessment.menu_options) == 5
    assert len(assessment.control_flow) == 3
    assert len(assessment.io_operations) == 1
    assert assessment.copybook_dependencies == []


def test_schema_v1_backwards_compatibility():
    assessment_v1 = make_perfect_assessment_v1()
    assert assessment_v1.schema_version == "1.0.0"
    assert assessment_v1.scope.analyzed_file.endswith("BANK-MAIN.CBL")
    assert len(assessment_v1.observations) >= 1
    assert len(assessment_v1.unsupported_assumptions) >= 1


def test_reasoning_effort_type_contract():
    valid_efforts = get_args(ReasoningEffort)
    assert "low" in valid_efforts
    assert "medium" in valid_efforts
    assert "high" in valid_efforts
    assert "none" in valid_efforts
    assert "max" in valid_efforts
    assert "minimal" in valid_efforts
    assert "xhigh" in valid_efforts
    assert "invalid_effort" not in valid_efforts
