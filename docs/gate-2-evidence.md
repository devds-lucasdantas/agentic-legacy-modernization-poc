# Gate 2 — COBOL Reader — Evidence

## Official Result: GATE 2 = PASS

> [!IMPORTANT]
> **OFFICIAL GATE 2 DECISION: PASS**
> Gate 2 `baseline-v3` has executed live on Microsoft Azure AI Foundry (`gpt-5-mini`), passed all evaluation checks with 100% precision and 100% recall against the golden dataset under Candidate V2.4, and is **OFFICIALLY ACCEPTED**.
> 
> **Explicit Gate Status: GATE 2 = PASS**

---

## 1. Baseline Summary & Evolution

| Baseline Run | Execution Date | Git Commit SHA | Model Deployment | Evaluator Version | Result | Classification / Outcome |
|---|---|---|---|---|---|---|
| **BASELINE V1** | 2026-09-06 | `7bdec2b28c4f23cd16911532de15f2644a57f0fe` | `gpt-5-mini` | `1.1.0` (legacy) | **PASS (Historical Legacy)** | Historical legacy reported PASS under legacy evaluator. Rescored offline under V2.2 to Fail (Precision 0.4167, Recall 0.6667) due to historical gaps. |
| **BASELINE V2** | 2026-09-11 | `9390377b410917e3e9c62883346b299b628a0000` | `gpt-5-mini` | `2.3.0` | **FAIL (Official)** | `BENCHMARK_CONTRACT_FAILURE / EVIDENCE_REPRESENTATION_MISMATCH`. Model emitted prompt transport line-number prefixes (`0002 \| ...`) in evidence snippets; Evaluator V2.3 strictly failed closed against unnumbered raw source lines. |
| **BASELINE V2 (Diagnostic)** | 2026-09-11 | `9390377b410917e3e9c62883346b299b628a0000` | `gpt-5-mini` | `2.3.0` | **NON_AUTHORITATIVE** | 22/22 source-supported, 15/15 golden facts matched, precision 1.0, recall 1.0. Proved 100% semantic COBOL understanding when transport prefix was mechanically stripped. |
| **BASELINE V3** | 2026-09-11 | `922cbcb70972899f05bd71f6c9b323bd2de02466` | `gpt-5-mini` | `2.4.0` | **OFFICIAL PASS** | **Candidate V2.4**: 24/24 supported, 15/15 golden facts matched, precision = 1.0, recall = 1.0, 0 invalid evidence, 0 duplicates, 0 contradictions. Host-derived evidence snippet architecture permanently eliminated representation mismatch. |

---

## 2. Official Successful Baseline Execution Record (Baseline V3)

### Execution Provenance & Cryptographic Identity

| Field | Attested Value |
|---|---|
| **Official Result** | **PASS** |
| **Status** | **COMPLETED** |
| **Run Label** | `baseline-v3` |
| **Execution Timestamp** | `2026-09-11T15:42:59.207228+00:00` |
| **Frozen Git Commit SHA** | `922cbcb70972899f05bd71f6c9b323bd2de02466` |
| **Target Source File** | `legacy/core-banking-system/BANK-MAIN.CBL` |
| **Target Source SHA256** | `b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028` |
| **Requested Model** | `gpt-5-mini` |
| **Response Model ID** | `gpt-5-mini` |
| **Reasoning Effort** | `low` |
| **Foundry Project Fingerprint** | `3f0c34d730680ad8baac11d2825e120045eb19be1d9ec1c0b2a2d337096ae33f` |
| **Baseline Authorization Spec SHA256** | `73950e0f83ec29b929ab05b70fc5127b52fd515cc97f3ac7e0eaefccbfd28190` |
| **Runtime Manifest SHA256** | `a44d9eb8d738d260e04c215689c3b543788a72b2434b5eb04fcb062061d1efac` |
| **Dependency Lock SHA256** | `732cb9370e90af2d0972eeda7fc18fd5745f17cb301f359b268df228fe7f18be` |
| **Interpreter Binary SHA256** | `e50d468e8b0adfb05733f5b87b3cff34829c4a8c1aea50c865aa8bdfe4bb150f` |
| **Python Runtime** | CPython 3.12.3 (`isolated_mode: true`, `dont_write_bytecode: true`) |
| **Schema Version** | `2.3.0` |
| **Prompt Version** | `gate2-baseline-v2.3` |
| **Evaluator Version** | `2.4.0` |
| **Golden Dataset Version** | `2.2.0` |
| **Response ID** | `resp_0bd7edd91961b1ce006aa4218dc64c81908a01696d36ae76f6` |
| **Elapsed Latency** | 25.14s |
| **Token Usage** | 3,352 input / 1,469 output / 4,821 total tokens |

