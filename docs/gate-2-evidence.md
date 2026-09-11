# Gate 2 — COBOL Reader — Evidence

## Status: V1_REPORTED_PASS / V2_PENDING

> [!IMPORTANT]
> **Status Clarification & Candidate Versioning:**
> - **BASELINE V1** reported `PASS` under legacy Evaluator `v1.1.0` on 2026-09-06.
> - Successive adversarial reviews and the Final Authorization Review identified correctness, schema, refusal handling, provenance, isolation, and soundness vulnerabilities.
> - BASELINE V1 remains preserved immutable historical experimental evidence.
> - **Gate 2 Candidate V2.3 Specification:**
>   - Candidate Version: **Gate 2 Candidate V2.3**
>   - `schema_version = 2.2.0` (model-visible schema unchanged)
>   - `prompt_version = gate2-baseline-v2.2` (prompt contract unchanged)
>   - `evaluator_version = 2.3.0` (semantic menu key normalization update)
>   - `golden_dataset_version = 2.2.0` (expected facts unchanged)
> - Component versions are intentionally decoupled: model schema and prompt contracts were not altered, preserving evaluation integrity.
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

## 2. Historical Adversarial Review Findings (A3-01 to A3-11) & Candidate V2.2

A third independent adversarial audit examined Candidate V2.1 and identified critical baseline-blockers, remediated under Candidate V2.2:

| ID | Finding Description | Remediation in Candidate V2.2 |
|---|---|---|
| **A3-01** | Strict literal parsing & menu separation: DISPLAY literals and menu keys were conflated with quoted tokens, and broad `.rstrip(".")` corrupted PIC clauses. | Implemented `parse_cobol_literal_token`, `parse_source_menu_key_token`, `normalize_menu_key`, `normalize_semantic_literal` (idempotent), narrow `normalize_pic` grammar, and non-vacuous DISPLAY evidence binding. |
| **A3-02** | Discriminated union wire incompatibility: Pydantic `Field(discriminator=...)` produced unsupported `oneOf` and `discriminator` in OpenAI wire schema. | Replaced discriminated unions with standard plain unions (`anyOf`), removed literal defaults, ensuring all fields are strictly required. |
| **A3-03** | Incomplete refusal detection: Responses API refusals could be nested in message content items without being caught. | Implemented recursive `inspect_response_for_refusal` detecting top-level refusals, output-level `ResponseOutputRefusal`, and message-content nested refusals. |
| **A3-04** | Git provenance bypass: `git status` missed changes with `assume-unchanged`; untracked overlays hijacked imports; non-isolated Python loaded host packages. | Implemented byte-for-byte full tracked tree comparison against `git show HEAD:<path>`, filesystem overlay scanning, post-import origin verification, and isolated Python (`sys.flags.isolated == 1`). |
| **A3-05** | Runtime attestation drift: subtle package differences between `pip freeze` and `importlib.metadata`. | Implemented single canonical representation (`normalized-pkg-name==version`) comparing active runtime packages against `requirements-lock.txt` for exact set equality. |
| **A3-11** | Documentation and manifest reconciliation. | Reconciled `docs/gate-2-evidence.md` with manifests, preserved V2.1 rescore intact, generated V2.2 rescore. |

---

## 3. Final Authorization Review Findings (F1 to F6) & Remediations in Candidate V2.3

The Final Authorization Review of Candidate V2.2 issued `DO NOT AUTHORIZE BASELINE V2` with exactly six authorization findings. All six were independently reproduced, confirmed, and remediated in Candidate V2.3:

