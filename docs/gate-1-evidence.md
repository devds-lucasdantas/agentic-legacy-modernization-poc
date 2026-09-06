# Gate 1 — Hello Foundry — Evidence

## Result: PASS

| Field | Value |
|---|---|
| Date | 2026-09-06 |
| Subscription | Azure for Students (`<subscription-id>`) |
| Environment | WSL (Ubuntu 24.04), Python 3.12.3 |
| Resource Group | `rg-legacy-modernization` |
| Region | `brazilsouth` |
| Foundry Resource | `<foundry-resource-name>` (`AIServices` S0) |
| Foundry Project | `legacy-modernization` (`Microsoft.CognitiveServices/accounts/projects`) |
| Logical Endpoint | `https://<foundry-resource-endpoint>.services.ai.azure.com` |
| Model Deployment | `gpt-5-mini` |
| Model Version | `2025-08-07` |
| Deployment SKU | `GlobalStandard` (capacity: 10 = 10K TPM) |
| Contract API | OpenAI Responses API (`openai_client.responses.create`) |
| Script | `python scripts/hello-foundry.py` |
| Response ID | `<response-id>` |
| Elapsed Time | 11.50s |
| Response Output | `Hello from Azure AI Foundry` |
| Input Tokens | 19 |
| Output Tokens | 248 (includes reasoning and output tokens) |
| Total Tokens | 267 |

> **Repository Hygiene & Privacy Note:** The Azure Subscription ID, live Foundry resource name, live endpoint URL, and Response ID have been replaced with placeholders for repository hygiene and infrastructure privacy. The endpoint is not a credential (access strictly requires Microsoft Entra ID authentication and Azure RBAC authorization), but live endpoint URLs and server-side execution IDs are redacted to prevent unnecessary external probing.

## Execution Log

```text
Endpoint: https://<foundry-resource-endpoint>.services.ai.azure.com
Model:    gpt-5-mini

[OK] DefaultAzureCredential created
[OK] AIProjectClient connected
[OK] OpenAI client obtained

--- Calling Responses API ---
[OK] Response received in 11.50s

Response: Hello from Azure AI Foundry

--- Metadata ---
{
  "gate": "1",
  "status": "PASS",
  "model": "gpt-5-mini",
  "endpoint": "https://<foundry-resource-endpoint>.services.ai.azure.com",
  "response_id": "<response-id>",
  "elapsed_seconds": 11.5,
  "input_tokens": 19,
  "output_tokens": 248,
  "total_tokens": 267
}
```

## Model Selection & Quota Investigation

During the Gate 1 discovery phase, all permitted regions (`brazilsouth`, `canadacentral`, `centralus`, `spaincentral`, `southafricanorth`) were scanned for quotas:

| Model | Status in Catalog | Default Quota in Subscription | Decision |
|---|---|---|---|
| `gpt-5-mini` (`2025-08-07`) | GenerallyAvailable | **500K TPM** (GlobalStandard) | **SELECTED** — Immediate active quota, no request required, supports Responses API & Structured Outputs. |
| `gpt-5.4-mini` (`2026-03-17`) | GenerallyAvailable | **0 TPM** (All 5 allowed regions) | **Registered candidate** for future comparative evals (requires manual quota request). |
| `gpt-5.6-luna` (`2026-07-09`) | GenerallyAvailable | **0 TPM** (All 5 allowed regions) | **Registered candidate** for future reasoning evals (requires manual quota request). |
| `gpt-4.1-mini` (`2025-04-14`) | Legacy | 200K TPM | Rejected due to Legacy lifecycle status. |
| `gpt-4o-mini` (`2024-07-18`) | Deprecating | 0 TPM | Rejected due to Deprecating lifecycle status. |

## Verification Criteria Met

- [x] End-to-end path validated: Python (`azure-ai-projects` + `azure-identity`) → Azure AI Foundry → Responses API → LLM response.
- [x] Modern Foundry architecture deployed without legacy AI Hub.
- [x] Strict cost controls respected: Global Standard pay-as-you-go, no PTU/provisioned capacity, no fixed-cost resources.
- [x] Responses API contract confirmed for Gates 2–3 agent development.
