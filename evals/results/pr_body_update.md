# Gate 2: add source-grounded COBOL reader and deterministic evaluation

## Official Gate 2 Result: PASS

Gate 2 **baseline-v3** executed live on Microsoft Azure AI Foundry (`gpt-5-mini`), passed all evaluation checks with 100% precision and 100% recall against the golden dataset under **Candidate V2.4**, and is **OFFICIALLY ACCEPTED**.

- **Official Decision:** **GATE 2 = PASS**
- **Successful Baseline Run:** `baseline-v3`
- **Candidate Architecture:** Candidate V2.4 (Host-derived evidence snippets)
- **Frozen Git Commit SHA:** `922cbcb70972899f05bd71f6c9b323bd2de02466`
- **Requested Model / Response Model:** `gpt-5-mini` / `gpt-5-mini`
- **Evidence Documentation:** [docs/gate-2-evidence.md](docs/gate-2-evidence.md)
- **Cryptographic Integrity Manifest:** [evals/observed/baseline-v3-manifest.json](evals/observed/baseline-v3-manifest.json)
- **Preserved Execution Directory:** [evals/observed/baseline-v3/](evals/observed/baseline-v3/)

---

## Baseline-V3 Official Live Metrics

| Metric | Target | Observed Live Value | Status |
|---|---|---|---|
| **Raw Predictions** | > 0 | 24 | PASS |
| **Unique Predictions** | No duplicates | 24 | PASS |
| **Supported Predictions** | Valid AST & Source grounding | 24 | PASS |
| **Unsupported Predictions** | 0 | 0 | PASS |
| **Invalid Evidence** | 0 | 0 | PASS |
| **Duplicates** | 0 | 0 | PASS |
| **Contradictions** | 0 | 0 | PASS |
| **Matched Golden Facts** | 15 / 15 | 15 / 15 (100%) | PASS |
| **Missing Golden Facts** | 0 | 0 | PASS |
| **Precision** | >= 0.80 | **1.0 (100%)** | PASS |
| **Recall** | >= 0.80 | **1.0 (100%)** | PASS |
| **Gate 2 Pass Flag** | `true` | **`true`** | **PASS** |

### Execution Provenance
- **Foundry Project Fingerprint:** `3f0c34d730680ad8baac11d2825e120045eb19be1d9ec1c0b2a2d337096ae33f`
- **Target Source File:** `legacy/core-banking-system/BANK-MAIN.CBL` (`b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028`)
- **Baseline Authorization Spec SHA256:** `73950e0f83ec29b929ab05b70fc5127b52fd515cc97f3ac7e0eaefccbfd28190`
- **Runtime Manifest SHA256:** `a44d9eb8d738d260e04c215689c3b543788a72b2434b5eb04fcb062061d1efac`
- **Dependency Lock SHA256:** `732cb9370e90af2d0972eeda7fc18fd5745f17cb301f359b268df228fe7f18be`
- **Interpreter Binary SHA256:** `e50d468e8b0adfb05733f5b87b3cff34829c4a8c1aea50c865aa8bdfe4bb150f`
- **Versions:** Schema `2.3.0` | Prompt `gate2-baseline-v2.3` | Evaluator `2.4.0` | Golden `2.2.0`
- **Tokens & Latency:** 3,352 prompt + 1,469 completion = 4,821 total tokens in 25.14s

---

## Non-Blocking Reporting Debt (Follow-up Technical Debt)

In `evals/observed/baseline-v3/evaluation.json`, `supported_predicted_count` correctly reports `24`, while `supported_predictions` serializes as `[]`.

- **Root Cause:** Evaluator V2.4 maintains its internal `supported_preds` list and uses it correctly for all metrics, golden matching, and the PASS decision, but does not serialize that list into `report.supported_predictions`.
- **Classification:** `NON_BLOCKING_REPORTING_DEBT`
- **Why Non-Blocking:**
  - `supported_predicted_count = 24` is computed directly from the actual supported predictions list;
  - All 15 expected facts contain `matched_prediction` populated with verified fact objects and exact source citations;
  - Raw model output (`bank-main-assessment.json`) and enriched output (`bank-main-assessment-enriched.json`) are preserved byte-for-byte;
  - Zero unsupported, invalid, duplicate, or contradictory predictions exist;
  - Gate 2 decision does not depend on the omitted list serialization.
- **Operational Directive:** Evaluator code is not modified and baseline-v3 is not rerun. This debt is documented for future maintenance.

---

## Candidate V2.4 Architecture (Phase B)

To permanently eliminate prompt-transport vs. raw-source evidence representation mismatches, Candidate V2.4 shifts evidence snippet creation to the host/evaluator layer while keeping the raw model output purely model-visible:

1. **Model-Visible SourceEvidence Schema (`agents/legacy_analyzer/schemas/assessment.py`)**
   - The model-visible wire schema contains ONLY line coordinates:
     - `line_start: int`
     - `line_end: int`
   - Configured with `extra = "forbid"` — no `snippet` field exists in the OpenAI wire schema.
   - Clean and simple: rejects legacy snippets without backward-compatibility hacks.

2. **Host-Side Deterministic Evidence Derivation (`src/cobol/evidence_enricher.py`)**
   - Evaluator deterministically derives exact source code snippets from verified source bytes + line spans.
   - Preserves pure model output in `bank-main-assessment.json`.
   - Writes enriched output with verified snippets to `bank-main-assessment-enriched.json` clearly marked as host-derived.

