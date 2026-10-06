# Native-feeling window for the Prescripts app. Displays the exact same
# Streamlit server ThePrescriptsLauncher.exe has always run, but in a plain
# pywebview window (Windows' built-in WebView2 -- no separate runtime to
# install) instead of the user's actual browser: no address bar, no tabs, its
# own icon in the taskbar/Alt-Tab. No change to any page code anywhere else
# -- this only changes how the same server gets displayed.
#
# ThePrescriptsLauncher.exe launches this (via pythonw.exe, hidden) in place
# of running Streamlit directly.
import base64
import ctypes
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import webview

SCRIPTS_DIR = Path(__file__).resolve().parent
# Must match REDIRECT_URI in prescripts/data/spotify.py and Port in
# LauncherSrc/ThePrescriptsLauncher.cs.
PORT = 8501
URL = f"http://127.0.0.1:{PORT}"
# Not committed (see .gitignore) -- purely local runtime state.
PID_FILE = SCRIPTS_DIR / ".desktop_app.pid"
# Left by the Settings page's update when requirements.txt changed (same
# path as PIP_PENDING in prescripts/data/updates.py), with pip's output
# kept beside it in case the install goes wrong.
PIP_PENDING = SCRIPTS_DIR / ".update_needs_pip"
PIP_LOG = SCRIPTS_DIR / ".update_pip.log"
# The window shown meanwhile, and what of pip's output it shows (cut to fit).
UPDATE_WINDOW = SCRIPTS_DIR / "static" / "update_window.html"
_PIP_STEPS = ("Collecting", "Downloading", "Requirement already satisfied", "Installing", "Successfully")
_STATUS_WIDTH = 42
# Same check as PRIVATE_LOOK in prescripts/common.py (not imported from
# there, since that pulls in all of Streamlit): the original author's own
# logo, kept outside the repo, picks their private look over the public one.
_IMAGES_DIR = SCRIPTS_DIR.parent / "Images"
PRIVATE_LOOK = (_IMAGES_DIR / "The_Index_Logo.webp").exists()
if PRIVATE_LOOK:
    # Generated from Images/The_Index_Logo.webp (padded to square;
    # webview.start's icon= wants a real .ico on Windows, not the webp app.py
    # uses for the browser-tab favicon).
    ICON_PATH = _IMAGES_DIR / "The_Index_Logo.ico"
    # Title bar only (the window's small icon) -- the plain transparent logo
    # reads fine there against the title bar, and the user prefers it without
    # the black square. The black-backdrop ICON_PATH stays the big icon,
    # which is what the taskbar and Alt-Tab show.
    TITLE_BAR_ICON_PATH = _IMAGES_DIR / "The_Index_Logo_plain.ico"
else:
    ICON_PATH = TITLE_BAR_ICON_PATH = SCRIPTS_DIR / "static" / "forget_me_not.ico"

# .streamlit/config.toml holds the public look's colors; the private look
# overrides them at launch (flags beat the config file). Must match
# ACCENT_COLOR in prescripts/common.py. The private look is also dark-only
# (the sky blue is unreadable on white), while the public one keeps light
# mode for anyone who wants it. theme.base can't force that -- with both
# [theme.light] and [theme.dark] defined, the viewer's light/dark preference
# still picks one -- so the light slot just gets the dark palette too
# (values from config.toml's [theme.dark]).
_PRIVATE_DARK_PALETTE = {
    "primaryColor": "#96c4ec",
    "linkColor": "#96c4ec",
    "backgroundColor": "#000000",
    "secondaryBackgroundColor": "#111318",
    "textColor": "#f0f8ff",
    "borderColor": "#2a2f3a",
    "codeBackgroundColor": "#0a0a0d",
}
_PRIVATE_THEME_FLAGS = [
    f"--theme.{mode}.{key}={value}"
    for mode in ("light", "dark")
    for key, value in _PRIVATE_DARK_PALETTE.items()
]

