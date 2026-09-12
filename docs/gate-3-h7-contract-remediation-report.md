# Gate 3 H7 Contract 3.5.0 Remediation Report

**Date:** 2026-09-12  
**Contract Version:** 3.5.0  
**Functional Commit (H7-0):** `cf98c24c9e5cd0e2e9b4287ec8101ad78efc8763`  
**Classification:** `MIXED_CONTRACT_REMEDIATION`  
**Mode:** OFFLINE ONLY  
**Live Provider Calls:** 0  
**Baseline-v2 Executed:** NO  

---

## 1. Executive Summary

Following the offline scientific postmortem of Gate 3 Baseline-v1 (official result 24/59, FAIL), Contract 3.5.0 implements deterministic remediation across schema constraints, system prompt instructions, verifier capabilities, and supplementary proposition policies.

Crucially, H7 strictly adheres to the core principle: **REJECT, NEVER REPAIR**. Host validators reject malformed model values without normalizing, stripping prefixes, or filling missing semantic declarations. All 59 required golden facts remain factually and semantically identical.

---

## 2. Preconditions & Baseline-v1 Immutability

### Baseline-v1 Artifact Manifest Verification
Baseline-v1 artifacts and specification remain permanently frozen and immutable:
- **Baseline-v1 Candidate SHA (C1):** `9f5c5d2dbe4f1c61aa666f3a3388b54d89751669`
- **Baseline-v1 Authorization SHA (A1):** `9672708e6bcdc01f9d6377535afbb9e11258126e`
- **Baseline-v1 Spec SHA-256 (`evals/baselines/gate-3-baseline-v1.json`):**  
  `b37e8815e2605f279ecc417b8e037f0b235f5e1dcfa64d79b10708e852509695`
- **Baseline-v1 Artifact Manifest (`artifacts/gate-3/baseline-v1/manifest.json`):**  
  All 13 recorded artifact file hashes verified 100% identical.
- **Legacy Source Fixture (`legacy/`):** 0 diff lines (completely unchanged).

---

## 3. Verifier Capability Matrix

A comprehensive deterministic capability probe of `SystemCobolParser`, `SystemSupportIndex`, and `SystemEvaluatorV3` established the verifier boundaries:

