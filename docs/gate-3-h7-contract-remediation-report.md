# Gate 3 H7.1 Contract 3.5.0 Remediation Report

**Date:** 2026-09-12  
**Contract Version:** 3.5.0  
**Functional Commit (H7-0):** `cf98c24c9e5cd0e2e9b4287ec8101ad78efc8763`  
**Hotfix Functional Commit (H7.1-0):** `8ef190c719b4f9ece622de5e5ce912d9783d7687`  
**Classification:** `MIXED_CONTRACT_REMEDIATION`  
**Mode:** OFFLINE ONLY  
**Live Provider Calls:** 0  
**Baseline-v2 Executed:** NO  

---

## 1. Executive Summary

Following the offline scientific postmortem of Gate 3 Baseline-v1 (official result 24/59, FAIL), Contract 3.5.0 and Hotfix H7.1 implement deterministic remediation across schema constraints, system prompt instructions, verifier capabilities, CLI default coherence, strict authorization diff binding, and supplementary proposition policies.

Crucially, H7/H7.1 strictly adheres to the core principle: **REJECT, NEVER REPAIR**. Host validators reject malformed model values without normalizing, stripping prefixes, or filling missing semantic declarations. All 59 required golden facts remain factually and semantically identical.

---

## 2. Preconditions & Baseline-v1 Immutability

### Baseline-v1 Artifact Manifest Verification
Baseline-v1 artifacts and specification remain permanently frozen and immutable:
- **Baseline-v1 Candidate SHA (C1):** `9f5c5d2dbe4f1c61aa666f3a3388b54d89751669`
- **Baseline-v1 Authorization SHA (A1):** `9672708e6bcdc01f9d6377535afbb9e11258126e`
- **Baseline-v1 Spec SHA-256 (`evals/baselines/gate-3-baseline-v1.json`):**  
  `b37e8815e2605f279ecc417b8e037f0b235f5e1dcfa64d79b10708e852509695`
- **Baseline-v1 Artifact Manifest (`artifacts/gate-3/baseline-v1/manifest.json`):**  
  All 13 recorded artifact file hashes verified 100% identical:
  - `authorization-spec.json`: `45aaa53c18dcdb1302df1fe6b737738f2726d4e87543f905482e581588282ffa`
  - `canonical-input-bundle.txt`: `18aaf4dbf9cfa7c279b047ee26744d7b763d3c6f77770818b191e1756f20152d`
  - `enriched-assessment.json`: `3dae1133961c0fd990db109ebc499682ef458ae48cd06e27d89b919619267e76`
  - `evaluation.json`: `d4726ac356a83ad8c46de6f2367039cadc5be34ef71eb57a42679cacbdbe8fcd`
  - `model-assessment.json`: `3dae1133961c0fd990db109ebc499682ef458ae48cd06e27d89b919619267e76`
  - `parser-coverage-certificate.json`: `a33df30b73f79ac053afd5118fa3cb1ed97413a255b31b1f2ef169c1c4f948e3`
  - `production-prompt.md`: `5561e3cb9a57f48f71eeb19b5a1801ecf96d4aefdbf81ded01e915524171c944`
  - `raw-response.json`: `9afc19c399eef0ddbed56c8def4ab6cacc370ca4079f0df42619e840a1f43b2b`
  - `run-metadata.json`: `1a260a9b718c6bfeee841c1f402e39f609f52f34ece9566d32cc0e5d00e93e61`
  - `runtime-manifest.json`: `54cc4318fc3dde9f049f8ba0af14045473bcad33cad32c25e9ea1f42bff49d74`
  - `source-manifest.json`: `1e66800ec41272af55dec2b9f78a3dc1d02979870c26c8327943a5276235b203`
  - `terminal-result.json`: `125ab79d1d4268d49fecad9ca27f625e55cb0d70f09e537f8e84d68ca724cced`
  - `wire-schema.json`: `45f32c9e0a65bc039b94f7270efff88f3d92cc86e09288a9c1033cf465c3529a`
- **Legacy Source Fixture (`legacy/`):** 0 diff lines (completely unchanged).

---

## 3. Verifier Capability Matrix (Deterministic Implementation Mapping)

Derived directly from `SystemAssessment`, `SystemCobolParser`, `SystemSupportIndex`, and `SystemEvaluatorV3`:

