# GATE 3 REMEDIATION AND PRE-ASTRA HOTFIX — AUDIT REPORT

**Generated mechanically from repository data without manual constants.**

## 1. Provenance and Repository State
- **Audited Hotfix Candidate SHA (Commit H0)**: `946b8bfd7bb93ec5912420d54d77a8f144a130f6`
- **Report Source SHA**: `946b8bfd7bb93ec5912420d54d77a8f144a130f6`
- **Preserved Remote Anchor**: `e8bd484`
- **Pre-Hotfix Candidate SHA (Commit C)**: `6a7267c4ee00b21fc13813ff3021f196eb0064f2`
- **Base Candidate SHA (Commit C0)**: `48123358a2023dae91b56cb4437c9eeeb5a967f7`
- **Legacy Repository Status**: `UNTOUCHED / CLEAN`
- **Gate 2 Artifacts Status**: `UNTOUCHED / CLEAN`
- **Live Calls Made**: `0`
- **Baseline-v1 Executions Run**: `0`
- **Authorization Commit A**: `NOT CREATED` (strictly deferred)

### Recent Forward Git Commits
```text
946b8bf fix(gate-3): pre-astra hotfix - wire file status certificate, remove prompt leakage, eliminate expected_git_sha, enforce version contract
6a7267c docs(gate-3): record mechanically generated remediation round 3 audit report for candidate 4812335
4812335 feat(gate-3): round 3 pre-astra corrections (fail-closed parser, level-88 losslessness, file status certificate, 18 category policies, and runner plumbing)
e8bd484 docs(gate-3): sync mechanical remediation report to commit 62a9053
62a9053 docs(gate-3): add mechanically generated remediation round 2 audit report
239aa8c feat(gate-3): two-phase authorization, irrevocable reservation, and targeted regression suite
72843ce feat(gate-3): independent static golden dataset, schema leakage removal, and category policies
364e334 fix(gate-3): add type annotation to adversarial regressions test
```

## 2. Independent Golden Dataset Verification
- **Authoring Method**: `INDEPENDENT_STATIC_SOURCE_AUDIT`
- **Total Required Facts**: `59`
- **Auditor Rationale Present**: `True`
- **Production Parser Independence**: Zero golden-authoring files import `SystemCobolParser` or `SystemSupportIndex`

### Ground Truth Category Breakdown
| Proposition Category | Required Count | Category Policy |
| :--- | :---: | :--- |
| `BEHAVIORAL_RISK` | 4 | `REQUIRED_PREREGISTERED_CORE` |
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

**Sum of Category Expected Counts**: `59` (Mechanically verified == `59`)

## 3. Two-Phase Non-Self-Referential Authorization Specification
- **Spec Version**: `3.3.0`
- **Target Run Label**: `baseline-v1`
- **Requested Model**: `gpt-5-mini`
- **Foundry Project Fingerprint**: `3f0c34d730680ad8baac11d2825e120045eb19be1d9ec1c0b2a2d337096ae33f`
- **Candidate Git SHA**: `` (empty string enforces no live calls on candidate commit)
- **Legacy `expected_git_sha`**: `REMOVED` (forbids legacy ambiguity in Gate 3)
- **Composite Source Bundle SHA256**: `95bb386b51d653c0a1834e1950634a9887b7cb6826b8c317a07c4b6a4167d060`
- **Source Manifest SHA256**: `daf28b3314199db8e31bfacdf2fb8441b54682caa7854ed288e1bc00866a1dd1`
- **Production Prompt SHA256**: `c14c476652a00f80365d5e681d133e741bc7e01812ae22e33109c4d70db68712`
- **Wire Schema SHA256**: `b3cca032a01ac0b5c567f0592bf231ca83e6b3d708dec8385b74b21d8b74ee77`

## 4. Parser Statement Coverage and Round 3 Grammar Support
- **Total Physical Lines**: `247`
- **Logical Statements Parsed**: `207`
- **Parsed and Scored Statements**: `118`
- **Recognized but Unscored Statements**: `89`
- **Unsupported Relevant Statements**: `0`
- **Fail-Closed Parser**: Only allowlisted constructs receive PARSED_AND_SCORED or RECOGNIZED_BUT_UNSCORED; all other statements fall through to UNSUPPORTED_RELEVANT and fail-closed early abort blocks execution with 0 calls.
- **Level-88 Losslessness**: Preserves condition values in RecordFieldFact; participates in declaration identity but has 0 storage bytes, excluded from byte offsets, and excluded from representation compatibility.
- **File Status Ownership & Official Wiring**: Owned by SELECT file binding. Wired into official evaluation runner: `SystemSupportIndex(facts, bundle, file_status_certificate=parser.file_status_certificate)`. Mandatory in official mode (raises RuntimeError if missing on MISSING_ERROR_STATUS).
- **Structural Binding Verification**: Binding identity resolved structurally via `affected_resource_evidence` matching `resource_span` and `operation_evidence` matching `operations_span`. Proposition-ID substring heuristics completely eliminated.
- **Generic File Operations**: WRITE statements resolve to owning FD and emit FileOperationFacts; evaluated under OPTIONAL_SUPPLEMENTARY policy.

## 5. Model Schema, Evaluator & Runner Integrity
- **18 Category Policies**: 13 REQUIRED_EXHAUSTIVE, 4 REQUIRED_PREREGISTERED_CORE, 1 OPTIONAL_SUPPLEMENTARY (FILE_OPERATION with 0 recall obligation, strict precision penalty).
- **Deterministic Behavioral Risk**: Scored on program_id, risk_category, risk_basis_kind, and impact_category; role-bound spans on operation and resource.
- **Structured Operation Sequence**: Scored with 4 role-bound spans (first_operation, second_operation, first_resource, second_resource).
- **Prompt Leakage Removed**: Replaced fixture-specific text with neutral temporal ordering instruction; verified prompt SHA256.
- **Version Contract Verification**: Preflight parses and verifies actual golden JSON `version == spec['golden_dataset_version']`, `SCHEMA_VERSION == spec['schema_version']`, `EVALUATOR_VERSION == spec['evaluator_version']`, and `PROMPT_VERSION == spec['prompt_version']`.
- **Runner Spec Git Object Plumbing**: Retrieves baseline spec from authorization commit A via `git show {A}:evals/baselines/gate-3-baseline-v1.json`; enforces canonical path, normalized 3.3.0 versions, clean diff C..A, and snapshot execution from C.
- **14 Immutable Artifacts**: Verified SHA256 preservation in `manifest.json`.