| Category | Model-Visible Fields / Tokens | Facts Parser Produces | Facts Certified by Support Index | Supplementary Assertions Exhaustively Verifiable? | Canonical Semantic Key Representation | Canonical Evidence Roles | Evidence Span Rule |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **ProgramDeclaration** | `program_id` | PROGRAM-ID division headers | Distinct program compilation units | No (only compilation units in bundle) | `PROGRAM_DECLARATION\|{program_id}` | `evidence`: exact PROGRAM-ID statement | Physical line span occupied by PROGRAM-ID statement only (no division header) |
| **RecordLayout** | `program_id`, `record_name`, `fields` (`level`, `name`, `picture`, `usage`, `condition_values`) | 01-level record hierarchies and field items | File and working-storage 01 record layouts | No (only 01 records in bundle) | `RECORD_LAYOUT\|{program_id}:{record_name}` | `evidence`: 01 declaration through last field | Physical line span of 01 record declaration through its constituent fields |
| **RecordLayoutRelation** | `layout_a_name`, `layout_b_name`, `relationship_kind` (`IDENTICAL`, `EQUIVALENT_BYTE_COUNT`, `INCOMPATIBLE`) | All $N(N-1)/2$ pairwise layout combinations (10 pairs for 5 layouts) | All 10 pairwise comparisons certified deterministically | **YES** (exhaustive pairwise coverage) | `RECORD_LAYOUT_RELATION\|{layout_a}:{layout_b}` (ordered) | `evidence`: layout A physical span | Exact physical line span of layout A |
| **InternalCall** | `caller_program_id`, `target_program_id` | Procedural CALL statements | Internal program-to-program dispatch | No (only internal CALLs in bundle) | `INTERNAL_CALL\|{caller}->{target}` | `evidence`: exact CALL statement | Physical line span of CALL statement only |
| **CallerContinuationConstraint** | `caller_program_id`, `callee_program_id`, `termination_statement`, `call_evidence`, `callee_termination_evidence` | CALL statements paired with callee STOP RUN / GOBACK | Caller execution termination constraints | No (only pairs in bundle) | `CALLER_CONTINUATION_CONSTRAINT\|{caller}->{callee}` | `call_evidence`: CALL in caller; `callee_termination_evidence`: STOP RUN in callee | Exact physical line span occupied by each respective statement |
| **ResourceLifecycle** | `program_id`, `resource_name`, `access_mode` (`INPUT`, `OUTPUT`), `ordered_operations` (`OPEN_INPUT`, `OPEN_OUTPUT`, `OPEN_IO`, `OPEN_EXTEND`, `READ`, `WRITE`, `REWRITE`, `DELETE`, `CLOSE`) | File control entries & I/O procedural statements | Strict sequence of lifecycle verbs per file | No (only files in bundle) | `RESOURCE_LIFECYCLE\|{program_id}:{resource}` | `evidence`: enclosing procedure/paragraph | Exact physical line span enclosing the resource lifecycle routine |
| **OperationSequence** | `program_id`, `first_operation`, `second_operation`, 4 evidence spans | Sequential external command dispatches | Temporal ordering between external operations | No | `OPERATION_SEQUENCE\|{program_id}:{op1}->{op2}` | `first_assignment_evidence`, `first_call_evidence`, `second_assignment_evidence`, `second_call_evidence` | Exact physical line spans for assignments and calls |
| **ComputationDataflow** | `program_id`, `source_field`, `target_field`, `operation_verb` (`ADD`, `SUBTRACT`, `MOVE`) | Arithmetic and move statements | Field-level transformations and accumulations | No (open-ended field combinations unverifiable) | `COMPUTATION_DATAFLOW\|{program_id}:{src}->{tgt}` | `evidence`: arithmetic/move statement | Exact physical line span occupied by computation statement only |
| **PlatformDependency** | `program_id`, `platform_family`, `command_literal` | System call commands & platform invocations | Discrete command syntax literals | No (open-ended commands unverifiable) | `PLATFORM_DEPENDENCY\|{program_id}:{command}` | `evidence`: command statement | Exact physical line span of statement containing literal |
| **BehavioralRisk** | `program_id`, `risk_category` (`IO_ERROR_HANDLING`, `DATA_INTEGRITY`), `risk_basis_kind` (`MISSING_ERROR_STATUS`, `NON_ATOMIC_EXTERNAL_MUTATION`), `impact_category` (`ERROR_VISIBILITY`, `DATA_INTEGRITY`) | File status checks and atomicity defects | Host-verifiable risk patterns | No (speculative risks unverifiable) | `BEHAVIORAL_RISK\|{program_id}:{basis}:{res}` | `operation_evidence`, `affected_resource_evidence` | Exact physical line spans for defect statement and resource |
| **DataTransferRelation** | `source_entity`, `target_entity`, `transfer_mechanism` | 01-record MOVE relationships only | 01-record level data transfers | No (elementary field transfers unverifiable) | `DATA_TRANSFER_RELATION\|{src}->{tgt}` | `evidence`: MOVE statement | Exact physical line span occupied by record MOVE statement |
| **DataStateComparison** | `dataset_name`, `field_name`, `expected_initial_value`, `source_written_value`, `discrepancy_detected`, `causal_provenance` | Cross-file fixture vs code discrepancy analysis | Data discrepancies between persistent fixtures and initializers | No (open-ended fields unverifiable) | `DATA_STATE_COMPARISON\|{dataset}:{field}` | `source_evidence`: value assignment statement | Exact physical line span of source assignment |

---

## 4. Anti-Repair Principle Implementation

