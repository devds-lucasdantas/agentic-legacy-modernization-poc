# GATE 3 POST-ASTRA REMEDIATION — AUDIT REPORT

**Generated mechanically from repository data and offline verification.**

## 1. Provenance and Repository State
- **Audited Remediated Candidate SHA (Commit H2-0)**: `3ec2ee1592cdf2cb44991d960a05d5b6c125546b`
- **Report HEAD (Commit H2)**: `PENDING_COMMIT`
- **Pre-Remediation Anchor HEAD**: `72467779ad3bc536bc8eafda8bec54ad22bf4797`
- **Pre-Astra Hotfix SHA**: `946b8bfd7bb93ec5912420d54d77a8f144a130f6`
- **Base Candidate SHA**: `48123358a2023dae91b56cb4437c9eeeb5a967f7`
- **Legacy Repository Status**: `UNTOUCHED / CLEAN` (all 6 legacy fixture files byte-identical)
- **Gate 2 Artifacts Status**: `UNTOUCHED / CLEAN`
- **Live Calls Made**: `0`
- **Baseline-v1 Executions Run**: `0`
- **Authorization Commit A**: `NOT CREATED` (strictly deferred)

### Recent Forward Git Commits
```text
3ec2ee1 feat(gate-3): post-astra remediation for system analysis
7246777 docs(gate-3): update remediation report for pre-astra hotfix candidate 946b8bf
946b8bf fix(gate-3): pre-astra hotfix - wire file status certificate, remove prompt leakage, eliminate expected_git_sha, enforce version contract
6a7267c docs(gate-3): record mechanically generated remediation round 3 audit report for candidate 4812335
4812335 feat(gate-3): round 3 pre-astra corrections (fail-closed parser, level-88 losslessness, file status certificate, 18 category policies, and runner plumbing)
```

## 2. Resolution of Adversarial Review Findings (Astra Remediation)

### CF1 / Findings 1-2: Resource-Grounded Behavioral Risks
- Extended `BehavioralRiskFact` and `BehavioralRisk` schema with `resource_name: str | None`.
- Updated `get_semantic_key()` to incorporate `resource_name` deterministically:
  `BEHAVIORAL_RISK:{program_id}:{risk_category}:{risk_basis_kind}:{impact_category}:{resource_name or ''}`.
- Grounded all `MISSING_ERROR_STATUS` risks in `ACCOUNT-FILE` and `TEMP-FILE` respectively.
- Grounded `NON_ATOMIC_EXTERNAL_MUTATION` in `ACCOUNTS.DAT`.

### CF2 / Finding 3: Extension-Preserving File Bindings
- Upgraded `ASSIGN TO` parser regex to be quote-aware and extension-preserving.
- Internal files bound to exact filesystem targets preserving `.DAT` and `.TMP` extensions:
  - `ACCOUNT-FILE` -> `ACCOUNTS.DAT`
  - `TEMP-FILE` -> `ACCOUNTS.TMP`
  - `BACKUP-FILE` -> `ACCOUNTS.BAK`
  - `REPORT-FILE` -> `TRANS_REPORT.TXT`
- Ground truth golden dataset V3.4.0 and parser support index perfectly aligned on canonical targets.

### CF3 / Finding 4: Generic Shell Classifier & Target-Matched Non-Atomic Mutation
- Replaced brittle string matching with `classify_command_operation(cmd_text)`.
- Generic classifier unnests shell wrappers (`cmd /c`, `/bin/sh -c`, `sh -c`, `bash -c`).
- Recognizes primitive file operations: `DELETE`, `RENAME`, `COPY`, `MOVE`.
- `NON_ATOMIC_EXTERNAL_MUTATION` is derived ONLY when the delete target strictly matches the rename target (`op1_tgt.upper() == op2_tgt.upper()`), identifying non-atomic in-place file replacement.

### CF4 / Finding 5: Unit-Scoped Record-to-FD Isolation
- Isolated `unit_record_to_fd: dict[str, dict[str, str]]` indexed by compilation unit (`program_id`).
- Precludes cross-program bleed where identical record level-01 identifiers in different files could falsely resolve across program boundaries.

