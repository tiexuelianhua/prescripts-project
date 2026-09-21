# The app's own record of what it has seen play, used to fill gaps in
# Spotify's "recently played" list. Spotify's API list leaves out some plays
# that its own apps' history shows (observed 2026-09-21: two tracks skipped
# after ~83s and ~1s were missing from the API for 5+ minutes while later
# tracks appeared), and the docs say nothing about which plays are omitted.
#
# Every fresh /me/player fetch calls record_observation() (see
# spotify_data.current_playback), so plays are captured whichever page is
# open. Only plays seen while the app was running and polling are recorded --
# this fills gaps, it isn't a complete history. Like spotify_data.py, no
# Streamlit rendering calls.
#
# Stored in Spotify/observed_plays.json next to the credentials (outside the
# git repo), newest MAX_ENTRIES kept.
import datetime as dt
import json
import threading
import time

from prescripts_common import SCRIPTS_DIR

HISTORY_PATH = SCRIPTS_DIR.parent / "Spotify" / "observed_plays.json"
MAX_ENTRIES = 200
# If the app hasn't looked at the player for longer than this, what it last
# saw is no longer trustworthy (the page was closed mid-song): the previous
# track is dropped instead of recorded with a stale end time and position.
MAX_GAP_S = 30
# The same track reappearing with its position this far back means it was
# replayed, not continued.
REPLAY_JUMP_S = 10
# Plays shorter than this aren't recorded.
MIN_LISTENED_S = 1
# An observed play counts as the same one Spotify already lists if it's the
# same track and the end times are within this many seconds (Spotify's
# played_at is when the play ended; ours is when we last saw it, a few
# seconds of polling granularity earlier).
DUPLICATE_WINDOW_S = 30
# A play counts as "skipped" (and says where) if it stopped this many seconds
# or more before the track's end.
SKIPPED_MARGIN_S = 8

_lock = threading.Lock()
_current: dict | None = None      # the track being watched right now
_plays: list[dict] | None = None  # loaded lazily; newest last


def _load() -> list[dict]:
    global _plays
    if _plays is None:
        try:
            _plays = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _plays = []
    return _plays


def _save(plays: list[dict]) -> None:
    try:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_PATH.write_text(json.dumps(plays[-MAX_ENTRIES:], ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass  # losing a history entry must never break the page


def _iso(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse(iso: str) -> dt.datetime:
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _finish(current: dict) -> None:
    # Caller holds _lock.
    if current["progress_s"] < MIN_LISTENED_S:
        return
    plays = _load()
    plays.append({
        "uri": current["uri"],
        "name": current["name"],
        "artists": current["artists"],
        "duration_s": current["duration_s"],
        "listened_s": round(current["progress_s"]),
        "ended_at": _iso(current["last_seen"]),
    })
    del plays[:-MAX_ENTRIES]
    _save(plays)


def record_observation(playback: dict | None) -> None:
    global _current
    item = (playback or {}).get("item")
    uri = (item or {}).get("uri") or ""
    # Episodes aren't in Spotify's recently-played list either; local files
    # have no library state to show like buttons for.
    if not item or item.get("type") == "episode" or not uri or uri.startswith("spotify:local:"):
        return

    now = playback.get("fetched_at") or time.time()
    progress_s = (playback.get("progress_ms") or 0) / 1000
    with _lock:
        current = _current
        trustworthy = current is not None and now - current["last_seen"] <= MAX_GAP_S
        if trustworthy and current["uri"] == uri and progress_s >= current["progress_s"] - REPLAY_JUMP_S:
            current["last_seen"] = now
            current["progress_s"] = max(current["progress_s"], progress_s)
            return
        if trustworthy:
            _finish(current)
        _current = {
            "uri": uri,
            "name": item["name"],
            "artists": [artist["name"] for artist in item.get("artists", [])],
            "duration_s": round((item.get("duration_ms") or 0) / 1000),
            "progress_s": progress_s,
            "last_seen": now,
        }


def _format_position(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def merge_with_api(api_items: list[dict], limit: int = 10) -> list[dict]:
    # api_items: Spotify's recently-played items ({"track", "played_at"}),
    # newest first. Returns up to `limit` items in the same shape, with the
    # app's own observed plays that Spotify's list doesn't have mixed in by
    # end time. Observed-only items carry "skipped_at" (a "m:ss" position)
    # when they stopped before the track's end.
    with _lock:
        observed = list(_load())

    api_times = [(item["track"]["uri"], _parse(item["played_at"])) for item in api_items]
    # Older than Spotify's oldest listed play would just push the list past
    # what Spotify was asked for; only fill in gaps within its window.
    oldest = min((played_at for _, played_at in api_times), default=None)

    extras = []
    for play in observed:
        ended_at = _parse(play["ended_at"])
        if oldest is not None and ended_at < oldest:
            continue
        if any(
            uri == play["uri"] and abs((ended_at - played_at).total_seconds()) <= DUPLICATE_WINDOW_S
            for uri, played_at in api_times
        ):
            continue
        stopped_early = play["listened_s"] < play["duration_s"] - SKIPPED_MARGIN_S
        extras.append({
            "track": {
                "name": play["name"],
                "uri": play["uri"],
                "artists": [{"name": name} for name in play["artists"]],
                "type": "track",
            },
            "played_at": play["ended_at"],
            "skipped_at": _format_position(play["listened_s"]) if stopped_early else None,
        })

    merged = api_items + extras
    merged.sort(key=lambda item: _parse(item["played_at"]), reverse=True)
    return merged[:limit]
