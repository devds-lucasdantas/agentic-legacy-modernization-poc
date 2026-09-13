# Gate 3 H7.3 Contract 3.5.2 Remediation Report

**Date:** 2026-09-13  
**Contract Version:** 3.5.2  
**Functional Commit (H7.3-0):** `3dfe8ff40c767e71fba3fa1458d3c26058e072f8`  
**Classification:** `FINAL_DOMAIN_CLOSURE_REMEDIATION`  
**Mode:** OFFLINE ONLY  
**Live Provider Calls:** 0  
**Baseline-v2 Executed:** NO (`candidate_git_sha = ""`)  

---

## 1. Executive Summary

Following the Gate 3 Plan Review approving the H7.3 / Contract 3.5.2 remediation plan with required clarifications, Contract 3.5.2 completes the final domain-closure remediation. This release resolves all remaining findings (F-01, F-03, F-05) while strictly preserving the passed areas from H7.2 (F-02, F-04, F-06, F-07):

1. **Host-Side Only PICTURE Canonicalization (Clarification 1 & F-01):**  
   `canonicalize_picture()` operates exclusively during host source parsing. The model-side wire schema requires an already-canonical lexical representation. `RecordFieldFact.__post_init__` performs zero repair. The evaluator explicitly asserts `model_fact.picture == host_fact.picture`. Non-canonical model variants (`PIC 9(10)`, `9(10).`, ` 9(10)`) fail without constructor transformation.
2. **Elimination of Punctuation Heuristics (Clarification 2 & F-01):**  
   Ad-hoc character replacement rules (such as `_` vs `-`) are completely eliminated. PICTURE punctuation is preserved exactly. The model value must match the host fact value exactly (`model -(10)9 == host -(10)9` passes; `model _(10)9` fails because values differ).
3. **Explicit Condition Value Domain & Content Preservation (Clarification 3 & F-01):**  
   `condition_values` represent source literal content. Host parsing removes syntactic quotation delimiters and preserves literal text content faithfully (casing, spaces, hyphens). The supported literal subset is strictly defined; unsupported forms (e.g. `THRU` ranges, complex quoting) fail parser coverage closed as `UNSUPPORTED_RELEVANT`. The evaluator asserts `model_val == fact_val`.
4. **Real Child Path Traversal in Test Suite (Clarification 4 & F-06/F-07):**  
   Tests 5E and 5F execute the genuine child entrypoint (`execute_internal_child`) with network boundaries isolated:
   - **5E:** Confirms that `load_authorization_spec_from_git` receives the exact relative spec path (`gate-3-baseline-v1.json` for v1, `gate-3-baseline-v2.json` for v2).
   - **5F:** Forces each component runtime version mismatch (golden dataset, wire schema, evaluator, prompt) through the real child path, verifying immediate exit code 1 with 0 provider calls before agent invocation.
5. **Final Model/Host Domain Capability Matrix (Clarification 5 & F-05):**  
   Every model-visible `Literal` token across `FileOperation`, `ResourceLifecycle`, `OperationSequence`, `ComputationDataflow`, `PlatformDependency`, `BehavioralRisk`, `CausalProvenance`, and `DataTransferRelation` has been audited against both the generated wire schema and the runtime support index. All uncertifiable tokens have been removed from the model domain.
6. **Preservation of Prior H7.2 Passes (Clarification 6):**  
   F-02 (complete layout endpoint canonicalization), F-04 (total layout comparator), F-06 (mandatory relative child spec path), and F-07 (strict runtime version equality) were re-verified with adversarial probes with zero regressions.

All 59 frozen golden propositions remain bit-for-bit identical in semantics, categories, and evidence spans to commit A1 (`9672708e6bcdc01f9d6377535afbb9e11258126e`). Baseline-v1 artifacts and legacy fixtures remain strictly immutable.

---

## 2. Preconditions & Baseline-v1 Immutability

### Baseline-v1 Artifact Manifest Verification
Baseline-v1 artifacts and specification remain permanently frozen and immutable:
- **Baseline-v1 Candidate SHA (C1):** `9f5c5d2dbe4f1c61aa666f3a3388b54d89751669`
- **Baseline-v1 Authorization SHA (A1):** `9672708e6bcdc01f9d6377535afbb9e11258126e`
- **Baseline-v1 Spec SHA-256 (`evals/baselines/gate-3-baseline-v1.json`):**  
  `b37e8815e2605f279ecc417b8e037f0b235f5e1dcfa64d79b10708e852509695`
