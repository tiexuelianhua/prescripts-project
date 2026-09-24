# Data/business logic for the Spotify page -- OAuth token handling and the
# Web API's REST calls, deliberately with no Streamlit *rendering* calls
# (st.cache_data is fine, it's just a caching decorator with no UI output).
# That separation means other pages (e.g. an Overview page wanting "what's
# playing") can import and call these directly without accidentally
# triggering spotify_page.py's own UI as a side effect of the import.
#
# Remote control, not in-page streaming: this only ever calls the plain Web
# API (including its /me/player control endpoints), never the Web Playback
# SDK (a separate JavaScript library for actually streaming audio through
# the page itself) -- decided against that so this page stays pure Python/
# Streamlit, consistent with every other page's architecture. Playback
# controls here act on whichever Spotify device (phone, desktop app,
# another browser tab) is already active elsewhere.
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

from play_history import record_observation
from prescripts_common import SCRIPTS_DIR
from spotify_log import SLOW_THRESHOLD_S, log_event

SPOTIFY_DIR = SCRIPTS_DIR.parent / "Spotify"
SETTINGS_PATH = SPOTIFY_DIR / "settings.json"

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"
# Spotify requires an explicit loopback IP literal, not the hostname
# "localhost" (a 2026 security tightening -- prevents hostname-hijacking
# attacks on the OAuth callback). Port matches the desktop launcher's actual
# `streamlit run app.py` with no port configured, so Streamlit's default.
# The path must be this page's own URL -- Streamlit's multipage routing
# sends a bare-root request to whichever page has default=True (Home), and
# only this page's script ever looks at st.query_params for the OAuth
# callback, so landing on the bare root silently drops the code. The path
# itself ("spotify_page") is inferred by Streamlit from this file's name
# (spotify_page.py); this must be kept in sync if the file is ever renamed.
REDIRECT_URI = "http://127.0.0.1:8501/spotify_page"
# Least-privilege: only what this page (currently playing, playback control,
# queue, recently played, playlists, liked songs) actually uses.
SCOPES = [
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "user-read-recently-played",
    "playlist-read-private",
    "user-library-read",
    "user-library-modify",
]


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return {}


def save_settings(settings: dict) -> None:
    SPOTIFY_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def is_configured() -> bool:
    settings = load_settings()
    return bool(settings.get("client_id")) and bool(settings.get("client_secret"))


def is_connected() -> bool:
    return bool(load_settings().get("refresh_token"))


# Persisted (not just session state) on purpose: this is meant to survive an
# app restart/reload, which is exactly the situation it exists to guard --
# see spotify_widgets.py's read-only rendering.
def is_read_only() -> bool:
    return bool(load_settings().get("read_only"))


def set_read_only(value: bool) -> None:
    settings = load_settings()
    settings["read_only"] = value
    save_settings(settings)


def authorize_url() -> str:
    settings = load_settings()
    params = {
        "client_id": settings["client_id"],
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        # Otherwise a previously-granted scope set is reused silently even
        # after SCOPES above has grown -- forces the consent screen to
        # actually reflect what this app currently asks for.
        "show_dialog": "true",
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def _token_request(body: dict) -> dict:
    # Spotify's token endpoint authenticates the app via HTTP Basic auth
    # (base64 "client_id:client_secret"), not as body parameters -- sending
    # them in the body instead (an earlier bug here) gets silently rejected.
    settings = load_settings()
    credentials = f"{settings['client_id']}:{settings['client_secret']}"
    basic_auth = base64.b64encode(credentials.encode()).decode()
    request = urllib.request.Request(
        TOKEN_URL, data=urllib.parse.urlencode(body).encode(), method="POST"
    )
    request.add_header("Authorization", f"Basic {basic_auth}")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode())


def exchange_code_for_tokens(code: str) -> None:
    token_data = _token_request({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    })
    settings = load_settings()
    settings["access_token"] = token_data["access_token"]
    settings["refresh_token"] = token_data["refresh_token"]
    settings["token_expires_at"] = time.time() + token_data["expires_in"]
    save_settings(settings)


def disconnect() -> None:
    settings = load_settings()
    for key in ("access_token", "refresh_token", "token_expires_at"):
        settings.pop(key, None)
    save_settings(settings)