# Fullscreen is toggled with F11, like any browser/app -- not on by default
# at launch, since that's a bigger behavior change than just "make it
# possible". Ctrl+Q quits, the same as closing the window.
_SHORTCUTS_JS = """
document.addEventListener("keydown", (event) => {
    if (event.key === "F11") {
        event.preventDefault();
        window.pywebview.api.toggle_fullscreen();
    } else if (event.ctrlKey && event.key.toLowerCase() === "q") {
        event.preventDefault();
        window.pywebview.api.quit();
    }
});
"""


class _Api:
    # pywebview only picks up js_api if it's passed to create_window() itself
    # (stored as a private attribute there) -- window doesn't exist yet at
    # that point, so it's wired in afterwards instead of at construction.
    #
    # Must stay named with a leading underscore: pywebview exposes every
    # *public* attribute of a js_api object to JS, not just methods, and
    # confirmed live that a public `window` attribute here (holding the
    # whole Window object) hangs the window before it ever finishes loading
    # -- no exception, just silence forever after "_pywebviewready event
    # fired". Isolated with a minimal repro outside the app before touching
    # this file again: renaming to `_window` alone was the entire fix.
    _window: "webview.Window | None" = None
    # Set by restart(): once the window's closed and the server's stopped,
    # main() starts a fresh copy of this script.
    _restart = False

    def toggle_fullscreen(self) -> None:
        self._window.toggle_fullscreen()

    def quit(self) -> None:
        self._window.destroy()

    def restart(self) -> None:
        # Called by the Settings page after an update.
        self._restart = True
        self._window.destroy()


def _inject_shortcuts(window: "webview.Window") -> None:
    # Runs in the dedicated background thread webview.start(func=...) spins
    # up once the GUI loop is ready -- deliberately not wired via
    # `window.events.loaded += ...` instead: that fires the callback
    # synchronously on the GUI thread itself, and run_js() blocks waiting on
    # another of that same window's lifecycle events -- calling it from
    # there deadlocked the whole window (confirmed live: "(Not Responding)"
    # that never recovered). A plain wait() here, off the GUI thread, is the
    # pattern pywebview's own docs use for anything that needs to touch the
    # window after it's up.
    window.events.loaded.wait()
    window.run_js(_SHORTCUTS_JS)
    _set_title_bar_icon()


def _set_title_bar_icon() -> None:
    # pywebview's icon= sets both of the window's icons from the one file, so
    # the small one gets swapped afterwards via plain Win32 calls. Found by
    # owning process rather than by title, since an Explorer window open on
    # the "The Prescripts" folder would share it.
    if not TITLE_BAR_ICON_PATH.exists():
        return
    user32 = ctypes.windll.user32
    our_pid = os.getpid()
    hwnds = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def collect(hwnd, _):
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
        if pid.value == our_pid and user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
            hwnds.append(hwnd)
        return True

    user32.EnumWindows(collect, None)
    user32.LoadImageW.restype = ctypes.c_void_p
    size = user32.GetSystemMetrics(49)  # SM_CXSMICON
    hicon = user32.LoadImageW(
        None, str(TITLE_BAR_ICON_PATH), 1, size, size, 0x10  # IMAGE_ICON, LR_LOADFROMFILE
    )
    if not hicon:
        return
    for hwnd in hwnds:
        # WM_SETICON, ICON_SMALL
        user32.SendMessageW(ctypes.c_void_p(hwnd), 0x0080, 0, ctypes.c_void_p(hicon))


def _kill_previous_instance() -> None:
    # ThePrescriptsLauncher.exe's own StopExistingServer() already clears
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


def _update_window_html() -> str:
    font = base64.b64encode((SCRIPTS_DIR / "static" / "Galmuri14.woff2").read_bytes()).decode()
    accent = _PRIVATE_DARK_PALETTE["primaryColor"] if PRIVATE_LOOK else "#7578b2"
    return UPDATE_WINDOW.read_text(encoding="utf-8").replace("__FONT__", font).replace("__ACCENT__", accent)


def _pip_status(line: str) -> str | None:
    # One of pip's progress lines, shortened to fit the window, or None for
    # the rest (warnings, notices, blank lines).
    line = line.strip()
    if not line.startswith(_PIP_STEPS):
        return None
    return line if len(line) <= _STATUS_WIDTH else line[: _STATUS_WIDTH - 1] + "…"


