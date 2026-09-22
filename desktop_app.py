# Native-feeling window for the Prescripts app. Displays the exact same
# Streamlit server MealReceiptsLauncher.exe has always run, but in a plain
# pywebview window (Windows' built-in WebView2 -- no separate runtime to
# install) instead of the user's actual browser: no address bar, no tabs, its
# own icon in the taskbar/Alt-Tab. No change to any page code anywhere else
# -- this only changes how the same server gets displayed.
#
# MealReceiptsLauncher.exe launches this (via pythonw.exe, hidden) in place
# of running Streamlit directly.
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import webview

SCRIPTS_DIR = Path(__file__).resolve().parent
# Must match REDIRECT_URI in spotify_data.py and Port in
# LauncherSrc/MealReceiptsLauncher.cs.
PORT = 8501
URL = f"http://127.0.0.1:{PORT}"
# Not committed (see .gitignore) -- purely local runtime state.
PID_FILE = SCRIPTS_DIR / ".desktop_app.pid"


def _kill_previous_instance() -> None:
    # MealReceiptsLauncher.exe's own StopExistingServer() already clears
    # whatever's bound to Port before starting this script -- that stays in
    # place as a fallback for a stray server with no pidfile of its own (e.g.
    # one left over from before this existed). This handles the other half:
    # a *window* left over from a previous run. Killing only Port's listener
    # would leave that old pywebview window open and showing a dead
    # connection, since the window's own process isn't the one bound to
    # Port -- the Streamlit server it started as a child is.  "/T" kills
    # that whole tree, server included, so nothing needs killing twice.
    if not PID_FILE.exists():
        return
    try:
        old_pid = int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return
    subprocess.run(["taskkill", "/PID", str(old_pid), "/T", "/F"], capture_output=True)


def _wait_for_server(timeout_s: float = 30) -> None:
    # Otherwise the window loads before Streamlit's listening, and shows a
    # connection-refused page for a moment.
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)


def main() -> None:
    _kill_previous_instance()
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(SCRIPTS_DIR / "app.py"),
            "--server.port",
            str(PORT),
            # This window is the UI now -- don't also pop the user's actual
            # browser open to the same server.
            "--server.headless",
            "true",
        ],
        cwd=SCRIPTS_DIR,
    )
    try:
        _wait_for_server()
        webview.create_window("The Prescripts", URL, width=1200, height=850, min_size=(800, 600))
        # Blocks until the window is closed -- that's the signal to tear the
        # server down too, in the `finally` below, rather than leaving it
        # running invisibly until the next launch's port-based cleanup.
        webview.start()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        try:
            PID_FILE.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
