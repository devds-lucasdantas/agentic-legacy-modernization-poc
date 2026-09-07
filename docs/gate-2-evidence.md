# Gate 2 — COBOL Reader — Evidence

## Status: V1_REPORTED_PASS / V2_PENDING

> [!IMPORTANT]
> **Status Clarification:**
> - **BASELINE V1** reported `PASS` under legacy Evaluator `v1.1.0` on 2026-09-06.
> - A subsequent independent adversarial review demonstrated substantial correctness and soundness weaknesses across Evaluator v1.1.0, the evidence validator, the output schema, and the runner.
> - BASELINE V1 remains preserved immutable historical experimental evidence.
> - Gate 2 final validation is **PENDING BASELINE V2**.
> - **BASELINE V2 has NOT been executed.** Zero live model calls were performed during this corrective engineering session.

---

## 1. Historical Execution Record (Baseline V1)

| Field | Value |
|---|---|
| Historical Date | 2026-09-06 |
| Environment | WSL (Ubuntu 24.04), Python 3.12.3 |
| Git Commit SHA | `7bdec2b28c4f23cd16911532de15f2644a57f0fe` |
| Target File | `legacy/core-banking-system/BANK-MAIN.CBL` |
| Source SHA256 | `b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028` |
| Model Deployment | `gpt-5-mini` |
| Model Version | `2025-08-07` |
| Contract API | OpenAI Responses API Structured Outputs (`responses.parse`) |
| Reasoning Effort | `low` |
| Schema Version | `1.0.0` (preserved in `agents/legacy_analyzer/schemas/assessment_v1.py`) |
| Prompt Version | `gate2-baseline-v1` |
| Evaluator Version | `1.1.0` (legacy) |
| Run Label | `baseline-v1` |
| Elapsed Time | 32.78s |
| Input Tokens | 3,738 |
| Output Tokens | 3,218 |
| Total Tokens | 6,956 |

### Preserved Artifacts & Integrity Manifest
All historical artifacts from the V1 execution are preserved untouched in `artifacts/gate-2/baseline-v1/` and tracked in `evals/observed/baseline-v1-manifest.json`:
- `bank-main-assessment.json`: SHA256 `062f689e47225c56cba0285a4cf131e50889c25f46bb101d2ec75727918a22bc`
- `evaluation.json`: SHA256 `b19326e0e3b97b09ca66432657e05fc8aa107b1d9df50e5ebf89998ea38a6a68`
- `run-metadata.json`: SHA256 `d4bb0f86b4028045a557342629b3ae3d29252bcfe2ea012eeb8ff569ee8ee496`
- `assessment-schema.json`: SHA256 `5bb919d7d130a84e4f7fc46c0a0c4ec3efc21115cc49c25e8a5b2829ec37ea81`

Sanitized copies (with live endpoints, subscription IDs, and response IDs removed) are maintained under `evals/observed/gate-2-baseline-v1-assessment.json` and `evals/observed/gate-2-baseline-v1-metadata.json`.

---

## 2. Adversarial Review Findings (F1–F10)

An independent adversarial audit reproduced 10 distinct failure modes in Evaluator v1.1.0 and associated runner components:

1. **F1 (Evidence Validation Bug):** `evidence_validator.py:109` checked `if norm_snippet in norm_actual or norm_actual in norm_snippet:`. Blank lines evaluated to `norm_actual = ""`, accepting arbitrary fabricated snippets. Furthermore, appending fabricated statements to real source lines passed validation.
2. **F2 (Permissive Fact Matching):** `evaluator.py:276-290` accepted control flow matches across dissimilar constructs. In historical artifact `artifacts/gate-2/baseline-v1/evaluation.json:60`, `control.evaluate_choice` was matched by `PERFORM UNTIL`!
3. **F3 (Incomplete False-Positive Coverage):** I/O operations and control flow checks only inspected evidence validity without determining whether the underlying statements actually existed in source.
4. **F4 (Assumption Escape Hatch):** `unsupported_assumptions` in Schema V1 allowed affirmative callee claims to bypass hallucination detection.
5. **F5 (Schema Answer Leakage):** Schema V1 field descriptions leaked exact fixture values (`BANK-MAIN`, `INIT-DB`, `TRANS-PROC`, `REPORT-GEN`, `WS-CHOICE = '4'`).
6. **F6 (Artifact Overwrite Risk):** Runner invoked `mkdir(parents=True, exist_ok=True)`, allowing accidental overwrite of historical runs.
7. **F7 (Brittle Prohibited Rule Probes):** Scope rules relied on fragile substring checks (e.g. `"creates 3 accounts"`), easily evaded by paraphrasing.
8. **F8 (Conflation of Absence with Default):** `copybook_dependencies_found` defaulted to `[]`, meaning omitted model outputs were rewarded as confirmed absence.
9. **F9 (Weak Git Provenance):** Runner checked only `git rev-parse HEAD`, failing to verify working tree cleanliness.
10. **F10 (SDK & Typing Misalignment):** `openai>=1.40.0` was overly permissive; active SDK is `openai 3.8.0` paired with `azure-ai-projects 2.6.0`, which defines `ReasoningEffort` literals `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`.

---

## 3. Historical Baseline V1 Offline Rescore under Evaluator V2

To objectively evaluate the historical V1 output against corrected standards, an offline rescoring adapter (`src/validation/v1_rescore.py`) processed the preserved `bank-main-assessment.json` using Evaluator V2 rules.

Full rescore report: `evals/results/gate-2-v1-rescored-with-v2.json`.