- **Legacy Source Fixtures (`legacy/`):** 0 diff lines (verified against manifest `daf28b33...` and bundle `95bb386b...`).
- **Baseline-v2 Authorization Spec (`evals/baselines/gate-3-baseline-v2.json`):**  
  `candidate_git_sha = ""` (execution strictly unauthorized).

---

## 3. Detailed Remediation Breakdown

### F-01 & Clarification 1: PICTURE Canonicalization Host-Side Only & Anti-Repair
- **Host-Side Extraction:** `canonicalize_picture()` in `src/cobol/system_cobol_parser.py` strips `PIC` keywords, trailing periods, and normalizes standard whitespace during source parsing to generate the canonical host fact.
- **Model-Side Schema Boundary:** `validate_canonical_literal_text` in `agents/legacy_analyzer/schemas/system_assessment.py` validates that model-emitted PICTURE strings are unquoted, non-empty, and trimmed.
- **No Constructor Repair:** `RecordFieldFact.__post_init__` in `src/cobol/system_atomic_facts.py` does not perform canonicalization or repair.
- **Evaluator Explicit Invariant:** `SystemEvaluatorV3._evaluate_record_layout` compares `model_field.picture == host_field.picture` directly.
- **Rejection of Non-Canonical Representations:** Probes confirm that model values `PIC 9(10)`, `9(10).`, ` 9(10)`, and `_(10)9` are rejected.

### F-01 & Clarification 2: Elimination of `_` vs `-` Heuristic
- The parser, schema, and evaluator contain no character substitution heuristics between `_` and `-`.
- All PICTURE punctuation is preserved verbatim.
- Semantic correctness is determined solely by exact equality between model-emitted picture and host-fact picture.

### F-01 & Clarification 3: Condition Value Domain Explicitness & Strict Preservation
- **Source Literal Content:** Level-88 `condition_values` represent source literal content.
- **Host Parser Boundary:** `SystemCobolParser._parse_data_division` strips syntactic quotation delimiters (`'`, `"`) and preserves content verbatim. Casing, hyphens, and whitespace are preserved (e.g. `'SAVINGS-ACTIVE'` -> `SAVINGS-ACTIVE`).
- **Fail-Closed Parser Coverage:** Unsupported literal syntax (e.g., `THRU` range syntax or interior escaped quotes) triggers `UNSUPPORTED_RELEVANT`, failing parser coverage closed.
- **Evaluator Anti-Repair Assertion:** `SystemEvaluatorV3` asserts `model_val == fact_val` across all condition values, rejecting casing, whitespace, or quoting alterations.

### F-02: Complete Layout Endpoint Canonicalization (Preserved)
- Endpoints `(layout_name, evidence_span)` are canonicalized as complete units.
- Canonical orientation uses layout name primarily, with evidence file path and line coordinates as tie-breakers.
- `(A, evA), (B, evB)` is equivalent to `(B, evB), (A, evA)`, while swapped evidence `(B, evA), (A, evB)` is rejected as unsupported.

### F-03: Dual-Basis Behavioral Risk Boundaries
- Explicit evidence spans defined for both behavioral risk patterns:
  - `MISSING_ERROR_STATUS`: `operation_evidence` spans the file operation envelope; `affected_resource_evidence` covers the file binding `SELECT/ASSIGN`.
  - `NON_ATOMIC_EXTERNAL_MUTATION`: `operation_evidence` spans the external dispatch `CALL`; `affected_resource_evidence` covers the command assignment statement.

### F-04: Total Record Layout Comparator Preserving Semantics (Preserved)
- `SystemCobolParser._compare_records_generically` deterministically evaluates all pairs:
  - If field count, PICTURE sequence, or USAGE sequence differs: `REPRESENTATION_MISMATCH`.
  - If representation matches: identical container name yields `IDENTICAL`, differing container name yields `EQUIVALENT`.

