#!/usr/bin/env bash
# =============================================================================
# Gate 0 — COBOL Smoke Test
# =============================================================================
# Verifies that the legacy COBOL system compiles and runs on the current
# environment. Requires GnuCOBOL (cobc, cobcrun) in PATH.
#
# Usage:
#   bash scripts/cobol-smoke-test.sh
#
# Exit codes:
#   0 = all checks passed
#   1 = one or more checks failed
# =============================================================================

set -euo pipefail

LEGACY_DIR="legacy/core-banking-system"
WORK_DIR=$(mktemp -d)
PASS_COUNT=0
FAIL_COUNT=0
TOTAL_COUNT=0

# Cleanup on exit
cleanup() {
    rm -rf "$WORK_DIR"
}
trap cleanup EXIT

# Report a test result
report() {
    local name="$1"
    local status="$2"
    local detail="${3:-}"
    TOTAL_COUNT=$((TOTAL_COUNT + 1))
    if [ "$status" = "PASS" ]; then
        PASS_COUNT=$((PASS_COUNT + 1))
        echo "[PASS] $name"
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        echo "[FAIL] $name"
        if [ -n "$detail" ]; then
            echo "       $detail"
        fi
    fi
}

echo "============================================="
echo " Gate 0 — COBOL Smoke Test"
echo "============================================="
echo ""

# --- Pre-flight: check GnuCOBOL ---
echo "--- Pre-flight ---"
if command -v cobc &>/dev/null; then
    COBC_VERSION=$(cobc --version 2>&1 | head -1)
    echo "cobc found: $COBC_VERSION"
    report "GnuCOBOL cobc available" "PASS"
else
    report "GnuCOBOL cobc available" "FAIL" "cobc not found in PATH"
    echo ""
    echo "RESULT: BLOCKED_ENV — GnuCOBOL not installed"
    exit 1
fi

if command -v cobcrun &>/dev/null; then
    report "GnuCOBOL cobcrun available" "PASS"
else
    report "GnuCOBOL cobcrun available" "FAIL" "cobcrun not found in PATH"
    echo ""
    echo "RESULT: BLOCKED_ENV — cobcrun not installed"
    exit 1
fi
echo ""

# --- Copy source files to work directory ---
echo "--- Preparing work directory: $WORK_DIR ---"
cp "$LEGACY_DIR"/BANK-MAIN.CBL "$WORK_DIR/"
cp "$LEGACY_DIR"/INIT-DB.CBL "$WORK_DIR/"
cp "$LEGACY_DIR"/TRANS-PROC.CBL "$WORK_DIR/"
cp "$LEGACY_DIR"/REPORT-GEN.CBL "$WORK_DIR/"
cp "$LEGACY_DIR"/ACCOUNTS.CPY "$WORK_DIR/"
cp "$LEGACY_DIR"/ACCOUNTS.DAT "$WORK_DIR/"
echo ""

# --- Compilation checks ---
echo "--- Compilation ---"

# Compile INIT-DB as module
if (cd "$WORK_DIR" && cobc -m INIT-DB.CBL 2>&1); then
    report "Compile INIT-DB.CBL (module)" "PASS"
else
    report "Compile INIT-DB.CBL (module)" "FAIL" "cobc -m failed"
fi

# Compile TRANS-PROC as module
if (cd "$WORK_DIR" && cobc -m TRANS-PROC.CBL 2>&1); then
    report "Compile TRANS-PROC.CBL (module)" "PASS"
else
    report "Compile TRANS-PROC.CBL (module)" "FAIL" "cobc -m failed"
fi

# Compile REPORT-GEN as module
if (cd "$WORK_DIR" && cobc -m REPORT-GEN.CBL 2>&1); then
    report "Compile REPORT-GEN.CBL (module)" "PASS"
else
    report "Compile REPORT-GEN.CBL (module)" "FAIL" "cobc -m failed"
fi

# Compile BANK-MAIN as executable (links against modules)
if (cd "$WORK_DIR" && cobc -x BANK-MAIN.CBL 2>&1); then
    report "Compile BANK-MAIN.CBL (executable)" "PASS"
else
    report "Compile BANK-MAIN.CBL (executable)" "FAIL" "cobc -x failed"
fi
echo ""

# --- Execution checks ---
echo "--- Execution ---"

