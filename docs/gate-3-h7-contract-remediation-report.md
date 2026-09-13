# Gate 3 H7.2 Contract 3.5.1 Remediation Report

**Date:** 2026-09-12  
**Contract Version:** 3.5.1  
**Functional Commit (H7.2-0):** `c559ece8fde0512759b29108978b2e528b752b87`  
**Classification:** `FINAL_CONTRACT_CORRECTION`  
**Mode:** OFFLINE ONLY  
**Live Provider Calls:** 0  
**Baseline-v2 Executed:** NO (`candidate_git_sha = ""`)  

---

## 1. Executive Summary

Following the independent review of H7.1 (Contract 3.5.0) which returned a "DO NOT PROCEED" verdict due to findings F-01 through F-07, Contract 3.5.1 implements the definitive contract correction under the approved four adjustments:

1. **Adjustment 1 (F-01 - Model-Side Canonical Boundary & Strict Reject-Never-Repair):**  
   Field classification separates fields into closed categorical tokens (strict `Literal` types / exact equality), COBOL identifiers (canonical uppercase logical tokens), and source/literal text (unquoted, whitespace-trimmed, case-preserved). Evaluator boundary enforces defense-in-depth assertion `model_value == fact_value` before fact registration. All silent host-side repairs and auto-normalizations are eliminated.
2. **Adjustment 2 (F-02 - Complete Layout Endpoint Canonicalization):**  
   Record layout relation endpoints are represented as complete pairs `(layout_name, evidence_span)` and canonicalized primarily by canonical layout name, using evidence coordinates only as a tie-breaker. Layout name and evidence span move together, guaranteeing `(A, evA), (B, evB) == (B, evB), (A, evA)` while rejecting swapped evidence `(B, evA), (A, evB)` without altering frozen golden semantics.
3. **Adjustment 3 (F-04 - Total Record Layout Comparator Preserving Semantics):**  
   The binary layout comparator is made total without redefining existing relation semantics. If field cardinality, PICTURE sequence, or USAGE sequence differs, `REPRESENTATION_MISMATCH` is returned. For representation-compatible layouts, the deterministic rule is preserved: identical container names yield `IDENTICAL`, differing container names yield `EQUIVALENT`.
4. **Adjustment 4 (F-05 C - Host-Only COBOL I-O Normalization):**  
   COBOL `OPEN I-O` syntax is mapped to canonical `access_mode = "IO"` and `operation = "OPEN_IO"` at host extraction only. The model schema strictly requires `IO` and `OPEN_IO`. Non-canonical model variants (`I-O`, `OPEN_I-O`, `OPEN_I_O`) fail schema validation.

All 59 frozen golden propositions remain bit-for-bit identical to commit A1 (`9672708e6bcdc01f9d6377535afbb9e11258126e`). Baseline-v1 artifacts and legacy fixtures remain strictly immutable.

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
- **Legacy Source Fixtures (`legacy/`):** 0 diff lines (verified against manifest `daf28b33...` and bundle `95bb386b...`).

---

## 3. Remediation of Independent Review Findings (F-01 through F-07)

### F-01 & Adjustment 1: Model-Side Canonical Boundary & Anti-Repair Invariant
- **Root Cause in H7.1:** Model-emitted noncanonical values (lowercase identifiers, leading/trailing whitespace, surrounding quotes, or noncanonical aliases) could pass schema validation and be silently repaired in `SystemAtomicFact.__post_init__` constructors before matching against golden facts.
- **Contract 3.5.1 Remediation:**
  - **Closed Categorical Tokens:** Bound to exact `Literal[...]` types across all schema models (`CallMechanism`, `StatementType`, `ContinuationConstraintType`, `FileOpVerb`, `LifecycleAccessMode`, `LifecycleOperationVerb`, `OperationKind`, `ComputationVerb`, `PlatformFamily`, `RiskCategory`, `RiskBasisKind`, `ImpactCategory`, `RecordRelationType`, `DataTransferVerb`, `CausalProvenance`). Non-canonical tokens fail schema validation directly.
  - **COBOL Identifiers:** Validated via `validate_canonical_identifier` requiring uppercase, no leading/trailing whitespace, and no consecutive spaces (`program_id`, `record_name`, field names, `internal_file_name`, `caller_program`, `target_program`, etc.).
  - **Source/Literal Text:** Validated via `validate_canonical_literal_text` requiring unquoted and trimmed text while strictly preserving lexical case and interior content (`command_literal`, `command_template`, `external_file_name`, `dat_record_value`, `initializer_code_value`, `picture`).
  - **Evaluator Defense-in-Depth:** In `SystemEvaluatorV3`, helper `_assert_canonical` verifies `model_val == fact_val` across all 17 fact categories before registering candidates, raising `ValueError` if any constructor transformation is detected.
  - **Anti-Repair Verification:** Test `test_h7_anti_repair_all_normalization_families` verifies fail-closed rejection across all 5 normalization families (identifier casing/whitespace, token casing, whitespace stripping, quote stripping, and alias mapping).

