# Lyrics for the Spotify page, from LRCLIB (https://lrclib.net) -- a free,
# keyless, community-maintained lyrics database. Spotify's own Web API has no
# lyrics endpoint at all. Like spotify_data.py, no Streamlit rendering calls.
#
# Lookups run on a background thread and are polled, never awaited: LRCLIB is
# slow and flaky (4-10s per uncached request was typical when this was
# written, with the occasional timeout or 503), and a request made inline
# would block the script thread -- freezing every live refresh on the page
# (the 1s now-playing tick included) until it came back.
#
# Results are held in memory only, for the life of the server process --
# nothing is written to disk.
import bisect
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from spotify_log import log_event

API_BASE = "https://lrclib.net/api"
# LRCLIB asks clients to identify themselves.
USER_AGENT = "PrescriptsApp/1.0 (personal project; https://github.com/tiexuelianhua/prescripts-project)"
REQUEST_TIMEOUT_S = 20
# A failed lookup (timeout, 5xx) is retried on a later poll after this long,
# rather than immediately (would hammer a struggling service) or never.
RETRY_AFTER_FAILURE_S = 60
MAX_ENTRIES = 300
# How far apart (seconds) a search result's length may be from the playing
# track's and still count as the same recording.
DURATION_TOLERANCE_S = 3

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="lyrics")
_lock = threading.Lock()
# track uri -> {"state": "loading" | "done" | "failed", "lyrics": dict | None, "at": float}
_entries: dict[str, dict] = {}

_TIMESTAMP = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")


def _get_json(path: str, params: dict):
    request = urllib.request.Request(
        f"{API_BASE}/{path}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
        return json.loads(response.read().decode())


def parse_synced(text: str | None) -> list[tuple[int, str]]:
    # LRC format: "[mm:ss.xx] words", where one line can carry several
    # timestamps ("[00:12.00][00:45.00] chorus line").
    lines = []
    for raw_line in (text or "").splitlines():
        stamps = _TIMESTAMP.findall(raw_line)
        if not stamps:
            continue
        words = _TIMESTAMP.sub("", raw_line).strip()
        for minutes, seconds in stamps:
            lines.append((int((int(minutes) * 60 + float(seconds)) * 1000), words))
    lines.sort(key=lambda line: line[0])
    return lines


def _shape(record: dict) -> dict:
    synced = parse_synced(record.get("syncedLyrics"))
    plain = record.get("plainLyrics") or "\n".join(words for _, words in synced) or None
    return {
        "plain": plain,
        "synced": synced or None,
        "instrumental": bool(record.get("instrumental")),
    }


def _fetch(track_name: str, artist_name: str, album_name: str, duration_s: int) -> dict | None:
    # Exact lookup first (fast when it hits); on a 404, fall back to search --
    # e.g. "Azumi Takahashi" vs LRCLIB's "Azumi Takahashi, Lotus Juice" misses
    # the exact match but the search finds it.
    try:
        return _shape(_get_json("get", {
            "track_name": track_name,
            "artist_name": artist_name,
            "album_name": album_name,
            "duration": duration_s,
        }))
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise

    results = _get_json("search", {"q": f"{track_name} {artist_name}"})
    candidates = [
        record for record in results
        if (record.get("plainLyrics") or record.get("syncedLyrics") or record.get("instrumental"))
        and abs((record.get("duration") or 0) - duration_s) <= DURATION_TOLERANCE_S
    ]
    if not candidates:
        return None
    # Closest length wins; synced beats plain-only on a tie.
    best = min(
        candidates,
        key=lambda record: (abs(record["duration"] - duration_s), not record.get("syncedLyrics")),
    )
    return _shape(best)


def _run_lookup(uri: str, args: tuple) -> None:
    track_name, artist_name, _album, duration_s = args
    label = f'lyrics: "{track_name}" - {artist_name} ({duration_s}s)'
    started = time.time()
    try:
        lyrics = _fetch(*args)
        entry = {"state": "done", "lyrics": lyrics, "at": time.time()}
        if lyrics is None:
            outcome = "not found"
        elif lyrics["instrumental"] and not lyrics["plain"]:
            outcome = "instrumental"
        else:
            outcome = "found (synced)" if lyrics["synced"] else "found (plain only)"
        log_event(f"{label}: {outcome} in {time.time() - started:.1f}s")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        # ValueError covers a malformed JSON body.
        entry = {"state": "failed", "lyrics": None, "at": time.time()}
        detail = f"HTTP {error.code}" if isinstance(error, urllib.error.HTTPError) else type(error).__name__
        log_event(f"{label}: FAILED ({detail}) after {time.time() - started:.1f}s")
    with _lock:
        _entries[uri] = entry


def lyrics_status(uri: str, track_name: str, artist_name: str, album_name: str, duration_s: int) -> dict:
    # Never blocks. Returns {"state": "loading"}, {"state": "failed"}, or
    # {"state": "done", "lyrics": {...} | None} (None = LRCLIB has nothing).
    # Poll it: the first call starts the lookup, later calls pick up the result.
    with _lock:
        entry = _entries.get(uri)
        stale_failure = (
            entry is not None
            and entry["state"] == "failed"
            and time.time() - entry["at"] > RETRY_AFTER_FAILURE_S
        )
        if entry is None or stale_failure:
            if len(_entries) >= MAX_ENTRIES:
                for old_uri in sorted(_entries, key=lambda key: _entries[key]["at"])[: MAX_ENTRIES // 10]:
                    if _entries[old_uri]["state"] != "loading":
                        del _entries[old_uri]
            entry = _entries[uri] = {"state": "loading", "lyrics": None, "at": time.time()}
            _executor.submit(_run_lookup, uri, (track_name, artist_name, album_name, duration_s))
        return dict(entry)


def current_line_index(synced: list[tuple[int, str]], progress_ms: float) -> int | None:
    # Index of the line being sung at progress_ms, or None before the first
    # line starts.
    index = bisect.bisect_right([start for start, _ in synced], progress_ms) - 1
    return index if index >= 0 else None
