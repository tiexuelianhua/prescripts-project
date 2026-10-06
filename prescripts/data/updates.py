# Updates (#42): whether GitHub has a newer version of this copy's code, and
# moving the copy to it. No Streamlit rendering here (pages/settings.py
# draws it). Only versions whose tests passed on GitHub are offered, so a
# broken push never reaches anyone, and nothing updates without a click.
#
# Needs a copy installed with git: a ZIP install has no record of which
# version it is, so the page points those to the README instead.
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

import streamlit as st

from prescripts.common import SCRIPTS_DIR

REPO = "tiexuelianhua/prescripts-project"
API = f"https://api.github.com/repos/{REPO}"
# Left for desktop_app.py when an update changes requirements.txt: it runs
# pip on the next launch, before the server starts, because Windows locks
# the installed packages' files while the app is running.
PIP_PENDING = SCRIPTS_DIR / ".update_needs_pip"
# How many changes the Settings page lists before "and N more".
CHANGES_SHOWN = 8


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=SCRIPTS_DIR, capture_output=True, text=True, encoding="utf-8", timeout=120,
        # The desktop window's server has no console, so without this every
        # git call would flash one up.
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def in_desktop_window() -> bool:
    # desktop_app.py sets this for the server it starts, so the page knows
    # the window can restart itself after an update.
    return os.environ.get("PRESCRIPTS_DESKTOP") == "1"


def local_version() -> dict | None:
    # This copy's commit and its date, or None for a ZIP install (or no git).
    if not (SCRIPTS_DIR / ".git").exists() or shutil.which("git") is None:
        return None
    result = _git("log", "-1", "--format=%H %cs")
    if result.returncode != 0 or not result.stdout.strip():
        return None
    sha, date = result.stdout.split()
    return {"sha": sha, "date": date}


def _get(url: str):
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"The Prescripts (https://github.com/{REPO})",
    })
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode())


@st.cache_data(ttl=3600, show_spinner=False)
def check_for_update(local_sha: str) -> dict:
    # The newest version on main whose tests passed, against this copy:
    # {"state": "available" | "up_to_date" | "own_changes", plus for
    # "available" the version's "sha" and "changes" (commit titles, newest
    # first)}. Cached for an hour: GitHub allows 60 unsigned requests an
    # hour, and this costs two. Raises on network trouble (not cached).
    runs = _get(f"{API}/actions/workflows/tests.yml/runs?branch=main&event=push&status=success&per_page=1")
    if not runs["workflow_runs"]:
        return {"state": "up_to_date"}
    latest = runs["workflow_runs"][0]["head_sha"]
    try:
        compare = _get(f"{API}/compare/{local_sha}...{latest}")
    except urllib.error.HTTPError as error:
        if error.code == 404:  # this copy's commit isn't on GitHub: made here
            return {"state": "own_changes"}
        raise
    if compare["status"] == "ahead":
        titles = [commit["commit"]["message"].splitlines()[0] for commit in compare["commits"]]
        return {"state": "available", "sha": latest, "changes": titles[::-1]}
    # "behind": this copy is already past the newest tested version (a push
    # whose tests are still running), which counts as up to date.
    return {"state": "own_changes" if compare["status"] == "diverged" else "up_to_date"}


def apply_update(sha: str) -> tuple[str | None, bool]:
    # Moves this copy to `sha` (fast-forward only, so nothing of the user's
    # is ever merged or overwritten). Returns (what went wrong or None,
    # whether requirements.txt changed and pip needs to run).
    fetch = _git("fetch", "origin", "main")
    if fetch.returncode != 0:
        return f"Couldn't download the update: {fetch.stderr.strip()}", False
    if _git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        return ("This copy has edits of its own to the code, so it wasn't updated. "
                "Undo them (`git checkout .` in the prescripts-project folder) or update by hand."), False
    needs_pip = _git("diff", "--quiet", "HEAD", sha, "--", "requirements.txt").returncode != 0
    merge = _git("merge", "--ff-only", sha)
    if merge.returncode != 0:
        return f"Couldn't update: {merge.stderr.strip() or merge.stdout.strip()}", False
    return None, needs_pip
