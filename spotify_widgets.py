# Streamlit widgets shared by the Spotify page and the Overview page's
# Spotify tile (transport buttons, the seekable position slider). Lives
# apart from spotify_data.py because that module deliberately has no
# rendering calls, and apart from spotify_page.py because importing a page
# script runs its whole UI.
import datetime
import time
import urllib.error

import streamlit as st

from spotify_data import (
    live_progress_ms,
    next_track,
    no_active_device,
    pause,
    play,
    previous_track,
    seek,
)
from spotify_log import log_event


def run_control(action, *, success=None, rerun=True, rerun_scope="app", **kwargs) -> bool:
    # Toasts (not st.error/st.warning) because the callers re-run themselves
    # every second as fragments -- an inline message inside one would be
    # wiped a second later. A success rerun()s the whole app (so state shown
    # elsewhere refreshes too; rerun_scope="fragment" narrows that to the
    # calling fragment) unless `success` gives a message to toast in its
    # place, or `rerun=False` (needed inside widget callbacks, where
    # st.rerun() is a no-op). Returns whether the action succeeded.
    try:
        action(**kwargs)
    except urllib.error.HTTPError as error:
        if no_active_device(error):
            st.toast("Nothing playing right now -- open Spotify on a device first.", icon="⚠️")
        else:
            st.toast(f"Spotify couldn't do that right now (error {error.code}).", icon="⚠️")
        return False
    except (urllib.error.URLError, TimeoutError):
        st.toast("Couldn't reach Spotify right now.", icon="⚠️")
        return False
    if success:
        st.toast(success, icon="✅")
    elif rerun:
        st.rerun(scope=rerun_scope)
    return True


def render_transport_controls(playback: dict, key_prefix: str, icons_only: bool = False) -> None:
    # icons_only drops the text labels (tooltips keep the names) for narrow
    # spots like the Overview tile, where "Previous" got cut off as "Prev...".
    def label(icon: str, text: str) -> str:
        return icon if icons_only else f"{icon} {text}"

    columns = st.columns(3)
    with columns[0]:
        if st.button(label("⏮", "Previous"), key=f"{key_prefix}_previous", help="Previous", width="stretch"):
            run_control(previous_track)
    with columns[1]:
        if playback.get("is_playing"):
            if st.button(label("⏸", "Pause"), key=f"{key_prefix}_pause", help="Pause", width="stretch"):
                run_control(pause)
        else:
            if st.button(label("▶", "Play"), key=f"{key_prefix}_play", help="Play", width="stretch"):
                run_control(play)
    with columns[2]:
        if st.button(label("⏭", "Next"), key=f"{key_prefix}_next", help="Next", width="stretch"):
            run_control(next_track)