### F-02 & Adjustment 2: Complete Layout Endpoint Canonicalization
- **Root Cause in H7.1:** Permuted layout relation endpoints were canonicalized by sorting layout names without moving evidence spans, allowing mismatched name-evidence pairs to pass.
- **Contract 3.5.1 Remediation:**
  - Complete endpoint abstraction: `endpoint = (layout_name, evidence_span)`.
  - Canonical orientation determined primarily by canonical layout name, using evidence file path and line coordinates as tie-breakers if names are identical.
  - Symmetrical endpoint swap: `(name_a, span_a)` and `(name_b, span_b)` swap together.
  - Validated invariant: `(A, evA), (B, evB) == (B, evB), (A, evA)` passes, while swapped evidence `(B, evA), (A, evB)` is rejected as unsupported.
  - Verification: Test `test_h7_layout_endpoint_permutations_and_golden_invariance` validates canonical orientation, reversed complete endpoints, swapped names only, swapped evidence only, and duplicate detection across all 10 pairwise combinations.

### F-03: Dual-Basis Behavioral Risk Boundaries
- **Root Cause in H7.1:** `BehavioralRisk` evidence boundaries were underspecified for dual bases.
- **Contract 3.5.1 Remediation:**
  - Defined explicit evidence boundaries in schema and prompt:
    - For `MISSING_ERROR_STATUS`: `operation_evidence` covers the file operation envelope (first through last grounded file operation on affected binding); `affected_resource_evidence` covers the exact `SELECT/ASSIGN` binding span.
    - For `NON_ATOMIC_EXTERNAL_MUTATION`: `operation_evidence` covers the exact external mutation dispatch call interval; `affected_resource_evidence` covers the command assignment statement identifying the mutation target.
  - Verification: Test `test_h7_behavioral_risk_dual_basis_verification` verifies both risk bases in `TRANS-PROC` (`MISSING_ERROR_STATUS` and `NON_ATOMIC_EXTERNAL_MUTATION`) against the support index.

### F-04 & Adjustment 3: Total Layout Comparator Preserving Semantics
- **Root Cause in H7.1:** The proposed comparator redefined `IDENTICAL` to require matching field names, breaking existing fixture semantics.
- **Contract 3.5.1 Remediation:**
  - Implemented total comparator in `SystemCobolParser._compare_records_generically`:
    - If no `DATA_FIELD` exists: return `None`.
    - If field cardinality differs: return `REPRESENTATION_MISMATCH`.
    - If PICTURE sequence differs: return `REPRESENTATION_MISMATCH`.
    - If USAGE sequence differs: return `REPRESENTATION_MISMATCH`.
    - Else: if `rec_a.container_name == rec_b.container_name` return `IDENTICAL`, else return `EQUIVALENT`.
  - Verification: Existing fixture layout relations remain completely unchanged (4 IDENTICAL, 6 EQUIVALENT). In-memory mutation probe (`test_h7_heterogeneous_in_memory_layout_comparison_probe`) mutating `INIT-DB.CBL` `REC-ACC-NUMBER` `9(10)` to `9(11)` proves the comparator is total, yielding all 10 pairwise relations with `REPRESENTATION_MISMATCH` for modified pairs.

