# A small diagnostic log for the Spotify page and the Overview tile: slow
# refreshes, failed or slow Spotify/LRCLIB requests, lyrics lookups, and how
# long each track played before the song changed. Nothing here affects
# behavior -- it exists so "it lagged just now" can be answered by reading a
# file instead of guessing.
#
# Lives next to the Spotify credentials in Spotify/ (outside the git repo),
# and trims itself so it can't grow without bound.
import contextlib
import functools
import threading
import time

from prescripts_common import SCRIPTS_DIR

LOG_PATH = SCRIPTS_DIR.parent / "Spotify" / "page_log.txt"
# Once the file passes MAX_BYTES, only the newest KEEP_BYTES are kept.
MAX_BYTES = 256_000
KEEP_BYTES = 128_000
# Anything slower than this is worth a line. A normal refresh is well under
# it (a cached one takes a few ms; one that hits Spotify about 0.2-0.4s).
SLOW_THRESHOLD_S = 1.0

_lock = threading.Lock()


def log_event(message: str) -> None:
    # Called from background threads too (the lyrics lookup), hence the lock.
    # A logging failure must never break the page, so I/O errors are dropped.
    try:
        with _lock:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            if LOG_PATH.exists() and LOG_PATH.stat().st_size > MAX_BYTES:
                tail = LOG_PATH.read_bytes()[-KEEP_BYTES:]
                # Start on a whole line, not partway through one.
                LOG_PATH.write_bytes(tail[tail.find(b"\n") + 1:])
            with LOG_PATH.open("a", encoding="utf-8") as log:
                log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


@contextlib.contextmanager
def slow_watch(label: str, threshold_s: float = SLOW_THRESHOLD_S):
    # Logs a line if the wrapped block takes longer than threshold_s.
    started = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - started
        if elapsed > threshold_s:
            log_event(f"slow: {label} took {elapsed:.2f}s")


def log_slow(label: str, threshold_s: float = SLOW_THRESHOLD_S):
    # Decorator form of slow_watch, for the fragment functions. Goes BELOW
    # @st.fragment; functools.wraps keeps the function's name, which is part
    # of what Streamlit derives a fragment's identity from.
    def decorate(func):
        @functools.wraps(func)
        def timed(*args, **kwargs):
            with slow_watch(label, threshold_s):
                return func(*args, **kwargs)
        return timed
    return decorate
