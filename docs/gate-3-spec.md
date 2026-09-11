# Gate 3 Specification: Multi-File COBOL System Understanding & Architectural Analysis

## 1. Executive Summary & Gate 3 Objectives

Gate 3 elevates the modernization pipeline from single-program unit reading (Gate 2: `BANK-MAIN.CBL`) to full multi-file legacy system understanding. The target application is an IBM Enterprise / Micro Focus compatible core banking system comprising 4 executable COBOL programs, 1 shared copybook definition, and 1 sequential data file (6 files total, 247 physical source lines).

The primary objective of Gate 3 is to prove that an agentic legacy analyzer can reliably ingest a complete multi-source legacy bundle and synthesize an end-to-end architectural, dataflow, control-flow, and behavioral risk assessment. The assessment is evaluated strictly against a 54-unit canonical golden proposition dataset using deterministic, AST-grounded, host-derived verification with zero reliance on fuzzy or LLM-based evaluators.

---

## 2. Target System Bundle Inventory

The legacy core banking system is located under `legacy/core-banking-system/`. All files are immutable upstream artifacts.

| File Name | File Type | Physical Lines | SHA256 Hash | System Role |
|---|---|---|---|---|
| `BANK-MAIN.CBL` | COBOL Program | 36 | `b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028` | Main dispatch menu, user interactive loop, subprogram caller |
| `INIT-DB.CBL` | COBOL Program | 46 | `cb3f48653ca265d6fe620714ee88185c7c13a013914a84d47c21ae9320e85ff7` | Database/file initializer, initial account record population |
| `TRANS-PROC.CBL` | COBOL Program | 96 | `8295b9c0fb925f6f43708a38a9d1bbad5b83938be830d984cfb77626964efc77` | Transaction processor (deposits, withdrawals, balance calculations) |
| `REPORT-GEN.CBL` | COBOL Program | 57 | `a7fa76251bdf858ff40e8fe3fc8bb8eb1895a5fbc40d6c5bb5d2eb7b243be8dc` | Account audit and balance report generator |
| `ACCOUNTS.CPY` | Copybook | 9 | `5eb747e92383c2763f6834468f0cb6ee7c191a32997aa774bf79d8c3683a48e7` | Shared account record schema (`ACCOUNT-RECORD`, fields, PICTURE clauses) |
| `ACCOUNTS.DAT` | Sequential Data | 3 | `b1c5b8b9826d0ba480a8f8e025ec1ff5fcbcadba1a5e1cf3e7fcb9a07172fa82` | Test data fixture containing seed account records |

**Total Physical Lines:** 247 lines.

---

## 3. Isolated 3-Tier Parser Architecture & Coverage Certificate

The Gate 3 COBOL parsing engine operates in total isolation from external network dependencies. It evaluates the entire six-file bundle through a 3-tier analysis model:

### 3.1 Three Analysis Tiers

- **Tier 1: Intra-Program Structural Facts**
  Extracts program identifiers, division/section boundaries, file control paragraphs (`SELECT ... ASSIGN`), file descriptions (`FD`), copybook inclusions (`COPY`), working-storage records, and program entry points.
- **Tier 2: Intra-Procedural Logic & Control Flow**
  Parses procedural paragraphs, statement sequences, conditional branches (`IF / ELSE / END-IF`, `EVALUATE / WHEN / END-EVALUATE`), iterative loops (`PERFORM UNTIL ...`), arithmetic computations (`ADD`, `SUBTRACT`, `COMPUTE`), file I/O operations (`OPEN`, `READ`, `WRITE`, `CLOSE`), interactive console I/O (`DISPLAY`, `ACCEPT`), and run-unit termination (`STOP RUN`, `EXIT PROGRAM`, `GOBACK`).
- **Tier 3: Inter-Program & System-Wide Relationships**
  Synthesizes cross-program call graphs (`CALL 'INIT-DB'`, `CALL 'TRANS-PROC'`, `CALL 'REPORT-GEN'`), shared dataflow and record mutations (movement between `ACCOUNT-REC` and `TEMP-REC`), file lifecycle protocols across programs, and system-level behavioral/architectural risks (e.g., missing status code checks on file I/O, unvalidated user input, unbounded loops).

### 3.2 Parser Statement Classification System

Every physical source line in the COBOL bundle is systematically classified without omissions:
1. **`PARSED_AND_SCORED`**: The statement is fully parsed into AST nodes and directly supports one or more golden propositions.
2. **`RECOGNIZED_BUT_UNSCORED`**: The statement is recognized by the grammar as valid COBOL syntax present in the system, but does not directly map to a scored golden proposition.
3. **`UNSUPPORTED_RELEVANT`**: The statement represents relevant application logic that the parser cannot recognize or classify. Any statement falling into this category immediately triggers `EVALUATION_BLOCKED` and halts verification.