| Finding | Severity | Defect & Impact | Remediation in Candidate V2.3 |
|---|---|---|---|
| **F1** | HIGH | `normalize_menu_key()` used `.strip()`, erroneously repairing malformed model keys like `" 1 "` or `" other "` into valid keys (`"1"`, `"OTHER"`), masking hallucinations. | Refactored `normalize_menu_key()` to eliminate all whitespace stripping. Characters are preserved verbatim. Case-canonicalize `OTHER` only when the complete original semantic value is exactly the keyword `OTHER` (case-insensitive, exact length 5). Exported `normalize_model_menu_key = normalize_menu_key`. Bumped `evaluator_version` to `2.3.0`. |
| **F2** | HIGH | Application code was executed directly from the mutable working tree, permitting executable overlays (forged `.pyc`, untracked root packages like `dotenv/`, `openai.py`, or assume-unchanged files) to hijack execution. | Implemented two-phase architecture: Phase A runs stdlib-only preflight; Phase B extracts an immutable Git application snapshot from authorized commit tree (`git archive <expected_git_sha>`) under a sanitized Git environment into a temporary directory. The child execution process spawns with `-I -B`, controlled `cwd`, and isolated `sys.path`. |
| **F3** | HIGH | The model alias was frozen via `--expected-model`, but the Foundry project endpoint / resource was not frozen pre-invocation. | Added `--expected-project-fingerprint <sha256>` (64 hex characters) required for baseline runs. Implemented canonical URL normalization and SHA256 hashing. Runner verifies project fingerprint pre-invocation before any reservation or model call. |
| **F4** | MEDIUM | Actual Python runtime identity was not persisted, omitting interpreter build, implementation, cache tag, and isolation state. | Persisted host-owned runtime provenance dictionary in `run-metadata.json` containing `python_version`, `python_implementation`, `python_cache_tag`, `python_build`, `isolated_mode`, `runtime_manifest_sha256`, `dependency_lock_sha256`, and `interpreter_binary_sha256`. Purged local filesystem paths (`sys.executable`). |
| **F5** | MEDIUM | Failure during initial RESERVED state write stranded the artifact run label directory. | Implemented atomic run-directory reservation with automatic rollback: if initial state writing fails, the preparation directory is completely unlinked and removed, leaving zero surviving bytes or partial metadata. `atomic_write_json` removes temporary files on any exception. |
| **F6** | MEDIUM | Late-failed runs or error exceptions could retain raw Foundry endpoints in on-disk artifacts or exception logs. | Completely removed `endpoint` from `ExecutionMetadata` and disk artifacts. Replaced with `foundry_project_fingerprint`. Sanitized exception messages in `write_failure_run_state` to strip endpoints and credentials. Raw endpoints are never persisted. |

---

## 4. The Four Required Amendments (Approved for V2.3)

