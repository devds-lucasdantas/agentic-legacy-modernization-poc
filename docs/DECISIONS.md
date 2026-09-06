# Architectural Decisions

## AD-001: Azure Subscription
- **Decision:** Azure for Students ($100 credit, valid until 2027-09-06)
- **Rationale:** No credit card required, verified via GitHub Student
- **Risk:** Regional restrictions on AI services (RequestDisallowedByAzure)
- **Mitigation:** Check Policy → Assignments before Gate 1

## AD-002: Repository Visibility
- **Decision:** Public
- **Rationale:** Educational PoC, unlimited GitHub Actions minutes, no sensitive data

## AD-003: COBOL Integration
- **Decision:** Snapshot in `legacy/core-banking-system/`
- **Rationale:** Maximum reproducibility, works offline, enables PRs within same repo
- **Baseline:** Commit `770860d4a11f1d203b0369456d867108097a550f` (2026-09-06)
- **Update Policy:** Explicit and documented, never automatic

## AD-004: Authentication (Local)
- **Decision:** `az login` + `DefaultAzureCredential`
- **Rationale:** SDK standard, no secrets to manage locally

## AD-005: Authentication (CI)
- **Decision:** OIDC / Workload Identity Federation (at Gate 4)
- **Rationale:** No long-lived secrets. Skip client_secret entirely.
- **Fallback:** If student tenant blocks App Registration, document as BLOCKED_AUTH

## AD-006: Foundry Architecture
- **Decision:** Resource Group → Foundry resource → Foundry project → model deployment
- **Rationale:** Current Microsoft Foundry architecture (not legacy AI Hub/hub-based)
- **Constraint:** Only use Hub if a future feature explicitly requires it

## AD-007: Inference API
- **Decision:** Responses API (`openai_client.responses.create()`)
- **Rationale:** Current recommended contract. Chat Completions only as proven fallback.
- **Structured Output:** `responses.parse(..., text_format=<PydanticModel>)` at Gate 2+

## AD-008: Model Selection
- **Decision:** `gpt-5-mini` (GlobalStandard, version `2025-08-07`, `brazilsouth`)
- **Selection Criteria:** Region availability × active subscription quota × Responses API support × Structured Output support × cost
- **Quota Validation:** `gpt-5-mini` has 500K TPM active quota in the Azure for Students subscription without requiring manual request; `gpt-5.4-mini` and `gpt-5.6-luna` have 0 TPM default quota across all 5 allowed regions.
- **Future Candidates:** `gpt-5.4-mini` and `gpt-5.6-luna` registered for future comparative evals once quota is requested.
- **Rejected:** `gpt-4.1-mini` (Legacy status), `gpt-4o-mini` (Deprecating status).
- **Deployment Type:** Global Standard (pay-per-token, capacity 10 = 10K TPM, no PTU/provisioned capacity).
- **Constraint:** No fixed-cost or provisioned resources.

## AD-009: Primary Goal
- **Decision:** Prove technology first (Gates 0–4), polish for demo later (Gates 5–6)

## AD-010: Python Version
- **Decision:** Python 3.12 (fixed, not runner default)

## AD-011: Legacy Code Integrity
- **Decision:** COBOL code preserved exactly as upstream. No STOP RUN → GOBACK patch.
- **Rationale:** Agent should detect the STOP RUN issue as a modernization risk. Fixing the COBOL defeats the purpose of the analysis PoC.
- **Scope:** No functional COBOL modifications in Gates 0–3.

## AD-012: COBOL Module Execution
- **Decision:** Use `cobcrun` to execute modules compiled with `cobc -m`
- **Rationale:** `cobc -m` produces shared libraries (.so/.dll), not standalone executables. `cobcrun` is the GnuCOBOL standard for running modules.