### F-05 & Clarification 5: Final Model/Host Domain Capability Matrix
All model-visible `Literal` tokens across 8 categories are proven certified by fixture facts or generic synthetic overlays. Uncertifiable tokens were removed from Contract 3.5.2:
- `FileOperation`: `READ`, `WRITE`, `REWRITE`, `DELETE`, `OPEN_INPUT`, `OPEN_OUTPUT`, `OPEN_IO`, `OPEN_EXTEND`, `CLOSE` (all 9 certified).
- `ResourceLifecycle`: `access_mode` (`INPUT`, `OUTPUT`, `IO`, `EXTEND`), `ordered_operations` (7 certified lifecycle verbs).
- `OperationSequence`: `first_operation: Literal["DELETE"]`, `second_operation: Literal["RENAME"]` (pruned to certified operations).
- `ComputationDataflow`: `operation_verb: Literal["ADD", "SUBTRACT"]` (certified).
- `PlatformDependency`: `platform_family: Literal["WINDOWS"]` (certified).
- `BehavioralRisk`: `risk_category: Literal["IO_ERROR_HANDLING", "DATA_INTEGRITY"]`, `risk_basis_kind: Literal["MISSING_ERROR_STATUS", "NON_ATOMIC_EXTERNAL_MUTATION"]`, `impact_category: Literal["ERROR_VISIBILITY", "DATA_INTEGRITY"]` (certified).
- `CausalProvenance`: `causal_provenance: Literal["UNKNOWN"]` (pruned to certified token; speculative tokens removed).
- `DataTransferRelation`: `transfer_verb: Literal["MOVE"]` (certified).

### F-06 & Clarification 4: Real Child Path Traversal (Test 5E)
- `test_h7_5e_child_real_path_traversal` directly invokes `execute_internal_child`.
- Monitored argument `rel_path` passed to `load_authorization_spec_from_git`:
  - `gate-3-baseline-v1.json` for v1.
  - `gate-3-baseline-v2.json` for v2.

### F-07 & Clarification 4: Real Child Path Version Mismatch Rejection (Test 5F)
- `test_h7_5f_child_real_path_version_mismatches` tests each component mismatch via `execute_internal_child`:
  - Golden dataset version mismatch (`3.5.1` vs `3.5.2`) -> Exit 1, 0 provider calls.
  - Wire schema version mismatch (`3.5.1` vs `3.5.2`) -> Exit 1, 0 provider calls.
  - Evaluator version mismatch (`3.5.1` vs `3.5.2`) -> Exit 1, 0 provider calls.
  - Prompt version mismatch (`3.5.1` vs `3.5.2`) -> Exit 1, 0 provider calls.

---

## 4. Verifier Capability Matrix (Contract 3.5.2)