1. **Amendment 1: Harden Git Object Provenance**
   - Provenance-critical Git subprocesses (`rev-parse`, `ls-tree`, `show`, `archive`, `status`) execute under an explicitly sanitized Git environment:
     - `GIT_NO_REPLACE_OBJECTS=1` enforced unconditionally.
     - Environment removes inherited values for `GIT_DIR`, `GIT_WORK_TREE`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_INDEX_FILE`, and `GIT_REPLACE_REF_BASE`.
   - The application snapshot is extracted from the real object tree corresponding to `expected_git_sha` (`commit SHA -> tree -> extracted committed bytes`) before any application import.
   - Deterministic offline regression test verifies that git replace refs cannot spoof or alter the extracted snapshot bytes.
2. **Amendment 2: Canonical Foundry Project Fingerprint**
   - Canonical URL normalization function implemented centrally:
     - Trims external whitespace.
     - Strictly requires HTTPS scheme (rejects any other scheme).
     - Lowercases scheme and hostname.
     - Strips default port 443 if present.
     - Strips a single insignificant trailing slash.
     - Preserves project and path casing identity (never lowercases path blindly).
     - Rejects unexpected userinfo, query strings, and fragments.
   - Computes `SHA256(canonical_endpoint)` as a 64-character lowercase hexadecimal string.
   - Used identically for expected fingerprint creation and effective runtime config validation.
   - Authorized Foundry Project Fingerprint published below. Raw endpoint is never persisted or committed.
3. **Amendment 3: Initial Run Reservation Leaves Zero Stranded Bytes**
   - Implemented atomic reservation lifecycle:
     - Preflight checks must fully succeed before reservation.
     - Reservation creates directory and atomically writes initial `RESERVED` `run-state.json`.
     - Any failure during initial preparation triggers complete rollback: unlinks any temporary files, deletes `run-state.json`, and removes the directory.
     - Proved via offline tests: one-time failure leaves directory reusable; permanent failure leaves zero stranded bytes; concurrent reservation allows at most one process to succeed.
   - No model invocation can occur before durable initial reservation succeeds.
4. **Amendment 4: Strict Separation of Application / Dependencies / Output**
   - Parent process establishes three distinct provenance roots:
     - **APPLICATION CODE**: Authorized Git-derived snapshot directory only (`agents.*`, `src.*`).
     - **DEPENDENCIES**: Attested project virtualenv site-packages only (`openai`, `pydantic`, `azure.ai.projects`, `azure.identity`, `dotenv`).
     - **OUTPUT**: Parent-reserved artifact directory passed as an explicit internal capability.
   - Child execution process runs with `-I -B` under controlled `cwd` set to snapshot path.
   - Child verifies that the target artifact directory matches the parent capability.
   - Mutable working tree is completely excluded from the child's `sys.path`.
   - Snapshot temporary directory is safely cleaned up after child terminates without altering durable artifacts.

---

## 5. Authorized Foundry Project Fingerprint

The deterministic canonical fingerprint for the authorized Foundry project is:

```
3f0c34d730680ad8baac11d2825e120045eb19be1d9ec1c0b2a2d337096ae33f
```

- **Target Model Alias:** `gpt-5-mini`
- **Canonical Algorithm:** `SHA256(canonical_https_url)`
- **Raw Endpoint Persistence:** **ZERO** (raw endpoint is never written to disk or logs).

---

## 6. Historical Baseline V1 Offline Rescore Results

### Preserved V2.1 Rescore (`evals/results/gate-2-v1-rescored-with-v2.1.json`)
- **Total Historical Predictions Converted:** 24
- **Supported Predicted Facts:** 18
- **Unsupported Predicted Facts:** 6
- **Invalid Evidence Count:** 5
- **Matched Expected Facts:** 10 / 15
- **Precision:** 0.75
- **Recall:** 0.6667
- **Gate 2 Pass:** `false`

### Preserved V2.2 Rescore (`evals/results/gate-2-v1-rescored-with-v2.2.json`)
- **Total Historical Predictions Converted:** 24
- **Supported Predicted Facts:** 10
- **Unsupported Predicted Facts:** 14
- **Invalid Evidence Count:** 5
- **Matched Expected Facts:** 10 / 15
- **Precision:** 0.4167
- **Recall:** 0.6667
- **Gate 2 Pass:** `false`

---

## 7. Quality Gate Verification Status

All checks executed in the WSL Ubuntu 24.04 environment (`.venv` Python 3.12.3):

| Tool / Suite | Status | Details |
|---|---|---|
| `pytest` | **PASS (123/123)** | 100% offline tests passing across all test suites |
| Authorization Regressions V2.3 | **PASS (30/30)** | Explicit tests for F1–F6 and Amendments 1–4 in `evals/tests/test_authorization_regressions_v2_3.py` |
| Adversarial Regressions V3 | **PASS (26/26)** | Explicit tests for A3-01 to A3-11 and V2.2 Amendments 1–6 in `evals/tests/test_adversarial_regressions_v3.py` |
| Adversarial Regressions V2 | **PASS (28/28)** | Historical regression tests in `evals/tests/test_adversarial_regressions.py` |
| COBOL Reader Unit Suite | **PASS (23/23)** | Unit tests for reader, AST, fact extraction, and prompt contracts in `evals/tests/test_cobol_reader.py` |
| Source Mutation Suite | **PASS (10/10)** | In-memory source mutation tests proving dynamic AST and evidence tracking |
| Offline Verification Suite | **PASS (4/4)** | Offline agent and pipeline tests in `tests/test_offline.py` |
| Mandatory Positive Invariant | **PASS** | `make_perfect_assessment_v2()` -> Precision 1.0, Recall 1.0, 0 unsupp, 0 inv_ev, 0 dup, 0 cont, `gate_2_pass: True` |
| `ruff check .` | **PASS** | 0 lint errors |
| `ruff format --check .` | **PASS** | 37 files formatted and compliant |
| `mypy src agents scripts tests evals` | **PASS** | 0 issues found in 28 source files |
| `pip check` | **PASS** | No broken requirements found |
| Legacy Immutability | **PASS** | `git diff -- legacy/core-banking-system/` is strictly empty; SHA256 `b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028` |

---

## 8. Execution Command for Future Baseline V2

When authorized by human review, BASELINE V2 must be invoked in isolated Python mode with exact parameters:

```bash
.venv/bin/python -I scripts/run-gate-2.py \
  --run-label baseline-v2 \
  --expected-git-sha <AUTHORIZED_CANDIDATE_V2_3_COMMIT_SHA> \
  --expected-model gpt-5-mini \
  --expected-project-fingerprint 3f0c34d730680ad8baac11d2825e120045eb19be1d9ec1c0b2a2d337096ae33f
```