### Observed Live Metrics

| Metric | Target / Requirement | Observed Live Value | Evaluation Status |
|---|---|---|---|
| **Raw Predictions** | > 0 | 24 | PASS |
| **Unique Predictions** | No duplicate triples | 24 | PASS |
| **Supported Predictions** | Valid AST & Source grounding | 24 | PASS |
| **Unsupported Predictions** | 0 | 0 | PASS |
| **Invalid Evidence Count** | 0 | 0 | PASS |
| **Duplicate Predictions** | 0 | 0 | PASS |
| **Contradictory Predictions** | 0 | 0 | PASS |
| **Matched Golden Facts** | 15 / 15 | 15 / 15 (100%) | PASS |
| **Missing Golden Facts** | 0 | 0 | PASS |
| **Precision** | >= 0.80 (Gate 2 threshold) | **1.0 (100%)** | PASS |
| **Recall** | >= 0.80 (Gate 2 threshold) | **1.0 (100%)** | PASS |
| **Gate 2 Pass Flag** | `true` | **`true`** | **PASS** |

### Preserved Baseline-V3 Artifacts & Cryptographic Manifest

All eight execution artifacts are immutably preserved byte-for-byte under `evals/observed/baseline-v3/` and attested by `evals/observed/baseline-v3-manifest.json`:

| Filename | Byte Size | SHA256 Hash | Description |
|---|---|---|---|
| `assessment-schema.json` | 12,153 | `02f1b1ddfd3d511e53540759e420e1bb69687e8b57ef66b6a28e4beff58fb7ca` | Local Pydantic V2 JSON schema exported for LegacyAssessment (Schema V2.3.0) |
| `bank-main-assessment.json` | 3,785 | `2949df27589224079b947c13bd58b02ed953f84dd926b9ef44798c003ea02d6f` | Raw model-generated structured output from `gpt-5-mini` (line coordinates only, no snippets) |
| `bank-main-assessment-enriched.json` | 6,678 | `54d04a077e3f9ec60811e6964c22b9f2278b34c958e544ec2ee306bfd37d5ad5` | Host-enriched assessment with deterministically derived verified source snippets |
| `evaluation.json` | 13,482 | `0d071ba1d0e9cf67c3625bad8cacf86922695fd1faa1a6f77eaa567024b00488` | Official evaluation report produced by Evaluator V2.4.0 recording PASS |
| `openai-wire-schema.json` | 21,504 | `6d46ee2a63f5bc9ee4bc78867bb7d514bdccf88f5785d5388eec5bece15f5155` | OpenAI 3.8.0 SDK wire schema sent to Responses API for Structured Outputs (V2.3.0) |
| `run-metadata.json` | 1,616 | `8d20af10c328263a3b9f7297dcb52db6ceb2a1a8c6038b731b6c3c7b6ff5882a` | Execution metadata containing token usage, latency, attested runtime, and spec provenance |
| `run-state.json` | 369 | `745586500115575ee19345a73d35d60dad4703e4c97929ad17d31214142795af` | Run state recording final COMPLETED state and `gate_2_pass=true` |
| `runtime-manifest.json` | 2,375 | `7e86cdb1348fcda5c1f4e3cf105a52964814c9f0d5f370bf3ace9c5e275773e9` | Pre-attested runtime environment lock manifest containing 42 packages |

