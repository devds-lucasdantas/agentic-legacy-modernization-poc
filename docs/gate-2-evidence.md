# Gate 2 — COBOL Reader — Evidence

## Status: V1_REPORTED_PASS / V2_PENDING

> [!IMPORTANT]
> **Status Clarification & Candidate Versioning:**
> - **BASELINE V1** reported `PASS` under legacy Evaluator `v1.1.0` on 2026-09-06.
> - Three successive independent adversarial reviews (Audits 1, 2, and 3) identified critical correctness, schema, refusal handling, provenance, and soundness vulnerabilities.
> - BASELINE V1 remains preserved immutable historical experimental evidence.
> - Candidate Version: `schema_version = 2.2.0`, `evaluator_version = 2.2.0`, `prompt_version = gate2-baseline-v2.2`.
> - Gate 2 final validation is **PENDING BASELINE V2**.
> - **BASELINE V2 has NOT been executed.** Exactly zero live model calls were performed during this corrective cycle.

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
- `assessment-schema.json`: SHA256 `fcd047c2724c6132f263ddc2941b2a57f81b210ba6cd874059c496c6ab714d73`
- `bank-main-assessment.json`: SHA256 `5d270eb35e1e0311448049f0b68d3370bdbda3d2e9243cd30f83a588a4452fc7`
- `evaluation.json`: SHA256 `1aa8443e7b73e24d263930d8fbd3a6b10ee7ac22186917b4f2570043293177ae`
- `run-metadata.json`: SHA256 `e462dfbda3240004a730d9aa961d086b77f9c65652b0cf320aca3a588c802d90`

Sanitized copies are maintained under `evals/observed/gate-2-baseline-v1-assessment.json` and `evals/observed/gate-2-baseline-v1-metadata.json`.

---

## 2. Third Adversarial Review Findings (A3-01 to A3-11) & Remediation

A third independent adversarial audit examined Candidate V2.1 and identified critical baseline-blockers, which were remediated under Candidate V2.2:

| ID | Finding Description | Remediation in Candidate V2.2 |
|---|---|---|
| **A3-01** | Strict literal parsing & menu separation: DISPLAY literals and menu keys were conflated with quoted tokens, and broad `.rstrip(".")` corrupted PIC clauses. | Implemented `parse_cobol_literal_token`, `parse_source_menu_key_token`, `normalize_menu_key` (no repair of malformed model keys), `normalize_semantic_literal` (idempotent), narrow `normalize_pic` grammar, and non-vacuous DISPLAY evidence binding. |
| **A3-02** | Discriminated union wire incompatibility: Pydantic `Field(discriminator=...)` produced unsupported `oneOf` and `discriminator` in OpenAI 3.8.0 wire schema. | Replaced discriminated unions with standard plain unions (`anyOf`), removed literal defaults, ensuring all fields are strictly required and wire schema is supported by OpenAI Responses API Structured Outputs. |
| **A3-03** | Incomplete refusal detection: Responses API refusals could be nested in message content items without being caught. | Implemented recursive `inspect_response_for_refusal` detecting top-level refusals, output-level `ResponseOutputRefusal`, and message-content nested refusals, raising `ResponseRefusedError` with safe messages. |
| **A3-04** | Git provenance bypass: `git status` could miss changes with `assume-unchanged`; untracked overlays could hijack imports; non-isolated Python could load host packages. | Implemented byte-for-byte full tracked tree comparison against `git show HEAD:<path>`, filesystem overlay scanning (`sitecustomize.py`, loose `.pyc`, untracked `.py`), post-import origin verification, and mandatory isolated Python (`sys.flags.isolated == 1`). |
| **A3-05** | Runtime attestation drift: subtle package differences between `pip freeze` and `importlib.metadata`. | Implemented single canonical representation (`normalized-pkg-name==version`) comparing active runtime packages against `requirements-lock.txt` for exact set equality. |
| **A3-11** | Documentation and manifest reconciliation. | Reconciled `docs/gate-2-evidence.md` with `evals/observed/baseline-v1-manifest.json`, preserved V2.1 rescore intact, generated V2.2 rescore, and documented actual reproduced metrics. |

---

## 3. The Six Required Amendments (Approved for V2.2)

1. **Amendment 1: Separate Source Menu Token Parsing from Model Menu Values**
   - Source: `parse_source_menu_key_token("'1'") -> "1"`, `parse_source_menu_key_token("OTHER") -> "OTHER"`.
   - Model: semantic values `"1" -> "1"`, `"OTHER" -> "OTHER"`.
   - Model values such as `"'1'"`, `"1''"`, `"'1"`, `"1'"`, `"O'THER"` are preserved verbatim and NOT repaired into supported keys.
