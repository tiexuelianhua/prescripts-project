# Every page reads and writes its data in folders *beside* the code
# (Meal Receipts, Japanese, Spotify, ... next to this repo's folder), so
# running the app from here would touch the real data. Each test instead
# gets a throwaway copy of the code in a temp folder -- its data folders
# then land in that temp folder too -- and runs there in a fresh Python
# process, so nothing already imported from the real folder can leak in.
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).resolve().parent.parent
# Never copied: the virtual environment, git's own files, caches, and local
# runtime leftovers.
_SKIP = shutil.ignore_patterns(".venv", ".git", "__pycache__", ".pytest_cache", "*.exe", ".desktop_app.pid")


@pytest.fixture
def app_copy(tmp_path: Path) -> Path:
    copy = tmp_path / "Scripts"
    shutil.copytree(REPO_DIR, copy, ignore=_SKIP)
    return copy


def run_in(copy: Path, code: str) -> subprocess.CompletedProcess:
    # Runs `code` with the copy as both working folder and import path, after
    # checking the copy's modules really are the ones in use -- the guard
    # that keeps a test from ever writing next to the real repo.
    guard = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(copy)!r})
        import prescripts_common
        assert str(prescripts_common.SCRIPTS_DIR) == {str(copy)!r}, prescripts_common.SCRIPTS_DIR
    """)
    return subprocess.run(
        [sys.executable, "-c", guard + textwrap.dedent(code)],
        cwd=copy,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
    )
