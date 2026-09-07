"""General offline integration tests for legacy analyzer agent components."""

from agents.legacy_analyzer.agent import LegacyAnalyzerAgent
from agents.legacy_analyzer.config import FoundryConfig
from evals.fixtures.synthetic_assessments import make_perfect_assessment


def test_agent_initialization():
    cfg = FoundryConfig(
        foundry_project_endpoint="https://example.services.ai.azure.com/api/projects/test-proj",
        foundry_model="gpt-5-mini",
    )
    agent = LegacyAnalyzerAgent(config=cfg, reasoning_effort="low")
    assert agent.config.foundry_model == "gpt-5-mini"
    assert agent.reasoning_effort == "low"
    assert len(agent.system_prompt) > 0


def test_schema_field_presence():
    assessment = make_perfect_assessment()
    assert assessment.schema_version == "1.0.0"
    assert assessment.scope.analyzed_file.endswith("BANK-MAIN.CBL")
    assert assessment.program.program_id == "BANK-MAIN"
    assert len(assessment.call_dependencies) == 3
    assert len(assessment.menu_options) == 5
    assert len(assessment.control_flow) == 3
    assert len(assessment.io_operations) == 2