2. **Amendment 2: Update Model Prompt for V2.2 Semantics**
   - `prompt_version = "gate2-baseline-v2.2"` in `agents/legacy_analyzer/prompts/system.md`.
   - Clarified semantic literal contracts (characters inside quotes, preserve whitespace, no outer delimiters).
   - Clarified semantic menu option keys ("1", "OTHER", not COBOL quoted tokens).
   - Verbatim evidence snippets without answer leakage.
3. **Amendment 3: Preserve V2.1 Rescore History & Emit V2.2 Artifact**
   - `evals/results/gate-2-v1-rescored-with-v2.1.json` preserved untouched.
   - Fresh `evals/results/gate-2-v1-rescored-with-v2.2.json` generated and verified for exact reproducibility.
4. **Amendment 4: Require Isolated Python for Baseline Execution**
   - Baseline runs strictly require `sys.flags.isolated == 1` (`.venv/bin/python -I scripts/run-gate-2.py ...`).
   - Verified repository root added to `sys.path` only after provenance checks pass.
5. **Amendment 5: One Canonical Runtime/Lock Representation**
   - Shared `canonical_distribution_name(name)==version` mapping.
   - Fails on missing, unexpected, or version-mismatched packages.
   - Persists `runtime-manifest.json` and records SHA256 in run metadata.
6. **Amendment 6: Freeze Expected Model/Deployment Identity**
   - Mandatory `--expected-model` parameter for baseline runs.
   - Compares `--expected-model` against loaded config before artifact reservation.
   - Separately records `requested_model` and `response_model_id`.

---

## 4. Historical Baseline V1 Offline Rescore Results

### Preserved V2.1 Rescore (`evals/results/gate-2-v1-rescored-with-v2.1.json`)
- **Total Historical Predictions Converted:** 24
- **Supported Predicted Facts:** 18
- **Unsupported Predicted Facts:** 6
- **Invalid Evidence Count:** 5
- **Matched Expected Facts:** 10 / 15
- **Precision:** 0.75
- **Recall:** 0.6667
- **Gate 2 Pass:** `false`

### Fresh V2.2 Rescore (`evals/results/gate-2-v1-rescored-with-v2.2.json`)
Evaluated under Candidate V2.2 strict semantic literal contracts and literal parsing:
- **Total Historical Predictions Converted:** 24
- **Supported Predicted Facts:** 10
- **Unsupported Predicted Facts:** 14
- **Invalid Evidence Count:** 5
- **Matched Expected Facts:** 10 / 15
- **Precision:** 0.4167
- **Recall:** 0.6667
- **Gate 2 Pass:** `false`

---

## 5. Quality Gate Verification Status

All checks executed in the WSL Ubuntu 24.04 environment (`.venv` Python 3.12.3):

| Tool / Suite | Status | Details |
|---|---|---|
| `pytest` | **PASS (93/93)** | 100% offline tests passing across unit, regressions, V1 compatibility, mutations, and V3 adversarial suite |
| Adversarial Regressions V3 | **PASS (26/26)** | Explicit deterministic tests for A3-01 to A3-11 and Amendments 1–6 in `evals/tests/test_adversarial_regressions_v3.py` |
| Adversarial Regressions V2 | **PASS (28/28)** | Historical regression tests in `evals/tests/test_adversarial_regressions.py` passing |
| Source Mutation Suite | **PASS (10/10)** | In-memory source mutation tests proving dynamic tracking |
| Mandatory Positive Invariant | **PASS** | `make_perfect_assessment_v2()` -> Precision 1.0, Recall 1.0, 0 unsupp, 0 inv_ev, 0 dup, 0 cont, `gate_2_pass: True` |
| `ruff check .` | **PASS** | 0 lint errors |
| `ruff format --check .` | **PASS** | 36 files formatted and compliant |
| `mypy src agents scripts tests evals` | **PASS** | 0 issues found in 27 source files |
| `pip check` | **PASS** | No broken requirements found |
| Legacy Immutability | **PASS** | `git diff -- legacy/core-banking-system/` is strictly empty; SHA256 `b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028` |

---

## 6. Execution Command for Future Baseline V2

When authorized by human review, BASELINE V2 must be invoked in isolated Python mode with exact parameters:

```bash
.venv/bin/python -I scripts/run-gate-2.py \
  --run-label baseline-v2 \
  --expected-git-sha <COMMIT_SHA> \
  --expected-model gpt-5-mini
```