def _install_update_packages(api: _Api, pip_command: list[str] | None = None) -> None:
    # An update changed requirements.txt: pip runs now, with nothing of the
    # app's running to lock files, behind a small window following its
    # progress, then the app restarts as normal. The flag goes either way,
    # so a failed install can't keep the app from ever opening; pip's output
    # is in .update_pip.log, and install step 4 in the README redoes it by
    # hand. `pip_command` stands in for pip when trying the window out.
    # 536 x 240 leaves a 520 x 200 page under the title bar, the size the
    # window's design was tried at.
    window = webview.create_window(
        "The Prescripts", html=_update_window_html(), width=536, height=240, resizable=False
    )
    api._window = window
    # python.exe rather than pythonw.exe (what the shortcut runs), so pip
    # has an output to stream; CREATE_NO_WINDOW keeps its console hidden.
    python = Path(sys.executable).with_name("python.exe")
    command = pip_command or [str(python if python.exists() else sys.executable),
                              "-m", "pip", "install", "-r", "requirements.txt"]

    def install(window: "webview.Window") -> None:
        window.events.loaded.wait()
        process = subprocess.Popen(
            command, cwd=SCRIPTS_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        output = []
        for line in process.stdout:
            output.append(line)
            status = _pip_status(line)
            if status:
                window.evaluate_js(f"setStatus({json.dumps(status)})")
        process.wait()
        PIP_LOG.write_text("".join(output), encoding="utf-8")
        PIP_PENDING.unlink(missing_ok=True)
        if process.returncode != 0:
            window.evaluate_js(f"setStatus({json.dumps('pip had a problem, see .update_pip.log')})")
        # Lets the lines (and an easter egg, if one's playing) finish before
        # the window goes, but never holds the restart up for long.
        deadline = time.time() + 20
        while time.time() < deadline and not window.evaluate_js("window.animationDone"):
            time.sleep(0.3)
        time.sleep(1.5)
        api.restart()

    webview.start(install, window, icon=str(ICON_PATH) if ICON_PATH.exists() else None)


def _relaunch() -> None:
    # A fresh process, not a loop inside this one: the new code (and any
    # new packages) only load in a new Python. Its parent is gone by the time
    # it checks for a previous instance, and this one's pidfile is already
    # removed, so nothing kills it. Opens normally even if this one was
    # started minimised: the user just clicked Update.
    args = [arg for arg in sys.argv[1:] if arg != "--minimized"]
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), *args],
        cwd=SCRIPTS_DIR,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )


def main() -> None:
    _kill_previous_instance()
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    api = _Api()
    try:
        if PIP_PENDING.exists():
            _install_update_packages(api)
        else:
            _run_app(api)
    finally:
        try:
            PID_FILE.unlink()
        except OSError:
            pass
    if api._restart:
        _relaunch()


def _run_app(api: _Api) -> None:
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
            *(_PRIVATE_THEME_FLAGS if PRIVATE_LOOK else []),
        ],
        cwd=SCRIPTS_DIR,
        # Tells the Settings page it can offer "Update and restart".
        env={**os.environ, "PRESCRIPTS_DESKTOP": "1"},
    )
    try:
        _wait_for_server()
        # The Startup-folder shortcut passes --minimized (through
        # ThePrescriptsLauncher.exe), so at sign-in the window waits in the
        # taskbar instead of popping up over everything else starting.
        # Launched by hand, it opens as normal. Not focus=False as well: on
        # Windows that makes the window one that can never be activated, so
        # no key presses reached it all session (Ctrl+Q, Ctrl+Shift+H).
        minimized = "--minimized" in sys.argv[1:]
        window = webview.create_window(
            "The Prescripts",
            URL,
            width=1200,
            height=850,
            min_size=(800, 600),
            js_api=api,
            minimized=minimized,
        )
        api._window = window
        # Blocks until the window is closed -- that's the signal to tear the
        # server down too, in the `finally` below, rather than leaving it
        # running invisibly until the next launch's port-based cleanup.
        webview.start(
            _inject_shortcuts, window, icon=str(ICON_PATH) if ICON_PATH.exists() else None
        )
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
