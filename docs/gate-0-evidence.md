# Gate 0 — Baseline COBOL — Evidence

## Result: PASS

| Field | Value |
|---|---|
| Date | 2026-09-06 |
| Environment | WSL (Ubuntu 24.04) |
| GnuCOBOL cobc | 3.1.2.0 |
| GnuCOBOL cobcrun | 3.1.2.0 |
| Script | `bash scripts/cobol-smoke-test.sh` |
| Total checks | 9 |
| Passed | 9 |
| Failed | 0 |

## Checks

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | GnuCOBOL cobc available | PASS | 3.1.2.0 |
| 2 | GnuCOBOL cobcrun available | PASS | 3.1.2.0 |
| 3 | Compile INIT-DB.CBL (module) | PASS | Non-fatal `_FORTIFY_SOURCE` redefined warnings |
| 4 | Compile TRANS-PROC.CBL (module) | PASS | Non-fatal `_FORTIFY_SOURCE` redefined warnings |
| 5 | Compile REPORT-GEN.CBL (module) | PASS | Non-fatal `_FORTIFY_SOURCE` redefined warnings |
| 6 | Compile BANK-MAIN.CBL (executable) | PASS | Non-fatal `_FORTIFY_SOURCE` redefined warnings |
| 7 | Run INIT-DB (creates ACCOUNTS.DAT with 3 records) | PASS | |
| 8 | Run REPORT-GEN (produces summary report) | PASS | 3 accounts, total balance $17,600.50 |
| 9 | Run BANK-MAIN (menu loads, exit with '4') | PASS | |

## Intentionally Skipped

- **TRANS-PROC execution**: Skipped because `TRANS-PROC.CBL` invokes Windows-specific
  `cmd /c del` and `cmd /c ren` via `CALL 'SYSTEM'`. Compilation success is sufficient
  for Gate 0. The Windows-specific SYSTEM calls are preserved as a modernization risk
  in the golden dataset.

## Compiler Warnings

Non-fatal `_FORTIFY_SOURCE` redefined warnings occurred during compilation.
These are GnuCOBOL/GCC toolchain warnings unrelated to the COBOL source code
and do not affect functionality.

## Preserved Legacy Behaviors (Golden Dataset Risks)

These behaviors are intentionally **not corrected** — the agent must detect them:

1. **`STOP RUN` in subprograms** — All called modules use `STOP RUN` instead of `GOBACK`,
   terminating the entire run unit on each CALL.
2. **Windows-specific SYSTEM calls** — `TRANS-PROC.CBL` uses `cmd /c del` and `cmd /c ren`,
   not portable to Linux/Unix.
3. **Unused copybook** — `ACCOUNTS.CPY` exists but is not referenced by any `.CBL` file
   via `COPY`. Each program defines its own inline record layout.