### F-05: Ontology Domain Enforcements & Host-Only Normalization
- **F-05 A (`ComputationDataflow`):** Restricted `operation_verb` to `Literal["ADD", "SUBTRACT"]`. Golden fact `TRANS-PROC:WS-TOTAL-TRANS` (`ADD`) verified.
- **F-05 B (`ResourceLifecycle.evidence`):** Clarified evidence span from FIRST resource operation through LAST resource operation for that lifecycle.
- **F-05 C & Adjustment 4 (`COBOL I-O Normalization`):** Host parser maps `OPEN I-O` to canonical `access_mode = "IO"` and `operation = "OPEN_IO"`. The model must emit `IO` and `OPEN_IO` exactly; non-canonical forms (`I-O`, `OPEN_I-O`, `OPEN_I_O`) fail schema validation. `INPUT` and `OUTPUT` remain unchanged.
- **F-05 D (`PlatformDependency`):** Restricted `platform_family` to `Literal["WINDOWS"]`.
- **F-05 E (`CallEdge` Evidence & Duplicates):** Bound evidence to the first source-order occurrence of the call edge. Evaluator duplicate detection flags redundant call edges (`test_h7_duplicate_call_edge_detection`).

### F-06: Mandatory Relative Path in Child Spec Loading
- **Root Cause in H7.1:** `load_authorization_spec_from_git` had a default argument `rel_path = DEFAULT_AUTH_SPEC_PATH`, risking incorrect spec loading in child mode.
- **Contract 3.5.1 Remediation:** Removed the default argument, making `rel_path` mandatory. In `execute_internal_child`, `rel_spec_path` is dynamically derived from `auth_spec_path.resolve().relative_to(provenance_repo.resolve()).as_posix()`. Verified for both `baseline-v1` and `baseline-v2` in `test_h7_child_auth_spec_propagation`.

### F-07 & Clarification: Strict Runtime Version Equality
- **Root Cause in H7.1:** Ambiguity regarding multi-version runtime execution.
- **Contract 3.5.1 Remediation:**
  - Enforced strict runtime equality: `actual_version == selected_spec_version`.
  - `SUPPORTED_CONTRACT_VERSIONS = {"3.4.3", "3.5.0", "3.5.1"}` recognizes valid contract versions for provenance and specification selection.
  - Current Contract 3.5.1 runtime strictly executes Contract 3.5.1 specifications and fails closed if invoked against historical Contract 3.4.3 or Contract 3.5.0 specifications (`test_h7_strict_runtime_version_equality_negative_tests`).

---

## 4. Verifier Capability Matrix (Contract 3.5.1)

