# Gate 2 — COBOL Reader — Evidence

## Status: V1_REPORTED_PASS / V2_PENDING

> [!IMPORTANT]
> **Status Clarification & Candidate Versioning:**
> - **BASELINE V1** reported `PASS` under legacy Evaluator `v1.1.0` on 2026-09-06.
> - Two successive independent adversarial reviews (Audits 1 & 2) identified critical correctness and soundness vulnerabilities across the schema, parser, evidence validator, evaluator core, agent, and runner.
> - BASELINE V1 remains preserved immutable historical experimental evidence.
> - Candidate Version: `schema_version = 2.1.0`, `evaluator_version = 2.1.0`, `prompt_version = gate2-baseline-v2.1`.
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
- `bank-main-assessment.json`: SHA256 `062f689e47225c56cba0285a4cf131e50889c25f46bb101d2ec75727918a22bc`
- `evaluation.json`: SHA256 `b19326e0e3b97b09ca66432657e05fc8aa107b1d9df50e5ebf89998ea38a6a68`
- `run-metadata.json`: SHA256 `d4bb0f86b4028045a557342629b3ae3d29252bcfe2ea012eeb8ff569ee8ee496`
- `assessment-schema.json`: SHA256 `5bb919d7d130a84e4f7fc46c0a0c4ec3efc21115cc49c25e8a5b2829ec37ea81`

Sanitized copies are maintained under `evals/observed/gate-2-baseline-v1-assessment.json` and `evals/observed/gate-2-baseline-v1-metadata.json`.

---

## 2. Second Adversarial Review Findings (R1–R14) & Remediation

A second adversarial audit examined Candidate V2.0 and identified 14 vulnerabilities, all remediated in Candidate V2.1:

| ID | Finding Description | Remediation in V2.1 |
|---|---|---|
| **R1** | Multiplicity contradiction: multi-valued relations (CALL, DISPLAY) were grouped together, making PASS mathematically impossible. | Redesigned `contradiction_group_key` in `src/cobol/atomic_facts.py`: returns `None` for multi-valued relations so distinct CALLs coexist. Only single-valued facts (PROGRAM, menu branches, variable declarations) trigger contradiction checks. |
| **R2** | Evaluator mutated input assessment instances in place. | Evaluator V2.1 performs read-only conversions to `PredictedFact` and never modifies model assessment instances. |
| **R3** | Universal normalization applied unstructured token collapse across disparate types. | Type-aware normalization functions implemented: `normalize_identifier`, `normalize_pic`, `normalize_string_literal`, `normalize_condition`. |
| **R4** | `SourceSupportOracle` hardcoded BANK-MAIN answer maps (lines, targets, branches). | Replaced with deterministic subset COBOL parser `SourceFactExtractor` and `SourceSupportIndex`; zero hardcoded answer tokens remain. |
| **R5** | Token overlap validation allowed partial token hits. | Strict substring containment and verbatim fragment checking enforced in `EvidenceValidator`. |
| **R6** | Permissive git provenance allowed dirty worktrees in baseline runs via environment bypass. | Baseline runs strictly reject `GATE2_ALLOW_DIRTY_WORKTREE`, require exact commit SHA matching, and verify working tree files against `git show HEAD:<path>`. |
| **R7** | Error handling persisted raw exceptions, potentially leaking API keys, tokens, or endpoints into `run-state.json`. | Allowlist-only error persistence implemented in `write_failure_run_state`; only status, phase, error_type, safe_message, timestamp, git_sha written. |
| **R8** | Weak Responses API validation allowed non-completed or truncated agent outputs. | Agent requires strict `status == "completed"` and verifies `output_parsed` is an instance of `LegacyAssessment`. |
| **R9** | V1 rescore adapter performed answer substitutions and repairs. | Rebuilt `src/validation/v1_rescore.py` without substitutions; claims mapped faithfully. |
| **R10** | Dependencies were unlocked, risking drift. | Frozen exact `requirements-lock.txt` created and verified with `pip check`; lockfile hash recorded in metadata. |
| **R11** | Magic constants used for evidence span tolerance. | Replaced with occurrence-derived dynamic spans (`occurrence_span_length + 2`). |
| **R12** | Fabricated negative copy lines in host verification. | Entire file range `[1, total_lines]` used for whole-file absence assertion without fabricated line text. |
| **R13** | Dry-run reserved run directories and created empty folders. | Dry-run exits cleanly after preflight without creating artifact directory. |
| **R14** | Unhandled post-model exceptions left run state permanently in `STARTED`. | Strict phase tracking and allowlist failure persistence ensures run state transitions to `FAILED`. |

---

## 3. The 5 Required Amendments (Approved for V2.1)

1. **Amendment 1: Discriminated Schema Variants**
   - Eliminated generic multi-purpose control and action containers.
   - `MenuOption`: Discriminated union of `CallMenuOption` (`action_type: "CALL"`, `target_program: str`) and `DisplayMenuOption` (`action_type: "DISPLAY"`, `literal: str`). Structurally prevents CALLs without targets or DISPLAYs with CALL targets.
   - `ControlFlowConstruct`: Discriminated union of `PerformUntilConstruct` (`construct_type: "PERFORM_UNTIL"`), `EvaluateConstruct` (`construct_type: "EVALUATE"`), and `StopRunConstruct` (`construct_type: "STOP_RUN"`).
   - `IOOperation`: Discriminated union of `AcceptIO` (`operation_type: "ACCEPT"`) and `DisplayIO` (`operation_type: "DISPLAY"`).

