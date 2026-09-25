# Native-feeling window for the Prescripts app. Displays the exact same
# Streamlit server ThePrescriptsLauncher.exe has always run, but in a plain
# pywebview window (Windows' built-in WebView2 -- no separate runtime to
# install) instead of the user's actual browser: no address bar, no tabs, its
# own icon in the taskbar/Alt-Tab. No change to any page code anywhere else
# -- this only changes how the same server gets displayed.
#
# ThePrescriptsLauncher.exe launches this (via pythonw.exe, hidden) in place
# of running Streamlit directly.
import ctypes
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import webview

SCRIPTS_DIR = Path(__file__).resolve().parent
# Must match REDIRECT_URI in spotify_data.py and Port in
# LauncherSrc/ThePrescriptsLauncher.cs.
PORT = 8501
URL = f"http://127.0.0.1:{PORT}"
# Not committed (see .gitignore) -- purely local runtime state.
PID_FILE = SCRIPTS_DIR / ".desktop_app.pid"
# Same check as PRIVATE_LOOK in prescripts_common.py (not imported from
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
# ACCENT_COLOR / ACCENT_COLOR_LIGHT in prescripts_common.py.
_PRIVATE_THEME_FLAGS = [
    f"--theme.{mode}.{key}=#96c4ec"
    for mode in ("light", "dark")
    for key in ("primaryColor", "linkColor")
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

    def toggle_fullscreen(self) -> None:
        self._window.toggle_fullscreen()

    def quit(self) -> None:
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
            *(_PRIVATE_THEME_FLAGS if PRIVATE_LOOK else []),
        ],
        cwd=SCRIPTS_DIR,
    )
    try:
        _wait_for_server()
        api = _Api()
        # The Startup-folder shortcut passes --minimized (through
        # ThePrescriptsLauncher.exe), so at sign-in the window waits in the
        # taskbar instead of popping up over everything else starting.
        # Launched by hand, it opens as normal.
        minimized = "--minimized" in sys.argv[1:]
        window = webview.create_window(
            "The Prescripts",
            URL,
            width=1200,
            height=850,
            min_size=(800, 600),
            js_api=api,
            minimized=minimized,
            focus=not minimized,
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
        try:
            PID_FILE.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