| Fact Category | Model-Visible Fields | Parser Produced Facts | Support Index Certified Facts | Supplementary Assertions Verifiable? | Canonical Semantic Key Representation | Canonical Evidence Roles | Evidence Span Rule |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **ProgramDeclaration** | `program_id`, `evidence` | PROGRAM-ID division headers | Program compilation units in bundle | No (bundle compilation units only) | `PROGRAM_DECLARATION\|{program_id}` | `evidence` | Physical line span occupied by PROGRAM-ID statement only |
| **RecordLayout** | `program_id`, `record_name`, `fields` (`field_kind`, `level`, `name`, `picture`, `usage`, `condition_values`), `evidence` | 01 record layout definitions and elementary items | 01 record layouts in bundle | No (bundle 01 records only) | `RECORD_LAYOUT\|{program_id}:{record_name}` | `evidence` | Physical line span from 01 level declaration through its constituent fields |
| **RecordLayoutRelation** | `layout_a_name`, `layout_b_name`, `relation_type` (`IDENTICAL`, `EQUIVALENT`, `REPRESENTATION_MISMATCH`), `evidence_a`, `evidence_b` | All $N(N-1)/2$ pairwise layout combinations (10 pairs for 5 layouts) | All 10 pairwise comparisons certified deterministically | **YES** (exhaustive pairwise coverage certified) | `LAYOUT_RELATION:{layout_a_name}:{layout_b_name}:{relation_type}` | `evidence_a`, `evidence_b` | Exact physical line spans of layout A and layout B declarations respectively |
| **InternalCallResolution** | `caller_program`, `callee_program`, `call_evidence`, `target_declaration_evidence` | Calls resolving internally within repository | Internal caller-to-callee linkage | No (bundle calls only) | `INTERNAL_CALL_RES\|{caller_program}->{callee_program}` | `call_evidence`, `target_declaration_evidence` | Exact physical line spans for CALL in caller and PROGRAM-ID in callee |
| **CallerContinuationConstraint** | `caller_program`, `callee_program`, `constraint_type` (`PROCESS_TERMINATION_ON_CALL`, `RETURN_TO_CALLER`), `call_evidence`, `callee_termination_evidence` | CALL statements paired with callee STOP RUN / GOBACK | Caller execution termination constraints | No (bundle pairs only) | `CALLER_CONT_CONSTRAINT\|{caller_program}->{callee_program}\|{constraint_type}` | `call_evidence`, `callee_termination_evidence` | Exact physical line spans occupied by CALL in caller and termination in callee |
| **ResourceLifecycle** | `program_id`, `resource_name`, `access_mode` (`INPUT`, `OUTPUT`, `IO`, `EXTEND`), `ordered_operations` (`OPEN_INPUT`, `OPEN_OUTPUT`, `OPEN_IO`, `OPEN_EXTEND`, `READ`, `WRITE`, `REWRITE`, `DELETE`, `CLOSE`), `evidence` | File control entries & I/O procedural statements | Strict sequence of lifecycle verbs per file | No (bundle files only) | `RESOURCE_LIFECYCLE\|{program_id}:{resource_name}\|{access_mode}\|{','.join(ordered_operations)}` | `evidence` | Physical line span from FIRST through LAST resource operation |
| **OperationSequence** | `program_id`, `first_operation`, `second_operation`, `first_assignment_evidence`, `first_call_evidence`, `second_assignment_evidence`, `second_call_evidence` | Sequential external command dispatches | Temporal ordering between external operations | No | `OPERATION_SEQUENCE\|{program_id}:{first_operation}->{second_operation}` | `first_assignment_evidence`, `first_call_evidence`, `second_assignment_evidence`, `second_call_evidence` | Exact physical line spans for assignments and calls |
| **ComputationDataflow** | `program_id`, `source_field`, `target_field`, `operation_verb` (`ADD`, `SUBTRACT`), `evidence` | Arithmetic statements (`ADD`, `SUBTRACT`) | Field-level accumulations | No (open-ended field combinations unverifiable) | `COMPUTATION_DATAFLOW\|{program_id}:{source_field}->{target_field}\|{operation_verb}` | `evidence` | Exact physical line span occupied by computation statement only |
| **PlatformDependency** | `program_id`, `platform_family` (`WINDOWS`), `command_literal`, `evidence` | System call commands & platform invocations | Discrete command syntax literals | No (open-ended command literals unverifiable) | `PLATFORM_DEPENDENCY\|{program_id}:{platform_family}\|{command_literal}` | `evidence` | Exact physical line span containing the command literal statement |
| **BehavioralRisk** | `program_id`, `risk_category` (`IO_ERROR_HANDLING`, `DATA_INTEGRITY`), `risk_basis_kind` (`MISSING_ERROR_STATUS`, `NON_ATOMIC_EXTERNAL_MUTATION`), `impact_category` (`ERROR_VISIBILITY`, `DATA_INTEGRITY`), `resource_name`, `operation_evidence`, `affected_resource_evidence` | File status checks and atomicity defects | Host-verifiable risk patterns | No (speculative risks unverifiable) | `BEHAVIORAL_RISK\|{program_id}:{risk_category}\|{risk_basis_kind}\|{impact_category}\|{resource_name}` | `operation_evidence`, `affected_resource_evidence` | Operation envelope and affected resource declaration spans |
| **DataTransferRelation** | `program_id`, `source_entity`, `target_entity`, `transfer_verb` (`MOVE`), `evidence` | 01-record MOVE relationships only | 01-record level data transfers | No (elementary field transfers unverifiable) | `DATA_TRANSFER_RELATION\|{program_id}:{source_entity}->{target_entity}\|{transfer_verb}` | `evidence` | Exact physical line span occupied by record MOVE statement |
| **DataStateComparison** | `entity_id`, `dat_record_value`, `initializer_code_value`, `causal_provenance`, `dat_evidence`, `initializer_evidence` | Cross-file fixture vs code discrepancy analysis | Data discrepancies between persistent fixtures and initializers | No (open-ended fields unverifiable) | `DATA_STATE_CMP:{entity_id}:{dat_record_value}:{initializer_code_value}:{causal_provenance}` | `dat_evidence`, `initializer_evidence` | Exact physical line spans in data file and initializer code respectively |

---

## 5. Golden Dataset Semantic Equality Proof

