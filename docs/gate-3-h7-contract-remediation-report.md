# Gate 3 H7.6 Contract 3.5.3 Remediation Report

**Date:** 2026-09-14  
**Contract Version:** 3.5.3  
**Functional Commit (H7.6-D):** `2b8b5f981d156ecba0360b8713f95f495e6567ed`  
**Functional Commit (H7.6-C):** `60c243e3761b9657f6d7316ae63158557d83db41`  
**Functional Commit (H7.6-B):** `e37a58e87498c863fc90a3674cf48f7608240590`  
**Functional Commit (H7.6-A):** `0e7b42fe31e9c704257125eef050dbd44933939d`  
**Prior Report Commit (H7.5):** `ec2bcb4d42b1c172bade60d1fe872105841dfe8d`  
**Classification:** `STRUCTURAL_VERIFIER_LOGICAL_PARSING_AND_EXHAUSTIVE_COMPLETENESS_REMEDIATION`  
**Mode:** STRICTLY OFFLINE  
**Live Provider Calls:** 0  
**Baseline-v2 State:** Byte-for-byte preserved (`108c51b222e476f32bd98c092c5dc814be9a25b4d1b93ae60f0f28ea2f5a631d`)  
**Baseline-v3 Spec:** Created (`evals/baselines/gate-3-baseline-v3.json`, `candidate_git_sha = ""`)  
**Baseline-v3 Execution:** NO (`artifacts/gate-3/baseline-v3` does not exist)  

---

## 1. Executive Summary

Following the Gate 3 Plan Review approving the H7.3 / Contract 3.5.2 remediation plan with required clarifications, and the subsequent H7.3.1 fail-closed hotfix, Contract 3.5.2 completes the final domain-closure remediation and fail-closed hotfix implementation. This release resolves all findings (F-01, F-03, F-05, F1, F2, F3, F4) while strictly preserving the passed areas from H7.2 (F-02, F-04, F-06, F-07):

1. **Host-Side Only PICTURE Canonicalization (Clarification 1 & F-01):**  
   `canonicalize_picture()` operates exclusively during host source parsing. The model-side wire schema requires an already-canonical lexical representation. `RecordFieldFact.__post_init__` performs zero repair. The evaluator explicitly asserts `model_fact.picture == host_fact.picture`. Non-canonical model variants (`PIC 9(10)`, `9(10).`, ` 9(10)`) fail without constructor transformation.
2. **Elimination of Punctuation Heuristics (Clarification 2 & F-01):**  
   Ad-hoc character replacement rules (such as `_` vs `-`) are completely eliminated. PICTURE punctuation is preserved exactly. The model value must match the host fact value exactly (`model -(10)9 == host -(10)9` passes; `model _(10)9` fails because values differ).
3. **Explicit Condition Value Domain & Content Preservation (Clarification 3 & F-01 & F1):**  
   `condition_values` represent source literal content. Host parsing removes syntactic quotation delimiters and preserves literal text content faithfully (casing, spaces, hyphens). Under F1, only simple literal `VALUE`/`VALUES` forms that can be represented losslessly as an ordered list of literal content are supported. Any unsupported syntax—including `THRU`, `THROUGH`, `OR`, ranges, or interior/escaped quoting—is classified `UNSUPPORTED_RELEVANT`, produces NO partial or approximated `CONDITION_NAME` fact, and ensures `ParserCoverageCertificate` causes fail-closed behavior (`is_evaluation_blocked = True`).
4. **Unsupported External Command Sequences Fail Closed (F2):**  
   Only adjacent recognized external command dispatches matching the model-visible `DELETE -> RENAME` sequence emit an `OperationSequence` fact and associated `NON_ATOMIC_EXTERNAL_MUTATION` risk fact. Any other adjacent recognized external command pair (such as `RENAME -> DELETE`, `DELETE -> DELETE`, `RENAME -> RENAME`) is classified `UNSUPPORTED_RELEVANT` across the sequence statements, failing coverage closed without fabricating an uncertifiable sequence. Contiguous dispatches are distinguished from branched dispatches by verifying absence of intervening procedural statements.
5. **Real Child Path Traversal in Test Suite (Clarification 4 & F-06/F-07):**  
   Tests 5E and 5F execute the genuine child entrypoint (`execute_internal_child`) with network boundaries isolated:
   - **5E:** Confirms that `load_authorization_spec_from_git` receives the exact relative spec path (`gate-3-baseline-v1.json` for v1, `gate-3-baseline-v2.json` for v2).
   - **5F:** Forces each component runtime version mismatch (golden dataset, wire schema, evaluator, prompt) through the real child path, verifying immediate exit code 1 with 0 provider calls before agent invocation.
6. **Correct Schema & Lifecycle Vocabulary (F3 & F-05):**  
   `ResourceLifecycle.ordered_operations` exposes strictly the 7 certified lifecycle verbs: `OPEN_INPUT`, `OPEN_OUTPUT`, `OPEN_IO`, `OPEN_EXTEND`, `READ`, `WRITE`, `CLOSE`. `REWRITE` and `DELETE` are not exposed in the Contract 3.5.2 wire schema. All uncertifiable tokens have been pruned.
7. **Preservation of Prior H7.2 & H7.3 Passes (F4):**  
   F-02 (complete layout endpoint canonicalization), F-04 (total layout comparator), F-06 (mandatory relative child spec path), and F-07 (strict runtime version equality) were re-verified alongside anti-repair probes, external file name case preservation, and risk selection with zero regressions.

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

