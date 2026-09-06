# Upstream Provenance

| Field | Value |
|---|---|
| Repository | https://github.com/fzn0x/core-banking-system |
| Branch | main |
| Commit SHA | 770860d4a11f1d203b0369456d867108097a550f |
| Snapshot Date | 2026-09-06 |
| License | MIT |
| Files Copied | BANK-MAIN.CBL, INIT-DB.CBL, TRANS-PROC.CBL, REPORT-GEN.CBL, ACCOUNTS.CPY, ACCOUNTS.DAT, LICENSE |

## Purpose

This directory contains a verbatim snapshot of the upstream COBOL project
used as a **legacy fixture** for the Agentic Legacy Modernization PoC.

The code is preserved exactly as found in the upstream repository.
No functional modifications have been made.

## Updating

To update this snapshot:
1. Record the new commit SHA
2. Download the files from the upstream repository
3. Replace the files in this directory
4. Update this file with the new commit SHA and date
5. Re-run Gate 0 smoke tests to verify compilation