### 3.3 Parser Coverage Certificate

The parser computes and emits an immutable `ParserCoverageCertificate` containing:
- `physical_line_count`: Total physical lines across all six files (247).
- `blank_line_count`: Count of blank lines.
- `comment_line_count`: Count of COBOL comment lines (indicator column `*`).
- `data_fixture_line_count`: Count of raw data lines in `ACCOUNTS.DAT`.
- `logical_statement_count`: Total logical COBOL statements identified across all programs and copybooks.
- `parsed_and_scored_count`: Statements mapped to scored golden propositions.
- `recognized_but_unscored_count`: Valid COBOL statements recognized but not scored.
- `unsupported_relevant_count`: Must be strictly `0`.
- `per_statement_classifications`: Full statement-by-statement classification map with file, line range, verb, and category.

---

## 4. Canonical Golden Proposition Inventory (54 Units)

The golden dataset consists of exactly 54 atomic propositions categorized into 14 functional groups. The recall denominator is dynamically derived: $\sum_{i=1}^{14} \text{group\_count}_i = 54$.

### Summary of Groups and Propositions

| Group ID | Functional Group Name | Proposition Count |
|---|---|---|
| 1 | Architecture & Component Topology | 4 |
| 2 | Cross-Program Invocations & Dispatching | 6 |
| 3 | Shared Copybook Inclusion & Layout Grounding | 3 |
| 4 | Cross-Program Data Transfer & Record Mapping | 4 |
| 5 | Shared File Lifecycle Operations | 4 |
| 6 | Control Flow Topology & Paragraph Sequences | 5 |
| 7 | Arithmetic Operations & Computation Sequences | 7 |
| 8 | Conditional Branching & Evaluation Predicates | 4 |
| 9 | Interactive I/O Operations | 3 |
| 10 | Run-Unit Termination Semantics | 3 |
| 11 | Behavioral Risks & Edge Cases | 4 |
| 12 | System-Level Architectural Risks | 3 |
| 13 | In-Memory Working Storage State & Flags | 3 |
| 14 | Cross-File Transaction Processing Protocol | 1 |
| **Total** | **All 14 Groups** | **54** |

### Complete 54-Proposition Catalog

