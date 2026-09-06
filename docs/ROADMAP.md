# Roadmap

## Phase 1 — Legacy Analysis PoC

| Gate | Description | Status | Dependencies |
|------|-------------|--------|--------------|
| 0 | Baseline COBOL (compile + smoke test) | **PASS** (2026-09-06) | [Evidence](gate-0-evidence.md) |
| 1 | Hello Foundry (auth + simple response) | **PASS** (2026-09-06) | [Evidence](gate-1-evidence.md) |
| 2 | COBOL Reader (single file → structured JSON) | NOT_RUN | Gate 1 |
| 3 | Legacy Analyzer (full system → assessment) | NOT_RUN | Gate 2 |
| 4 | GitHub Actions (manual trigger pipeline) | NOT_RUN | Gate 3, OIDC |
| 5 | Draft PR (automated PR creation) | NOT_RUN | Gate 4 |
| 6 | Night Worker (scheduled execution) | NOT_RUN | Gate 5 |
| 7 | Foundry Hosted Agent (comparison experiment) | NOT_RUN | Gate 6 |

## Phase 2 — Characterization Tests (future)
- Generate automated tests from the legacy assessment
- Test COBOL behavior without modifying it

## Phase 3 — COBOL Refactoring (future)
- Small refactorings preserving characterization tests

## Phase 4 — Business Rule Extraction (future)
- Implementation-independent representation of business rules

## Phase 5 — Modern Implementation (future)
- COBOL → modern stack with behavioral comparison
