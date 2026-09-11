# GATE 3 REMEDIATION ROUND 2 — EXECUTION AND AUDIT REPORT

**Generated mechanically from repository data without manual constants.**

## 1. Provenance and Repository State
- **Current Git HEAD**: `62a90531dc495bfe595a92cca280b7c42bfa2901`
- **Preserved Remote Anchor**: `364e334`
- **Legacy Repository Status**: `UNTOUCHED / CLEAN`
- **Gate 2 Artifacts Status**: `UNTOUCHED / CLEAN`
- **Live Calls Made**: `0`
- **Baseline Executions Run**: `0`

### Recent Forward Git Commits
```text
62a9053 docs(gate-3): add mechanically generated remediation round 2 audit report
239aa8c feat(gate-3): two-phase authorization, irrevocable reservation, and targeted regression suite
72843ce feat(gate-3): independent static golden dataset, schema leakage removal, and category policies
364e334 fix(gate-3): add type annotation to adversarial regressions test
1dec1ec feat(gate-3): implement authorization specification, responses api path, and runner hardening
fdb3fb5 feat(gate-3): real source-mutating counterfactuals and independent oracle tests
fbddbf6 feat(gate-3): rebuild golden dataset and independent semantic verifier
148ca4b feat(gate-3): generic ast parser and fact extractor with zero fixture identifiers
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
- **Spec Version**: `3.0.0`
- **Target Run Label**: `baseline-v1`
- **Requested Model**: `gpt-5-mini`
- **Foundry Project Fingerprint**: `3f0c34d730680ad8baac11d2825e120045eb19be1d9ec1c0b2a2d337096ae33f`
- **Candidate Git SHA (Candidate C)**: `` (empty string enforces no live calls on candidate commit C)
- **Composite Source Bundle SHA256**: `95bb386b51d653c0a1834e1950634a9887b7cb6826b8c317a07c4b6a4167d060`
- **Source Manifest SHA256**: `daf28b3314199db8e31bfacdf2fb8441b54682caa7854ed288e1bc00866a1dd1`
- **Production Prompt SHA256**: `10f6d119d1fab30aecd16ee3c8e9bf33c477947496215d58c452063cc1db818f`
- **Wire Schema SHA256**: `286de267d2dc51c290c940fc20c91b7be4e2da4c1bf24d20939c4522988b3a88`

## 4. Parser Statement Coverage and Dynamic Offsets
- **Total Physical Lines**: `247`
- **Logical Statements Parsed**: `208`
- **Parsed and Scored Statements**: `115`
- **Recognized but Unscored Statements**: `93`
- **Unsupported Relevant Statements**: `0`
- **Zero Fixture Assumptions**: Removed `or 'ACCOUNTS'`, `record[:10]`, `record[40:55]`, and `'BAL'` substring checks. Dynamic AST picture parsing (`parse_cobol_picture`) adapts to mutated copybook layouts.
- **Non-Atomic Update Consequence**: Qualified to `CANONICAL_DATASET_UNAVAILABLE` (eliminated `PERMANENT_DATA_LOSS`).

## 5. Model Schema & Wire Integrity
- **Duplicate Collection Removed**: Removed `programs`; retained single canonical `program_declarations`.
- **Answer Leakage Removed**: Replaced specific fixture hints in `risk_category` with generic taxonomy (`IO_ERROR_HANDLING`, `DATA_INTEGRITY`, `CONTROL_FLOW`, `PORTABILITY`, `RESOURCE_LIFECYCLE`).
- **Irrevocable Reservation**: Enforced atomic exclusive directory creation and fail-closed re-entry on `RESERVED`, `MODEL_INVOCATION`, `FAILED`, and `COMPLETED`.
- **Preflight Identity Checks**: Enforced preflight verification of model and endpoint fingerprint before `MODEL_INVOCATION` write.
- **14 Immutable Artifacts**: Verified SHA256 preservation in `manifest.json`.