2. **Amendment 2: Fail-Closed Source Parsing**
   - `SourceFactExtractor` tracks `parse_complete: bool`, `unsupported_statement_count: int`, and `unsupported_statements: list[str]`.
   - Ambiguous or malformed syntax (e.g. unrecognizable COPY or branch syntax) marks `parse_complete = False`.
   - If parsing is incomplete, authoritative negative absence facts (such as COPY dependency count = 0) are strictly suppressed, preventing invalid Gate 2 PASS.

3. **Amendment 3: Strengthened Baseline Git/Execution Provenance**
   - Baseline runs prohibit `GATE2_ALLOW_DIRTY_WORKTREE`.
   - Baseline runs reject non-empty `PYTHONPATH` and non-empty `PYTHONHOME`.
   - For all benchmark-critical files (runner, agent, prompt, schemas, extractor, support index, evaluators, golden dataset, source fixture, lockfile), the runner computes SHA256 of the working tree file and compares it against `git show HEAD:<path>`. Any discrepancy aborts before artifact reservation or model invocation.

4. **Amendment 4: Allowlist-Based Error Artifacts**
   - Artifact safety in `run-state.json` relies strictly on allowlisted fields (`status`, `failed_phase`, `error_type`, `safe_message`, `timestamp`, `git_sha`).
   - Raw exception strings, SDK response representations, endpoint URLs, authorization headers, and local directory paths are never written to disk artifacts.
   - Verified with adversarial test cases injecting synthetic API keys and bearer tokens.

5. **Amendment 5: Reconstructable Environment Capture**
   - Generated exact `requirements-lock.txt` for the WSL Python 3.12.3 virtual environment.
   - Pinned exact versions: `openai==3.8.0`, `azure-ai-projects==2.6.0`, `azure-identity==1.25.3`, `pydantic==2.13.5`, `pydantic-settings==2.15.0`.
   - All quality checks (`pytest`, `ruff`, `mypy`, `pip check`) executed from the identical virtual environment intended for BASELINE V2.

---

## 4. Historical Baseline V1 Offline Rescore with Evaluator V2.1

Using the rebuilt unadulterated V1 rescore adapter (`src/validation/v1_rescore.py`), the historical Baseline V1 output was evaluated against the V2.1 evaluator core and golden dataset V2.1:

- **Report Path:** `evals/results/gate-2-v1-rescored-with-v2.1.json`
- **Total Historical Predictions Converted:** 24
- **Supported Predicted Facts:** 23
- **Unsupported Predicted Facts:** 1
- **Invalid Evidence:** 1 (`data.ws_choice` cited lines 7..9, including line 6 `DATA DIVISION.`)
- **Expected Facts (V2.1):** 15
- **Matched Expected Facts:** 14 / 15
- **Missing Expected Facts:** 1 (`data.ws_choice`)
- **Precision:** 0.9583 (23/24)
- **Recall:** 0.9333 (14/15)
- **Gate 2 Result under V2.1:** **FAIL** (`gate_2_pass: false`)

---

## 5. Quality Gate Verification Status

All checks executed in the WSL Ubuntu 24.04 environment (`.venv` Python 3.12.3):

| Tool / Suite | Status | Details |
|---|---|---|
| `pytest` | **PASS (67/67)** | 100% offline tests passing across unit, adversarial regressions, V1 compatibility, and source mutations |
| Adversarial Regressions | **PASS (30/30)** | Explicit deterministic tests for R1–R14 and Amendments 1–5 in `evals/tests/test_adversarial_regressions.py` |
| Source Mutation Suite | **PASS (10/10)** | In-memory source mutation tests proving the extractor and evaluator dynamically track code changes |
| Mandatory Positive Invariant | **PASS** | `make_perfect_assessment_v2()` -> Precision 1.0, Recall 1.0, 0 unsupp, 0 inv_ev, 0 dup, 0 cont, `gate_2_pass: True` |
| `ruff check .` | **PASS** | 0 lint errors |
| `ruff format --check .` | **PASS** | 35 files formatted and compliant |
| `mypy src agents scripts tests evals` | **PASS** | 0 issues found in 26 source files |
| `pip check` | **PASS** | No broken requirements found |
| Legacy Immutability | **PASS** | `git diff -- legacy/core-banking-system/` is strictly empty; SHA256 `b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028` |

---

## 6. Next Steps & Gate 2 Validation Path

1. **Commit & Push:** Commit logical changes on `feat/gate-2-cobol-reader` and push to origin.
2. **Update PR #1:** Update PR description via GitHub CLI to reflect Candidate V2.1 status and readiness for Third Adversarial Review.
3. **Execution of Baseline V2 (Future Session):** Once authorized by human review, execute `python scripts/run-gate-2.py --run-label baseline-v2 --expected-git-sha <COMMIT_SHA>` with clean worktree.
4. **Gate 3 Unblock:** Gate 3 remains blocked until BASELINE V2 achieves a verified PASS under Evaluator V2.1 rules.