```
Group 1: Architecture & Component Topology (4 units)
- prop.arch.bank_main: Program BANK-MAIN serves as root orchestrator.
- prop.arch.init_db: Program INIT-DB initializes sequential account database.
- prop.arch.trans_proc: Program TRANS-PROC executes credit and debit transactions.
- prop.arch.report_gen: Program REPORT-GEN produces formatted account summary reports.

Group 2: Cross-Program Invocations & Dispatching (6 units)
- prop.call.main_calls_init: BANK-MAIN invokes INIT-DB via dynamic CALL literal.
- prop.call.main_calls_trans: BANK-MAIN invokes TRANS-PROC via dynamic CALL literal.
- prop.call.main_calls_report: BANK-MAIN invokes REPORT-GEN via dynamic CALL literal.
- prop.dispatch.menu_opt_1: Option '1' in BANK-MAIN dispatches to INIT-DB.
- prop.dispatch.menu_opt_2: Option '2' in BANK-MAIN dispatches to TRANS-PROC.
- prop.dispatch.menu_opt_3: Option '3' in BANK-MAIN dispatches to REPORT-GEN.

Group 3: Shared Copybook Inclusion & Layout Grounding (3 units)
- prop.copy.trans_proc_includes_cpy: TRANS-PROC includes ACCOUNTS.CPY.
- prop.copy.report_gen_includes_cpy: REPORT-GEN includes ACCOUNTS.CPY.
- prop.copy.layout_acc_balance_comp3: Copybook defines ACC-BALANCE as PIC S9(13)V99 COMP-3.

Group 4: Cross-Program Data Transfer & Record Mapping (4 units)
- prop.transfer.init_rec_write: INIT-DB populates and writes INIT-ACCOUNT-RECORD to ACCOUNT-FILE.
- prop.transfer.rec_to_tmp: TRANS-PROC moves ACCOUNT-REC into TEMP-REC working storage.
- prop.transfer.tmp_to_rec: TRANS-PROC moves updated TEMP-REC back to ACCOUNT-REC before rewriting.
- prop.transfer.rep_rec_read: REPORT-GEN reads ACCOUNT-REC into audit accumulation buffer.

Group 5: Shared File Lifecycle Operations (4 units)
- prop.lifecycle.init_output: INIT-DB opens ACCOUNT-FILE in OUTPUT mode and closes upon completion.
- prop.lifecycle.trans_account_read: TRANS-PROC opens ACCOUNT-FILE in I-O mode, reads sequentially, and closes.
- prop.lifecycle.trans_temp_output: TRANS-PROC manages temporary work file lifecycle (OPEN OUTPUT/CLOSE).
- prop.lifecycle.report_input: REPORT-GEN opens ACCOUNT-FILE in INPUT mode and closes upon EOF.

Group 6: Control Flow Topology & Paragraph Sequences (5 units)
- prop.flow.main_loop: BANK-MAIN executes main dispatch loop UNTIL WS-CHOICE = '4'.
- prop.flow.trans_loop: TRANS-PROC processes transactions in a sequential loop UNTIL EOF-FLAG = 'Y'.
- prop.flow.report_loop: REPORT-GEN iterates through account records UNTIL WS-EOF-FLAG = 'Y'.
- prop.flow.main_evaluate: BANK-MAIN evaluates user choice using EVALUATE WS-CHOICE construct.
- prop.flow.trans_evaluate: TRANS-PROC branches on transaction type using EVALUATE TR-TYPE construct.

Group 7: Arithmetic Operations & Computation Sequences (7 units)
- prop.math.deposit_add: TRANS-PROC adds transaction amount to account balance for credit/deposit.
- prop.math.withdrawal_sub: TRANS-PROC subtracts transaction amount from account balance for debit.
- prop.math.trans_counter_add: TRANS-PROC increments transaction count counter by 1.
- prop.math.rep_total_add: REPORT-GEN accumulates account balance into system grand total.
- prop.math.rep_count_add: REPORT-GEN increments total active accounts counter by 1.
- prop.math.rep_deposit_tot: REPORT-GEN sums total deposited volume across processed records.
- prop.math.rep_withdraw_tot: REPORT-GEN sums total withdrawn volume across processed records.

Group 8: Conditional Branching & Evaluation Predicates (4 units)
- prop.branch.nsf_check: TRANS-PROC validates sufficient funds before applying debit (balance >= amount).
- prop.branch.invalid_menu: BANK-MAIN handles WHEN OTHER with invalid option error notification.
- prop.branch.invalid_tx_type: TRANS-PROC handles unrecognized transaction types in WHEN OTHER.
- prop.branch.eof_condition: REPORT-GEN checks for AT END condition on sequential file read.

Group 9: Interactive I/O Operations (3 units)
- prop.io.main_menu_display: BANK-MAIN displays interactive selection menu to stdout.
- prop.io.main_choice_accept: BANK-MAIN accepts user option from stdin into WS-CHOICE.
- prop.io.report_summary_display: REPORT-GEN outputs formatted audit report headers and totals.

Group 10: Run-Unit Termination Semantics (3 units)
- prop.term.main_stop_run: BANK-MAIN executes STOP RUN upon exit option selection.
- prop.term.sub_exit_init: INIT-DB exits back to caller via EXIT PROGRAM / GOBACK.
- prop.term.sub_exit_trans: TRANS-PROC exits back to caller via EXIT PROGRAM / GOBACK.

Group 11: Behavioral Risks & Edge Cases (4 units)
- prop.risk.missing_file_status: Programs omit FILE STATUS clause, creating silent I/O failure risk.
- prop.risk.comp3_unpack_overflow: High-volume conversions risk arithmetic overflow on packed decimals.
- prop.risk.unvalidated_menu_input: ACCEPT WS-CHOICE accepts unvalidated characters before evaluation.
- prop.risk.concurrent_file_access: Multiple subprograms open ACCOUNT-FILE sequentially without shared lock.

Group 12: System-Level Architectural Risks (3 units)
- prop.risk.monolithic_coupling: Programs tightly coupled through hardcoded CALL program literals.
- prop.risk.stateful_file_dependence: System relies on local filesystem persistence without transactional rollback.
- prop.risk.unhandled_eof_trans: TRANS-PROC behavior under unexpected empty file condition.

Group 13: In-Memory Working Storage State & Flags (3 units)
- prop.state.main_ws_choice: BANK-MAIN maintains menu selection state in WS-CHOICE PIC X(1).
- prop.state.trans_eof_flag: TRANS-PROC maintains sequential file status in EOF-FLAG PIC X(1).
- prop.state.rep_totals_buffer: REPORT-GEN maintains grand totals in working-storage accumulator fields.

Group 14: Cross-File Transaction Processing Protocol (1 unit)
- prop.protocol.e2e_lifecycle: System executes full end-to-end cycle: Initialize DB -> Process Transactions -> Generate Audit Report.
```

---

