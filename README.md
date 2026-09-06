# Agentic Legacy Modernization PoC

Proof of Concept for agentic modernization of COBOL legacy systems using
Microsoft Azure AI Foundry.

## Goal

Prove that an AI agent can **reliably understand** a small COBOL banking system
and produce a **structured, verifiable** legacy assessment — before attempting
any code transformation.

## Architecture

```
GitHub Actions
  └── GnuCOBOL compile/test
  └── Python legacy-analyzer-agent
        └── Azure AI Foundry (Responses API)
              └── Structured legacy assessment
                    └── Pydantic / JSON Schema validation
                          └── Deterministic evals
                                └── Markdown reports
                                      └── Draft PR → Human Review
```

## Legacy System

The target is [fzn0x/core-banking-system](https://github.com/fzn0x/core-banking-system)
(MIT license), a small COBOL banking system with:

- `BANK-MAIN.CBL` — Main menu driver
- `INIT-DB.CBL` — Database initialization (3 seed accounts)
- `TRANS-PROC.CBL` — Deposit/withdrawal processing
- `REPORT-GEN.CBL` — Balance summary report
- `ACCOUNTS.CPY` — Copybook (account record structure)
- `ACCOUNTS.DAT` — Data file (fixed-width records)

A versioned snapshot is in `legacy/core-banking-system/`.

## Gates

| Gate | Name | Status |
|------|------|--------|
| 0 | Baseline COBOL | **PASS** (9/9 checks, GnuCOBOL 3.1.2.0) |
| 1 | Hello Foundry | **PASS** (gpt-5-mini, Responses API) |
| 2 | COBOL Reader | NOT_RUN |
| 3 | Legacy Analyzer | NOT_RUN |
| 4 | GitHub Actions | NOT_RUN |
| 5 | Draft PR | NOT_RUN |
| 6 | Night Worker | NOT_RUN |
| 7 | Hosted Agent (optional) | NOT_RUN |

## Quick Start

### Gate 0 — COBOL Smoke Test

Requires GnuCOBOL (`cobc`, `cobcrun`):

```bash
# Linux
sudo apt-get install gnucobol

# Run smoke test
bash scripts/cobol-smoke-test.sh
```

### Gate 1+ — Agent

See `docs/SETUP.md` for Azure AI Foundry setup.

## License

This project is MIT licensed. The COBOL legacy code in `legacy/` retains its
original MIT license from the upstream repository.