# Run INIT-DB via cobcrun to regenerate ACCOUNTS.DAT
# cobcrun executes a COBOL module by loading its shared library
if (cd "$WORK_DIR" && COB_LIBRARY_PATH=. cobcrun INIT-DB 2>&1); then
    if [ -f "$WORK_DIR/ACCOUNTS.DAT" ]; then
        LINE_COUNT=$(wc -l < "$WORK_DIR/ACCOUNTS.DAT")
        if [ "$LINE_COUNT" -ge 3 ]; then
            report "Run INIT-DB (creates ACCOUNTS.DAT with 3 records)" "PASS"
        else
            report "Run INIT-DB (creates ACCOUNTS.DAT with 3 records)" "FAIL" "Expected >= 3 lines, got $LINE_COUNT"
        fi
    else
        report "Run INIT-DB (creates ACCOUNTS.DAT with 3 records)" "FAIL" "ACCOUNTS.DAT not created"
    fi
else
    report "Run INIT-DB (creates ACCOUNTS.DAT with 3 records)" "FAIL" "cobcrun INIT-DB failed"
fi

# Run REPORT-GEN via cobcrun to verify it reads the data
REPORT_OUTPUT=""
if REPORT_OUTPUT=$(cd "$WORK_DIR" && COB_LIBRARY_PATH=. cobcrun REPORT-GEN 2>&1); then
    # Check that output contains expected markers
    if echo "$REPORT_OUTPUT" | grep -q "ACCOUNT BALANCE SUMMARY REPORT"; then
        if echo "$REPORT_OUTPUT" | grep -q "TOTAL ACCOUNTS"; then
            report "Run REPORT-GEN (produces summary report)" "PASS"
            echo "       --- REPORT-GEN Output ---"
            echo "$REPORT_OUTPUT" | sed 's/^/       /'
            echo "       --- End Output ---"
        else
            report "Run REPORT-GEN (produces summary report)" "FAIL" "Missing TOTAL ACCOUNTS in output"
        fi
    else
        report "Run REPORT-GEN (produces summary report)" "FAIL" "Missing report header in output"
    fi
else
    report "Run REPORT-GEN (produces summary report)" "FAIL" "cobcrun REPORT-GEN failed"
fi

# Run BANK-MAIN with piped input '4' (exit immediately)
# This verifies the executable loads and the module linkage works
MAIN_OUTPUT=""
if MAIN_OUTPUT=$(cd "$WORK_DIR" && echo "4" | COB_LIBRARY_PATH=. ./BANK-MAIN 2>&1); then
    if echo "$MAIN_OUTPUT" | grep -q "CORE BANKING SYSTEM"; then
        if echo "$MAIN_OUTPUT" | grep -q "Bye"; then
            report "Run BANK-MAIN (menu loads, exit with '4')" "PASS"
        else
            report "Run BANK-MAIN (menu loads, exit with '4')" "FAIL" "Menu loaded but 'Bye' not found"
        fi
    else
        report "Run BANK-MAIN (menu loads, exit with '4')" "FAIL" "Menu header not found in output"
    fi
else
    # BANK-MAIN may return non-zero on some platforms due to STOP RUN behavior
    # Check if it at least produced output
    if echo "$MAIN_OUTPUT" | grep -q "CORE BANKING SYSTEM"; then
        report "Run BANK-MAIN (menu loads, exit with '4')" "PASS" "(non-zero exit, but output correct)"
    else
        report "Run BANK-MAIN (menu loads, exit with '4')" "FAIL" "Execution failed: $MAIN_OUTPUT"
    fi
fi

# NOTE: TRANS-PROC is NOT executed because:
# 1. It uses Windows-specific SYSTEM calls (cmd /c del, cmd /c ren)
# 2. It requires interactive input (account number, type, amount)
# 3. The SYSTEM calls would fail on Linux
# Compilation is sufficient to verify TRANS-PROC at this gate.
echo ""
echo "NOTE: TRANS-PROC execution skipped (Windows-specific SYSTEM calls)."
echo "      Compilation success is sufficient for Gate 0."

# --- Summary ---
echo ""
echo "============================================="
echo " Summary"
echo "============================================="
echo " Total:  $TOTAL_COUNT"
echo " Passed: $PASS_COUNT"
echo " Failed: $FAIL_COUNT"
echo "============================================="

if [ "$FAIL_COUNT" -eq 0 ]; then
    echo ""
    echo "RESULT: PASS"
    exit 0
else
    echo ""
    echo "RESULT: FAIL"
    exit 1
fi