| Fact Category | Model-Visible Fields | Parser Produced Facts | Support Index Certified Facts | Supplementary Assertions Verifiable? | Canonical Semantic Key Representation | Canonical Evidence Roles | Evidence Span Rule |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **ProgramDeclaration** | `program_id`, `evidence` | PROGRAM-ID division headers | Program compilation units in bundle | No (bundle compilation units only) | `PROGRAM_DECLARATION\|{program_id}` | `evidence` | Physical line span occupied by PROGRAM-ID statement only |
| **RecordLayout** | `program_id`, `record_name`, `fields` (`field_kind`, `level`, `name`, `picture`, `usage`, `condition_values`), `evidence` | 01 record layout definitions and elementary items | 01 record layouts in bundle | No (bundle 01 records only) | `RECORD_LAYOUT\|{program_id}:{record_name}` | `evidence` | Physical line span from 01 level declaration through its constituent fields |
| **RecordLayoutRelation** | `layout_a_name`, `layout_b_name`, `relation_type` (`IDENTICAL`, `EQUIVALENT`, `REPRESENTATION_MISMATCH`), `evidence_a`, `evidence_b` | All $N(N-1)/2$ pairwise layout combinations (10 pairs for 5 layouts) | All 10 pairwise comparisons certified deterministically | **YES** (exhaustive pairwise coverage certified) | `LAYOUT_RELATION:{layout_a_name}:{layout_b_name}:{relation_type}` | `evidence_a`, `evidence_b` | Exact physical line spans of layout A and layout B declarations respectively |
| **InternalCallResolution** | `caller_program`, `callee_program`, `call_evidence`, `target_declaration_evidence` | Calls resolving internally within repository | Internal caller-to-callee linkage | No (bundle calls only) | `INTERNAL_CALL_RES\|{caller_program}->{callee_program}` | `call_evidence`, `target_declaration_evidence` | Exact physical line spans for CALL in caller and PROGRAM-ID in callee |
| **CallerContinuationConstraint** | `caller_program`, `callee_program`, `constraint_type` (`PROCESS_TERMINATION_ON_CALL`, `RETURN_TO_CALLER`), `call_evidence`, `callee_termination_evidence` | CALL statements paired with callee STOP RUN / GOBACK | Caller execution termination constraints | No (bundle pairs only) | `CALLER_CONT_CONSTRAINT\|{caller_program}->{callee_program}\|{constraint_type}` | `call_evidence`, `callee_termination_evidence` | Exact physical line spans occupied by CALL in caller and termination in callee |
| **ResourceLifecycle** | `program_id`, `resource_name`, `access_mode` (`INPUT`, `OUTPUT`, `IO`, `EXTEND`), `ordered_operations` (`OPEN_INPUT`, `OPEN_OUTPUT`, `OPEN_IO`, `OPEN_EXTEND`, `READ`, `WRITE`, `REWRITE`, `DELETE`, `CLOSE`), `evidence` | File control entries & I/O procedural statements | Strict sequence of lifecycle verbs per file | No (bundle files only) | `RESOURCE_LIFECYCLE\|{program_id}:{resource_name}\|{access_mode}\|{','.join(ordered_operations)}` | `evidence` | Physical line span from FIRST through LAST resource operation |
| **OperationSequence** | `program_id`, `first_operation` (`DELETE`), `second_operation` (`RENAME`), `first_assignment_evidence`, `first_call_evidence`, `second_assignment_evidence`, `second_call_evidence` | Sequential external command dispatches | Temporal ordering between external operations | No | `OPERATION_SEQUENCE\|{program_id}:{first_operation}->{second_operation}` | `first_assignment_evidence`, `first_call_evidence`, `second_assignment_evidence`, `second_call_evidence` | Exact physical line spans for assignments and calls |
| **ComputationDataflow** | `program_id`, `source_field`, `target_field`, `operation_verb` (`ADD`, `SUBTRACT`), `evidence` | Arithmetic statements (`ADD`, `SUBTRACT`) | Field-level accumulations | No (open-ended field combinations unverifiable) | `COMPUTATION_DATAFLOW\|{program_id}:{source_field}->{target_field}\|{operation_verb}` | `evidence` | Exact physical line span occupied by computation statement only |
| **PlatformDependency** | `program_id`, `platform_family` (`WINDOWS`), `command_literal`, `evidence` | System call commands & platform invocations | Discrete command syntax literals | No (open-ended command literals unverifiable) | `PLATFORM_DEPENDENCY\|{program_id}:{platform_family}\|{command_literal}` | `evidence` | Exact physical line span containing the command literal statement |
| **BehavioralRisk** | `program_id`, `risk_category` (`IO_ERROR_HANDLING`, `DATA_INTEGRITY`), `risk_basis_kind` (`MISSING_ERROR_STATUS`, `NON_ATOMIC_EXTERNAL_MUTATION`), `impact_category` (`ERROR_VISIBILITY`, `DATA_INTEGRITY`), `resource_name`, `operation_evidence`, `affected_resource_evidence` | File status checks and atomicity defects | Host-verifiable risk patterns | No (speculative risks unverifiable) | `BEHAVIORAL_RISK\|{program_id}:{risk_category}\|{risk_basis_kind}\|{impact_category}\|{resource_name}` | `operation_evidence`, `affected_resource_evidence` | Operation envelope and affected resource declaration spans |
| **DataTransferRelation** | `program_id`, `source_entity`, `target_entity`, `transfer_verb` (`MOVE`), `evidence` | 01-record MOVE relationships only | 01-record level data transfers | No (elementary field transfers unverifiable) | `DATA_TRANSFER_RELATION\|{program_id}:{source_entity}->{target_entity}\|{transfer_verb}` | `evidence` | Exact physical line span occupied by record MOVE statement |
| **DataStateComparison** | `entity_id`, `dat_record_value`, `initializer_code_value`, `causal_provenance` (`UNKNOWN`), `dat_evidence`, `initializer_evidence` | Cross-file fixture vs code discrepancy analysis | Data discrepancies between persistent fixtures and initializers | No (open-ended fields unverifiable) | `DATA_STATE_CMP:{entity_id}:{dat_record_value}:{initializer_code_value}:{causal_provenance}` | `dat_evidence`, `initializer_evidence` | Exact physical line spans in data file and initializer code respectively |