Track A evaluates raw COBOL -> model -> `SystemAssessment`. H7 implements strict schema validators that fail closed rather than normalizing malformed inputs:
1. **PICTURE Clause:** Rejects `PIC ` / `PICTURE ` keywords and trailing sentence period `.`. Model must emit the canonical specification body (e.g. `X(20)`).
2. **USAGE Declaration:** Explicitly required for `DATA_FIELD` (`DISPLAY`, `COMP-3`, `BINARY`). Implicit COBOL usage must be emitted explicitly as `DISPLAY`. Defaulting or injecting `DISPLAY` is strictly forbidden.
3. **Container Identifiers:** `RecordLayout.program_id` rejects path separators (`/`, `\`) and file extensions (`.CPY`, `.CBL`).
4. **Lifecycle Verbs:** Rejects descriptive qualifiers (`(loop)`, `(per record)`). Emits only canonical tokens.
5. **Platform Commands:** Rejects placeholder templates (`<...>`, `*`).
6. **Risk Ontology:** Enforces closed `Literal` enumerations matching verifier certifications.

---

## 5. Golden Semantic Equality Proof

Golden dataset metadata was synchronized to version `3.5.0` while preserving 100% of propositions, semantic keys, evidence spans, and policy settings.

- **Old Golden Semantic Digest (HEAD):**  
  `0bb874ca3070f71f23134fe2ec4f7cc2d48c37d2bc4663887d343a6d159d65f2`
- **New Golden Semantic Digest (H7-0):**  
  `0bb874ca3070f71f23134fe2ec4f7cc2d48c37d2bc4663887d343a6d159d65f2`
- **Proposition Count:** 59 (Unchanged)
- **Result:** Exact semantic equality verified (`old == new`).

---

## 6. Target Baseline-v2 Contract (Contract 3.5.0)

A fresh baseline-v2 specification was created at `evals/baselines/gate-3-baseline-v2.json`:
- `spec_version`: `3.5.0`
- `run_label`: `baseline-v2`
- `candidate_git_sha`: `""` (unfrozen, awaiting future authorization)
- `requested_model`: `gpt-5-mini`
- `reasoning_effort`: `low`
- `openai_client_max_retries`: 0
- `application_model_retries`: 0
- `maximum_model_attempts`: 1
- `maximum_logical_invocation_count`: 1

### Synchronized Cryptographic Hashes
- `prompt_sha256`: `0bf26bced63e4f1d548f347d6958eda37370ce62651f88157adab9a89a17daaa`
- `wire_schema_sha256`: `6b03424b36738028901b89cb3fed037ab1db0d4b21e3b906db9370bd6ecd6c49`
- `golden_dataset_sha256`: `3091efa8dd27cb5af56ff1f4eba8f6713feedbf68b192c1c70b8978071964a60`
- `bundle_sha256`: `95bb386b51d653c0a1834e1950634a9887b7cb6826b8c317a07c4b6a4167d060`
- `source_manifest_sha256`: `daf28b3314199db8e31bfacdf2fb8441b54682caa7854ed288e1bc00866a1dd1`
- `dependency_lock_sha256`: `732cb9370e90af2d0972eeda7fc18fd5745f17cb301f359b268df228fe7f18be`

---

## 7. Quality Gates & Test Results

All offline quality gates passed cleanly:
1. **Targeted H7 Regression Suite (`evals/tests/test_h7_contract_regressions.py`):**  
   18 passed (Tests A through P, anti-repair proof, positive oracle).
2. **Full Repository Pytest Suite:**  
   285 passed.
3. **Ruff Lint:**  
   Passed (0 errors).
4. **Ruff Format:**  
   Passed (67 files formatted, 0 diffs).
5. **Mypy Typecheck:**  
   Passed (Success: no issues found in 53 source files).
6. **Pip Dependency Hygiene:**  
   Passed (No broken requirements found).
7. **Gate 2 Regression Tests:**  
   Passed (30 adversarial regressions passed, 4 offline contract tests passed).
8. **Positive Oracle Offline Verification:**  
   `precision = 1.0`, `recall = 1.0`, `unsupported = 0`, `duplicates = 0`, `contradictions = 0`, `invalid evidence = 0`, `Gate 3 PASS`.
9. **Anti-Overfitting Verification:**  
   Verified zero fixture-specific program names, copybook names, account IDs, dataset values, or known line numbers in model-facing materials (`agents/legacy_analyzer/prompts/system_v3.md` and schema docstrings).