### Claim Accounting & Unevaluated Fields
- **Historical Claim Count:** 36 total claims in V1 output.
- **Converted Claims:** 24 claims mapped deterministically to canonical `AtomicFact` representations.
- **Unevaluated Claims:** 12 claims could not be deterministically evaluated under V2 rules:
  - 4 free-form narrative `observations`
  - 5 ungrounded `unsupported_assumptions`
  - 3 `call_type` claims (`DYNAMIC` vs `STATIC`, which are linker/compiler binding properties not provable from single-file source syntax)
- **Note:** Because 12 historical claims remain unevaluated and V1 was subject to Schema V1 answer hints, this rescore evaluates deterministic structural claims only, not every historical assertion.

### Rescore Metrics
- **Supported Predicted Facts:** 23
- **Unsupported Predicted Facts:** 1
- **Invalid Evidence Detected:** 1 (`data.ws_choice` cited lines 7..9, which included line 6 `DATA DIVISION.`)
- **Expected Golden Facts (V2):** 15
- **Matched Golden Facts:** 14
- **Missing Golden Facts:** 1 (`data.ws_choice` due to invalid evidence span)
- **Precision:** 0.9583 (23/24)
- **Recall:** 0.9333 (14/15)
- **Gate 2 V2 Pass Status:** **FAIL** (`gate_2_pass_under_v2_rules: false`)

---

## 4. Gate 2 V2 Architecture & Corrective Hardening

The following architecture and validation mechanisms have been implemented and verified:

### Canonical Atomic Fact Model (`src/cobol/atomic_facts.py`)
- `AtomicFact`: Pure semantic identity (kind, subject, predicate, object, attributes).
- `PredictedFact`: Model assertion pairing an `AtomicFact` with `SourceEvidence`.
- `SupportedFact`: Ground-truth support pairing an `AtomicFact` with an oracle support line span and required text fragments.
- Explicit negative fact modeling: Confirmed absence of copybooks normalizes to `AtomicFact(kind="dependency_scan", subject="COPY", predicate="dependency_count", object="0")`.
- Contradiction detection keys: Defined per fact kind (e.g. field name for data fields, option key for menu options, dependency type for scans). Duplicate conflicting values trigger contradiction penalties.

### Deterministic Source Support Oracle (`src/cobol/oracle.py`)
- Statically derives 15+ ground-truth supported facts from `BANK-MAIN.CBL`.
- Establishes bounded support spans and required verbatim fragments for every fact kind.

### Evidence Validator V2 (`src/validation/evidence_validator.py`)
- Eliminates `norm_actual in norm_snippet` bug.
- Rejects blank-line citations and fabricated snippet additions.
- Validates ellipsis snippets strictly in source sequence.
- Implements `validate_claim_evidence`: Citation line spans must overlap the oracle support span, adhere to strict maximum span bounds, and contain all required tokens.

### Schema V2 & Agent V2
- `agents/legacy_analyzer/schemas/assessment.py`: Schema version `2.0.0`.
- Eliminated fixture answer tokens (`BANK-MAIN`, `INIT-DB`, `TRANS-PROC`, `REPORT-GEN`, `WS-CHOICE`).
- Eliminated `unsupported_assumptions` and ungrounded `observations`.
- Required `copybook_dependencies` (no default factory).
- `agents/legacy_analyzer/agent.py`: Handles model refusal and incomplete generation; typed with `ReasoningEffort`.

### Runner Lifecycle & Provenance (`scripts/run-gate-2.py`)
1. Preflight checks: Git branch check, clean worktree verification, source immutability SHA256 check.
2. Mandatory `--expected-git-sha` for any `baseline-*` run.
3. Atomic run directory reservation before model invocation (`mkdir(parents=True, exist_ok=False)`).
4. Run state tracking via `run-state.json` (`STARTED` -> `COMPLETED` / `FAILED`).
5. Safe logging: Live endpoints and credentials masked.

### Golden Dataset V2 (`evals/expected/bank-main-single-v2.json`)
- 15 canonical expected atomic facts with 1-to-1 matching.

---

## 5. Test & Tooling Verification Status

| Tool / Suite | Result | Details |
|---|---|---|
| `pytest` | **PASS (50/50)** | 100% offline test suite passing in WSL Ubuntu 24.04 (Python 3.12.3) |
| Adversarial Regression Suite | **PASS (23/23)** | All 23 review vulnerabilities verified as deterministically rejected in `evals/tests/test_adversarial_regressions.py` |
| `ruff` | **PASS** | 0 linting or formatting errors across entire repository (`ruff check .`, `ruff format .`) |
| `mypy` | **PASS** | 0 type errors across `src`, `agents`, `scripts`, `tests`, `evals` |
| Legacy Source Immutability | **PASS** | `git diff -- legacy/core-banking-system/` is empty; SHA256 `b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028` |

---

## 6. Next Steps & Gate 2 Validation Path

1. **Commit & Push:** Push all Gate 2 V2 corrective implementation, schemas, evaluators, and regression tests to `feat/gate-2-cobol-reader`.
2. **Update PR #1:** Clarify that V1 reported PASS under Evaluator v1.1.0, document findings, and mark final validation as pending BASELINE V2.
3. **Execution of Baseline V2 (Future Session):** Once authorized, execute `python scripts/run-gate-2.py --run-label baseline-v2 --expected-git-sha <COMMIT_SHA>` against Azure AI Foundry with clean worktree.
4. **Gate 3 Unblock:** Gate 3 remains blocked until BASELINE V2 achieves a verified PASS under Evaluator V2 rules.