| Fact Category | Model-Visible Fields | Parser Produced Facts | Support Index Certified Facts | Supplementary Assertions Verifiable? | Canonical Semantic Key Representation | Canonical Evidence Roles | Evidence Span Rule |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **ProgramDeclaration** | `program_id`, `evidence` | PROGRAM-ID division headers | Program compilation units in bundle | No (bundle compilation units only) | `PROGRAM_DECLARATION\|{program_id}` | `evidence` | Physical line span occupied by PROGRAM-ID statement only |
| **RecordLayout** | `program_id`, `record_name`, `fields` (`field_kind`, `level`, `name`, `picture`, `usage`, `condition_values`), `evidence` | 01 record layout definitions and elementary items | 01 record layouts in bundle | No (bundle 01 records only) | `RECORD_LAYOUT\|{program_id}:{record_name}` | `evidence` | Physical line span from 01 level declaration through its constituent fields |
| **RecordLayoutRelation** | `layout_a_name`, `layout_b_name`, `relation_type` (`IDENTICAL`, `EQUIVALENT`, `REPRESENTATION_MISMATCH`), `evidence_a`, `evidence_b` | All $N(N-1)/2$ pairwise layout combinations (10 pairs for 5 layouts) | All 10 pairwise comparisons certified deterministically | **YES** (exhaustive pairwise coverage certified) | `LAYOUT_RELATION:{layout_a_name}:{layout_b_name}:{relation_type}` | `evidence_a`, `evidence_b` | Exact physical line spans of layout A and layout B declarations respectively |
| **InternalCallResolution** | `caller_program`, `callee_program`, `call_evidence`, `target_declaration_evidence` | Calls resolving internally within repository | Internal caller-to-callee linkage | No (bundle calls only) | `INTERNAL_CALL_RES\|{caller_program}->{callee_program}` | `call_evidence`, `target_declaration_evidence` | Exact physical line spans for CALL in caller and PROGRAM-ID in callee |
| **CallerContinuationConstraint** | `caller_program`, `callee_program`, `constraint_type` (`PROCESS_TERMINATION_ON_CALL`, `RETURN_TO_CALLER`), `call_evidence`, `callee_termination_evidence` | CALL statements paired with callee STOP RUN / GOBACK | Caller execution termination constraints | No (bundle pairs only) | `CALLER_CONT_CONSTRAINT\|{caller_program}->{callee_program}\|{constraint_type}` | `call_evidence`, `callee_termination_evidence` | Exact physical line spans occupied by CALL in caller and termination in callee |
| **ResourceLifecycle** | `program_id`, `resource_name`, `access_mode` (`INPUT`, `OUTPUT`), `ordered_operations` (`OPEN_INPUT`, `OPEN_OUTPUT`, `OPEN_IO`, `OPEN_EXTEND`, `READ`, `WRITE`, `REWRITE`, `DELETE`, `CLOSE`), `evidence` | File control entries & I/O procedural statements | Strict sequence of lifecycle verbs per file | No (bundle files only) | `RESOURCE_LIFECYCLE\|{program_id}:{resource_name}\|{access_mode}\|{','.join(ordered_operations)}` | `evidence` | Exact physical line span enclosing the resource lifecycle routine |
| **OperationSequence** | `program_id`, `first_operation`, `second_operation`, `first_assignment_evidence`, `first_call_evidence`, `second_assignment_evidence`, `second_call_evidence` | Sequential external command dispatches | Temporal ordering between external operations | No | `OPERATION_SEQUENCE\|{program_id}:{first_operation}->{second_operation}` | `first_assignment_evidence`, `first_call_evidence`, `second_assignment_evidence`, `second_call_evidence` | Exact physical line spans for assignments and calls |
| **ComputationDataflow** | `program_id`, `source_field`, `target_field`, `operation_verb` (`ADD`, `SUBTRACT`, `MOVE`), `evidence` | Arithmetic and move statements | Field-level transformations and accumulations | No (open-ended field combinations unverifiable) | `COMPUTATION_DATAFLOW\|{program_id}:{source_field}->{target_field}\|{operation_verb}` | `evidence` | Exact physical line span occupied by computation statement only |
| **PlatformDependency** | `program_id`, `platform_family` (`WINDOWS`, `POSIX`, `MAINFRAME_OS`), `command_literal`, `evidence` | System call commands & platform invocations | Discrete command syntax literals | No (open-ended command literals unverifiable) | `PLATFORM_DEPENDENCY\|{program_id}:{platform_family}\|{command_literal}` | `evidence` | Exact physical line span containing the command literal statement |
| **BehavioralRisk** | `program_id`, `risk_category` (`IO_ERROR_HANDLING`, `DATA_INTEGRITY`), `risk_basis_kind` (`MISSING_ERROR_STATUS`, `NON_ATOMIC_EXTERNAL_MUTATION`), `impact_category` (`ERROR_VISIBILITY`, `DATA_INTEGRITY`), `resource_name`, `operation_evidence`, `affected_resource_evidence` | File status checks and atomicity defects | Host-verifiable risk patterns | No (speculative risks unverifiable) | `BEHAVIORAL_RISK\|{program_id}:{risk_category}\|{risk_basis_kind}\|{impact_category}\|{resource_name}` | `operation_evidence`, `affected_resource_evidence` | Exact physical line spans for defect statement and resource |
| **DataTransferRelation** | `program_id`, `source_entity`, `target_entity`, `transfer_verb` (`MOVE`), `evidence` | 01-record MOVE relationships only | 01-record level data transfers | No (elementary field transfers unverifiable) | `DATA_TRANSFER_RELATION\|{program_id}:{source_entity}->{target_entity}\|{transfer_verb}` | `evidence` | Exact physical line span occupied by record MOVE statement |
| **DataStateComparison** | `entity_id`, `dat_record_value`, `initializer_code_value`, `causal_provenance`, `dat_evidence`, `initializer_evidence` | Cross-file fixture vs code discrepancy analysis | Data discrepancies between persistent fixtures and initializers | No (open-ended fields unverifiable) | `DATA_STATE_CMP:{entity_id}:{dat_record_value}:{initializer_code_value}:{causal_provenance}` | `dat_evidence`, `initializer_evidence` | Exact physical line spans in data file and initializer code respectively |

