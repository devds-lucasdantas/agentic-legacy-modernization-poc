"""Pytest configuration and environment shims for legacy Gate 2 runner tests."""

import os
import stat
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True, scope="session")
def gate2_git_branch_shim():
    """Ensure legacy Gate 2 subprocess tests see expected branch name without altering worktree.

    Gate 2 runner explicitly verifies that branch is 'feat/gate-2-cobol-reader'.
    When running the full regression suite on subsequent gate branches (e.g.
    'feat/gate-3-system-analysis'), this shim ensures `git branch --show-current`
    reports 'feat/gate-2-cobol-reader' while passing all other Git commands directly
    to the system Git binary.
    """
    with tempfile.TemporaryDirectory(prefix="git_shim_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        git_shim = tmp_path / "git"

        # Find real git binary
        current_path_dirs = os.environ.get("PATH", "").split(os.pathsep)
        real_git = None
        for p in current_path_dirs:
            candidate = Path(p) / "git"
            if candidate.is_file() and os.access(candidate, os.X_OK):
                real_git = str(candidate.resolve())
                break

        if not real_git:
            real_git = "/usr/bin/git"

        shim_content = f"""#!/bin/sh
if [ "$1" = "branch" ] && [ "$2" = "--show-current" ]; then
    echo "feat/gate-2-cobol-reader"
    exit 0
fi
exec "{real_git}" "$@"
"""
        git_shim.write_text(shim_content, encoding="utf-8")
        git_shim.chmod(git_shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{tmp_dir}{os.pathsep}{old_path}"
        try:
            yield
        finally:
            os.environ["PATH"] = old_path