# st.slider can't format plain numbers as m:ss, but it can for datetime.time
# values -- so the position is carried as a time-of-day-style value
# (00:00 up to the track's length), which also puts real elapsed/total
# labels at the slider's ends instead of an unlabeled percentage bar.
def _to_time(ms: float) -> datetime.time:
    seconds = int(ms // 1000)
    return datetime.time(seconds // 3600, seconds % 3600 // 60, seconds % 60)


def _to_ms(value: datetime.time) -> int:
    return ((value.hour * 60 + value.minute) * 60 + value.second) * 1000


# How long a position the slider was placed at still counts as "recent" for
# telling stale echoes from real seeks (see _on_seek). Must exceed the worst
# lag between the server moving the slider and the browser having caught up.
_RECENT_POSITION_WINDOW_S = 12

# The fragment ticks about once a second (see spotify_page.py's now_playing);
# a gap much wider than that means it didn't run for a while -- most likely
# the tab was backgrounded (switched away to another app), since Streamlit
# pauses a fragment's auto-rerun while its page isn't the active one (see
# spotify_page.py's "Leaving the page stops the timer" note). Coming back
# from a gap like that, the browser's next reported slider value can be an
# echo of wherever it was frozen before the gap -- the same "stale echo read
# as a real seek" failure _on_seek already guards against below, just stale
# by longer than _RECENT_POSITION_WINDOW_S covers. See _on_seek's resume
# guard for how this is used.
_RESUME_GAP_THRESHOLD_S = 2.5


def _on_seek(key: str) -> None:
    position_ms = _to_ms(st.session_state[key])
    now = time.time()

    # A gap wider than a normal tick was just detected in render_seek_slider
    # (below), which re-armed this guard for one more window's worth of time.
    # Ignore outright, regardless of what position it claims: right after a
    # resume the report can't be trusted the way an in-page echo can, since
    # we don't know how long the browser was actually frozen for.
    if now < st.session_state.get(f"{key}_resume_guard_until", 0):
        log_event(f"seek ignored (post-resume echo): {key} reported {position_ms // 1000}s")
        return

    # This fires whenever the value the browser reports differs from the one
    # the server last set -- and the server moves the slider every second, so
    # a click on ANY other widget can report a position from a few ticks ago
    # (the browser's copy lags when the server is busy; 4.6s was observed on
    # Overview, which does more work per run). Without a check that reads as
    # the user dragging the slider back, and sends Spotify a real seek: an
    # audible glitch on whatever's playing, and a slider that jumps.
    #
    # A stale echo is always a second the slider was recently *placed* at;
    # a real drag to somewhere new almost never is. (Cost: a deliberate
    # backwards seek of less than the window is ignored -- forwards is fine.)
    recent_seconds = {
        second for second, placed_at in st.session_state.get(f"{key}_placed", [])
        if now - placed_at <= _RECENT_POSITION_WINDOW_S
    }
    ignored = position_ms // 1000 in recent_seconds
    if ignored:
        return
    if run_control(seek, rerun=False, position_ms=position_ms):
        log_event(f"seek: {key} -> {position_ms // 1000}s")
        st.session_state[f"{key}_seeked"] = (position_ms, time.time())


def _displayed_progress_ms(playback: dict, key: str) -> float:
    # Spotify's player state can lag a beat behind a seek it just accepted;
    # for a couple of seconds afterwards, trust the target over the fetch so
    # the slider doesn't snap back to the old spot before catching up.
    seeked = st.session_state.get(f"{key}_seeked")
    if seeked:
        target_ms, seeked_at = seeked
        elapsed = time.time() - seeked_at
        if elapsed < 2.5:
            return target_ms + (elapsed * 1000 if playback.get("is_playing") else 0)
    return live_progress_ms(playback)


def inject_seek_slider_styles(*keys: str) -> None:
    # During a page load the seek slider can visibly hop as it catches up to
    # the real position (the browser's copy trails the server's while the
    # page is busy). Blur and lock it for the duration instead, so it
    # reappears already at the right second.
    #
    # Two triggers, each with its own delay before the blur starts (leaving
    # it always fades back over 0.4s):
    #
    # 1. Streamlit's data-stale marker on the slider's element container --
    #    set only during a FULL page run (never during the 1s fragment
    #    refreshes), until the element is redrawn. Delay 0.3s, so a quick
    #    full rerun (e.g. after clicking pause) doesn't flash it.
    # 2. Any run at all (fragment refreshes included) that's still going
    #    after 1s. A normal refresh finishes in well under that, but a
    #    delayed one freezes the slider and then makes it leap; this covers
    #    that. It can't use the app-wide "script running" state alone with a
    #    short delay -- that made the slider flicker on ordinary refreshes
    #    (the 5s Spotify fetch alone takes ~0.3s) -- hence the long delay.
    #
    # Call once per page, outside any fragment, passing each seek slider's
    # key.
    base = ", ".join(f".st-key-{key}" for key in keys)
    running = ", ".join(
        f'[data-testid="stApp"][data-test-script-state="running"] .st-key-{key}' for key in keys
    )
    stale = ", ".join(f'.st-key-{key}[data-stale="true"]' for key in keys)
    st.markdown(
        f"""
        <style>
        {base} {{
            transition: filter 0.4s ease, opacity 0.4s ease;
        }}
        {running} {{
            filter: blur(4px);
            opacity: 0.5;
            pointer-events: none;
            transition: filter 0.25s ease 1s, opacity 0.25s ease 1s;
        }}
        {stale} {{
            filter: blur(4px);
            opacity: 0.5;
            pointer-events: none;
            transition: filter 0.25s ease 0.3s, opacity 0.25s ease 0.3s;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_seek_slider(playback: dict, key: str) -> None:
    duration_ms = (playback.get("item") or {}).get("duration_ms") or 0
    if not duration_ms:
        return
    # Written before the widget exists on this run, which is what lets the
    # timer move it -- the widget's own state would otherwise win.
    placed_ms = min(_displayed_progress_ms(playback, key), duration_ms)
    now = time.time()

    # Detect a gap since this slider's last tick (see _RESUME_GAP_THRESHOLD_S)
    # and arm _on_seek's resume guard if so, before anything below prunes or
    # extends the "placed" history -- the guard is what actually matters once
    # a gap like that has happened, not what's left in that history.
    last_render_at = st.session_state.get(f"{key}_last_render_at")
    if last_render_at is not None and now - last_render_at > _RESUME_GAP_THRESHOLD_S:
        st.session_state[f"{key}_resume_guard_until"] = now + _RECENT_POSITION_WINDOW_S
    st.session_state[f"{key}_last_render_at"] = now

    st.session_state[f"{key}_placed"] = [
        (second, placed_at) for second, placed_at in st.session_state.get(f"{key}_placed", [])
        if now - placed_at <= _RECENT_POSITION_WINDOW_S
    ] + [(int(placed_ms // 1000), now)]
    st.session_state[key] = _to_time(placed_ms)
    st.slider(
        "Position",
        min_value=datetime.time(0, 0, 0),
        max_value=_to_time(duration_ms),
        step=datetime.timedelta(seconds=1),
        format="HH:mm:ss" if duration_ms >= 3_600_000 else "mm:ss",
        key=key,
        on_change=_on_seek,
        args=(key,),
        label_visibility="collapsed",
    )
