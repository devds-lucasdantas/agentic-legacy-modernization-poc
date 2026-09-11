# Gate 2 Baseline-V2 Postmortem

## Executive Summary

| Field | Value |
|---|---|
| Run Label | `baseline-v2` |
| Execution Timestamp | `2026-09-11T13:34:41.664555+00:00` |
| Git Commit SHA | `9390377b410917e3e9c62883346b299b628a0000` |
| Model | `gpt-5-mini` |
| Official Result | **FAIL** (`gate_2_pass = false`) |
| Classification | **BENCHMARK_CONTRACT_FAILURE / EVIDENCE_REPRESENTATION_MISMATCH** |

---

## 1. Official Observed Metrics

In the first live execution of Gate 2 Candidate V2.3.1 (`baseline-v2`), the following metrics were recorded in `artifacts/gate-2/baseline-v2/evaluation.json`:

| Metric | Official Result |
|---|---|
| Raw / Unique Predictions | 22 / 22 |
| Supported Predictions | 1 |
| Unsupported Predictions | 21 |
| Invalid Evidence Count | 21 |
| Expected Facts Matched | 1 / 15 |
| Missing Expected Facts | 14 / 15 |
| Precision | 0.0455 (4.55%) |
| Recall | 0.0667 (6.67%) |
| Contradictions | 0 |
| Duplicates | 0 |
| Gate Decision | **FAIL** |

The single supported prediction was the host-owned absence assertion for copybooks (`DEPENDENCY_SCAN:COPY:DEPENDENCY_COUNT:0`), which is verified host-side across the entire file and carries an empty snippet. All 21 model-generated positive predictions were rejected by the evaluator for invalid evidence snippets.

---

## 2. Root Cause Analysis

### A. The Transport Representation Ingestion
To provide line-level visibility without guessing, the analyzer agent's source preparation module (`src/cobol/source_reader.py`) formats the source code provided in the user prompt as numbered lines:
```text
0001 |        IDENTIFICATION DIVISION.
0002 |        PROGRAM-ID. BANK-MAIN.
...
0022 |                    EVALUATE WS-CHOICE
0023 |                    WHEN '1'
0024 |                         CALL 'INIT-DB'
```
Each line is prefixed with a 4-digit line number followed by `" | "` (`NNNN | `).

### B. The Contract Ambiguity in the Prompt
The system prompt (`agents/legacy_analyzer/prompts/system.md`) contained contradictory instructions regarding snippet extraction:
1. **Instruction 4 (Evidence Traceability)**:
   > *"Every identified program identifier, variable, dependency, menu option, control flow construct, and I/O statement MUST carry precise line number citations and verbatim snippets from the numbered source code provided."*
2. **Semantic Extraction Contract (Evidence Snippets)**:
   > *"evidence snippets must always contain verbatim source code text from the cited lines exactly as it appears in the source file, preserving original quotes and formatting."*

Faced with this ambiguity, the model prioritized Instruction 4 and faithfully copied the text exactly as presented in its prompt context:
```json
{
  "program": {
    "program_id": "BANK-MAIN",
    "evidence": {
      "line_start": 2,
      "line_end": 2,
      "snippet": "0002 |        PROGRAM-ID. BANK-MAIN."
    }
  }
}
```

### C. Evaluator Verification Failure
The deterministic evidence validator (`src/validation/evidence_validator.py`) slices raw source bytes without line numbers:
```python
actual_slice_lines = source_lines[evidence.line_start - 1 : evidence.line_end]
# Line 2: "       PROGRAM-ID. BANK-MAIN."
```
Because `"0002 |        PROGRAM-ID. BANK-MAIN."` does not appear in the raw source line `"       PROGRAM-ID. BANK-MAIN."`, the evaluator strictly and correctly failed closed:
```text
"Invalid evidence citation: Evidence snippet '0002 |        PROGRAM-ID. BANK-MAIN.' does not match actual source text in lines [2..2]"
```
Because valid evidence is a strict prerequisite for fact support, all 21 positive predictions became unsupported, resulting in 1/15 recall and 0.0455 precision.

---

## 3. Independent Diagnosis: Not a Semantic COBOL Understanding Failure

This failure was strictly a benchmark evidence contract defect, not a failure of COBOL semantic comprehension.

When the transport prefix `^[0-9]{4} \| ` is removed via a structurally verified offline diagnostic rescore:
- **All 21 invalid snippets** become exact cited raw-source matches.
- **All 14 previously missing positive expected facts** become matched.
- **Host-owned no-COPY** remains matched (15/15).
- **All 22 predictions** are fully source-supported.
- **Precision = 1.0 (100%)**.
- **Recall = 1.0 (100%)**.
- **Contradictions = 0**, **Duplicates = 0**.

The model understood every variable, call, menu dispatch, evaluate structure, loop condition, and display literal with 100% fidelity.

---

## 4. Remediation: Candidate V2.4 Architecture

Rather than adding ad-hoc string-stripping heuristics to the evaluator or papering over the defect with fuzzy repairs, Candidate V2.4 fixes the root architectural defect: **eliminating model-generated snippet redundancy**.

The model should only infer information it uniquely needs to determine:
- Semantic fact fields (identifiers, operands, literals, constructs)
- Source span coordinates (`line_start`, `line_end`)

The host layer is deterministically responsible for deriving the exact source text snippet from verified raw source bytes.

```
+------------------------+
|   MODEL PREDICTION     |  ->  fact semantics + { line_start, line_end }
+------------------------+
            |
            v
+------------------------+
|    HOST ENRICHMENT     |  ->  reads verified raw source lines [start..end]
+------------------------+      derives exact snippet deterministically
            |
            v
+------------------------+
|  EVALUATOR VALIDATION  |  ->  verifies fact support, span overlap,
+------------------------+      and required semantic fragments fail-closed
```

This guarantees 100% fail-closed grounding while permanently eliminating LLM transcription mismatches.
