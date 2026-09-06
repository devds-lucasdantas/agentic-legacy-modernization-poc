#!/usr/bin/env python3
"""Gate 1 — Hello Foundry

Minimal script to validate the end-to-end path:
  Python → Azure Identity → AI Foundry → Responses API → response.

Usage:
    # Ensure FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL are set
    python scripts/hello-foundry.py

Exit codes:
    0 = success (response received)
    1 = failure (auth, config, or API error)
"""

import json
import os
import sys
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def main() -> int:
    # --- Validate environment ---
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    model = os.environ.get("FOUNDRY_MODEL", "").strip()

    if not endpoint:
        print("ERROR: FOUNDRY_PROJECT_ENDPOINT is not set.")
        print("See docs/SETUP.md for instructions.")
        return 1

    if not model:
        print("ERROR: FOUNDRY_MODEL is not set.")
        print("Set it to the deployment name discovered during Foundry setup.")
        return 1

    print(f"Endpoint: {endpoint}")
    print(f"Model:    {model}")
    print()

    # --- Authenticate ---
    try:
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()
        print("[OK] DefaultAzureCredential created")
    except Exception as e:
        print(f"[FAIL] Authentication error: {e}")
        return 1

    # --- Connect to Foundry project ---
    try:
        from azure.ai.projects import AIProjectClient
        project_client = AIProjectClient(
            endpoint=endpoint,
            credential=credential,
        )
        print("[OK] AIProjectClient connected")
    except Exception as e:
        print(f"[FAIL] Foundry project connection error: {e}")
        return 1

    # --- Get OpenAI client and call Responses API ---
    try:
        openai_client = project_client.get_openai_client()
        print("[OK] OpenAI client obtained")
    except Exception as e:
        print(f"[FAIL] Failed to get OpenAI client: {e}")
        return 1

    print()
    print("--- Calling Responses API ---")
    start_time = time.time()

    try:
        response = openai_client.responses.create(
            model=model,
            input="Say 'Hello from Azure AI Foundry' and nothing else.",
        )
        elapsed = time.time() - start_time

        # Extract response text
        output_text = getattr(response, "output_text", None)
        if not output_text and hasattr(response, "output"):
            output_parts = []
            for item in response.output:
                if hasattr(item, "content"):
                    for content_part in item.content:
                        if hasattr(content_part, "text"):
                            output_parts.append(content_part.text)
            output_text = "".join(output_parts)

        print(f"[OK] Response received in {elapsed:.2f}s")
        print()
        print(f"Response: {output_text}")
        print()

        # --- Report metadata ---
        metadata = {
            "gate": "1",
            "status": "PASS",
            "model": model,
            "endpoint": endpoint,
            "response_id": getattr(response, "id", None),
            "elapsed_seconds": round(elapsed, 2),
        }

        # Try to extract usage info if available
        if hasattr(response, "usage") and response.usage is not None:
            metadata["input_tokens"] = getattr(response.usage, "input_tokens", None)
            metadata["output_tokens"] = getattr(response.usage, "output_tokens", None)
            metadata["total_tokens"] = getattr(response.usage, "total_tokens", None)

        print("--- Metadata ---")
        print(json.dumps(metadata, indent=2))

        return 0

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"[FAIL] Responses API call failed after {elapsed:.2f}s: {e}")
        print()
        print(f"Error type: {type(e).__name__}")

        # Provide diagnostic hints
        error_str = str(e).lower()
        if "401" in error_str or "unauthorized" in error_str:
            print("HINT: Check that your Azure CLI login has access to the Foundry project.")
        elif "404" in error_str or "not found" in error_str:
            print("HINT: Check that FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL are correct.")
        elif "quota" in error_str or "429" in error_str:
            print("HINT: Quota exceeded. Check your model deployment quota in Azure Portal.")
        elif "disallowed" in error_str or "policy" in error_str:
            print("HINT: Your subscription may restrict AI services in this region.")
            print("Check Azure Portal → Policy → Assignments → 'Allowed resource deployment regions'.")

        return 1


if __name__ == "__main__":
    sys.exit(main())
