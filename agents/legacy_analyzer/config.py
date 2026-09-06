"""Configuration for the legacy-analyzer agent.

Reads environment variables with validation. Both FOUNDRY_PROJECT_ENDPOINT
and FOUNDRY_MODEL are required — no hardcoded defaults for model selection.
"""

from pydantic_settings import BaseSettings


class FoundryConfig(BaseSettings):
    """Azure AI Foundry connection settings.

    All values are read from environment variables (or a .env file).
    """

    foundry_project_endpoint: str
    """Foundry project endpoint.
    Format: https://<resource>.services.ai.azure.com/api/projects/<project>
    """

    foundry_model: str
    """Model deployment name. Determined during Gate 1 based on
    region availability, quota, and Responses API / Structured Output support.
    """

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


def load_config() -> FoundryConfig:
    """Load and validate Foundry configuration from environment.

    Raises:
        ValidationError: If required environment variables are missing.
    """
    return FoundryConfig()  # type: ignore[call-arg]
