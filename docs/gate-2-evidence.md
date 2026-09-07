# Gate 2 — COBOL Reader — Evidence

## Result: PASS

| Field | Value |
|---|---|
| Date | 2026-09-06 |
| Environment | WSL (Ubuntu 24.04), Python 3.12.3 |
| Git Commit SHA | `7bdec2b28c4f23cd16911532de15f2644a57f0fe` |
| Target File | `legacy/core-banking-system/BANK-MAIN.CBL` |
| Source SHA256 | `b03adc9592f2853006263ef67fcc6dc716b99333b84bc0198bff7b7f0af1a028` |
| Model Deployment | `gpt-5-mini` |
| Model Version | `2025-08-07` |
| Contract API | OpenAI Responses API Structured Outputs (`responses.parse`) |
| Reasoning Effort | `low` |
| Schema Version | `1.0.0` |
| Prompt Version | `gate2-baseline-v1` |
| Evaluator Version | `1.1.0` |
| Run Label | `baseline-v1` |
| Logical Endpoint | `https://<foundry-resource-endpoint>.services.ai.azure.com` |
| Response ID | `<response-id>` |
| Elapsed Time | 32.78s |
| Input Tokens | 3,738 |
| Output Tokens | 3,218 (includes reasoning and output tokens) |
| Total Tokens | 6,956 |
| Execution Policy | One logical model invocation, with no application-level semantic retry; SDK retained default transport retry policy (`max_retries = 2`) |

> **Repository Hygiene & Privacy Note:** The live Azure AI Foundry resource endpoint, server-side Response ID, and subscription identifiers have been replaced with placeholders (`<foundry-resource-endpoint>`, `<response-id>`, `<subscription-id>`) for repository hygiene and infrastructure privacy. Access requires Microsoft Entra ID authentication and Azure RBAC authorization.

---

## Tooling & Static Verification Status

In accordance with benchmark reporting standards:

| Tool / Check | Status | Details |
|---|---|---|
| `mypy` | **NOT_RUN / NOT_INSTALLED** | Static type checker not installed in environment; no claim of mypy runtime type-checking |
| Pydantic v2 validation | **ACTIVE** | Full runtime schema enforcement (`LegacyAssessment`, strict `extra="forbid"`) |
| Python type annotations | **PRESENT** | Type hints present across all agent, parser, and evaluation modules |
| `pytest` | **PASS** | 25/25 unit & evaluation tests passing (100% offline test suite) |
| `ruff` | **PASS** | 0 linting or formatting violations |

---

## Deterministic Evaluation Results

| Metric | Target / Threshold | Measured | Result |
|---|---|---|---|
| `schema_valid` | `true` | `true` | **PASS** |
| `scope_valid` | `true` | `true` | **PASS** |
| `source_sha256_match` | `true` | `true` | **PASS** |
| `evidence_valid` | `true` | `true` | **PASS** |
| `invalid_evidence_count` | `0` | `0` | **PASS** |
| True Positives (TP) | — | `15` | — |
| False Positives (FP) | — | `0` | — |
| False Negatives (FN) | — | `0` | — |
| Precision | — | `1.0` (100.0%) | **PASS** |
| Recall | >= 0.90 | `1.0` (100.0%) | **PASS** |
| Expected Golden Facts | `15` | `15` | **PASS** |
| Matched Golden Facts | `15` | `15` | **PASS** |
| Missing Golden Facts | `0` | `0` | **PASS** |
| Unsupported / Invented Facts | `0` | `0` | **PASS** |
| Prohibited Rule Violations | `0` | `0` | **PASS** |

---

## Line-Number Consistency Audit & Fact Verification Breakdown

Physical line numbers in `legacy/core-banking-system/BANK-MAIN.CBL` are 1-indexed (lines 1 to 36, counting blank lines).

All three representations (Physical Source, Golden Dataset, and Model-produced `SourceEvidence`) use the same physical line contract. The table below correlates the physical source lines, the golden dataset expectations, and the model's exact cited evidence spans:

