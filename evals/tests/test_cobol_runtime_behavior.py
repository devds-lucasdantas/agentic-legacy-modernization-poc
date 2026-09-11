"""GnuCOBOL runtime sandbox execution tests for Gate 3.

Verifies that the multi-file legacy banking programs compile and execute
accurately in an isolated sandbox without mutating repository sources.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LEGACY_DIR = REPO_ROOT / "legacy" / "core-banking-system"


def has_gnu_cobol() -> bool:
    """Check if cobc compiler binary is available in the environment."""
    return shutil.which("cobc") is not None


@pytest.mark.skipif(not has_gnu_cobol(), reason="GnuCOBOL compiler (cobc) not installed")
def test_cobol_runtime_init_db_and_report():
    """Compile INIT-DB and REPORT-GEN in isolated sandbox and verify execution output."""
    with tempfile.TemporaryDirectory(prefix="cobol_sandbox_") as tmp_dir:
        sandbox = Path(tmp_dir)

        # Copy legacy files to sandbox to prevent mutating repository state
        for f in LEGACY_DIR.iterdir():
            if f.is_file():
                shutil.copy2(f, sandbox / f.name)

        # 1. Compile INIT-DB
        res = subprocess.run(
            ["cobc", "-x", "-free", "INIT-DB.CBL"],
            cwd=sandbox,
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            # Try fixed format if free format failed
            res = subprocess.run(
                ["cobc", "-x", "INIT-DB.CBL"],
                cwd=sandbox,
                capture_output=True,
                text=True,
            )
        assert res.returncode == 0, f"INIT-DB compilation failed: {res.stderr}"

        # 2. Execute INIT-DB to generate ACCOUNTS.DAT
        exe_name = "./INIT-DB" if os.name != "nt" else "INIT-DB.exe"
        run_res = subprocess.run([exe_name], cwd=sandbox, capture_output=True, text=True)
        assert run_res.returncode == 0, f"INIT-DB execution failed: {run_res.stderr}"
        assert "Database initialized." in run_res.stdout

        # Verify ACCOUNTS.DAT was created
        data_file = sandbox / "ACCOUNTS.DAT"
        assert data_file.is_file()
        assert data_file.stat().st_size > 0

        # 3. Compile REPORT-GEN
        res = subprocess.run(
            ["cobc", "-x", "-free", "REPORT-GEN.CBL"],
            cwd=sandbox,
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            res = subprocess.run(
                ["cobc", "-x", "REPORT-GEN.CBL"],
                cwd=sandbox,
                capture_output=True,
                text=True,
            )
        assert res.returncode == 0, f"REPORT-GEN compilation failed: {res.stderr}"

        # 4. Execute REPORT-GEN and verify summary report output
        rep_exe = "./REPORT-GEN" if os.name != "nt" else "REPORT-GEN.exe"
        rep_res = subprocess.run([rep_exe], cwd=sandbox, capture_output=True, text=True)
        assert rep_res.returncode == 0, f"REPORT-GEN execution failed: {rep_res.stderr}"
        assert "ACCOUNT BALANCE SUMMARY REPORT" in rep_res.stdout
        assert "TOTAL ACCOUNTS:" in rep_res.stdout
        assert "BANK BALANCE:" in rep_res.stdout