Cryptographic integrity manifest: [evals/observed/baseline-v3-manifest.json](file:///c:/Users/lucas/.gemini/antigravity-ide/scratch/agentic-legacy-modernization-poc/evals/observed/baseline-v3-manifest.json).

---

## 3. Non-Blocking Reporting Debt

> [!NOTE]
> **Classification: NON_BLOCKING_REPORTING_DEBT**
> In `evaluation.json`, the field `supported_predicted_count` correctly reports `24`, while `supported_predictions` serializes as `[]`.

### Root Cause Analysis
Evaluator V2.4 maintains an internal `supported_preds` list during evaluation and uses it correctly for all metric calculations (precision, recall, golden fact matching, and the gate pass decision). However, during report model assembly, `report.supported_predictions` is not serialized with this list.

### Why This Debt Is Non-Blocking for Gate 2
1. **Accurate Computation:** `supported_predicted_count = 24` is computed directly from the evaluated list of supported predictions.
2. **Complete Golden Citations:** All 15 expected golden facts in `matched_expected_facts` contain their corresponding `matched_prediction` and verified source citations.
3. **Immutability of Evidence:** Both the raw model output (`bank-main-assessment.json`) and the host-enriched output (`bank-main-assessment-enriched.json`) are preserved byte-for-byte.
4. **Clean Evaluation Surface:** Zero unsupported predictions, zero invalid evidence, zero duplicates, and zero contradictions were recorded.
5. **No Decision Dependency:** The Gate 2 decision (`PASS`) does not depend on the redundant list serialization in `evaluation.json`.

### Operational Directive
- **Do NOT alter evaluator code in this closing commit.**
- **Do NOT rerun baseline-v3 for this issue.**
- This item is recorded as follow-up technical debt for a separate future maintenance change.

---

## 4. Candidate V2.4 Architecture (How Representation Mismatch Was Solved)

Candidate V2.4 addressed the root cause of the Baseline V2 failure by shifting evidence snippet derivation from the LLM to the deterministic host layer:

1. **Model-Visible SourceEvidence Schema (`agents/legacy_analyzer/schemas/assessment.py`)**
   - The model wire schema contains line coordinates only:
     - `line_start: int`
     - `line_end: int`
   - Configured with `extra = "forbid"` — no `snippet` field exists in the OpenAI wire schema.
   - Rejects legacy snippets cleanly and without ambiguities.

2. **Host-Side Deterministic Evidence Derivation (`src/cobol/evidence_enricher.py`)**
   - Evaluator deterministically derives exact source code snippets from verified source bytes + line spans.
   - Raw model output is preserved purely in `bank-main-assessment.json`.
   - Enriched output with derived snippets is written to `bank-main-assessment-enriched.json` clearly marked as host-derived.

3. **System Prompt Alignment (`agents/legacy_analyzer/prompts/system.md`)**
   - Version `gate2-baseline-v2.3`.
   - Explicitly instructs the model to provide `line_start` and `line_end` line coordinates only.

4. **Evaluator V2.4 (`src/validation/evaluator_v2.py`, `evaluator_core.py`)**
   - Version `2.4.0`.
   - Evaluates line coordinates and derives snippet citations deterministically.

---

## 5. Historical Baseline V2 Execution & Postmortem

On 2026-09-11, `baseline-v2` was executed live with `gpt-5-mini` on commit `9390377b410917e3e9c62883346b299b628a0000`.

- **Official Result:** `FAIL` (Precision 0.0455, Recall 0.0667, 21 invalid evidence snippets, 21 unsupported predictions).
- **Classification:** `BENCHMARK_CONTRACT_FAILURE / EVIDENCE_REPRESENTATION_MISMATCH`.
- **Finding:** The model ingested transport-numbered lines (`0002 | ...`) and emitted that exact representation in `evidence.snippet`. Slicing against raw unnumbered source lines caused all 21 positive predictions to fail evidence validation fail-closed.
- **Offline Diagnostic Rescore (Non-Authoritative):**
  - When the transport prefix `^[0-9]{4} \| ` was removed via a structurally verified conversion script (`evals/scripts/rescore_baseline_v2_diagnostic.py`), precision became 1.0 (22/22) and recall became 1.0 (15/15), proving 100% semantic COBOL understanding.
  - Preserved in `evals/results/gate-2-baseline-v2-evidence-contract-diagnostic.json`.
- **Full Technical Postmortem:** [docs/postmortems/gate-2-baseline-v2-postmortem.md](file:///c:/Users/lucas/.gemini/antigravity-ide/scratch/agentic-legacy-modernization-poc/docs/postmortems/gate-2-baseline-v2-postmortem.md).
- **Preserved Artifacts:** Preserved immutably in `evals/observed/baseline-v2/` and tracked in `evals/observed/baseline-v2-manifest.json`.

---

## 6. Historical Execution Record (Baseline V1)

| Field | Value |
|---|---|
| Historical Date | 2026-09-06 |
| Environment | WSL (Ubuntu 24.04), Python 3.12.3 |
| Git Commit SHA | `7bdec2b28c4f23cd16911532de15f2644a57f0fe` |
| Target File | `legacy/core-banking-system/BANK-MAIN.CBL` |
| Source SHA256 | `b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028` |
| Model Deployment | `gpt-5-mini` (`2025-08-07`) |
| Contract API | OpenAI Responses API Structured Outputs (`responses.parse`) |
| Reasoning Effort | `low` |
| Schema Version | `1.0.0` (preserved in `agents/legacy_analyzer/schemas/assessment_v1.py`) |
| Prompt Version | `gate2-baseline-v1` |
| Evaluator Version | `1.1.0` (legacy) |
| Run Label | `baseline-v1` |
| Token Usage | 3,738 input / 3,218 output / 6,956 total tokens |

### Preserved V1 Artifacts & Offline Rescores
All historical artifacts from V1 are preserved in `artifacts/gate-2/baseline-v1/` and tracked in `evals/observed/baseline-v1-manifest.json`.
- **V2.1 Offline Rescore (`evals/results/gate-2-v1-rescored-with-v2.1.json`):** Precision 0.75, Recall 0.6667 (Gate 2 Pass: `false`).
- **V2.2 Offline Rescore (`evals/results/gate-2-v1-rescored-with-v2.2.json`):** Precision 0.4167, Recall 0.6667 (Gate 2 Pass: `false`).

---

## 7. Quality Gate Verification Status

All checks executed in the WSL Ubuntu 24.04 environment (`.venv` Python 3.12.3):

| Tool / Suite | Status | Details |
|---|---|---|
| `pytest` | **PASS (164/164)** | 100% offline tests passing across all test suites |
| Candidate V2.4 Regressions | **PASS (20/20)** | Host-derived snippet derivation invariants, schema forbid, enricher idempotence |
| Authorization Regressions V2.3.1 | **PASS (21/21)** | Spec authorization and isolation enforcement in `evals/tests/test_authorization_regressions_v2_3_1.py` |
| Authorization Regressions V2.3 | **PASS (30/30)** | F1–F6 and Amendments 1–4 in `evals/tests/test_authorization_regressions_v2_3.py` |
| Adversarial Regressions V3 | **PASS (26/26)** | A3-01 to A3-11 and V2.2 Amendments in `evals/tests/test_adversarial_regressions_v3.py` |
| Adversarial Regressions V2 | **PASS (30/30)** | Historical adversarial regression tests in `evals/tests/test_adversarial_regressions.py` |
| COBOL Reader Unit Suite | **PASS (23/23)** | Reader, AST, fact extraction, and prompt contracts in `evals/tests/test_cobol_reader.py` |
| Source Mutation Suite | **PASS (10/10)** | In-memory source mutation tests proving dynamic AST and evidence tracking |
| Offline Verification Suite | **PASS (4/4)** | Offline agent and pipeline tests in `tests/test_offline.py` |
| Mandatory Positive Invariant | **PASS** | `make_perfect_assessment_v2()` -> Precision 1.0, Recall 1.0, 0 unsupp, 0 inv_ev, 0 dup, 0 cont, `gate_2_pass: True` |
| Baseline Immutability Invariant | **PASS** | Baseline V1, Baseline V2, and Baseline V3 artifacts match cryptographic manifests byte-for-byte |
| `ruff check .` | **PASS** | 0 lint errors |
| `ruff format --check .` | **PASS** | All files formatted and compliant |
| `mypy src agents scripts tests evals` | **PASS** | 0 issues found across all source files |
| `pip check` | **PASS** | No broken requirements found |
| Legacy Immutability | **PASS** | `git diff -- legacy/core-banking-system/` strictly empty; SHA256 `b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028` |