### F-01, Clarification 3 & F1: Level-88 Value Syntax Strictness & Fail-Closed Behavior
- **Supported Subset:** Level-88 `condition_values` represent source literal content for simple single literals or ordered lists of literals.
- **Fail-Closed Range & Delimiter Syntax:** Any usage of `THRU`, `THROUGH`, `OR`, range operators (`..`), unclosed quotes, or interior escaped quotes (`''`, `""`, `\`) causes the statement to be classified as `StatementClassification.UNSUPPORTED_RELEVANT`.
- **No Partial Facts Emitted:** When unsupported syntax is detected, no approximated or truncated `CONDITION_NAME` AST item or fact is emitted.
- **Certificate Blocking:** The presence of `UNSUPPORTED_RELEVANT` statements marks `ParserCoverageCertificate.is_evaluation_blocked = True`, ensuring strict fail-closed enforcement.

### F2: External Command Sequence Generic Coverage & Fail-Closed Invariants
- **Adjacency Requirement:** Two external commands (`MOVE ... TO WS-CMD` followed by `CALL 'SYSTEM' USING WS-CMD`) form an adjacent temporal sequence if and only if they are directly adjacent with zero intervening procedural or control-flow statements.
- **Supported Sequence Extraction:** The only supported and model-visible sequence is `DELETE -> RENAME`, which emits an `OperationSequenceFact` and (when operands target the same resource) a `BehavioralRiskFact` for `NON_ATOMIC_EXTERNAL_MUTATION`.
- **Fail-Closed on Other Shapes:** Any other adjacent pair of recognized external commands (`RENAME -> DELETE`, `DELETE -> DELETE`, `RENAME -> RENAME`) is marked `UNSUPPORTED_RELEVANT` across the sequence statements, preventing incomplete understanding claims while avoiding fabricating non-model-visible facts.

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

### F-05 & F3: Model/Host Domain Capability Matrix & Exact Vocabulary
All model-visible `Literal` tokens across all categories match the runtime wire schema and support index:
- `ResourceLifecycle.ordered_operations`: Exactly the 7 certified lifecycle verbs: `OPEN_INPUT`, `OPEN_OUTPUT`, `OPEN_IO`, `OPEN_EXTEND`, `READ`, `WRITE`, `CLOSE`. `REWRITE` and `DELETE` are not part of the wire schema.
- `ResourceLifecycle.access_mode`: `INPUT`, `OUTPUT`, `IO`, `EXTEND`.
- `OperationSequence`: `first_operation: Literal["DELETE"]`, `second_operation: Literal["RENAME"]`.
- `ComputationDataflow`: `operation_verb: Literal["ADD", "SUBTRACT"]`.
- `PlatformDependency`: `platform_family: Literal["WINDOWS"]`.
- `BehavioralRisk`: `risk_category: Literal["IO_ERROR_HANDLING", "DATA_INTEGRITY"]`, `risk_basis_kind: Literal["MISSING_ERROR_STATUS", "NON_ATOMIC_EXTERNAL_MUTATION"]`, `impact_category: Literal["ERROR_VISIBILITY", "DATA_INTEGRITY"]`.
- `CausalProvenance`: `causal_provenance: Literal["UNKNOWN"]`.
- `DataTransferRelation`: `transfer_verb: Literal["MOVE"]`.

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
| **ResourceLifecycle** | `program_id`, `resource_name`, `access_mode` (`INPUT`, `OUTPUT`, `IO`, `EXTEND`), `ordered_operations` (`OPEN_INPUT`, `OPEN_OUTPUT`, `OPEN_IO`, `OPEN_EXTEND`, `READ`, `WRITE`, `CLOSE`), `evidence` | File control entries & I/O procedural statements | Strict sequence of lifecycle verbs per file | No (bundle files only) | `RESOURCE_LIFECYCLE\|{program_id}:{resource_name}\|{access_mode}\|{','.join(ordered_operations)}` | `evidence` | Physical line span from FIRST through LAST resource operation |
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
- **Baseline-v2 Candidate SHA:** `""` (unexecuted)

All cryptographic hashes match `evals/baselines/gate-3-baseline-v2.json` exactly.

---

## 7. Quality Gates & Test Suite Verification

1. **Targeted H7 / H7.3.1 Regression Suite (`evals/tests/test_h7_contract_regressions.py`):**  
   33 passed (Tests 5A through 5F, anti-repair across all 5 normalization families, picture canonicalization boundary, condition value literal content preservation, level-88 fail-closed behavior, unsupported external command sequence fail-closed behavior, real child entry path propagation, runtime component version mismatch fail-closed behavior, complete layout endpoint permutations and tie-breaking, total comparator across all 10 pairwise relations, behavioral risk dual-basis verification, duplicate call edge detection, positive oracle).
2. **Adversarial Regression Suite (`evals/tests/test_adversarial_regressions_gate3.py`):**  
   24 passed (including CF1 through CF12 with updated fail-closed assertions for reversed command sequencing).
3. **Runner & Authorization Contract Suite (`evals/tests/test_gate_3_runner.py`):**  
   12 passed (including F1 CLI default coherence and F2 strict authorization diff binding for 3.5.2).
4. **Remediation Regression Suite (`evals/tests/test_gate_3_remediation_regressions.py`):**  
   25 passed (including child failure scenarios, reservation state handling, and immutable artifact preservation).
5. **H5 & H6 Regression Suites:**  
   21 passed (post-seal immutability, multiprocess reservation races, preserved transport serialization).
6. **Full Repository Pytest Suite:**  
   302 passed, 0 failures.
7. **Linter & Formatter (`ruff check .`, `ruff format --check .`):**  
   Passed (0 errors, 68 files formatted cleanly).
8. **Static Type Checking (`mypy src agents evals scripts`):**  
   Passed (Success: no issues found in 51 source files).
9. **Dependency Hygiene (`pip check`):**  
   Passed (No broken requirements found).
10. **Dry-Run Preflight (`python scripts/run-gate-3.py --dry-run --allow-dirty`):**  
    `[OK] Dry-run preflight verification complete. All authorization checks PASSED.`

---

## 8. Historical H7.3.1 Status

- **Functional Commit (H7.3.1-0):** `82829ec159fc3bf3428411351b1d1937db9482a1`
- **Report Commit (H7.3.1):** `a0f901c6a0ae5cf081a66d2fced41c69357ee329`
- **Historical Functional Commit (H7.3-0):** `3dfe8ffd9cf7cc6d2f9d385e899f8df505869b3a`
- **Historical Report Commit (H7.3):** `e03e05406f76663c2be8b9c038c481b3e0b162cf`

---

## 9. Gate 3 H7.4 / Contract 3.5.3 Structural Verifier & Logical Parsing Remediation

**Date:** 2026-09-13  
**Contract Version:** 3.5.3  
**Functional Commit (H7.4-0):** `9def1a79cdf5fa45395b7922347ea408960e9cbf`  
**Report Commit (H7.4):** Direct report-only child of `H7.4-0`  
**Classification:** `STRUCTURAL_VERIFIER_AND_LOGICAL_PARSING_REMEDIATION`  
**Mode:** STRICTLY OFFLINE  
**Live Provider Calls:** 0  
**Baseline-v2 State:** Byte-for-byte preserved (`108c51b222e476f32bd98c092c5dc814be9a25b4d1b93ae60f0f28ea2f5a631d`)  
**Baseline-v3 Spec:** Created (`evals/baselines/gate-3-baseline-v3.json`, `candidate_git_sha = ""`)  
**Baseline-v3 Execution:** NO (`artifacts/gate-3/baseline-v3` does not exist)  

### 9.1 Summary of Remediated Findings

H7.4 addresses the four independently reproduced blockers (B-01 through B-04) and three additional high findings identified during the post-H7.3.1 independent review, incorporating all five required plan review clarifications:

1. **B-01: Structural Semantic-Key Collision / False 59/59 (Clarification 1):**
   - **Root Cause:** SystemSupportIndex previously used string semantic keys as the sole support proof. For compound facts with structured child elements (such as `RecordLayoutFact` with condition values `("A", "B")` vs `("A,B",)`), different dataclass structures mapped to identical string keys, falsely certifying candidate assertions.
   - **Remediation:** Exact canonical dataclass equality (`candidate_fact == supported_fact.fact`) is now the authoritative structural support proof. The support index enforces a strict 6-step verification sequence:
     1. Semantic-key bucket lookup
     2. Exact complete structured fact equality (`candidate_fact == supported_fact.fact`)
     3. Exact evidence role-set equality
     4. Exact canonical path equality
     5. Exact line_start / line_end equality
     6. Category-specific certificate checks
   - **Deterministic Identity:** `get_canonical_structured_identity()` provides deterministic JSON-canonical identity for deduplication, diagnostics, and testing, but does not replace dataclass equality as the support proof.

2. **B-02: Multiline Level-88 Partial-Fact Emission (Clarification 4):**
   - **Root Cause:** Unbounded level-88 parsing swallowed subsequent data division entries or emitted partial condition facts when encountering malformed or multiline quote syntax.
   - **Remediation:** The level-88 collector in `SystemCobolParser` is strictly bounded and stops at any structural boundary: paragraph headers, section headers, division headers, another level 88, or any new 01/05/77 data declaration.
   - **Fail-Closed Behavior:** On unclosed quotes or syntax errors, the parser discards partial condition state, emits NO condition fact, registers `UNSUPPORTED_RELEVANT`, sets `is_evaluation_blocked = True`, and cleanly recovers to parse subsequent declarations independently.

3. **B-03: False DELETE -> RENAME Certification Across Control Boundaries (Clarification 4):**
   - **Root Cause:** Command pairing between `MOVE ... TO CMD` and `CALL "SYSTEM"` did not verify control-flow linearity, incorrectly pairing dispatches across branch and block boundaries.
   - **Remediation:** `has_procedural_barrier_between()` checks raw source lines between command dispatches for branching/conditional constructs (`IF`, `ELSE`, `END-IF`, `EVALUATE`, `WHEN`, `END-EVALUATE`), loop structures (`PERFORM`, `END-PERFORM`), control transfers (`GO`, `GOTO`, `STOP`, `GOBACK`, `EXIT`), regional markers (`SECTION`, paragraphs), and I/O / side effects (`DISPLAY`, `ACCEPT`). Only strictly linear, adjacent dispatches without intervening barriers pair into `OperationSequence` and emit `NON_ATOMIC_EXTERNAL_MUTATION`.

4. **B-04: Baseline-v2 Reservation Preservation & Baseline-v3 Creation:**
   - **Root Cause:** A prior dry-run invocation consumed the baseline-v2 reservation slot, rendering baseline-v2 immutable and non-reusable.
   - **Remediation:** `artifacts/gate-3/baseline-v2/reservation-state.json` is preserved byte-for-byte with its exact hash `108c51b222e476f32bd98c092c5dc814be9a25b4d1b93ae60f0f28ea2f5a631d`.
   - Baseline-v3 is initialized via `evals/baselines/gate-3-baseline-v3.json` (`spec_version = "3.5.3"`, `candidate_git_sha = ""`).
   - `artifacts/gate-3/baseline-v3` DOES NOT EXIST (0 dry-run or live executions were executed).

5. **Additional High Findings:**
   - **Incomplete Source-Literal Preservation (Clarification 3):** Replaced all `.strip("'\"")` in parsing with `exact_syntactic_unquote()`, which strictly removes exactly one matching pair of outer quotes (`'` or `"`) from raw tokens, preserving all interior content verbatim (boundary spaces, casing, hyphens). `validate_canonical_literal_text` and `validate_source_literal_content` reject leading/trailing whitespace without repairing, enforcing anti-repair.
   - **Typed SystemAssessment Anti-Repair Bypass (Clarification 2):** In `evaluate_assessment()`, the assessment is serialized via `model_dump(mode="python", round_trip=True)` and revalidated via `SystemAssessment.model_validate(raw_payload)`. Any mutated post-instantiation objects fail revalidation with `ValidationError`.
   - **FileBinding.organization Model/Verifier Domain Mismatch:** Harmonized schema definition to `Literal["LINE_SEQUENTIAL", "SEQUENTIAL"]`, aligning schema, parser, and verifier domain.

### 9.2 Scientific Golden Dataset Verification (Clarification 5)

The 59-fact golden dataset `evals/expected/system-understanding-v3.json` was directly compared against commit A1 (`9672708e6bcdc01f9d6377535afbb9e11258126e`):
- **Propositions:** 59/59 propositions identical in IDs, categories, semantic keys, evidence spans, and auditor rationale.
- **Scientific Fields:** `benchmark_design`, `golden_authoring_method`, `provenance_notes`, `total_expected_facts`, `category_policies`, `group_counts` are 100% identical.
- **Metadata Difference:** Excludes ONLY `"version": "3.5.3"` (vs `"version": "3.4.3"` in A1).
- **Golden Dataset SHA-256:** `da5bdee9286dd5fbc79cb8331b70aabf73fca029fe4a3d3c5ede5ed2c984b82b`.

### 9.3 Cryptographic Artifact Hashes (Contract 3.5.3)

| Component | File / Accessor | SHA-256 Hash |
|---|---|---|
| Production Prompt | `agents/legacy_analyzer/prompts/system_v3.md` | `4be25cfc25933d6f0e69cbeeae1efe12ccf2e1354857e04c90108d8534ea92e8` |
| Wire Schema | `get_system_openai_wire_schema()` | `1cd36bf69496c063bc93a15c9334398e2256be527b4de3ff2e9b897a09c94c3c` |
| Golden Dataset | `evals/expected/system-understanding-v3.json` | `da5bdee9286dd5fbc79cb8331b70aabf73fca029fe4a3d3c5ede5ed2c984b82b` |
| Baseline-v3 Spec | `evals/baselines/gate-3-baseline-v3.json` | `5a03a737616de2213d3f0abf464648c91d398eee64dc63560d1d5806d11b1cd9` |
| Baseline-v2 Reservation | `artifacts/gate-3/baseline-v2/reservation-state.json` | `108c51b222e476f32bd98c092c5dc814be9a25b4d1b93ae60f0f28ea2f5a631d` |
| Canonical Bundle | `legacy/` (6 artifacts) | `95bb386b51d653c0a1834e1950634a9887b7cb6826b8c317a07c4b6a4167d060` |
| Source Manifest | Source manifest | `daf28b3314199db8e31bfacdf2fb8441b54682caa7854ed288e1bc00866a1dd1` |
| Dependency Lock | `requirements-lock.txt` | `732cb9370e90af2d0972eeda7fc18fd5745f17cb301f359b268df228fe7f18be` |
| Baseline-v3 Candidate SHA | `candidate_git_sha` | `""` (unexecuted) |

### 9.4 Test Suite & Quality Gates

1. **H7 / H7.4 Contract Regression Suite (`evals/tests/test_h7_contract_regressions.py`):**  
   39 passed (including full B-01 adversarial matrix with 7-field vs 6-field injected picture, condition values comma collisions, schema anti-repair validation, collision resilience, complete model tree revalidation, bounded level-88 unclosed quote handling, strict procedural barriers, generic structural equality, and direct comparison vs A1).
2. **Adversarial Regression Suite (`evals/tests/test_adversarial_regressions_gate3.py`):**  
   24 passed.
3. **Runner Suite (`evals/tests/test_gate_3_runner.py`):**  
   12 passed (including baseline-v3 CLI default and spec coherence).
4. **Remediation Regression Suite (`evals/tests/test_gate_3_remediation_regressions.py`):**  
   25 passed.
5. **Round 3 Regressions Suite (`evals/tests/test_round3_regressions.py`):**  
   15 passed.
6. **H5 & H6 Regression Suites:**  
   21 passed.
7. **Full Repository Pytest Suite:**  
   308 passed, 0 failures (1 pre-existing warning).
8. **Linter & Formatter (`ruff check .`, `ruff format --check .`):**  
   Passed (0 errors, all 68 source files formatted cleanly).
9. **Static Type Checking (`mypy src agents evals scripts`):**  
   Passed (Success: no issues found in 51 source files).
10. **Baseline-v2 Reservation Invariant:**  
    Byte-for-byte SHA matches `108c51b222e476f32bd98c092c5dc814be9a25b4d1b93ae60f0f28ea2f5a631d`.
11. **Baseline-v3 Isolation Invariant:**  
    `artifacts/gate-3/baseline-v3` does not exist.

---

## 10. H7.4.1 Contract 3.5.3 Source-Literal Content Hotfix

Following comprehensive review of H7.4, H7.4.1 was approved with four mandatory corrections to enforce precise source-literal content semantics without heuristic truncation or artificial schema constraints.

### 10.1 Four Required Adjustments

1. **Generic Source-Literal Content Permits Valid Strings Verbatim (Including Empty):**
   - In `agents/legacy_analyzer/schemas/system_assessment.py`, `validate_source_literal_content()` was updated to treat literal content strictly as semantic strings after exact syntactic unquoting (`exact_syntactic_unquote()`).
   - The generic validator does not enforce universal non-emptiness. It permits `""`, `" "`, `"  A  "`, `"\"A\""`, `"'A'"`, and arbitrary punctuation/case verbatim. It does not strip, uppercase, collapse whitespace, infer syntactic quotes, or reject quote-looking boundary characters.
   - Domain-specific non-emptiness is enforced at the individual field level (`external_file_name`, `command_template`, `command_literal`).
   - Condition values (`condition_values`) and data state values (`dat_record_value`, `initializer_code_value`) permit empty strings `""` where supported by the source domain.

2. **Parser Source Extraction Fails Closed on Unsupported Quoting:**
   - In `src/cobol/system_cobol_parser.py`, all literal extraction paths were audited:
     - `SELECT ... ASSIGN`: Identified complete literal tokens, verified exactly one matching outer quote pair, preserved all interior characters, and failed closed with `UNSUPPORTED_RELEVANT` (and zero `FileBindingFact`) on unclosed quotes, same-quote doubled escapes, backslashes, unseparated trailing garbage (e.g. `'accounts.dat'xyz`), and empty file names.
     - `tokenize_cobol_line()`: Refined to capture contiguous unseparated tokens (such as `'A''B'` or `'accounts.dat'extra`) as full un-split tokens so the parser detects unseparated doubled quotes and malformed syntax rather than silently truncating them into separate tokens.
     - Level-88 conditions: Validates each value token, allowing opposite-quote literal content (e.g. `VALUE '"A"'` -> `'"A"'`), empty literals `VALUE ''` -> `""`, while failing closed on same-quote escapes (`'A''B'`), unclosed quotes, or backslashes.
     - Command literals (`MOVE ... TO WS-CMD` / `CALL 'SYSTEM'`): Fails closed on unclosed quotes, doubled quotes, backslashes, or empty command literals, while preserving exact boundary whitespace (`MOVE ' cmd /c ... '`).
     - Initializer moves: Fails closed on unsupported quote syntax, preserving empty and whitespace-bearing literals.

3. **Removed Character-Based Placeholder Heuristics from `command_literal`:**
   - Removed speculative regex/character bans (`*`, `<`, `>`, `...`) from `PlatformDependency.command_literal`. Concrete shell syntax containing wildcards or redirections (e.g. `cmd /c del *.tmp`) can now be represented losslessly.
   - Grounding is enforced via structured equality against host facts (`model command_literal == exact host command_literal`). A fabricated template placeholder (e.g. `cmd /c <...>`) fails support certification because it does not equal any grounded host fact, not via schema regex heuristics.

4. **Aligned Model-Visible Field Descriptions on Wire Schema:**
   - Updated descriptions across all affected literal fields in `SystemAssessment` (`condition_values`, `external_file_name`, `command_template`, `command_literal`, `dat_record_value`, `initializer_code_value`) to explicitly instruct the model:
     *"Exact unquoted source literal CONTENT... Preserve case, punctuation, internal and boundary whitespace, and quote characters that are part of the content. Do not include the syntactic COBOL outer quote delimiters."*
   - `FileBinding.organization`: Retained strictly as `"File organization: LINE_SEQUENTIAL or SEQUENTIAL"`.
   - Updated `wire_schema_sha256` to reflect the updated field descriptions.

### 10.2 Cryptographic Hashes (Contract 3.5.3 Post-H7.4.1)

| Component | File / Accessor | SHA-256 Hash | Status |
|---|---|---|---|
| Production Prompt | `agents/legacy_analyzer/prompts/system_v3.md` | `4be25cfc25933d6f0e69cbeeae1efe12ccf2e1354857e04c90108d8534ea92e8` | Unchanged |
| Wire Schema | `get_system_openai_wire_schema()` | `07655be0a119440e1f693cbd3242842ed87e82c43518bce61f741bc7dc4423dc` | Updated (descriptions) |
| Golden Dataset | `evals/expected/system-understanding-v3.json` | `da5bdee9286dd5fbc79cb8331b70aabf73fca029fe4a3d3c5ede5ed2c984b82b` | Unchanged (A1 identical) |
| Baseline-v3 Spec | `evals/baselines/gate-3-baseline-v3.json` | `d3629d68066d800dc37afa938ab9b53d706e5a6842ff4b62b8a79b80a589377e` | Updated (`wire_schema_sha256`) |
| Baseline-v2 Reservation | `artifacts/gate-3/baseline-v2/reservation-state.json` | `108c51b222e476f32bd98c092c5dc814be9a25b4d1b93ae60f0f28ea2f5a631d` | Intact & Unmodified |
| Canonical Bundle | `legacy/` (6 artifacts) | `95bb386b51d653c0a1834e1950634a9887b7cb6826b8c317a07c4b6a4167d060` | Unchanged |
| Source Manifest | Source manifest | `daf28b3314199db8e31bfacdf2fb8441b54682caa7854ed288e1bc00866a1dd1` | Unchanged |
| Dependency Lock | `requirements-lock.txt` | `732cb9370e90af2d0972eeda7fc18fd5745f17cb301f359b268df228fe7f18be` | Unchanged |
| Baseline-v3 Candidate SHA | `candidate_git_sha` | `""` | Strictly Unexecuted |

### 10.3 Structural Collision Matrix & Regression Traversal

The H7.4.1 test suite in `evals/tests/test_h7_contract_regressions.py` verifies full end-to-end traversal across:
`SOURCE OVERLAY -> PARSER -> HOST FACTS / CERTIFICATE -> MODEL SCHEMA -> EVALUATOR -> SUPPORT INDEX`.

- **Positive Exact Content Cases:**
  - `FileBinding`: exact spaces (`' accounts.dat '`), opposite quotes (`'"accounts.dat"'`) pass parser and evaluator. Single-property mutations (trimming, casing, quote-stripping) verified strictly rejected by evaluator.
  - Level-88: boundary spaces (`' A '`), opposite quotes (`'"A"'`), empty string (`''`) certified; single-property mutations rejected by evaluator.
  - Commands: boundary spaces (`' cmd /c ... '`), wildcard shell syntax (`cmd /c del *.tmp`) pass parser and evaluator; fabricated placeholders rejected by evaluator against host facts.
  - DataStateComparison: boundary spaces (`  100.50,PENDING  `) and empty string (`""`) certified; trimmed mutations rejected by evaluator.
- **Fail-Closed Unsupported Quoting Probes:**
  - SELECT/ASSIGN doubled quote (`'accounts''dat'`), unclosed quote (`'accounts.dat`), trailing unseparated characters (`'accounts.dat'xyz`), stray quote (`'accounts.dat' 'extra'`) -> `unsupported_relevant_count >= 1`, 0 `FileBindingFact`.
  - Level-88 doubled quote (`'A''B'`) -> `unsupported_relevant_count >= 1`, 0 condition facts.
  - Command literal doubled quote (`'cmd /c del ''test.dat'''`) -> `unsupported_relevant_count >= 1`, 0 `CommandInvocationFact`, 0 `PlatformDependencyFact`.
- **H7.4 Structural Collision Matrix Re-run:**
  - 11/11 structural tests passed cleanly.
- **Full Pytest Suite:**
  - 313/313 passed (0 regressions across the entire repository).

---

## 11. Final Status (H7.4.1 Release)

- **Functional Commit (H7.4.1-0):** `548bb08817cd6faea731c85cdf2c884b9bfa029e`
- **Report Commit (H7.4.1):** `dca44ef1603652f41b4625fe8aea1c6be9a23ba1`
- **Remote Branch:** `feat/gate-3-system-analysis`
- **Baseline-v3 Spec:** `evals/baselines/gate-3-baseline-v3.json` (`candidate_git_sha = ""`)
- **Execution Status:** Strictly offline. Zero provider calls, zero baseline runs, no baseline-v3 reservation, baseline-v2 reservation byte-for-byte preserved.

---

## 12. H7.4.2 Procedural Syntax & Coverage Hotfix Details

H7.4.2 eliminates procedural syntax loopholes and decouples concrete external command fact support from sequence/risk pattern detection. It resolves findings B-01, B-02, H-01, and H-02:

### 12.1 B-01: Strict CALL Target Syntax Before AST Emission
1. **Target Syntax Parsed Before AST Creation:**
   In `src/cobol/system_cobol_parser.py`, CALL target parsing strictly validates candidate targets before constructing `ASTCall`.
2. **Simple Quoted Literal Grammar:**
   - Requires exactly one matching outer quote pair (`'...'` or `"..."`).
   - Literal content must be non-empty (`len(content) > 0`).
   - Rejects doubled same-quote escapes (e.g. `'A''B'`, `"A""B"`).
   - Rejects backslash escapes (`\`).
   - Rejects unseparated trailing garbage after closing quote (e.g. `'TARGET'xyz`).
   - Preserves exact source literal content without ad-hoc modification.
3. **Dynamic Call Grammar:**
   - Requires a canonical COBOL identifier matching `^[A-Za-z0-9_-]+$`.
   - Quote characters are **never** silently reclassified as dynamic targets.
4. **Fail-Closed Behavior:**
   - Any malformed or unsupported target is classified `UNSUPPORTED_RELEVANT`.
   - **Zero** `ASTCall`, `CallOccurrenceFact`, `CallEdgeFact`, or `InternalCallResolutionFact` are emitted.
   - Coverage certificate blocks evaluation (`is_evaluation_blocked = True`).
   - Probes verified: `CALL 'TARGET`, `CALL "TARGET`, `CALL 'A''B'`, `CALL "A""B"`, `CALL 'TARGET'xyz`, `CALL 'TARGET\X'`, malformed `CALL 'SYSTEM'`.

### 12.2 B-02: Procedural Statement Grammar Detects Same-Line Barriers
1. **Procedural Control-Flow Barrier Detection:**
   - Defined `PROCEDURAL_CONTROL_FLOW_BARRIERS` encompassing `IF`, `ELSE`, `END-IF`, `EVALUATE`, `WHEN`, `END-EVALUATE`, `PERFORM`, `GO`, `GOTO`, `STOP`, `GOBACK`, `DISPLAY`, `ACCEPT`.
   - Unquoted control-flow tokens on the same physical line outside supported single-statement grammar trigger `UNSUPPORTED_RELEVANT` classification.
2. **`CALL ... USING` Operands Boundary:**
   - Operands end before any control-flow delimiter, preventing absorption of keywords (such as `ELSE`) into argument lists.
   - Inline compound statements fail closed immediately rather than silently continuing.
3. **Endpoint & Intervening Line Barrier Verification:**
   - `has_procedural_barrier_between()` verifies absence of procedural barriers across both intervening lines and the endpoint lines themselves (`line_start_excl` and `line_end_excl`).
   - In the exact auditor scenario:
     ```cobol
     IF FLAG = 1
         MOVE 'cmd /c del accounts.dat' TO BUFFER
         CALL 'SYSTEM' USING BUFFER ELSE
         MOVE 'cmd /c ren accounts.tmp accounts.dat' TO BUFFER
         CALL 'SYSTEM' USING BUFFER
     END-IF
     ```
     Same-line `ELSE` on the CALL line is detected as a procedural barrier. Line 3 is classified `UNSUPPORTED_RELEVANT`. No false `DELETE -> RENAME` sequence is formed, and no false `NON_ATOMIC_EXTERNAL_MUTATION` risk fact is emitted. Coverage fails closed cleanly.

### 12.3 H-01: Literal MOVE Syntax Validation During MOVE Parsing
1. **Immediate Syntax Validation:**
   - `MOVE` statement parsing in `src/cobol/system_cobol_parser.py` validates source and target syntax before emitting `ASTMove`.
   - Complete supported literal form requires: `MOVE <complete-supported-literal> TO <target-identifier>`.
2. **Malformed Literal Detection:**
   - Unclosed quotes (`MOVE 'TARGET TO BUFFER`, `MOVE "TARGET TO BUFFER`), doubled quotes (`MOVE 'A''B' TO BUFFER`), trailing garbage (`MOVE 'TARGET'xyz TO BUFFER`), missing `TO` (`MOVE 'TARGET'`), missing target (`MOVE 'TARGET' TO`), or same-line control-flow barriers fail closed immediately as `UNSUPPORTED_RELEVANT`.
   - Zero `ASTMove` usable for downstream scored concepts is emitted. Coverage is blocked.
   - Command-pairing logic never receives unvalidated or malformed move statements.

### 12.4 H-02: Decoupling Command Fact Support from Mutation-Sequence Support
1. **Explicit Separation of Three Independent Concepts:**
   - **A. Syntax Support:** Can the parser losslessly understand the statement? (Fail closed as `UNSUPPORTED_RELEVANT` if unparseable or unmodeled).
   - **B. Command Fact Support:** Can a concrete external command invocation and platform dependency be grounded? (Emit `CommandInvocationFact` and `PlatformDependencyFact` if recognized concrete command, with clean coverage).
   - **C. Mutation-Sequence Support:** Does a proven direct linear pair match `DELETE -> RENAME`? (Emit `OperationSequenceFact` and `NON_ATOMIC_EXTERNAL_MUTATION` risk).
2. **Concrete Commands No Longer Conflated with Sequence Shape:**
   - Valid Windows commands like `cmd /c echo test`, `cmd /c dir`, `cmd /c del *.tmp`, or isolated single `DELETE` / `RENAME` commands emit supported facts with clean coverage (`unsupported_relevant_count == 0`), even when `classify_command_operation` returns `EXECUTE` or other operations.
   - Non-matching command pairs (e.g. `RENAME -> DELETE`, `DELETE -> DELETE`, `RENAME -> RENAME`) are not marked unsupported simply because they do not form `DELETE -> RENAME`; they emit valid individual command facts without false sequence or risk facts.

### 12.5 Test Results & Invariants
- **Pytest Suite:** 317/317 passed across the entire repository.
- **Contract Regressions:** 48/48 passed in `evals/tests/test_h7_contract_regressions.py` including dedicated B-01, B-02, H-01, and H-02 test sections.
- **Static Analysis:** `ruff check .` passed; `ruff format --check .` 68 files formatted; `mypy src agents evals scripts` 0 issues across 51 source files; `pip check` 0 broken requirements.
- **Immutability & Hashes:** All baseline-v3 expected hashes, legacy bundle, baseline-v2 reservation hash, and non-existence of baseline-v3 artifacts verified.

---

## 13. Historical Status (H7.4.2 Release)

- **Functional Commit (H7.4.2-0):** `0808eadb7e97b11f8ac980511efb3fab98041065`
- **Report Commit (H7.4.2):** `855a2efd68786369d079662be7b0cfece2c0c350`
- **Remote Branch:** `feat/gate-3-system-analysis`
- **Baseline-v3 Spec:** `evals/baselines/gate-3-baseline-v3.json` (`candidate_git_sha = ""`)
- **Review Verdict:** DO NOT PROCEED (findings F-01 through F-09 identified during H7.4.2 review; remediated in H7.4.3)

---

## 14. H7.4.3 / Contract 3.5.3 Exact Procedural Grammar & Static Resolution Remediation

H7.4.3 eliminates procedural parsing loopholes, establishes a unified procedural starter architecture, implements three-outcome Windows mutation command classification, isolates dynamic CALL targets, enforces exact single-argument CALL/USING semantics, and verifies the end-to-end production path for spaced filename mutations. It resolves findings F-01 through F-09 and incorporates all five required clarifications:

### 14.1 F-01 & Clarification 4: Strict CALL/USING Syntax & Command Binding
1. **Grammar Restriction:**
   Supported CALL syntax is strictly `CALL <target>` or `CALL <target> USING <exactly-one-identifier>`.
   Any second or subsequent argument (e.g. `CALL TARGET USING ARG1 ARG2`, `CALL 'SYSTEM' USING OTHER BUFFER`) fails closed as `UNSUPPORTED_RELEVANT`. Zero `CallOccurrenceFact` is emitted.
2. **Compound Trailing Starter Rejection:**
   Trailing unquoted procedural starters after a USING argument (e.g. `CALL 'SYSTEM' USING BUFFER CALL OTHER`) fail closed as `UNSUPPORTED_RELEVANT` with zero partial fact extraction.
3. **Exact Variable Binding for SYSTEM Dispatch:**
   `CALL 'SYSTEM' USING <id>` dispatches command execution only when `<id>` strictly matches the assigned command variable (`s2.using_args == [s1.target_operand]`). When `<id>` refers to another identifier, the statement is valid COBOL (clean coverage), but produces zero `CommandInvocationFact` for that assignment pair.

### 14.2 F-02 & Clarification 4: Dynamic CALL Target Static Resolution Isolation
1. **Dynamic Target Identification:**
   Dynamic CALL statements (e.g. `CALL SYSTEM USING BUFFER.` where `SYSTEM` is an identifier) are classified as `call_mechanism == "DYNAMIC_TARGET"`.
2. **Strict Static Isolation:**
   Dynamic CALL targets emit:
   - Zero `InternalCallResolutionFact` (dynamic identifiers do not resolve to static internal programs).
   - Zero `CallerContinuationConstraintFact` (caller continuation constraints are established only for static literal calls).
   - Zero `CommandInvocationFact` (dynamic targets never dispatch SYSTEM commands).
   - Zero `PlatformDependencyFact`, `OperationSequenceFact`, or `BehavioralRiskFact`.

### 14.3 F-03: Variable Alignment Between Assignment and SYSTEM Call
In `src/cobol/system_cobol_parser.py`, pairing requires `s2.is_literal and s2.target == "SYSTEM" and s2.using_args == [s1.target_operand]`. Substring matching or set membership is replaced with exact single-element equality.

### 14.4 F-04 & Clarification 3: Three-Outcome Windows Mutation Command Classification & Spaced Filenames E2E
1. **Three-Outcome Architecture:**
   - **`NOT_MUTATION`:** Command does not enter the mutation family (e.g. `cmd /c echo test`, `cmd /c dir`). Yields exact `CommandInvocationFact`, `PlatformDependencyFact` where applicable, clean coverage (`unsupported_relevant_count == 0`), and is not eligible for sequence/risk derivation.
   - **`MUTATION_PARSED`:** Command belongs to mutation family and operands are losslessly parsed into deterministic `operation`, `source_operand`, and `target_operand`. Eligible for sequence and risk analysis.
   - **`MUTATION_UNSUPPORTED`:** Command enters mutation family (DEL, REN, COPY, etc.) but operand syntax cannot be interpreted losslessly (e.g. single quotes used for Windows grouping, unclosed quotes, missing operands). Opaque `CommandInvocationFact` is derived, but source statements fail closed as `UNSUPPORTED_RELEVANT` to block Gate 3 evaluation (`is_evaluation_blocked == True`). Zero `OperationSequenceFact` and zero `BehavioralRiskFact` are emitted.
2. **Windows Double-Quote Grouping:**
   `tokenize_windows_mutation_operands()` explicitly supports double-quote grouping (`"accounts old.dat"`) for Windows shell syntax. Single quotes are not shell grouping in Windows `cmd.exe` and trigger `MUTATION_UNSUPPORTED`.
3. **End-to-End Production Path Traversal:**
   The implementation traverses the real production path (source -> parser -> facts -> schema -> evaluator index):
   - **Different Targets (`del "accounts old.dat"` then `ren temp.tmp "accounts new.dat"`):** Supported `OperationSequenceFact` (DELETE -> RENAME); **NO** `BehavioralRiskFact` emitted. A model assessment asserting matching risk fails evaluator support.
   - **Same Target (`del "accounts old.dat"` then `ren temp.tmp "accounts old.dat"`):** Supported `OperationSequenceFact` (DELETE -> RENAME); supported `BehavioralRiskFact` with canonical uppercase `resource_name == "ACCOUNTS OLD.DAT"` (never raw quoted syntax like `'"ACCOUNTS'`). Evaluator verifies 100% precision/recall with zero unsupported predictions.

### 14.5 F-05: Quoted CALL Target Admission Normalization Rejection
CALL literal parsing validates candidate target content prior to admission:
- Lowercase targets (e.g. `CALL 'subprog'`) fail closed as `UNSUPPORTED_RELEVANT` (zero `CallOccurrenceFact`).
- Whitespace-padded targets (e.g. `CALL ' SUBPROG '`) fail closed as `UNSUPPORTED_RELEVANT` (zero `CallOccurrenceFact`).
- Exact uppercase identifiers (e.g. `CALL 'SUBPROG'`) are admitted as valid literal call occurrences.

### 14.6 F-06 & Clarification 1: Procedural Terminal Period Stripping & Legacy Host Facts Invariance
1. **Procedural Period Invariant:**
   The procedural parser sees all tokens on procedural lines. `consume_optional_terminal_period()` removes at most one terminal sentence-period token. Any interior unquoted period token (e.g. `CALL . TARGET`, `MOVE 'X' . TO BUFFER`, `MOVE . 'X' TO BUFFER`) fails closed as `UNSUPPORTED_RELEVANT`.
2. **Preservation of Non-Procedural & Numeric/Literal Tokens:**
   - Non-procedural token streams (DATA DIVISION, `PROGRAM-ID`, `SELECT`, `FD`, 01/05/88, `PIC`, declarative statements) are not altered.
   - Numeric literals with decimal points (e.g. `100.50`) and quoted literals with periods (e.g. `'file.name'`) remain single semantic tokens.
3. **Legacy Host Facts Invariance:**
   Parsing `legacy/core-banking-system` produces `unsupported_relevant_count == 0` and preserves the exact frozen certificate SHA-256 `74148cdb6b5c28c576406db77a8c84ae171a7fd1eec568c4d5a15256ef08f177`.

### 14.7 F-07 & Clarification 2: Unified Procedural Starter Architecture
1. **Unified Authoritative Vocabulary:**
   Established single authoritative `PROCEDURAL_KEYWORD_VOCABULARY` in `src/cobol/system_cobol_parser.py` and derived `PROCEDURAL_STATEMENT_STARTERS` directly from it, replacing multiple drifting local sets.
2. **Complete Grammar Consumption:**
   Every procedural branch in `_parse_file_unit()` proves complete consumption of its supported grammar:
   - Branches audited: `CALL`, `MOVE`, `READ`, `WRITE`, `OPEN`, `CLOSE`, `ADD`, `SUBTRACT`, `COMPUTE`, `MULTIPLY`, `DIVIDE`, `STOP`, `GOBACK`, `EXIT`, `PERFORM`, `DISPLAY`, `ACCEPT`, `IF`, `ELSE`, `END-IF`, `EVALUATE`, `WHEN`, `END-EVALUATE`, `END-PERFORM`, `END-READ`, `GO`, `GOTO`, `AT`, `NOT`, `FROM`.
   - Any trailing unquoted procedural starter causes the statement to fail closed as `UNSUPPORTED_RELEVANT`, emitting zero partial scored facts.
   - Probes verified: `COMPUTE X = Y CALL OTHER`, `MULTIPLY A BY B CALL OTHER`, `DIVIDE A INTO B CALL OTHER`, `IF X = 1 CALL OTHER`, `ELSE CALL OTHER`, `WHEN 1 CALL OTHER`.
   - Quoted content containing starter keywords (e.g. `MOVE 'CALL OTHER' TO WS-MSG`) remains valid and supported.

### 14.8 Clarification 5: Independent Scientific Evidence Verification
All immutable preconditions were independently verified without relying on scratch verification scripts:
- **Baseline-v1 Spec SHA:** `b37e8815e2605f279ecc417b8e037f0b235f5e1dcfa64d79b10708e852509695` (verified via `sha256sum evals/baselines/gate-3-baseline-v1.json`).
- **All 13 Baseline-v1 Manifest Artifacts:** Verified against `artifacts/gate-3/baseline-v1/manifest.json`:
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
- **Baseline-v2 Reservation File SHA:** `artifacts/gate-3/baseline-v2/reservation-state.json` SHA is `108c51b222e476f32bd98c092c5dc814be9a25b4d1b93ae60f0f28ea2f5a631d` (verified via `sha256sum`).
- **Baseline-v3 Artifact Non-Existence:** Verified `artifacts/gate-3/baseline-v3` does NOT exist.
- **Baseline-v3 Spec Empty Candidate:** `evals/baselines/gate-3-baseline-v3.json` has `candidate_git_sha == ""`.
- **A1 Golden Equality:** Independently recomputed and proven identical to A1 (excluding allowed version metadata 3.5.0 -> 3.5.3):
  - Bundle payload SHA: `18aaf4dbf9cfa7c279b047ee26744d7b763d3c6f77770818b191e1756f20152d` (100% byte-identical to A1).
  - Source manifest: All 6 files match A1 hashes byte-for-byte.
  - Dependency lock SHA: `732cb9370e90af2d0972eeda7fc18fd5745f17cb301f359b268df228fe7f18be`.
  - Golden dataset: `evals/expected/system-understanding-v3.json` SHA `da5bdee9286dd5fbc79cb8331b70aabf73fca029fe4a3d3c5ede5ed2c984b82b`.
  - Wire schema: Root schema keys match A1 wire schema.
  - Production prompt: Recomputed prompt identical to A1 prompt modulo contract version.

### 14.9 Test Results & Invariants
- **Pytest Suite:** 323/323 passed across the entire repository.
- **Contract Regressions:** 54/54 passed in `evals/tests/test_h7_contract_regressions.py` including 6 new comprehensive tests in Section 17.
- **Static Analysis:** `ruff check .` passed with 0 errors; `ruff format --check .` 68 files formatted; `mypy src agents evals scripts` 0 issues across 51 source files; `pip check` 0 broken requirements.

---

## 15. Final Status (H7.4.3 Release)

- **Functional Commit (H7.4.3-0):** `7f00571cf16cc9fb93d542a8840595372a586de6`
- **Report Commit (H7.4.3):** Direct report-only child of `H7.4.3-0`
- **Remote Branch:** `feat/gate-3-system-analysis`
- **Baseline-v3 Spec:** `evals/baselines/gate-3-baseline-v3.json` (`candidate_git_sha = ""`)
- **Execution Status:** Strictly offline. Zero provider calls, zero baseline runs, no baseline-v3 reservation, baseline-v2 reservation byte-for-byte preserved.

---

## 16. H7.4.4 / Contract 3.5.3 Host-Oracle Soundness Hotfix Details

H7.4.4 resolves all seven host-oracle BLOCKERs (B-01 through B-07) and two procedural HIGH issues identified during rigorous contract auditing under Contract 3.5.3 offline mode. It maintains byte-identical wire schema preservation (`wire_schema_sha256 = 07655be0...`), 100% frozen baseline-v2 reservation integrity, and strictly zero model provider calls.

### 16.1 BLOCKER & HIGH Remediations

1. **B-01: Identifier Domain Disambiguation (`src/cobol/identifier_domain.py` & Schemas)**
   - Created neutral `src/cobol/identifier_domain.py` containing domain predicates: `is_canonical_cobol_identifier()`, `validate_canonical_cobol_identifier()`, `is_numeric_literal()`, `is_computation_operand()`, and `validate_computation_operand()`.
   - Canonical COBOL identifiers must be uppercase alphanumeric with hyphens, matching `^(?=.*[A-Z])[A-Z0-9]+(?:-[A-Z0-9]+)*$`. Pure numeric tokens (e.g., `1000000003`) are explicitly rejected as COBOL identifiers.
   - Migrated COBOL declaration schema fields (`ProgramDeclaration.program_id`, `RecordLayout.program_id`, `RecordLayout.record_name`, `RecordField.name`, `FileBinding.program_id`, `FileBinding.internal_file_name`, `FileOperation.program_id`, `FileOperation.internal_file_name`, etc.) to `validate_canonical_cobol_identifier`.
   - Preserved `DataStateComparison.entity_id`, `FileBinding.external_file_name`, `FileOperation.resource_name`, `ResourceLifecycle.resource_name`, and `BehavioralRisk.resource_name` with `validate_canonical_identifier`, preserving numeric entity IDs (e.g. `1000000003`) and resource names with extensions/spaces (e.g. `ACCOUNTS OLD.DAT`).
   - `ComputationDataflow.source_field` enforces `validate_computation_operand`, admitting both canonical COBOL identifiers and valid numeric literals (`100.50`), while rejecting invalid tokens.

2. **B-02: Multiline Arithmetic Sentence-Boundary Isolation (`src/cobol/system_cobol_parser.py`)**
   - In `_parse_file_unit()`, tracked `line_is_terminated` via `consume_optional_terminal_period()`.
   - Multiline loops for `ADD` and `SUBTRACT` stop slurping immediately if `line_is_terminated` is `True`. An `ADD 1.` statement on a terminated line cannot absorb a subsequent sentence beginning with `TO WS-COUNT.`.
   - Incomplete statements terminated by periods fail closed as `UNSUPPORTED_RELEVANT`, emitting zero cross-sentence arithmetic facts.

3. **B-03: Shell Metacharacter & Wildcard Rejection in Mutation Operands**
   - `tokenize_windows_mutation_operands()` inspects command tokens and immediately rejects shell metacharacters and wildcards: `><|&^%!*?()`.
   - Metacharacter commands fail closed as `MUTATION_UNSUPPORTED`, preventing false `OperationSequenceFact` or `BehavioralRiskFact` derivation while preserving opaque `CommandInvocationFact` grounding.

4. **B-04: POSIX -c & Bare Mutation Command Wrappers Fail-Closed**
   - `classify_mutation_command()` un-wraps POSIX `-c` commands (e.g., `sh -c 'rm ...'`, `bash -c ...`, `/bin/sh -c ...`) and identifies mutation verbs (`rm`, `mv`, `cp`).
   - Rejects POSIX shell wrappers as `MUTATION_UNSUPPORTED` with reason `"POSIX shell mutation wrappers are unsupported for deterministic resource mutation analysis"`.
   - Rejects bare commands (e.g. `del accounts.dat` without `cmd /c`) as `MUTATION_UNSUPPORTED`.
   - Both categories fail closed with `UNSUPPORTED_RELEVANT`, blocking evaluation coverage while preserving opaque `CommandInvocationFact` grounding. In accordance with Contract 3.5.3 wire domain closure (where `PlatformFamily = Literal["WINDOWS"]`), POSIX commands emit strictly zero `PlatformDependencyFact`.

5. **B-05: Lossless Mutation Tokenization**
   - `tokenize_windows_mutation_operands()` rejects lossy whitespace: consecutive spaces (`\s{2,}`) or boundary whitespace inside operands.
   - Double-quoted grouping (`"accounts old.dat"`) is tokenized losslessly without whitespace collapse.

6. **B-06: Conflicting OPEN Modes Fail-Closed**
   - In `ResourceLifecycleFact` emission, audited all `OPEN` access modes across operations for each file.
   - If conflicting `OPEN` access modes exist (e.g., both `OPEN INPUT` and `OPEN OUTPUT` on the same resource in the same program), the parser marks the lifecycle as `UNSUPPORTED_RELEVANT`, emits **zero** `ResourceLifecycleFact`, and blocks evaluation coverage (`is_evaluation_blocked = True`). Individual truthful `FileOperationFact` entries remain grounded.

7. **B-07: Strict Structural Proof for Callee Continuation Constraints**
   - Implemented `_prove_callee_continuation(callee_unit)` requiring:
     - Zero `UNSUPPORTED_RELEVANT` statements in the callee;
     - Zero `GO` / `GOTO` statements;
     - All `ASTTermination` nodes agree on termination verb (`STOP_RUN` vs `GOBACK`/`EXIT`);
     - Control block depth is exactly 0 at termination;
     - The proving termination statement occurs at top level and is the final executable statement.
   - If continuation cannot be proven:
     - Emits `InternalCallResolutionFact` (since callee program exists);
     - Emits **zero** `CallerContinuationConstraintFact`;
     - Marks caller's `CALL` statement as `UNSUPPORTED_RELEVANT`, blocking evaluation coverage.

8. **HIGH Issues: Procedural Grammar Guards & Single-Token Periods**
   - All procedural statement handlers (`DISPLAY`, `ACCEPT`, `IF`, `ELSE`, `END-IF`, `EVALUATE`, `WHEN`, `END-EVALUATE`, `END-PERFORM`, `END-READ`, `AT`, `NOT`, `GO`, `GOTO`) enforce complete token consumption; unconsumed trailing syntax fails closed as `UNSUPPORTED_RELEVANT`. Standalone `FROM` fails closed.
   - `PARAGRAPH_HEADER` grammar excludes COBOL procedural reserved words and validates identifiers using `is_canonical_cobol_identifier`. Single-token lines ending in periods (`CALL.`, `MOVE.`, `END-IF.`, `END-PERFORM.`) are no longer misclassified as paragraph headers.

### 16.2 Clarification 8: Domain-Symmetry Matrix

| Domain / Value | `is_canonical_cobol_identifier` | `is_numeric_literal` | `is_computation_operand` | `validate_canonical_identifier` | `validate_canonical_cobol_identifier` |
|---|---|---|---|---|---|
| Pure Numeric (`1000000003`) | `False` | `True` | `True` | Valid (`1000000003`) | Rejection (`ValueError`) |
| Canonical COBOL ID (`ACCOUNT-RECORD`) | `True` | `False` | `True` | Valid (`ACCOUNT-RECORD`) | Valid (`ACCOUNT-RECORD`) |
| Lowercase ID (`account-record`) | `False` | `False` | `False` | Rejection (`ValueError`) | Rejection (`ValueError`) |
| Resource Name (`ACCOUNTS.DAT`) | `False` | `False` | `False` | Valid (`ACCOUNTS.DAT`) | Rejection (`ValueError`) |
| Resource Name with Spaces (`ACCOUNTS OLD.DAT`) | `False` | `False` | `False` | Valid (`ACCOUNTS OLD.DAT`) | Rejection (`ValueError`) |

### 16.3 Verification Invariants (CLI-Grounded, Zero Scratch Scripts)

- **Wire Schema SHA-256:** `07655be0a119440e1f693cbd3242842ed87e82c43518bce61f741bc7dc4423dc` (100% byte-identical).
- **Golden Dataset SHA-256:** `da5bdee9286dd5fbc79cb8331b70aabf73fca029fe4a3d3c5ede5ed2c984b82b` (identical to A1 modulo contract version).
- **Baseline-v2 Reservation SHA-256:** `108c51b222e476f32bd98c092c5dc814be9a25b4d1b93ae60f0f28ea2f5a631d` (intact and byte-for-byte preserved).
- **Baseline-v3 Spec (`evals/baselines/gate-3-baseline-v3.json`):** `candidate_git_sha == ""` throughout.
- **Baseline-v3 Run Directory:** `artifacts/gate-3/baseline-v3` does NOT exist.
- **Canonical Legacy Certificate SHA-256:** `e5900cba53db046c80e0e5f64618b549e894631a0eebfe42f8c502fe0ae948be` (80 facts fully supported, 0 unsupported).
- **Test Suite Pass Rates:**
  - Full repo test suite: **331 / 331 passed** (`wsl .venv/bin/pytest -q`).
  - H7 Contract regression suite: **62 / 62 passed** (`wsl .venv/bin/pytest -q evals/tests/test_h7_contract_regressions.py`).
- **Static Quality & Formatting:**
  - `ruff check .` -> All checks passed (0 errors).
  - `ruff format --check .` -> 69 files already formatted (0 changes).
  - `mypy src evals/tests` -> Success: no issues found in 35 source files.
  - `pip check` -> No broken requirements found.

---

## 17. Historical Status (H7.4.4 Release)

- **Functional Commit (H7.4.4-0):** `6560586eefc1865959bd3bc937a09cb1527ecac4`
- **Report Commit (H7.4.4):** `a02a8b0a9fc50b75b9fe68f09b735b63c628b4cb`
- **Remote Branch:** `feat/gate-3-system-analysis`
- **Baseline-v3 Spec:** `evals/baselines/gate-3-baseline-v3.json` (`candidate_git_sha = ""`)
- **Execution Status:** Strictly offline. Zero provider calls, zero baseline runs, no baseline-v3 reservation, baseline-v2 reservation byte-for-byte preserved.

---

## 18. H7.4.4.1 / Contract 3.5.3 Final Domain-Closure Hotfix Details

### 18.1 Domain-Closure Remediation (PlatformDependencyFact)
- **Host / Model Wire Asymmetry Elimination:** Contract 3.5.3 frozen wire schema specifies `PlatformFamily = Literal["WINDOWS"]`. In H7.4.4, `src/cobol/system_cobol_parser.py` was emitting `PlatformDependencyFact(platform_family="POSIX")` for POSIX shell commands (`/bin/sh -c ...`, `sh -c ...`, `bash -c ...`, `/usr/bin/bash -c ...`).
- **Domain Closure Enforcement:** The host parser now emits `PlatformDependencyFact(platform_family="WINDOWS")` strictly for supported Windows commands (`cmd /c ...`, `cmd.exe /c ...`). For all POSIX shell invocations, the host parser emits **zero** `PlatformDependencyFact` because `"POSIX"` is not a model-visible platform token in Contract 3.5.3.
- **Exact Opaque Command Invocation Preservation:** Exact opaque `CommandInvocationFact` remains grounded for valid `MOVE -> CALL 'SYSTEM'` bindings regardless of dialect.
- **POSIX Mutation vs Non-Mutation Coverage:**
  - *POSIX Mutation Commands* (`/bin/sh -c rm ...`, `bash -c mv ...`): Retain exact `CommandInvocationFact`, emit zero `PlatformDependencyFact`, fail closed as `MUTATION_UNSUPPORTED` (`unsupported_relevant_count >= 1`, `is_evaluation_blocked = True`), and derive zero `OperationSequenceFact` and zero `BehavioralRiskFact`.
  - *POSIX Non-Mutation Commands* (`/bin/sh -c echo test`, `sh -c echo test`, `bash -c echo test`): Retain exact `CommandInvocationFact`, emit zero `PlatformDependencyFact`, derive zero sequence/risk, and maintain clean coverage (`unsupported_relevant_count == 0`, `is_evaluation_blocked = False`). Clean coverage does not conceal a model-visible platform fact.
- **Domain-Closure Invariant:** All constructors of `PlatformDependencyFact` throughout the codebase enforce `platform_family="WINDOWS"`. Host parser can emit only tokens representable by the frozen wire schema (`07655be0a119440e1f693cbd3242842ed87e82c43518bce61f741bc7dc4423dc`).

### 18.2 Explanation of Coverage Certificate Byte Identity Change
Historical independent H7.4.3 review recorded legacy coverage certificate:
`74148cdb6b5c28c576406db77a8c84ae171a7fd1eec568c4d5a15256ef08f177`
H7.4.4 and H7.4.4.1 report:
`e5900cba53db046c80e0e5f64618b549e894631a0eebfe42f8c502fe0ae948be`

An exact semantic diff between H7.4.3 and H7.4.4.1 classification lists (`per_statement_classifications` on `legacy/core-banking-system`) identifies exactly 4 changed statement classifications out of 207 total statements (the remaining 203 statements are 100% identical):

| File | Span | Old Classification (H7.4.3) | New Classification (H7.4.4.1) | Rationale Introduced in H7.4.4 |
|---|---|---|---|---|
| `legacy/core-banking-system/BANK-MAIN.CBL` | `[34, 34]` | `verb='PARAGRAPH_HEADER'`, `RECOGNIZED_BUT_UNSCORED` | `verb='END-PERFORM'`, `RECOGNIZED_BUT_UNSCORED` | Correct procedural statement classification; single-token line `END-PERFORM.` is not a paragraph header. |
| `legacy/core-banking-system/REPORT-GEN.CBL` | `[48, 48]` | `verb='PARAGRAPH_HEADER'`, `RECOGNIZED_BUT_UNSCORED` | `verb='END-PERFORM'`, `RECOGNIZED_BUT_UNSCORED` | Correct procedural statement classification; single-token line `END-PERFORM.` is not a paragraph header. |
| `legacy/core-banking-system/TRANS-PROC.CBL` | `[79, 79]` | `verb='PARAGRAPH_HEADER'`, `RECOGNIZED_BUT_UNSCORED` | `verb='END-PERFORM'`, `RECOGNIZED_BUT_UNSCORED` | Correct procedural statement classification; single-token line `END-PERFORM.` is not a paragraph header. |
| `legacy/core-banking-system/TRANS-PROC.CBL` | `[94, 94]` | `verb='PARAGRAPH_HEADER'`, `RECOGNIZED_BUT_UNSCORED` | `verb='END-IF'`, `RECOGNIZED_BUT_UNSCORED` | Correct procedural statement classification; single-token line `END-IF.` is not a paragraph header. |

**Invariance and Soundness Proofs:**
- `unsupported_relevant_count == 0` is strictly maintained on the frozen legacy fixture.
- All 80 parser-derived supported facts (`SupportedSystemFact`) are **100% bit-for-bit identical** between H7.4.3 and H7.4.4.1.
- Frozen golden evaluation against `evals/expected/system-understanding-v3.json`:
  - Expected Fact Count: 59
  - Matched Expected Count: 59 (59/59)
  - Unsupported Count: 0
  - Precision: **1.0**
  - Recall: **1.0**
  - Gate 3 Pass: **True**
- The change in coverage certificate SHA-256 is entirely and solely attributable to the deliberate grammar correction distinguishing procedural closure tokens from paragraph headers.

### 18.3 Full Original Static Quality Gate (H7.4.4.1)
- `mypy src agents evals scripts` -> Success: no issues found in 52 source files.
- `pytest -q` -> 333 passed, 1 warning in 291.80s.
- `pytest -q evals/tests/test_h7_contract_regressions.py` -> 64 passed in 12.69s.
- `pytest -q evals/tests/test_adversarial_regressions_gate3.py` -> 24 passed in 2.94s.
- `pytest -q evals/tests/test_round3_regressions.py` -> 15 passed in 10.94s.
- `ruff check .` -> All checks passed (0 errors).
- `ruff format --check .` -> 69 files already formatted.
- `pip check` -> No broken requirements found.

### 18.4 Complete Scientific Immutability Invariants (CLI-Grounded)
| Asset | Target / File | Hash / Value | Verification Status |
|---|---|---|---|
| Baseline-v1 Spec | `evals/baselines/gate-3-baseline-v1.json` | `b37e8815e2605f279ecc417b8e037f0b235f5e1dcfa64d79b10708e852509695` | Byte-for-byte verified |
| Baseline-v1 Artifacts | `artifacts/gate-3/baseline-v1/manifest.json` | 13 artifacts matching manifest SHAs | All 13 verified identical |
| Baseline-v2 Reservation | `artifacts/gate-3/baseline-v2/reservation-state.json` | `108c51b222e476f32bd98c092c5dc814be9a25b4d1b93ae60f0f28ea2f5a631d` | Byte-for-byte verified |
| Production Prompt | `agents/legacy_analyzer/prompts/system_v3.md` | `4be25cfc25933d6f0e69cbeeae1efe12ccf2e1354857e04c90108d8534ea92e8` | Byte-for-byte verified |
| Generated Wire Schema | `get_system_openai_wire_schema()` | `07655be0a119440e1f693cbd3242842ed87e82c43518bce61f741bc7dc4423dc` | Byte-for-byte verified |
| Golden Dataset | `evals/expected/system-understanding-v3.json` | `da5bdee9286dd5fbc79cb8331b70aabf73fca029fe4a3d3c5ede5ed2c984b82b` | Byte-for-byte verified |
| Dependency Lock | `requirements-lock.txt` | `732cb9370e90af2d0972eeda7fc18fd5745f17cb301f359b268df228fe7f18be` | Byte-for-byte verified |
| Source Manifest | `evals/baselines/gate-3-baseline-v3.json` (`target_bundle`) | `daf28b3314199db8e31bfacdf2fb8441b54682caa7854ed288e1bc00866a1dd1` | Byte-for-byte verified |
| Canonical Bundle | `legacy/` (6 artifacts) | `95bb386b51d653c0a1834e1950634a9887b7cb6826b8c317a07c4b6a4167d060` | Byte-for-byte verified |
| Baseline-v3 Spec | `evals/baselines/gate-3-baseline-v3.json` | `candidate_git_sha = ""` | Verified empty |
| Baseline-v3 Artifacts | `artifacts/gate-3/baseline-v3` | Does NOT exist | Verified absent |

---

## 19. Historical Status (H7.4.4.1 Release)

- **Functional Commit (H7.4.4.1-0):** `dd8563b10fa3fb5f7db2a3cb9d91f2bac6e87100`
- **Report Commit (H7.4.4.1):** `750c9bca9da922f6493ba6f6a31cf30392f02051`
- **Remote Branch:** `feat/gate-3-system-analysis`
- **Baseline-v3 Spec:** `evals/baselines/gate-3-baseline-v3.json` (`candidate_git_sha = ""`)
- **Execution Status:** Strictly offline. Zero provider calls, zero baseline runs, no baseline-v3 reservation, baseline-v2 reservation byte-for-byte preserved.

---

## 20. H7.4.4.2 / Contract 3.5.3 Unrepresentable Platform Semantics Fail-Closed Hotfix Details

### 20.1 Problem Analysis: Elimination of POSIX Fail-Open Anomaly
Under Contract 3.5.3 wire schema:
- `PlatformFamily = Literal["WINDOWS"]` (only `"WINDOWS"` is model-visible).
- Category evaluation policy establishes `PLATFORM_DEPENDENCY = REQUIRED_EXHAUSTIVE`.

In H7.4.4.1, non-mutation POSIX commands (`/bin/sh -c echo test`, `sh -c echo test`, `bash -c echo test`, `/usr/bin/bash -c echo test`) emitted exact `CommandInvocationFact`, zero `PlatformDependencyFact`, but retained clean coverage (`unsupported_relevant_count == 0`, `is_evaluation_blocked == False`). This was identified as an unsound fail-open condition: because `PLATFORM_DEPENDENCY` is `REQUIRED_EXHAUSTIVE`, encountering a deterministically established POSIX platform dependency that cannot be represented by the model-visible wire schema must block evaluation coverage rather than silently concealing the unrepresentable platform dependency.

### 20.2 Required Semantics & Implementation
For every deterministically recognized `CommandDialect.POSIX_SHELL` invocation dispatched via literal `CALL 'SYSTEM'`:
1. **Retain Exact Command Invocation:** `CommandInvocationFact` remains fully grounded if the `MOVE -> CALL 'SYSTEM'` binding is otherwise valid.
2. **Zero Platform Dependency:** Emits strictly zero `PlatformDependencyFact` (Contract 3.5.3 wire schema permits only `"WINDOWS"`).
3. **Fail-Closed Coverage Block:** The command dispatch source statements are marked `StatementClassification.UNSUPPORTED_RELEVANT` with reason:
   `"POSIX shell command establishes an unrepresentable platform dependency outside Contract 3.5.3 frozen schema (PlatformFamily exposes ONLY WINDOWS)"`.
4. **Certificate Enforcement:** `ParserCoverageCertificate` evaluates to:
   - `unsupported_relevant_count >= 1`
   - `is_evaluation_blocked == True`
5. **Universal Application:** Applies equally to POSIX mutation (`/bin/sh -c rm ...`, `bash -c mv ...`) and POSIX non-mutation (`/bin/sh -c echo test`, `sh -c echo test`, `bash -c echo test`).
6. **Zero Fabricated Sequences/Risks:** Derived sequence (`OperationSequenceFact`) and risk (`BehavioralRiskFact`) remain zero.

### 20.3 Windows Positive Controls & Scope Preservations
- **Windows Commands (`cmd /c echo test`, `cmd.exe /c echo test`):**
  - Emits `CommandInvocationFact(command_template=win_cmd)`
  - Emits `PlatformDependencyFact(platform_family="WINDOWS", command_literal=win_cmd)`
  - Coverage remains clean: `unsupported_relevant_count == 0`, `is_evaluation_blocked == False`
  - Zero mutation sequence or risk derived.
- **Bare/Other Commands:** Unchanged, preserving existing behavior.
- **Frozen Legacy Fixture (`legacy/core-banking-system`):** Contains only Windows `cmd /c` dispatches (`del ACCOUNTS.DAT`, `ren ACCOUNTS.TMP ACCOUNTS.DAT`, `del ACCOUNTS.TMP`). Yields `unsupported_relevant_count == 0`, preserving the canonical certificate SHA-256 `e5900cba53db046c80e0e5f64618b549e894631a0eebfe42f8c502fe0ae948be` and 59/59 golden evaluation (precision=1.0, recall=1.0).

### 20.4 Two-Part Host/Wire Closure Invariant
The enforced closure invariant guarantees:
- **Invariant A (Sound Token Emission):** Every emitted `PlatformDependencyFact` token is wire-representable (`platform_family in {"WINDOWS"}`). No unsupported token (such as `"POSIX"`) can ever be instantiated in host support facts.
- **Invariant B (Completeness Fail-Closed):** If the parser deterministically observes an unrepresentable platform dependency outside the wire domain, coverage **MUST** fail closed (`unsupported_relevant_count >= 1`, `is_evaluation_blocked == True`) because `PLATFORM_DEPENDENCY` is `REQUIRED_EXHAUSTIVE`.

### 20.5 Full Original Static Quality Gate (H7.4.4.2)
- `mypy src agents evals scripts` -> Success: no issues found in 52 source files.
- `pytest -q` -> 334 passed, 1 warning in 297.66s.
- `pytest -q evals/tests/test_h7_contract_regressions.py` -> 65 passed in 12.89s.
- `pytest -q evals/tests/test_adversarial_regressions_gate3.py` -> 24 passed in 2.98s.
- `pytest -q evals/tests/test_round3_regressions.py` -> 15 passed in 11.20s.
- `ruff check .` -> All checks passed (0 errors).
- `ruff format --check .` -> 69 files already formatted.
- `pip check` -> No broken requirements found.

### 20.6 Complete Scientific Immutability Invariants (CLI-Grounded)
| Asset | Target / File | Hash / Value | Verification Status |
|---|---|---|---|
| Baseline-v1 Spec | `evals/baselines/gate-3-baseline-v1.json` | `b37e8815e2605f279ecc417b8e037f0b235f5e1dcfa64d79b10708e852509695` | Byte-for-byte verified |
| Baseline-v1 Artifacts | `artifacts/gate-3/baseline-v1/manifest.json` | 13 artifacts matching manifest SHAs | All 13 verified identical |
| Baseline-v2 Reservation | `artifacts/gate-3/baseline-v2/reservation-state.json` | `108c51b222e476f32bd98c092c5dc814be9a25b4d1b93ae60f0f28ea2f5a631d` | Byte-for-byte verified |
| Production Prompt | `agents/legacy_analyzer/prompts/system_v3.md` | `4be25cfc25933d6f0e69cbeeae1efe12ccf2e1354857e04c90108d8534ea92e8` | Byte-for-byte verified |
| Generated Wire Schema | `get_system_openai_wire_schema()` | `07655be0a119440e1f693cbd3242842ed87e82c43518bce61f741bc7dc4423dc` | Byte-for-byte verified |
| Golden Dataset | `evals/expected/system-understanding-v3.json` | `da5bdee9286dd5fbc79cb8331b70aabf73fca029fe4a3d3c5ede5ed2c984b82b` | Byte-for-byte verified |
| Dependency Lock | `requirements-lock.txt` | `732cb9370e90af2d0972eeda7fc18fd5745f17cb301f359b268df228fe7f18be` | Byte-for-byte verified |
| Source Manifest | `evals/baselines/gate-3-baseline-v3.json` (`target_bundle`) | `daf28b3314199db8e31bfacdf2fb8441b54682caa7854ed288e1bc00866a1dd1` | Byte-for-byte verified |
| Canonical Bundle | `legacy/` (6 artifacts) | `95bb386b51d653c0a1834e1950634a9887b7cb6826b8c317a07c4b6a4167d060` | Byte-for-byte verified |
| Baseline-v3 Spec | `evals/baselines/gate-3-baseline-v3.json` | `candidate_git_sha = ""` | Verified empty |
| Baseline-v3 Artifacts | `artifacts/gate-3/baseline-v3` | Does NOT exist | Verified absent |
| Legacy Certificate | `ParserCoverageCertificate` on `legacy/` | `e5900cba53db046c80e0e5f64618b549e894631a0eebfe42f8c502fe0ae948be` | Byte-for-byte verified |
| Golden Evaluation | Evaluation of frozen golden | 59/59, Precision=1.0, Recall=1.0 | Full Pass |

---

## 21. Final Status (H7.4.4.2 Release)

- **Functional Commit (H7.4.4.2-0):** `ad115a2b48ffcc7db998fa09a663ca680cf8a404`
- **Report Commit (H7.4.4.2):** Direct report-only child of `H7.4.4.2-0`
- **Remote Branch:** `feat/gate-3-system-analysis`
- **Baseline-v3 Spec:** `evals/baselines/gate-3-baseline-v3.json` (`candidate_git_sha = ""`)
- **Execution Status:** Strictly offline. Zero provider calls, zero baseline runs, no baseline-v3 reservation, baseline-v2 reservation byte-for-byte preserved.

---

## 22. H7.5 / Contract 3.5.3 Source-to-Host Soundness & Exhaustive Completeness Remediation (Astra Review Findings F-01 through F-11)

Following the Astra XHigh External Technical Audit on Contract 3.5.3, this remediation cycle comprehensively and soundly addresses all eleven audit findings (F-01 through F-11) across a strict 4-commit sequence, without regressions to reference evaluation metrics, schema invariants, or frozen baselines.

### 22.1 Audit Findings & Architectural Remediations Summary

#### F-01: Pure Host Fact Oracle Replacement in `evaluate_assessment`
- **Issue:** Evaluator previously compared candidate model predictions against `expected_propositions` directly, creating potential circularity and bypassing host extraction during mutation evaluations.
- **Remediation:** Refactored `evaluate_assessment` to use pure host-extracted atomic facts (`parser.extract_atomic_facts()`) as the sole authoritative evaluation oracle across all 11 categories. Dual-evaluation parity check verified on frozen reference codebase: host extraction produces exact equivalence with frozen golden dataset (`da5bdee...`).

#### F-02: Conservative Control-Flow Effect Proof in Procedural Continuation
- **Issue:** Caller continuation constraints relied on linear `last_stmt_verb` heuristics, vulnerable to dead-code, loops, and branching ambiguity.
- **Remediation:** Replaced line-order heuristics with hierarchical CFG block parsing (`_parse_procedural_cf_block`), finite loop termination verification (`_verify_finite_loop_progress`), and effect tracing (`_analyze_cf_nodes`) with cycle detection and interprocedural effect composition. If continuation outcome is indeterminate (`UNKNOWN`), the parser fails closed as `UNSUPPORTED_RELEVANT`.

#### F-03: Elimination of Partial AST Fact Emission
- **Issue:** Partial statements or failed validations could emit incomplete AST nodes or partial facts.
- **Remediation:** Ensured zero partial or placeholder AST nodes or facts are emitted upon validation failure. Malformed statements fail closed as `UNSUPPORTED_RELEVANT`.

#### F-04: Fail-Closed Classification of Unparseable Procedural Statements
- **Issue:** Unrecognized procedural statements were silently skipped instead of failing closed.
- **Remediation:** All non-allowlisted, invalid, or malformed procedural statements are strictly classified as `UNSUPPORTED_RELEVANT`, marking `is_evaluation_blocked = True` on `ParserCoverageCertificate`.

#### F-05: Strict Token Delimiter Handling in Free-Format COBOL Lexer
- **Issue:** Substring and punctuation parsing risked bleeding between adjacent tokens or misinterpreting numeric/quoted literals.
- **Remediation:** Lexer eliminates raw substring searching, enforcing exact word boundaries, respecting quoted string literals, handling period tokens soundly, and isolating single terminal sentence periods.

#### F-06: Sound OperationSequence Dispatches
- **Issue:** Non-standard external mutation sequences in the same linear block (such as `RENAME` followed by `DELETE`) were not properly classified.
- **Remediation:** Within a linear segment, any multi-dispatch pair outside the frozen wire schema domain (`DELETE` -> `RENAME`) is strictly classified as `UNSUPPORTED_RELEVANT`, failing coverage closed without fabricating uncertifiable facts.

#### F-07: Mandatory Organization on File Descriptors
- **Issue:** Missing or quoted file organization clauses could be ambiguously classified.
- **Remediation:** `SELECT` file control clauses with absent organization or organization in quoted literals strictly fail closed as `UNSUPPORTED_RELEVANT`.

#### F-08: Deterministic Total Record Comparator
- **Issue:** Pairwise record comparisons required strict symmetry, completeness, and tie-breaking.
- **Remediation:** Verified total record layout comparator across all $N(N-1)/2$ combinations, ensuring strict symmetry, deterministic orientation, and tie-breaking.

#### F-09: Evidence Span Alignment with Wire Schemas
- **Issue:** Evidence spans could encompass excessive whitespace or bleed into neighboring statements.
- **Remediation:** Aligned evidence spans to exact physical line bounds of constituent statements for all 11 fact categories, eliminating synthetic padding.

#### F-10: Source-Derived Exhaustive Completeness
- **Issue:** Exhaustive category verification lacked explicit representation independent of golden propositions.
- **Remediation:** Added `CanonicalExhaustiveObligation` (hashable, frozen dataclass with canonical tuple coordinates). Extracted host exhaustive obligations directly from host-parsed facts and candidates. Added exhaustive metrics (`host_exhaustive_fact_count`, `matched_host_exhaustive_fact_count`, `missing_host_exhaustive_fact_count`) to `EvaluationMetricSummary`. Enforced `missing_host_exhaustive_fact_count == 0` for `gate_3_pass`. Implemented runner preflight parity check in `scripts/run-gate-3.py` verifying 45/45 host-derived obligations match golden prior to attempt claims or model invocations.

#### F-11: Raw Invocation Terminal Failure Evidence Sealing
- **Issue:** Exceptions during `agent.invoke_raw(...)` bypassed evidence preservation and manifest sealing.
- **Remediation:** Attempt claim is irrevocably acquired before invocation. Exceptions during raw invocation route directly through `finalize_post_model_failure(...)`: persists `run-metadata.json`, writes `terminal-result.json` (`status="FAILED"`, `error_phase="MODEL_INVOCATION"`), seals `manifest.json`, produces zero fake response files, transitions `reservation-state.json` to `FAILED`, and exits 1 with zero retries.

---

### 22.2 Quality Gates & Verification (H7.5 Release)

1. **Targeted H7.5 Contract Regression Suite (`evals/tests/test_h7_contract_regressions.py`):**
   - 82 passed in 13.75s (including Sections 18 and 19 covering F-01 through F-10).
2. **Runner & Authorization Contract Suite (`evals/tests/test_gate_3_runner.py`):**
   - 13 passed in 33.62s (including `test_f11_raw_invocation_terminal_failure_sealing`).
3. **Adversarial Regression Suite (`evals/tests/test_adversarial_regressions_gate3.py`):**
   - 24 passed in 3.37s (including updated CF10 fail-closed semantics for RENAME -> DELETE ordering).
4. **Full Workspace Pytest Suite:**
   - 352 passed, 0 failures in 302.92s.
5. **Static Type Checking (`mypy src agents evals scripts`):**
   - Success: no issues found in 52 source files.
6. **Linter & Formatter (`ruff check .`, `ruff format --check .`):**
   - All checks passed, all files formatted cleanly.
7. **Dependency Hygiene (`pip check`):**
   - No broken requirements found.

---

### 22.3 Complete Scientific Immutability Invariants (CLI-Grounded)

| Asset | Target / File | Hash / Value | Verification Status |
|---|---|---|---|
| Baseline-v1 Spec | `evals/baselines/gate-3-baseline-v1.json` | `b37e8815e2605f279ecc417b8e037f0b235f5e1dcfa64d79b10708e852509695` | Byte-for-byte verified |
| Baseline-v1 Artifacts | `artifacts/gate-3/baseline-v1/manifest.json` | 13 artifacts matching manifest SHAs | All 13 verified identical |
| Baseline-v2 Reservation | `artifacts/gate-3/baseline-v2/reservation-state.json` | `108c51b222e476f32bd98c092c5dc814be9a25b4d1b93ae60f0f28ea2f5a631d` | Byte-for-byte verified |
| Production Prompt | `agents/legacy_analyzer/prompts/system_v3.md` | `4be25cfc25933d6f0e69cbeeae1efe12ccf2e1354857e04c90108d8534ea92e8` | Byte-for-byte verified |
| Generated Wire Schema | `get_system_openai_wire_schema()` | `07655be0a119440e1f693cbd3242842ed87e82c43518bce61f741bc7dc4423dc` | Byte-for-byte verified |
| Golden Dataset | `evals/expected/system-understanding-v3.json` | `da5bdee9286dd5fbc79cb8331b70aabf73fca029fe4a3d3c5ede5ed2c984b82b` | Byte-for-byte verified |
| Dependency Lock | `requirements-lock.txt` | `732cb9370e90af2d0972eeda7fc18fd5745f17cb301f359b268df228fe7f18be` | Byte-for-byte verified |
| Source Manifest | `evals/baselines/gate-3-baseline-v3.json` (`target_bundle`) | `daf28b3314199db8e31bfacdf2fb8441b54682caa7854ed288e1bc00866a1dd1` | Byte-for-byte verified |
| Canonical Bundle | `legacy/` (6 artifacts) | `95bb386b51d653c0a1834e1950634a9887b7cb6826b8c317a07c4b6a4167d060` | Byte-for-byte verified |
| Baseline-v3 Spec | `evals/baselines/gate-3-baseline-v3.json` | `candidate_git_sha = ""` | Verified empty |
| Baseline-v3 Artifacts | `artifacts/gate-3/baseline-v3` | Does NOT exist | Verified absent |
| Golden Semantic Digest | Proposition & Policy canonical JSON digest | `1160261957bddfe11ca13131da3cb2471d1dd1f5f208bf8cb4ce2e8dc9c77a92` | Byte-for-byte verified |
| Reference Evaluation | Golden vs Host Evaluator on `legacy/` | 59/59, Precision=1.0, Recall=1.0, Exhaustive=45/45 | Full Pass |

---

## 23. Historical H7.5 Release Status

- **Functional Commit H7.5-A:** `984920f2a8e9a5f253952576649a9d2ddd38cff2` (Host oracle & parser soundness F-01, F-03..F-09)
- **Functional Commit H7.5-B:** `b3dbbc9d537ec246b6153d799042170f74d39ea7` (Continuation effect proof F-02 & Exhaustive completeness F-10)
- **Functional Commit H7.5-C:** `d786c3fcd4e0bbc51d0f9e7b96e1d922dd1fccac` (Raw invocation terminal failure evidence sealing F-11)
- **Report Commit H7.5:** `ec2bcb4d42b1c172bade60d1fe872105841dfe8d`
- **Remote Branch:** `feat/gate-3-system-analysis`
- **Execution Mode:** Strictly OFFLINE. 0 provider calls, 0 baseline-v3 reservations, baseline-v2 reservation byte-for-byte preserved.

---

## 24. H7.6 / Contract 3.5.3 Comprehensive Remediation of Astra XHigh Audit Findings

Following the second-round independent Astra XHigh External Technical Audit on Gate 3 / Contract 3.5.3, all 13 findings (`B-01`, `B-02`, `H-01` through `H-08`, `M-01`, `M-02`, `D-01`) have been remediated across a strict 4-commit functional partition followed by this report commit.

### 24.1 Detailed Remediation Breakdown

#### B-01: Structural Finite-Loop Termination Proof
- **Finding:** Procedural loop analysis relied on step count heuristics that could fail to distinguish true non-terminating loops from valid terminating loops with complex progress conditions.
- **Remediation (`H7.6-B`):** Replaced ad-hoc step counters with a formal finite loop invariant proof in `_verify_finite_loop_progress`:
  1. Identifies loop control variables in `UNTIL` conditions.
  2. Proves that the loop body contains at least one progress-making mutation to the control variables.
  3. Proves monotonic delta progression toward the termination boundary.
  4. Verifies exit or termination site reachability.
  5. Any loop failing structural proof fails closed as indeterminate `UNKNOWN`, triggering `UNSUPPORTED_RELEVANT` coverage blockage.

#### B-02: Lossless Support-Index Occurrences
- **Finding:** `SystemSupportIndex` and `SourceSupportIndex` performed lossy deduplication by keying strictly on proposition IDs, causing identical propositions with distinct evidence spans to overwrite each other and obscuring honest fact occurrence counts.
- **Remediation (`H7.6-A`):** Redesigned support index internal storage:
  1. Maintained an ordered, complete list of occurrences per proposition ID without deduplication.
  2. Enhanced lookup methods (`get_facts_by_id`, `get_fact_by_id`, `find_matching_occurrence`) to operate losslessly over all occurrences.
  3. Reported honest occurrence counts (`total_expected_facts == 80` on canonical legacy bundle).

#### H-01: Control-Flow Outcome Algebra
- **Finding:** Branch outcome merging lacked a rigorous algebraic foundation for composing parallel and sequential procedural outcomes.
- **Remediation (`H7.6-B`):** Defined and implemented formal outcome algebra over procedural control flow paths:
  - Parallel composition ($O_1 \oplus O_2$): Both branches must agree on termination (`TERMINATES`) to yield definite termination; divergence between `TERMINATES` and `RETURNS` yields sound branch-level constraint evaluation.
  - Sequential composition ($O_1 \otimes O_2$): Early termination dominates subsequent statements; dead-code branches do not dilute prior termination proof.

#### H-02: Direct Callee Termination Site Provenance
- **Finding:** Caller continuation constraints could propagate transitive or fabricated termination assumptions without verifying direct evidence from the callee's physical termination site.
- **Remediation (`H7.6-B`):** Enforced direct callee termination site provenance:
  1. `CallerContinuationConstraintFact` requires direct evidence of the callee's physical `STOP RUN` or `GOBACK` statement.
  2. Transitive-only or ungrounded continuation assumptions fail closed as `UNKNOWN`.

#### H-03: Explicit CALL / SYSTEM Effect Summaries
- **Finding:** Interprocedural calls and external `CALL 'SYSTEM'` dispatches lacked explicit effect summaries, risking inaccurate side-effect assumptions.
- **Remediation (`H7.6-B`):** Constructed explicit effect summaries:
  - Internal `CALL`: Interprocedural summaries capturing parameter mutations and return/termination behavior.
  - `CALL 'SYSTEM'`: External process invocation summary ensuring system-level dispatches are never assumed to terminate the COBOL runtime process unless explicitly bounded.

#### H-04: Command Fail-Closed Semantics
- **Finding:** Unrecognized or non-allowlisted external command dispatches could be bypassed without enforcing coverage blocks.
- **Remediation (`H7.6-C`):** Strict fail-closed semantics on all external commands:
  - Only allowlisted commands (`cmd /c del ...`, `cmd /c ren ...`) in recognized sequences (`DELETE -> RENAME`) are certifiable.
  - Any non-allowlisted, malformed, or reversed dispatch pair strictly increments `unsupported_relevant_count >= 1` and sets `is_evaluation_blocked = True`.

#### H-05: Sentence-Period Control Boundary IR
- **Finding:** Period tokens could bleed across procedural statements, causing incorrect grouping of independent statements into linear segments.
- **Remediation (`H7.6-B`, `H7.6-C`):** Implemented strict sentence-period IR:
  - Period tokens unconditionally terminate active procedural control structures (`IF`, `PERFORM`, `EVALUATE`, `READ ... AT END`).
  - `OperationSequence` strictly enforces sentence boundaries, preventing dispatches across distinct sentences from being grouped into single operation sequences.

#### H-06: Level-88 Complete Grammar
- **Finding:** Level-88 condition names allowed non-standard prefixes (e.g. `88 COND PIC X VALUE ...`) or unclosed literals without failing closed.
- **Remediation (`H7.6-C`):** Enforced complete level-88 grammar:
  - Requires strict `88 <name> VALUE/VALUES <literal(s)>.` syntax.
  - Non-standard prefixes, missing values, unclosed quotes, or range keywords (`THRU`) fail closed as `UNSUPPORTED_RELEVANT`.

#### H-07: Sealed-Evidence State Machine
- **Finding:** Post-model failure finalization lacked read-back verification of evidence artifacts on disk, and could leave ambiguous reservation states if disk writes failed after evidence generation.
- **Remediation (`H7.6-D`):** Centralized `finalize_post_model_failure` with rigorous read-back verification:
  1. Re-reads `terminal-result.json` and `manifest.json` from disk.
  2. Verifies presence of all required phase artifacts in `manifest.json`.
  3. Verifies byte-for-byte SHA256 checksums of all manifested artifacts against bytes on disk.
  4. **Case A (Evidence Sealed, Reservation Write Failed):** If evidence is verified on disk but writing `FAILED` to `reservation-state.json` fails, status transitions to `COORDINATION_FAILURE`, evidence remains preserved, and `coordination-failure.json` is written with `evidence_sealed: True`.
  5. **Case B (Evidence Sealing Failed):** If artifact verification fails (e.g. SHA mismatch, missing file, disk corruption), status becomes `FAILED_UNSEALED`, `reservation-state.json` is marked `FAILED_UNSEALED`, and `coordination-failure.json` is written with `evidence_sealed: False` and `verification_errors`.

#### H-08: Post-Claim Failure Envelope & Irrevocable Claim Check
- **Finding:** If a failure occurred between attempt claim creation and model invocation, or if an attempt claim already existed, re-entry could potentially attempt uncoordinated execution.
- **Remediation (`H7.6-D`):**
  1. **Unconditional Claim Re-Entry Refusal:** Child startup checks for `attempt-claim.json`. If present, execution immediately halts with exit code 1 across all reservation states (`RESERVED`, `FAILED_UNSEALED`, `MODEL_INVOCATION`, `FAILED`, missing, corrupt) with 0 provider calls.
  2. **Wrapped Post-Claim Reservation Update:** The write of `MODEL_INVOCATION` to `reservation-state.json` is wrapped in `try...except`, routing to `finalize_post_model_failure(error_phase="MODEL_INVOCATION_RESERVATION")` on failure, sealing terminal failure evidence and exiting 1.

#### M-01: `FileOrganization.SEQUENTIAL` Certification
- **Finding:** `ORGANIZATION IS SEQUENTIAL` and `LINE SEQUENTIAL` clauses in `SELECT` statements required explicit parser certification.
- **Remediation (`H7.6-A`):** Explicitly parsed and certified `ORGANIZATION IS [LINE] SEQUENTIAL`, ensuring clean file binding fact extraction without spurious coverage blocks.

#### M-02: Record-Scope Layout Atomicity
- **Finding:** Unhandled statements within a 01 record definition could invalidate subsequent valid record definitions or divisions.
- **Remediation (`H7.6-C`):** Scoped layout atomicity to individual 01 records:
  - An invalidating statement within a record discards only that active record layout.
  - Invalidation does not bleed across record boundaries: valid sibling 01 records are certified independently while unsupported count increments.

#### D-01: Independent Golden Documentation & Traceability
- **Finding:** Golden dataset required explicit documentation of auditor-facing static source rationales and verified independence from the production parser.
- **Remediation (`H7.6-A` through `H7.6-D`):** Re-verified complete auditor rationales for all 59 propositions under `INDEPENDENT_STATIC_SOURCE_AUDIT`. Golden generation modules import zero parser logic.

---

## 25. Quality Gates & Final Verification (H7.6 Release)

### 25.1 Test Suite Verification
1. **Targeted H7 / Contract Regression Suite (`evals/tests/test_h7_contract_regressions.py`):**
   - **98 passed, 0 failures** (including 4 new tests in Section H7.6-D for H-07 and H-08).
2. **Runner & Authorization Contract Suite (`evals/tests/test_gate_3_runner.py`):**
   - **13 passed, 0 failures** (including irrevocable claim check, failure sealing, and dynamic Python 3.12 compatibility).
3. **Remediation Regression Suite (`evals/tests/test_gate_3_remediation_regressions.py`):**
   - **25 passed, 0 failures** (all 5 failure scenarios, reservation state transitions, immutable artifact preservation).
4. **Combined Gate 3 Regression Suites:**
   - **136 passed, 0 failures**.
5. **Static Type Checking (`mypy scripts/run-gate-3.py evals/tests/`):**
   - **Success: no issues found in source files**.
6. **Linter & Formatter (`ruff check .`, `ruff format --check .`):**
   - **All checks passed, all files formatted cleanly**.
7. **Dependency Hygiene (`pip check`):**
   - **No broken requirements found**.

### 25.2 Grounded Canonical Reference Metrics (`legacy/core-banking-system`)
- **Parser Supported Facts Count:** 80
- **Support Index Total Expected Facts:** 80
- **Support Index All Facts Count:** 80
- **Evaluation Gate 3 Pass:** `True`
- **Precision:** `1.0` (59 / 59)
- **Recall:** `1.0` (59 / 59)
- **Host Exhaustive Fact Count:** 45
- **Matched Host Exhaustive Fact Count:** 45
- **Missing Host Exhaustive Fact Count:** 0
- **Unsupported Relevant Count:** 0
- **Evaluation Blocked:** `False`

### 25.3 Complete Scientific Immutability Invariants (CLI-Grounded)

| Asset | Target / File | Hash / Value | Verification Status |
|---|---|---|---|
| Baseline-v1 Spec | `evals/baselines/gate-3-baseline-v1.json` | `b37e8815e2605f279ecc417b8e037f0b235f5e1dcfa64d79b10708e852509695` | Byte-for-byte verified |
| Baseline-v1 Artifacts | `artifacts/gate-3/baseline-v1/manifest.json` | 13 artifacts matching manifest SHAs | All 13 verified identical |
| Baseline-v2 Reservation | `artifacts/gate-3/baseline-v2/reservation-state.json` | `108c51b222e476f32bd98c092c5dc814be9a25b4d1b93ae60f0f28ea2f5a631d` | Byte-for-byte verified |
| Production Prompt | `agents/legacy_analyzer/prompts/system_v3.md` | `4be25cfc25933d6f0e69cbeeae1efe12ccf2e1354857e04c90108d8534ea92e8` | Byte-for-byte verified |
| Generated Wire Schema | `get_system_openai_wire_schema()` | `07655be0a119440e1f693cbd3242842ed87e82c43518bce61f741bc7dc4423dc` | Byte-for-byte verified |
| Golden Dataset | `evals/expected/system-understanding-v3.json` | `da5bdee9286dd5fbc79cb8331b70aabf73fca029fe4a3d3c5ede5ed2c984b82b` | Byte-for-byte verified |
| Dependency Lock | `requirements-lock.txt` | `732cb9370e90af2d0972eeda7fc18fd5745f17cb301f359b268df228fe7f18be` | Byte-for-byte verified |
| Source Manifest | `evals/baselines/gate-3-baseline-v3.json` (`target_bundle`) | `daf28b3314199db8e31bfacdf2fb8441b54682caa7854ed288e1bc00866a1dd1` | Byte-for-byte verified |
| Canonical Bundle | `legacy/` (6 artifacts) | `95bb386b51d653c0a1834e1950634a9887b7cb6826b8c317a07c4b6a4167d060` | Byte-for-byte verified |
| Baseline-v3 Spec | `evals/baselines/gate-3-baseline-v3.json` | `candidate_git_sha = ""` | Verified empty |
| Baseline-v3 Artifacts | `artifacts/gate-3/baseline-v3` | Does NOT exist | Verified absent |
| Golden Semantic Digest | Proposition & Policy canonical JSON digest | `0bb874ca3070f71f23134fe2ec4f7cc2d48c37d2bc4663887d343a6d159d65f2` | Byte-for-byte verified |
| Reference Evaluation | Golden vs Host Evaluator on `legacy/` | 59/59, Precision=1.0, Recall=1.0, Exhaustive=45/45 | Full Pass |

---

## 26. Final Status (H7.6 Release)

- **Functional Commit H7.6-A:** `0e7b42fe31e9c704257125eef050dbd44933939d` (Lossless support-index occurrences `B-02`, sequential certification `M-01`, documentation `D-01`)
- **Functional Commit H7.6-B:** `e37a58e87498c863fc90a3674cf48f7608240590` (Finite-loop proof `B-01`, CF algebra `H-01`, termination provenance `H-02`, effect summaries `H-03`, sentence IR `H-05`)
- **Functional Commit H7.6-C:** `60c243e3761b9657f6d7316ae63158557d83db41` (Fail-closed commands `H-04`, operation sequence CF `H-05`, level-88 grammar `H-06`, record layout atomicity `M-02`)
- **Functional Commit H7.6-D:** `2b8b5f981d156ecba0360b8713f95f495e6567ed` (Sealed-evidence state machine `H-07`, post-claim failure envelope & re-entry refusal `H-08`)
- **Report Commit H7.6:** Direct report-only child of `H7.6-D` (modifying strictly `docs/gate-3-h7-contract-remediation-report.md`)
- **Remote Branch:** `feat/gate-3-system-analysis`
- **Execution Mode:** Strictly OFFLINE. 0 provider calls, 0 baseline-v3 reservations, baseline-v2 reservation byte-for-byte preserved.