The proposition content and policy in `evals/expected/system-understanding-v3.json` were proven strictly identical to commit A1:
- **Baseline-v1 / Commit A1 Golden Semantic Digest:**  
  `1160261957bddfe11ca13131da3cb2471d1dd1f5f208bf8cb4ce2e8dc9c77a92`
- **Contract 3.5.1 Golden Semantic Digest:**  
  `1160261957bddfe11ca13131da3cb2471d1dd1f5f208bf8cb4ce2e8dc9c77a92`
- **Required Proposition Count:** 59 (Identical)
- **Status:** `old_digest == new_digest` (PASS - bit-for-bit identical proposition content, semantic keys, categories, policies, and evidence spans).

---

## 6. Cryptographic Artifact Hashes (Contract 3.5.1)

- **Production Prompt SHA-256 (`agents/legacy_analyzer/prompts/system_v3.md`):**  
  `a8f8dff17829ccad292faec45271bc7683f6fd213d9e99482f88a60795281a9d`
- **Wire Schema SHA-256 (`get_system_openai_wire_schema()`):**  
  `98cb24f6ea22e3674b4425d362d67e6701bafcb186c4544a3411c6b7cdca20a1`
- **Golden Dataset SHA-256 (`evals/expected/system-understanding-v3.json`):**  
  `c299f4287db16d92b86c19186e648510f39adf09f53645a9959a4a67b9fbe45b`
- **Canonical Input Bundle SHA-256:**  
  `95bb386b51d653c0a1834e1950634a9887b7cb6826b8c317a07c4b6a4167d060`
- **Source Manifest SHA-256:**  
  `daf28b3314199db8e31bfacdf2fb8441b54682caa7854ed288e1bc00866a1dd1`
- **Dependency Lock SHA-256 (`requirements-lock.txt`):**  
  `732cb9370e90af2d0972eeda7fc18fd5745f17cb301f359b268df228fe7f18be`

All cryptographic hashes match `evals/baselines/gate-3-baseline-v2.json` exactly.

---

## 7. Quality Gates & Test Suite Verification

1. **Targeted H7 Regression Suite (`evals/tests/test_h7_contract_regressions.py`):**  
   25 passed (Tests A through W, anti-repair across all 5 normalization families, complete layout endpoint permutations and tie-breaking, heterogeneous 9(10)->9(11) in-memory layout mutation probe, behavioral risk dual-basis verification, child auth spec propagation, strict runtime version equality negative tests, duplicate call edge detection, positive oracle).
2. **Runner & Authorization Contract Suite (`evals/tests/test_gate_3_runner.py`):**  
   12 passed (including F1 CLI default coherence and F2 strict authorization diff binding).
3. **Remediation Regression Suite (`evals/tests/test_gate_3_remediation_regressions.py`):**  
   25 passed (including child failure scenarios, reservation state handling, and immutable artifact preservation).
4. **H5 & H6 Regression Suites:**  
   21 passed (post-seal immutability, multiprocess reservation races, preserved transport serialization).
5. **Full Repository Pytest Suite:**  
   294 passed, 0 failures (execution time 281s).
6. **Linter & Formatter (`ruff check .`, `ruff format --check .`):**  
   Passed (0 errors, 68 files formatted cleanly).
7. **Static Type Checking (`mypy .`):**  
   Passed (Success: no issues found in 53 source files).
8. **Dependency Hygiene (`pip check`):**  
   Passed (No broken requirements found).
9. **Dry-Run Preflight (`python scripts/run-gate-3.py --dry-run --allow-dirty`):**  
   `[OK] Dry-run preflight verification complete. All authorization checks PASSED.`
10. **Synthetic End-to-End Execution (`python scripts/run-gate-3.py --synthetic --allow-dirty`):**  
    `Gate 3 evaluation complete. Pass: True (59/59)`.

---

## 8. Final Status

- **Functional Commit (H7.2-0):** `c559ece8fde0512759b29108978b2e528b752b87`
- **Report Commit (H7.2):** Direct report-only child of `H7.2-0`
- **Remote Branch:** `feat/gate-3-system-analysis`
- **Baseline-v2 Spec:** `evals/baselines/gate-3-baseline-v2.json` with `candidate_git_sha = ""`
- **Execution Status:** Offline implementation complete. No baseline-v2 execution or authorization was performed.