### CF5 / Finding 6: Role-Bound Support Index Verification
- In `SystemSupportIndex`, added role-bound assertion verification: when candidate fact specifies `resource_name`, it MUST strictly match `target_record.internal_file_name`.
- Eliminates false positive matches on distinct file handles within the same program.

### CF6 / Finding 7: Ground Truth Dataset V3.4.0 Alignment
- Bumped golden dataset version to `3.4.0`.
- All 5 `BEHAVIORAL_RISK` entries fully grounded with their respective `resource_name`.
- All 4 `FILE_BINDING` entries preserve file extensions (`.DAT`, `.TMP`).
- Total expected facts: **60**.

### CF7 / Finding 8: Strict Precision Formula & Duplicate Rejection
- In `SystemEvaluatorV3` (v3.4.0):
  $$\text{precision} = \frac{\text{supported\_predicted\_count}}{\text{unique\_predicted\_count}}$$
- Duplicate assertion occurrences are tracked in `duplicate_prediction_count`.
- If `duplicate_prediction_count > 0`, the evaluator immediately enforces `gate_3_pass = False`.

### CF8 / Finding 9: Raw Provider Boundary Architecture
- Refactored `SystemAnalyzerAgent.invoke_raw()`:
  1. Invokes Responses API with frozen wire schema (`text={"format": wire_schema}`).
  2. Receives provider response BEFORE any Pydantic/schema validation.
  3. Returns `(response, metadata, raw_response_text)`.
- In `scripts/run-gate-3.py`:
  1. Raw provider response is IMMEDIATELY serialized and persisted to disk at `raw-response.json`.
  2. Transition to `POST_MODEL_RESPONSE` state.
  3. Only then calls `validate_and_parse_response()` for status, refusal, response-model, and Pydantic validation.
  4. Even if output is malformed or Pydantic validation fails, the raw provider payload remains permanently preserved on disk for auditability.

### CF9 / Finding 10: Evidence-Based Exact Model Match
- Inspected Gate 1 and Gate 2 execution records: provider response model ID is exact `"gpt-5-mini"`.
- Zero aliases permitted. Strict equality `response_model == requested_model` enforced.
- Any mismatch after the baseline call results in immediate terminal failure (status `FAILED`, exit code 1, raw response preserved, reservation permanently consumed, zero retries).

### CF10 / Finding 11: Direct Child Authorization Contract
- Enforced direct child relationship in `validate_authorization_contract()`:
  $$A\hat{\ } == C$$
- Validates that parent of authorization commit A is candidate commit C via `git rev-parse --verify {A}^`.
- Validates that git diff between C and A touches strictly and exclusively `evals/baselines/gate-3-baseline-v1.json`.

### CF11 / Finding 12: Two-Layer State Model
- Separated mutable coordination state from immutable scientific records:
  1. **`reservation-state.json`**: Mutable lifecycle coordination file (`RESERVED` -> `MODEL_INVOCATION` -> `POST_MODEL_RESPONSE` -> `FINALIZING` -> `COMPLETED` / `FAILED`). Explicitly excluded from `manifest.json`.
  2. **`terminal-result.json`**: Immutable scientific outcome and evaluation provenance record. Written during `FINALIZING`, before `manifest.json`, and strictly included and hashed in `manifest.json`.

### CF12 / Finding 13: Strict Single-Attempt Execution Policy
- Guaranteed single-attempt invocation:
  - `openai_client_max_retries = 0`
  - `application_model_retries = 0`
  - `maximum_model_attempts = 1`
  - `maximum_logical_invocation_count = 1`
- Any preflight failure exits 1 with zero network calls.

## 3. Independent Golden Dataset Verification (V3.4.0)
- **Authoring Method**: `INDEPENDENT_STATIC_SOURCE_AUDIT`
- **Total Required Facts**: `60`
- **Auditor Rationale Present**: `True`
- **Production Parser Independence**: Zero golden-authoring files import `SystemCobolParser` or `SystemSupportIndex`.