| Fact ID | Category | Physical Source Range | Golden Dataset Range | Model Evidence Range | Alignment & Verbatim Snippet Match |
|---|---|---|---|---|---|
| `program.id` | Program | `0001..0002` | `0002` | `0001..0002` | **MATCH (Valid)**: Model cited enclosing header: `IDENTIFICATION DIVISION.\nPROGRAM-ID. BANK-MAIN.` |
| `data.ws_choice` | Data Fields | `0008` | `0008` | `0007..0009` | **MATCH (Valid)**: Model cited enclosing section: `DATA DIVISION.\nWORKING-STORAGE SECTION.\n01 WS-CHOICE  PIC X.` |
| `control.perform_loop` | Control Flow | `0012..0034` | `0012` | `0012..0034` | **MATCH (Valid)**: Model cited full loop block: `PERFORM UNTIL WS-CHOICE = '4'\n    ...\nEND-PERFORM.` |
| `io.accept_choice` | I/O | `0020` | `0020` | `0020` | **MATCH (Valid)**: Exact line match: `ACCEPT WS-CHOICE` |
| `control.evaluate_choice` | Control Flow | `0022..0033` | `0022` | `0022..0033` | **MATCH (Valid)**: Model cited full evaluate block: `EVALUATE WS-CHOICE\n    ...\nEND-EVALUATE` |
| `call.init_db` | Calls | `0024` | `0024` | `0024` | **MATCH (Valid)**: Exact line match: `CALL 'INIT-DB'` |
| `call.trans_proc` | Calls | `0026` | `0026` | `0026` | **MATCH (Valid)**: Exact line match: `CALL 'TRANS-PROC'` |
| `call.report_gen` | Calls | `0028` | `0028` | `0028` | **MATCH (Valid)**: Exact line match: `CALL 'REPORT-GEN'` |
| `menu.option_1` | Menu Options | `0023..0024` | `0023..0024` | `0015..0024` | **MATCH (Valid)**: Model cited from menu display to call: `DISPLAY '1. Init Database'\n...\nWHEN '1'\n     CALL 'INIT-DB'` |
| `menu.option_2` | Menu Options | `0025..0026` | `0025..0026` | `0016..0026` | **MATCH (Valid)**: Model cited from menu display to call: `DISPLAY '2. Transaction'\n...\nWHEN '2'\n     CALL 'TRANS-PROC'` |
| `menu.option_3` | Menu Options | `0027..0028` | `0027..0028` | `0017..0028` | **MATCH (Valid)**: Model cited from menu display to call: `DISPLAY '3. Report'\n...\nWHEN '3'\n     CALL 'REPORT-GEN'` |
| `menu.option_4` | Menu Options | `0029..0030` | `0029..0030` | `0018..0030` | **MATCH (Valid)**: Model cited from menu display to exit: `DISPLAY '4. Exit'\n...\nWHEN '4'\n     DISPLAY 'Bye.'` |
| `menu.option_other` | Menu Options | `0031..0032` | `0031..0032` | `0031..0032` | **MATCH (Valid)**: Exact line match: `WHEN OTHER\n     DISPLAY 'Invalid.'` |
| `control.stop_run` | Control Flow | `0036` | `0036` | `0036` | **MATCH (Valid)**: Exact line match: `STOP RUN.` |
| `dependency.no_copybooks` | Negative Fact | `0001..0036` | `0001..0036` | `N/A` | **MATCH (Valid)**: Whole file audited; 0 `COPY` statements confirmed |

### Missing Golden Facts (FN)
*None (0)*. All 15 golden facts were matched.

### False Positives & Unsupported Predicted Facts (FP)
*None (0)*. All predicted atomic statements mapped directly to valid facts in the source file. No hallucinated fields, CALL targets, or menu options were introduced.

### Invalid Evidence Items
*None (0)*. All 27 model-produced `SourceEvidence` items strictly validate against physical source lines with 0 line range or snippet mismatches.

### Scope & Prohibited Rule Violations
*None (0)*. The agent strictly adhered to single-file boundary isolation. Unanalyzed callee behaviors (`INIT-DB`, `TRANS-PROC`, `REPORT-GEN`) were properly recorded in `unsupported_assumptions` as unknown external contracts, rather than affirmative hallucinated statements.

---

## Execution Provenance & Artifacts

All raw execution files are preserved immutably in `artifacts/gate-2/baseline-v1/` (git-ignored):
- `bank-main-assessment.json`: Full Pydantic v2 structured output from model.
- `run-metadata.json`: Machine-readable execution and token consumption record.
- `assessment-schema.json`: JSON Schema exported from `LegacyAssessment`.
- `evaluation.json`: Deterministic evaluation output.