def _valid_access_token() -> str:
    settings = load_settings()
    # 60s safety margin so a token that's about to expire mid-request still
    # gets refreshed first, rather than failing the request that follows.
    if time.time() >= settings.get("token_expires_at", 0) - 60:
        token_data = _token_request({
            "grant_type": "refresh_token",
            "refresh_token": settings["refresh_token"],
        })
        settings["access_token"] = token_data["access_token"]
        # Spotify doesn't always issue a new refresh_token on refresh --
        # keep the existing one when it doesn't.
        if "refresh_token" in token_data:
            settings["refresh_token"] = token_data["refresh_token"]
        settings["token_expires_at"] = time.time() + token_data["expires_in"]
        save_settings(settings)
    return settings["access_token"]


def _api_request(method: str, path: str, params: dict | None = None, body: dict | None = None):
    token = _valid_access_token()
    url = f"{API_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            # A 204 (no active playback session, or a control action that
            # succeeded with nothing to return) is meant to have an empty
            # body, but in practice control endpoints (observed: pause) can
            # come back with whitespace or a non-JSON body even on success.
            # So only parse when the response says it's JSON, and treat an
            # unparseable body as "nothing to return" rather than failing an
            # action that worked.
            raw = response.read().strip()
            result = None
            if raw and "json" in response.headers.get("Content-Type", ""):
                try:
                    result = json.loads(raw)
                except json.JSONDecodeError:
                    result = None
    except urllib.error.HTTPError as error:
        log_event(f"Spotify API error: {method} {path} -> HTTP {error.code} after {time.time() - started:.2f}s")
        raise
    except (urllib.error.URLError, TimeoutError) as error:
        log_event(
            f"Spotify API unreachable: {method} {path} ({type(error).__name__}) "
            f"after {time.time() - started:.2f}s"
        )
        raise
    elapsed = time.time() - started
    if elapsed > SLOW_THRESHOLD_S:
        log_event(f"slow: Spotify API {method} {path} took {elapsed:.2f}s")
    return result


@st.cache_data(ttl=5)
def current_playback() -> dict | None:
    # Short ttl -- this is meant to feel live, not cached like a forecast.
    playback = _api_request("GET", "/me/player")
    if playback:
        # Stamped inside the cached function so it's frozen alongside
        # progress_ms -- live_progress_ms() below needs to know how old the
        # reported position is, and a cache hit shouldn't reset that clock.
        playback["fetched_at"] = time.time()
        # Runs once per real fetch (this function is cached), so plays are
        # captured whichever page is open. See play_history.py.
        record_observation(playback)
    return playback


def live_progress_ms(playback: dict) -> float:
    # Spotify only reports progress at fetch time, so between fetches this
    # extrapolates forward by the wall-clock time since (only while actually
    # playing -- a paused track's position doesn't move).
    progress = playback.get("progress_ms") or 0
    if playback.get("is_playing") and "fetched_at" in playback:
        progress += (time.time() - playback["fetched_at"]) * 1000
    duration = (playback.get("item") or {}).get("duration_ms") or 0
    return min(progress, duration) if duration else progress