### Ground Truth Category Breakdown
| Proposition Category | Required Count | Category Policy |
| :--- | :---: | :--- |
| `BEHAVIORAL_RISK` | 5 | `REQUIRED_PREREGISTERED_CORE` |
| `CALLER_CONTINUATION_CONSTRAINT` | 3 | `REQUIRED_EXHAUSTIVE` |
| `CALL_EDGE` | 4 | `REQUIRED_EXHAUSTIVE` |
| `CALL_OCCURRENCE` | 6 | `REQUIRED_EXHAUSTIVE` |
| `COMMAND_INVOCATION` | 3 | `REQUIRED_EXHAUSTIVE` |
| `COMPUTATION_DATAFLOW` | 2 | `REQUIRED_PREREGISTERED_CORE` |
| `DATA_STATE_COMPARISON` | 1 | `REQUIRED_EXHAUSTIVE` |
| `DATA_TRANSFER_RELATION` | 1 | `REQUIRED_PREREGISTERED_CORE` |
| `FILE_BINDING` | 4 | `REQUIRED_EXHAUSTIVE` |
| `FILE_OPERATION` | 0 | `OPTIONAL_SUPPLEMENTARY` |
| `INTERNAL_CALL_RESOLUTION` | 3 | `REQUIRED_EXHAUSTIVE` |
| `OPERATION_SEQUENCE` | 1 | `REQUIRED_EXHAUSTIVE` |
| `PLATFORM_DEPENDENCY` | 3 | `REQUIRED_EXHAUSTIVE` |
| `PROGRAM_DECLARATION` | 4 | `REQUIRED_EXHAUSTIVE` |
| `RECORD_LAYOUT` | 5 | `REQUIRED_EXHAUSTIVE` |
| `RECORD_LAYOUT_RELATION` | 7 | `REQUIRED_PREREGISTERED_CORE` |
| `RESOURCE_LIFECYCLE` | 4 | `REQUIRED_EXHAUSTIVE` |
| `TERMINATION_SITE` | 4 | `REQUIRED_EXHAUSTIVE` |

**Sum of Category Expected Counts**: `60` (Mechanically verified == `60`)

## 4. Two-Phase Authorization Specification Integrity (V3.4.0)
- **Spec Version**: `3.4.0`
- **Target Run Label**: `baseline-v1`
- **Requested Model**: `gpt-5-mini`
- **Foundry Project Fingerprint**: `3f0c34d730680ad8baac11d2825e120045eb19be1d9ec1c0b2a2d337096ae33f`
- **Candidate Git SHA**: `` (empty string enforces no live calls on candidate commit)
- **Composite Source Bundle SHA256**: `95bb386b51d653c0a1834e1950634a9887b7cb6826b8c317a07c4b6a4167d060`
- **Source Manifest SHA256**: `daf28b3314199db8e31bfacdf2fb8441b54682caa7854ed288e1bc00866a1dd1`
- **Production Prompt SHA256**: `954b41a3375b47c0b82f939e6ce20f865f5733f3fa14f346ef8d52367dca23d2`
- **Wire Schema SHA256**: `dd3f87d4f3b50c3d973796d19ca7dae8b5d345f1b1b01da4e9ec6bc30e3bbd22`
- **Golden Dataset SHA256**: `c5678ee291b26c63bca64dae61cbbff7f99991ca6fc82aee0045d47509f63569`

## 5. Offline Verification Suite Results
| Check | Tool / Framework | Scope | Result | Details |
| :--- | :--- | :--- | :---: | :--- |
| Static Linting | `ruff check .` | Repository-wide | **PASS** | 0 errors |
| Formatting | `ruff format --check .` | Repository-wide | **PASS** | 64 files checked, 0 violations |
| Type Checking | `mypy` | `src agents scripts tests evals` | **PASS** | 49 source files, 0 issues |
| Dependencies | `pip check` | Active environment | **PASS** | No broken requirements |
| Unit & Regression Tests | `pytest -v` | All 10 test modules | **PASS** | **236 / 236 passed (100%)** in 178s |