3. **System Prompt Alignment (`agents/legacy_analyzer/prompts/system.md`)**
   - Version `gate2-baseline-v2.3`.
   - Explicitly instructs the model to provide `line_start` and `line_end` line coordinates only.

4. **Evaluator V2.4 (`src/validation/evaluator_v2.py`, `evaluator_core.py`)**
   - Version `2.4.0`.
   - Derives snippet evidence citations host-side from raw source bytes.

5. **Commit-Bound Baseline Authorization Spec (`evals/baselines/gate-2-baseline-v3.json`)**
   - Frozen spec binding execution to git commit `922cbcb70972899f05bd71f6c9b323bd2de02466`.

---

## Live Baseline-V2 Execution & Root Cause Analysis (Historical Record)

On 2026-09-11, Gate 2 `baseline-v2` was executed live with `gpt-5-mini` on commit `9390377b410917e3e9c62883346b299b628a0000`.

- **Observed Result:**
  - `gate_2_pass = false`
  - `precision = 0.0455` (1 / 22 supported)
  - `recall = 0.0667` (1 / 15 expected matched)
  - `invalid_evidence_count = 21`
  - `unsupported_predicted_count = 21`

### Root Cause Classification
`BENCHMARK_CONTRACT_FAILURE / EVIDENCE_REPRESENTATION_MISMATCH`

The model accurately parsed all semantic elements of `BANK-MAIN.CBL`. However, because the system prompt provided the source code formatted with transport line numbers (`0001 | ...`, `0002 | ...`), the model emitted the exact transport-numbered lines inside `evidence.snippet` (e.g. `0002 |        PROGRAM-ID. BANK-MAIN.`).

Evaluator V2.3 strictly and correctly failed closed against the raw source bytes on disk where lines do not contain the transport line number prefix.

### Historical Evidence Preservation & Diagnostic Rescore
All seven live artifacts from `baseline-v2` were immutably preserved byte-for-byte in `evals/observed/baseline-v2/` and tracked via `evals/observed/baseline-v2-manifest.json`.

A comprehensive postmortem was published at `docs/postmortems/gate-2-baseline-v2-postmortem.md`.

An offline, structurally verified diagnostic rescore (`evals/scripts/rescore_baseline_v2_diagnostic.py`) was executed using Evaluator V2.3:
- Enforced strict invariant: every snippet line had exact transport prefix matching the cited span (`0002 | `, etc.).
- Exactly 21 snippets converted; 0 semantic fields modified.
- Diagnostic semantic hash before and after transport prefix removal is **identical**:
  `a2a41674058dbb8a20d962300c276e62ec617aab08f9b5641bc174b0bed74ce3`
- Diagnostic Result:
  - `precision: 1.0` (22 / 22 supported)
  - `recall: 1.0` (15 / 15 expected matched)
  - `invalid_evidence: 0`
  - `gate_2_pass: true`
- Persisted in: `evals/results/gate-2-baseline-v2-evidence-contract-diagnostic.json`.

---

## Quality Verification Status

All checks executed in the WSL Ubuntu 24.04 environment (`.venv` Python 3.12.3):

- **pytest:** **164/164 PASS** (100% offline across all test suites in ~2m)
  - `evals/tests/test_candidate_v2_4_regressions.py`: **20/20 PASS** (Candidate V2.4 architectural invariants)
  - `evals/tests/test_authorization_regressions_v2_3_1.py`: **21/21 PASS**
  - `evals/tests/test_authorization_regressions_v2_3.py`: **30/30 PASS**
  - `evals/tests/test_adversarial_regressions_v3.py`: **26/26 PASS**
  - `evals/tests/test_adversarial_regressions.py`: **30/30 PASS**
  - `evals/tests/test_cobol_reader.py`: **23/23 PASS**
  - `evals/tests/test_source_mutations.py`: **10/10 PASS**
  - `tests/test_offline.py`: **4/4 PASS**
- **Mandatory Positive Invariant:** **PASS** (`make_perfect_assessment_v2()` -> Precision 1.0, Recall 1.0, 0 unsupp, 0 inv_ev, 0 dup, 0 cont, `gate_2_pass: True`)
- **Baseline Immutability Invariant:** **PASS** (Baseline V1, Baseline V2, and Baseline V3 artifacts match cryptographic manifests byte-for-byte)
- **ruff check .:** **PASS** (0 lint errors across all files)
- **ruff format --check .:** **PASS** (all files formatted and compliant)
- **mypy src agents scripts tests evals:** **PASS** (0 issues across 32 source files)
- **pip check:** **PASS** (No broken requirements found)
- **Legacy source immutability:** **PASS** (`BANK-MAIN.CBL` untouched, SHA256 `b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028`)

---

## Current Status & Constraints

- **PR State:** OPEN (**Do NOT merge yet**)
- **Official Gate 2 Status:** **PASS**
- **BASELINE-V3 RERUNS = 0**
- **NEW LIVE MODEL CALLS = 0**
- **EXECUTABLE CODE MODIFICATIONS AFTER LIVE PASS = 0**
- **LEGACY SOURCE MODIFICATIONS = 0**
- **PR MERGES = 0**
- **HISTORY REWRITES = 0**
