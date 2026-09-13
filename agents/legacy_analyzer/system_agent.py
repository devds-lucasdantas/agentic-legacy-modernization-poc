"""Gate 3 System Analyzer Agent.

Executes multi-file COBOL analysis via Azure AI Foundry Responses API.

Enforces:
- Structured Outputs via OpenAI Responses API with SystemAssessment
- Reasoning effort binding ("low")
- Exactly one invocation attempt, zero client-side or application-side retries
- Provider refusal inspection
- Raw model output and token metrics capture
- Dry-run protection (no credentials loaded unless live execution authorized)
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from openai import OpenAI
from openai.types.responses import ResponseOutputRefusal
from openai.types.shared_params import Reasoning

from agents.legacy_analyzer.config import FoundryConfig, load_config
from agents.legacy_analyzer.schemas.system_assessment import (
    SCHEMA_VERSION,
    SystemAssessment,
)
from src.cobol.multi_source_reader import MultiSourceBundle, read_system_bundle
from src.validation.evaluator_v3 import EVALUATOR_VERSION

PROMPT_VERSION: str = "3.5.3"

ReasoningEffort = Literal[
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
]


class ResponseRefusedError(ValueError):
    """Raised when model response contains native refusal content."""


@dataclass
class SystemExecutionMetadata:
    """Execution metadata for a Gate 3 analysis run."""

    gate: str = "3"
    run_label: str = "baseline-v1"
    timestamp: str = ""
    model: str = ""
    requested_model: str = ""
    response_model_id: str | None = None
    model_version: str | None = None
    reasoning_effort: ReasoningEffort = "low"
    git_commit_sha: str = ""
    schema_version: str = SCHEMA_VERSION
    prompt_version: str = PROMPT_VERSION
    evaluator_version: str = EVALUATOR_VERSION
    response_id: str | None = None
    elapsed_seconds: float = 0.0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    schema_valid: bool = False
    foundry_project_fingerprint: str = ""
    raw_response_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert metadata to dictionary."""
        return asdict(self)


def load_system_v3_prompt(prompt_path: Path | None = None) -> str:
    """Load the Gate 3 system prompt markdown file."""
    path = prompt_path or (Path(__file__).resolve().parent / "prompts" / "system_v3.md")
    return path.read_text(encoding="utf-8")


def inspect_response_for_refusal(response: Any) -> None:
    """Traverse OpenAI Responses API response and reject native refusal content anywhere."""
    if getattr(response, "refusal", None):
        raise ResponseRefusedError("Model response was refused by provider policy.")

    output = getattr(response, "output", None)
    if isinstance(output, list):
        for item in output:
            if isinstance(item, ResponseOutputRefusal) or getattr(item, "type", None) == "refusal":
                raise ResponseRefusedError("Model response was refused by provider policy.")
            if getattr(item, "refusal", None):
                raise ResponseRefusedError("Model response was refused by provider policy.")
            content = getattr(item, "content", None)
            if isinstance(content, list):
                for c_item in content:
                    if getattr(c_item, "type", None) == "refusal" or getattr(
                        c_item, "refusal", None
                    ):
                        raise ResponseRefusedError("Model response was refused by provider policy.")