---

## 4. Remediation Highlights & Anti-Repair Enforcement

### Principle: Reject, Never Repair
The validator strictly rejects malformed outputs rather than mutating or cleaning them:
1. **PICTURE Clause:**
   - Model must emit the canonical specification body (e.g., `X(20)`, `9(10)`).
   - Rejects leading `PIC ` or `PICTURE ` keywords (`ValidationError`).
   - Rejects trailing periods `.` (`ValidationError`).
2. **USAGE Specification:**
   - Required for `DATA_FIELD` (`DISPLAY`, `COMP-3`, `BINARY`).
   - Implicit COBOL usage must be emitted explicitly as `DISPLAY`. Defaulting or silently injecting `DISPLAY` on the host side is forbidden.
   - `CONDITION_NAME` (level-88) must have `null` usage and `null` picture.
3. **Container Identifiers:**
   - `RecordLayout.program_id` rejects path separators (`/`, `\`) and extensions (`.CPY`, `.CBL`).
4. **Lifecycle Operation Verbs:**
   - Constrained to `Literal["OPEN_INPUT", "OPEN_OUTPUT", "OPEN_IO", "OPEN_EXTEND", "READ", "WRITE", "REWRITE", "DELETE", "CLOSE"]`.
   - Descriptive modifiers such as `(loop)` or `(per record)` are rejected.
5. **Platform Commands:**
   - Discrete command literals required. Rejects placeholders (`<...>`, `*`).
6. **CallerContinuationConstraint Roles:**
   - Preserved and verified: `call_evidence` (CALL in caller), `callee_termination_evidence` (termination in callee).

### Hotfix H7.1 Fixes (F1 & F2)
1. **F1 — CLI Default Coherence:**
   - `--run-label` defaults to `None`.
   - When omitted, `execute_gate_3` dynamically derives the effective `run_label` directly from the selected authorization specification's `run_label` (`spec["run_label"]`).
   - Thus default auth spec (`baseline-v2`) resolves to effective default run_label (`baseline-v2`).
   - Explicit mismatched run-label/spec calls (e.g. `--auth-spec v2 --run-label baseline-v1`) fail closed with `ValueError`.
   - Explicit v1 spec (`--auth-spec v1`) continues to support `baseline-v1` for historical offline verification.
2. **F2 — Strict Authorization Diff Binding:**
   - `validate_authorization_contract` derives the canonical repository-relative path of the selected authorization spec.
   - It requires candidate-to-authorization commit diff `C..A` to touch strictly and only `[rel_spec_path]`.
   - A v2 execution whose A commit modifies v1 is refused (`RuntimeError`).
   - A v1 execution whose A commit modifies v2 is refused (`RuntimeError`).
   - Multi-file authorization commits are refused (`RuntimeError`).

---

## 5. Golden Dataset Semantic Equality Proof

The proposition content and policy in `evals/expected/system-understanding-v3.json` were proven strictly identical:
- **HEAD Golden Semantic Digest:** `0bb874ca3070f71f23134fe2ec4f7cc2d48c37d2bc4663887d343a6d159d65f2`
- **H7-0 Golden Semantic Digest:** `0bb874ca3070f71f23134fe2ec4f7cc2d48c37d2bc4663887d343a6d159d65f2`
- **H7.1-0 Golden Semantic Digest:** `0bb874ca3070f71f23134fe2ec4f7cc2d48c37d2bc4663887d343a6d159d65f2`
- **Required Proposition Count:** 59 (Identical)
- **Status:** `old_digest == new_digest` (PASS)

---

## 6. Cryptographic Artifact Hashes (Contract 3.5.0)

- **Production Prompt SHA-256 (`agents/legacy_analyzer/prompts/system_v3.md`):**  
  `0bf26bced63e4f1d548f347d6958eda37370ce62651f88157adab9a89a17daaa`
- **Wire Schema SHA-256 (`json.dumps(wire_schema, sort_keys=True)`):**  
  `98ec1dbba32ac259c6d939b72d83a65a3d6b5cd6fe97d293d38f0737bee697a4`
- **Golden Dataset SHA-256 (`evals/expected/system-understanding-v3.json`):**  
  `3091efa8dd27cb5af56ff1f4eba8f6713feedbf68b192c1c70b8978071964a60`
- **Canonical Input Bundle SHA-256:**  
  `95bb386b51d653c0a1834e1950634a9887b7cb6826b8c317a07c4b6a4167d060`
- **Source Manifest SHA-256:**  
  `daf28b3314199db8e31bfacdf2fb8441b54682caa7854ed288e1bc00866a1dd1`
- **Dependency Lock SHA-256 (`requirements-lock.txt`):**  
  `732cb9370e90af2d0972eeda7fc18fd5745f17cb301f359b268df228fe7f18be`

---

## 7. Quality Gates & Test Suite Verification

1. **Targeted H7 Regression Suite (`evals/tests/test_h7_contract_regressions.py`):**  
   18 passed (Tests A through P, anti-repair proof, positive oracle).
2. **Runner & Authorization Contract Suite (`evals/tests/test_gate_3_runner.py`):**  
   12 passed (including F1 CLI default coherence and F2 4-way adversarial diff binding).
3. **Remediation Regression Suite (`evals/tests/test_gate_3_remediation_regressions.py`):**  
   25 passed.
4. **Full Repository Pytest Suite:**  
   287 passed, 0 failures.
5. **Linter & Formatter (`ruff check .`, `ruff format --check .`):**  
   Passed (0 errors, 68 files formatted cleanly).
6. **Static Type Checking (`mypy .`):**  
   Passed (Success: no issues found in 53 source files).
7. **Dependency Hygiene (`pip check`):**  
   Passed (No broken requirements found).
8. **Gate 2 Regression Tests:**  
   Passed (30 adversarial regressions passed, 4 offline contract tests passed).
9. **Positive Oracle Verification:**  
   `precision = 1.0`, `recall = 1.0`, `unsupported = 0`, `duplicates = 0`, `contradictions = 0`, `invalid evidence = 0`, `Gate 3 PASS`.
10. **Anti-Overfitting Verification:**  
    Model-facing prompt and schema docstrings verified free of fixture-specific program names, copybook names, account numbers, and dataset values.

---

## 8. Final Status
- **Commit H7.1-0:** `8ef190c719b4f9ece622de5e5ce912d9783d7687`
- **Commit H7.1:** Direct report-only child of `H7.1-0`
- **Remote Branch:** `feat/gate-3-system-analysis`
- **Baseline-v2 Spec:** `evals/baselines/gate-3-baseline-v2.json` with `candidate_git_sha = ""`
- **Execution Status:** Offline implementation complete. No baseline-v2 execution or authorization was performed.
