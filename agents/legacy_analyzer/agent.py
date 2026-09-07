"""Legacy Analyzer Agent — executes single-file COBOL analysis via Azure AI Foundry.

Enforces:
- Scope allowlist validation
- Read-only deterministic source preparation with line numbers
- SHA256 provenance calculation
- OpenAI Responses API native Structured Outputs with Pydantic v2
- Execution metadata collection
"""

import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from openai import OpenAI
from openai.types.shared_params import Reasoning

from agents.legacy_analyzer.config import FoundryConfig, load_config
from agents.legacy_analyzer.schemas.assessment import LegacyAssessment
from src.cobol.source_reader import (
    PreparedSource,
    prepare_source,
)


@dataclass
class ExecutionMetadata:
    """Execution metadata for an analysis run."""

    gate: str = "2"
    run_label: str = "baseline-v1"
    timestamp: str = ""
    model: str = ""
    model_version: str | None = None
    reasoning_effort: str = "low"
    source_file: str = ""
    source_sha256: str = ""
    git_commit_sha: str = ""
    schema_version: str = "1.0.0"
    prompt_version: str = "gate2-baseline-v1"
    evaluator_version: str = "1.1.0"
    response_id: str | None = None
    elapsed_seconds: float = 0.0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    schema_valid: bool = False
    endpoint: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert metadata to dictionary."""
        return asdict(self)


def load_system_prompt() -> str:
    """Load the system prompt markdown file."""
    prompt_path = Path(__file__).resolve().parent / "prompts" / "system.md"
    return prompt_path.read_text(encoding="utf-8")


class LegacyAnalyzerAgent:
    """Agent that performs single-file COBOL analysis using Azure AI Foundry Responses API."""

    def __init__(
        self,
        config: FoundryConfig | None = None,
        system_prompt: str | None = None,
        reasoning_effort: str = "low",
    ) -> None:
        self.config = config or load_config()
        self.system_prompt = system_prompt or load_system_prompt()
        self.reasoning_effort = reasoning_effort
        self._openai_client: OpenAI | None = None

    def _get_openai_client(self) -> OpenAI:
        """Lazy-initialize the authenticated OpenAI client from Foundry project."""
        if self._openai_client is None:
            from azure.ai.projects import AIProjectClient
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
            project_client = AIProjectClient(
                endpoint=self.config.foundry_project_endpoint,
                credential=credential,
            )
            self._openai_client = project_client.get_openai_client()
        return self._openai_client

    def analyze_source(
        self,
        source_path: str | Path = "legacy/core-banking-system/BANK-MAIN.CBL",
        run_label: str = "baseline-v1",
        repo_root: Path | None = None,
        git_commit_sha: str = "",
    ) -> tuple[LegacyAssessment, ExecutionMetadata]:
        """Analyze a permitted COBOL source file and return structured assessment and metadata.

        Args:
            source_path: Path to target source file (must be allowlisted).
            run_label: Identifier for this run, e.g. 'baseline-v1'.
            repo_root: Optional repository root path.
            git_commit_sha: Git commit SHA of the frozen baseline code.

        Returns:
            Tuple of (LegacyAssessment, ExecutionMetadata).
        """
        # 1. Enforce scope and prepare source
        prep: PreparedSource = prepare_source(source_path, repo_root=repo_root)

        user_input = (
            f"Analyze the following COBOL source file: {prep.relative_path}\n"
            f"SHA256: {prep.sha256}\n\n"
            f"Numbered Source Code:\n"
            f"```cobol\n{prep.numbered_content}\n```\n"
        )

        metadata = ExecutionMetadata(
            gate="2",
            run_label=run_label,
            timestamp=datetime.now(UTC).isoformat(),
            model=self.config.foundry_model,
            reasoning_effort=self.reasoning_effort,
            source_file=prep.relative_path,
            source_sha256=prep.sha256,
            git_commit_sha=git_commit_sha,
            endpoint=self.config.foundry_project_endpoint,
        )

        openai_client = self._get_openai_client()

        # 2. Invoke Responses API with Structured Outputs
        start_time = time.time()

        parsed_response = openai_client.responses.parse(
            model=self.config.foundry_model,
            instructions=self.system_prompt,
            input=user_input,
            text_format=LegacyAssessment,
            reasoning=cast(Reasoning, {"effort": self.reasoning_effort}),
        )

        elapsed = time.time() - start_time
        metadata.elapsed_seconds = round(elapsed, 2)

        # 3. Extract parsed Pydantic object and API metadata
        assessment: LegacyAssessment | None = getattr(parsed_response, "output_parsed", None)
        if not isinstance(assessment, LegacyAssessment):
            output_text = getattr(parsed_response, "output_text", None)
            if output_text and isinstance(output_text, str):
                assessment = LegacyAssessment.model_validate_json(output_text)

        if not isinstance(assessment, LegacyAssessment):
            raise ValueError(f"Failed to parse LegacyAssessment from response: {parsed_response}")

        metadata.schema_valid = True
        metadata.response_id = getattr(parsed_response, "id", None)

        if hasattr(parsed_response, "usage") and parsed_response.usage is not None:
            metadata.input_tokens = getattr(parsed_response.usage, "input_tokens", None)
            metadata.output_tokens = getattr(parsed_response.usage, "output_tokens", None)
            metadata.total_tokens = getattr(parsed_response.usage, "total_tokens", None)

        return assessment, metadata