def format_ms(ms: float) -> str:
    seconds = int(ms // 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"


def describe_item(item: dict) -> dict:
    # A podcast episode has no "artists" field at all (it has a "show"
    # instead) -- item["artists"] would KeyError the moment anything other
    # than a music track is playing.
    if item.get("type") == "episode":
        artists = item.get("show", {}).get("name", "")
    else:
        artists = ", ".join(artist["name"] for artist in item.get("artists", []))
    images = item.get("album", {}).get("images") or item.get("images", [])
    return {
        "name": item["name"],
        "artists": artists,
        # Smallest listed image is still plenty for the tile sizes used --
        # images are ordered largest-first.
        "image_url": images[-1]["url"] if images else None,
        "duration_ms": item.get("duration_ms") or 0,
    }


@st.cache_data(ttl=10)
def recently_played(limit: int = 10) -> list[dict]:
    result = _api_request("GET", "/me/player/recently-played", params={"limit": limit})
    return (result or {}).get("items", [])


@st.cache_data(ttl=60)
def playlists(limit: int = 20) -> list[dict]:
    result = _api_request("GET", "/me/playlists", params={"limit": limit})
    return (result or {}).get("items", [])


@st.cache_data(ttl=2)
def current_queue() -> list[dict]:
    # Short ttl (under the page's 3s refresh, so every refresh is fresh) for
    # the same reason as current_playback(). Spotify's
    # "queue" is what's up next (user-queued tracks first, then the rest of
    # the current context) and excludes the track playing right now.
    result = _api_request("GET", "/me/player/queue")
    return (result or {}).get("queue", [])


@st.cache_data(ttl=120)
def is_saved(uri: str) -> bool | None:
    # None (not False) when Spotify refuses with a 403 -- the token predates
    # the user-library-* scopes and needs a reconnect -- so the page can say
    # so instead of offering a Like button that can't work. Returned rather
    # than raised because st.cache_data doesn't cache exceptions, which
    # would mean re-hitting Spotify on every fragment tick (once a second).
    try:
        result = _api_request("GET", "/me/library/contains", params={"uris": uri})
    except urllib.error.HTTPError as error:
        if error.code == 403:
            return None
        raise
    return bool(result and result[0])


@st.cache_data(ttl=60)
def saved_flags(uris: tuple[str, ...]) -> list[bool] | None:
    # One request for a whole list (Spotify caps it at 40) -- the queue view
    # needs a saved/not-saved state per row, and a call per row would be ~15
    # requests every refresh. None on 403 for the same reason as is_saved().
    if not uris:
        return []
    try:
        result = _api_request("GET", "/me/library/contains", params={"uris": ",".join(uris[:40])})
    except urllib.error.HTTPError as error:
        if error.code == 403:
            return None
        raise
    return [bool(flag) for flag in (result or [])]


def save_item(uri: str) -> None:
    _api_request("PUT", "/me/library", params={"uris": uri})
    is_saved.clear()
    saved_flags.clear()


def unsave_item(uri: str) -> None:
    _api_request("DELETE", "/me/library", params={"uris": uri})
    is_saved.clear()
    saved_flags.clear()


def _clear_playback_cache() -> None:
    current_playback.clear()
    # Skipping, replaying, and queueing all change what's up next.
    current_queue.clear()


def play() -> None:
    _api_request("PUT", "/me/player/play")
    _clear_playback_cache()


def play_track(uri: str) -> None:
    _api_request("PUT", "/me/player/play", body={"uris": [uri]})
    _clear_playback_cache()


class NotInQueue(LookupError):
    """The track a queue row pointed at has left the queue since it was shown."""


def skip_to_queued(uri: str, position: int) -> None:
    # Plays a queued track now by skipping forward to it, the way Spotify's
    # own apps do when you tap a queued song: the songs ahead of it are
    # dropped, everything after it stays. play_track() isn't usable here --
    # a `uris` body replaces the whole playback context with that one track,
    # wiping out the rest of the queue.
    #
    # `position` is the 1-based row the button was shown on. The queue is
    # re-read fresh first: if it shifted since render (a song ended, an edit
    # from another device), skip to wherever that track is now -- the row
    # shown if it's still there (the same song can be queued twice), else
    # its first occurrence -- rather than blindly skipping `position` times.
    queue = (_api_request("GET", "/me/player/queue") or {}).get("queue", [])
    uris = [item.get("uri") for item in queue]
    if position <= len(uris) and uris[position - 1] == uri:
        skips = position
    elif uri in uris:
        skips = uris.index(uri) + 1
    else:
        raise NotInQueue(uri)
    for _ in range(skips):
        _api_request("POST", "/me/player/next")
    _clear_playback_cache()
    current_queue.clear()


def add_to_queue(uri: str) -> None:
    _api_request("POST", "/me/player/queue", params={"uri": uri})
    current_queue.clear()


def seek(position_ms: int) -> None:
    _api_request("PUT", "/me/player/seek", params={"position_ms": position_ms})
    _clear_playback_cache()


def pause() -> None:
    _api_request("PUT", "/me/player/pause")
    _clear_playback_cache()


def next_track() -> None:
    _api_request("POST", "/me/player/next")
    _clear_playback_cache()


def previous_track() -> None:
    _api_request("POST", "/me/player/previous")
    _clear_playback_cache()


def set_volume(percent: int) -> None:
    _api_request("PUT", "/me/player/volume", params={"volume_percent": percent})
    _clear_playback_cache()


def set_shuffle(state: bool) -> None:
    _api_request("PUT", "/me/player/shuffle", params={"state": "true" if state else "false"})
    _clear_playback_cache()


def no_active_device(error: urllib.error.HTTPError) -> bool:
    # Spotify's control endpoints (play/pause/next/...) 404 with this reason
    # when nothing's currently active on any device -- worth telling apart
    # from a real failure so the page can say "open Spotify somewhere
    # first" instead of a generic error.
    if error.code != 404:
        return False
    try:
        body = json.loads(error.read().decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return body.get("error", {}).get("reason") == "NO_ACTIVE_DEVICE"