class SystemAnalyzerAgent:
    """Gate 3 agent coordinating multi-file legacy system analysis."""

    def __init__(
        self,
        config: FoundryConfig | None = None,
        reasoning_effort: ReasoningEffort = "low",
        system_prompt: str | None = None,
    ) -> None:
        self.config = config or load_config()
        self.reasoning_effort = reasoning_effort
        self.system_prompt = system_prompt or load_system_v3_prompt()
        self._openai_client: OpenAI | None = None

    def _get_openai_client(self) -> OpenAI:
        """Lazy-initialize OpenAI client via Azure AI Foundry with max_retries=0."""
        if self._openai_client is None:
            from azure.ai.projects import AIProjectClient
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
            project_client = AIProjectClient(
                endpoint=self.config.foundry_project_endpoint,
                credential=credential,
            )
            client = project_client.get_openai_client()
            client.max_retries = 0
            self._openai_client = client
        return self._openai_client

    def format_bundle_prompt(self, bundle: MultiSourceBundle) -> str:
        """Format the multi-file bundle into input text for the Responses API."""
        return bundle.formatted_prompt_payload

    def invoke_raw(
        self,
        bundle: MultiSourceBundle | None = None,
        run_label: str = "baseline-v1",
        repo_root: Path | None = None,
        git_commit_sha: str = "",
    ) -> tuple[Any, SystemExecutionMetadata, str]:
        """Execute live Responses API analysis using create-style method before any parsing.

        Uses exact frozen Structured Outputs wire schema via text_format.
        Returns (raw_response_object, metadata, raw_response_json_str).
        """
        import json

        from agents.legacy_analyzer.schemas.system_export import (
            get_system_responses_text_format,
        )

        repo_dir = repo_root or Path.cwd()
        effective_bundle = bundle or read_system_bundle(repo_dir)

        metadata = SystemExecutionMetadata(
            gate="3",
            run_label=run_label,
            timestamp=datetime.now(UTC).isoformat(),
            model=self.config.foundry_model,
            requested_model=self.config.foundry_model,
            reasoning_effort=self.reasoning_effort,
            git_commit_sha=git_commit_sha,
            foundry_project_fingerprint=self.config.project_fingerprint,
        )

        user_input = self.format_bundle_prompt(effective_bundle)
        openai_client = self._get_openai_client()
        responses_format = get_system_responses_text_format()

        start_time = time.time()
        reasoning: Reasoning = {"effort": self.reasoning_effort}

        response = openai_client.responses.create(  # type: ignore[call-overload]
            model=self.config.foundry_model,
            instructions=self.system_prompt,
            input=user_input,
            text={"format": responses_format},
            reasoning=reasoning,
        )

        elapsed = time.time() - start_time
        metadata.elapsed_seconds = round(elapsed, 2)
        metadata.response_id = getattr(response, "id", None)
        metadata.response_model_id = getattr(response, "model", None)

        if hasattr(response, "usage") and response.usage is not None:
            metadata.input_tokens = getattr(response.usage, "input_tokens", None)
            metadata.output_tokens = getattr(response.usage, "output_tokens", None)
            metadata.total_tokens = getattr(response.usage, "total_tokens", None)

        try:
            raw_response_text = response.model_dump_json(indent=2)
        except Exception:
            raw_response_text = json.dumps(response, default=str, indent=2)

        metadata.raw_response_text = raw_response_text
        return response, metadata, raw_response_text

    def validate_and_parse_response(
        self,
        response: Any,
        metadata: SystemExecutionMetadata,
        requested_model: str,
    ) -> SystemAssessment:
        """Validate status, refusal, response-model, and parse structured output into
        SystemAssessment.
        """
        status = getattr(response, "status", None)
        if status != "completed":
            raise ValueError(f"Model response did not complete successfully: status='{status}'")

        inspect_response_for_refusal(response)

        response_model = getattr(response, "model", None)
        if response_model != requested_model:
            raise ValueError(
                f"Response model ID '{response_model}' does not match "
                f"requested model '{requested_model}'"
            )

        output_text = None
        output = getattr(response, "output", None)
        if isinstance(output, list):
            for item in output:
                content = getattr(item, "content", None)
                if isinstance(content, list):
                    for c in content:
                        text_val = getattr(c, "text", None)
                        if text_val:
                            output_text = text_val
                            break
                elif getattr(item, "text", None):
                    output_text = getattr(item, "text")
                if output_text:
                    break

        if not output_text:
            raise ValueError("Responses API response did not contain structured output text.")

        assessment = SystemAssessment.model_validate_json(output_text)
        metadata.schema_valid = True
        return assessment

    def analyze_system(
        self,
        bundle: MultiSourceBundle | None = None,
        run_label: str = "baseline-v1",
        repo_root: Path | None = None,
        git_commit_sha: str = "",
    ) -> tuple[SystemAssessment, SystemExecutionMetadata]:
        """Execute live Responses API analysis across all files in the system bundle.

        Strictly single-attempt, zero automatic retry.
        """
        response, metadata, _raw_text = self.invoke_raw(
            bundle=bundle,
            run_label=run_label,
            repo_root=repo_root,
            git_commit_sha=git_commit_sha,
        )
        assessment = self.validate_and_parse_response(
            response=response,
            metadata=metadata,
            requested_model=metadata.requested_model,
        )
        return assessment, metadata
