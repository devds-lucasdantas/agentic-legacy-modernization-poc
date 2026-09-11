"""Configuration for the legacy-analyzer agent.

Reads environment variables with validation. Both FOUNDRY_PROJECT_ENDPOINT
and FOUNDRY_MODEL are required — no hardcoded defaults for model selection.
"""

import hashlib
import re
import urllib.parse

from pydantic_settings import BaseSettings

HEX_64_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def normalize_foundry_endpoint(endpoint: str) -> str:
    """Canonical normalization of Azure AI Foundry project endpoint per Amendment 2.

    Conceptually:
    - trim external whitespace;
    - require HTTPS;
    - lowercase scheme and hostname;
    - normalize/remove default port if present (443);
    - remove a single insignificant trailing slash;
    - preserve project/path identity and casing (do not lowercase blindly);
    - reject unexpected userinfo;
    - reject unexpected query string;
    - reject fragment.

    Raises:
        ValueError: If endpoint fails any structural validation.
    """
    s = endpoint.strip()
    if not s:
        raise ValueError("Foundry endpoint string is empty.")

    parsed = urllib.parse.urlsplit(s)

    scheme = parsed.scheme.lower()
    if scheme != "https":
        raise ValueError(
            f"Disallowed endpoint scheme '{parsed.scheme}'. "
            "Only HTTPS is permitted for Foundry endpoints."
        )

    if parsed.username or parsed.password:
        raise ValueError("Foundry endpoint contains disallowed userinfo credentials.")

    if parsed.query:
        raise ValueError("Foundry endpoint contains disallowed query parameters.")

    if parsed.fragment:
        raise ValueError("Foundry endpoint contains disallowed fragment identifier.")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("Foundry endpoint is missing valid hostname.")

    port = parsed.port
    if port is not None and port != 443:
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname

    path = parsed.path
    if path.endswith("/") and len(path) > 1:
        path = path[:-1]
    elif path == "/":
        path = ""

    return f"https://{netloc}{path}"


def compute_foundry_project_fingerprint(endpoint: str) -> str:
    """Compute SHA256 hex digest of canonically normalized Foundry project endpoint."""
    norm = normalize_foundry_endpoint(endpoint)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def validate_project_fingerprint_format(fingerprint: str) -> None:
    """Validate project fingerprint format as exactly 64 hexadecimal characters."""
    if not HEX_64_PATTERN.fullmatch(fingerprint):
        raise ValueError(
            f"Invalid project fingerprint '{fingerprint}'. "
            "Must be exactly 64 lowercase hexadecimal SHA256 characters."
        )


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

    @property
    def project_fingerprint(self) -> str:
        """Deterministic normalized project identity fingerprint."""
        return compute_foundry_project_fingerprint(self.foundry_project_endpoint)


def load_config() -> FoundryConfig:
    """Load and validate Foundry configuration from environment.

    Raises:
        ValidationError: If required environment variables are missing.
    """
    return FoundryConfig()  # type: ignore[call-arg]