---

## 5. Golden Dataset Semantic Equality Proof

The proposition content and policy in `evals/expected/system-understanding-v3.json` were proven strictly identical to commit A1:
- **Baseline-v1 / Commit A1 Golden Semantic Digest:**  
  `1160261957bddfe11ca13131da3cb2471d1dd1f5f208bf8cb4ce2e8dc9c77a92`
- **Contract 3.5.2 Golden Semantic Digest:**  
  `1160261957bddfe11ca13131da3cb2471d1dd1f5f208bf8cb4ce2e8dc9c77a92`
- **Required Proposition Count:** 59 (Identical)
- **Status:** `old_digest == new_digest` (PASS - bit-for-bit identical proposition content, semantic keys, categories, policies, and evidence spans).

---

## 6. Cryptographic Artifact Hashes (Contract 3.5.2)

- **Production Prompt SHA-256 (`agents/legacy_analyzer/prompts/system_v3.md`):**  
  `721596b76a34ad2fd9c2798a2ef593bd3aa874ff0667984f8187f1b270177bfd`
- **Wire Schema SHA-256 (`get_system_openai_wire_schema()`):**  
  `c180119a9f803f24713f3ca91ec69089e1d05c54cbb781538e4c0fe305118c5a`
- **Golden Dataset SHA-256 (`evals/expected/system-understanding-v3.json`):**  
  `f3ee9a94a1bd230abcf6fd2b3418845f57a45bf541fae25ff0710be01ebf1856`
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
   31 passed (Tests 5A through 5F, anti-repair across all 5 normalization families, picture canonicalization boundary, condition value literal content preservation, real child entry path propagation, runtime component version mismatch fail-closed behavior, complete layout endpoint permutations and tie-breaking, total comparator across all 10 pairwise relations, behavioral risk dual-basis verification, duplicate call edge detection, positive oracle).
2. **Runner & Authorization Contract Suite (`evals/tests/test_gate_3_runner.py`):**  
   12 passed (including F1 CLI default coherence and F2 strict authorization diff binding for 3.5.2).
3. **Remediation Regression Suite (`evals/tests/test_gate_3_remediation_regressions.py`):**  
   25 passed (including child failure scenarios, reservation state handling, and immutable artifact preservation).
4. **H5 & H6 Regression Suites:**  
   21 passed (post-seal immutability, multiprocess reservation races, preserved transport serialization).
5. **Full Repository Pytest Suite:**  
   300 passed, 0 failures (execution time 286s).
6. **Linter & Formatter (`ruff check .`, `ruff format --check .`):**  
   Passed (0 errors, 54 files formatted cleanly).
7. **Static Type Checking (`mypy .`):**  
   Passed (Success: no issues found in 51 source files).
8. **Dependency Hygiene (`pip check`):**  
   Passed (No broken requirements found).
9. **Dry-Run Preflight (`python scripts/run-gate-3.py --dry-run --allow-dirty`):**  
   `[OK] Dry-run preflight verification complete. All authorization checks PASSED.`

---

## 8. Final Status

- **Functional Commit (H7.3-0):** `3dfe8ff40c767e71fba3fa1458d3c26058e072f8`
- **Report Commit (H7.3):** Direct report-only child of `H7.3-0`
- **Remote Branch:** `feat/gate-3-system-analysis`
- **Baseline-v2 Spec:** `evals/baselines/gate-3-baseline-v2.json` with `candidate_git_sha = ""`
- **Execution Status:** Offline implementation complete. No baseline-v2 execution or authorization was performed.