## 5. Neutral Model-Visible Wire Schema & Prompt Strategy

### 5.1 Neutral Model-Visible Schema

The model-visible schema defines only objective domain and program-analysis abstractions. It completely excludes benchmark-specific identifiers, golden fact keys, and test group indicators:

- `SystemAssessment`: Root container for multi-file system analysis.
- `SystemComponent`: Identified component/program, primary responsibility, and entry point.
- `CrossProgramInvocation`: Caller, callee, call mechanism (CALL literal), parameters passed.
- `SharedDataStructure`: Shared copybook name, record name, and declared fields.
- `ResourceLifecycle`: Resource/file name, declared program, access mode, and operation sequence (`OPEN`, `READ`, `WRITE`, `CLOSE`).
- `DataFlowTransfer`: Source data structure, target data structure, transfer verb (`MOVE`), context.
- `ControlFlowConstruct`: Program, construct type (`LOOP`, `EVALUATE`, `IF`), exit predicate / condition.
- `ComputationStep`: Program, arithmetic verb (`ADD`, `SUBTRACT`), target field, operand.
- `BehavioralRisk`: Program, risk category, precondition, ordered operations, consequence, severity.
- `ArchitecturalPattern`: System-level pattern or risk description, affected components, migration impact.
- `SourceEvidence`: Line coordinates (`file_path`, `line_start`, `line_end`). No model-emitted snippets.

### 5.2 Deterministic Verification Guardrails (Guardrail A)

In strict accordance with Guardrail A:
- **No Fuzzy/NLP/LLM Evaluation:** All evaluations are 100% deterministic and AST-grounded.
- **Canonical Normalization:** Semantic strings (operations, resource names, verbs, predicates) undergo canonical normalization (case-folding, whitespace collapsing, keyword canonicalization) and exact set/sequence comparison.
- **Explicit Lifecycle & Transfer Semantics (Guardrail B):** `prop.lifecycle.trans_account_read` verifies the actual `["OPEN", "READ", "CLOSE"]` lifecycle on `ACCOUNT-FILE` in `TRANS-PROC.CBL`. `prop.transfer.rec_to_tmp` verifies the explicit record movement from `ACCOUNT-REC` to `TEMP-REC`.

---

## 6. Counterfactual Matrix (CF-01 through CF-08)

The system verification suite includes an adversarial counterfactual matrix designed to test sensitivity to deliberate mutations in code, architecture, and data representation:

| ID | Mutation Target | Injected Mutation Description | Expected Evaluator Response |
|---|---|---|---|
| **CF-01** | `BANK-MAIN.CBL` | Remove `CALL 'TRANS-PROC'` invocation | Drops Group 2 Recall; rejects cross-program call assertions |
| **CF-02** | `ACCOUNTS.CPY` | Mutate `ACC-BALANCE PIC S9(13)V99 COMP-3` to DISPLAY (representation only, name unchanged) | Detects representation mutation; rejects COMP-3 proposition |
| **CF-03** | `INIT-DB.CBL` | Invert file open mode from `OUTPUT` to `INPUT` | Fails Group 5 lifecycle verification |
| **CF-04** | `TRANS-PROC.CBL` | Invert NSF condition (`<` instead of `>=`) | Detects business logic mutation in Group 8 |
| **CF-05** | `REPORT-GEN.CBL` | Remove balance accumulation (`ADD ACC-BALANCE TO ...`) | Fails arithmetic verification in Group 7 |
| **CF-06** | System Topology | Delete `ACCOUNTS.CPY` copybook reference | Fails shared copybook inclusion verification |
| **CF-07** | Control Flow | Remove `UNTIL WS-CHOICE = '4'` loop termination | Detects unbounded loop risk in Group 6/11 |
| **CF-08** | File Status | Add explicit `FILE STATUS IS WS-STATUS` clause | Rejects `prop.risk.missing_file_status` assertion |

---

## 7. Quality Gate Verification Criteria

Gate 3 offline evaluation requires:
1. `pytest`: 100% pass across all test suites (Gate 2 regressions + Gate 3 new suites).
2. `ParserCoverageCertificate`: 100% of physical lines classified; `unsupported_relevant_count == 0`.
3. Golden Proposition Recall: 54 / 54 (100%) against synthetic perfect assessment.
4. Precision: 1.0 against ground-truth source support index.
5. Counterfactual Sensitivity: 100% detection rate across all 8 counterfactual mutations.
6. Static Analysis: `ruff check .` = 0 errors, `ruff format --check .` = clean, `mypy` = 0 errors, `pip check` = clean.
7. Zero Live Calls: Zero requests to Azure AI Foundry, OpenAI, or external endpoints.
