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
    is_read_only,
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
    #
    # Every call is logged: this is the single choke point every transport
    # control (Next/Previous/Play/Pause, Like/Unlike, volume, shuffle, Play
    # again, Add to queue) and the seek slider all go through, so it's the
    # one place that can answer "did the app actually do this, and why" --
    # e.g. a track skip with no button click behind it in the log points at
    # a spurious call here rather than something on Spotify's own side.
    call = f"{action.__name__}({', '.join(f'{k}={v}' for k, v in kwargs.items())})"
    # Belt-and-suspenders backstop for Read-only mode: every call site that
    # can act on playback also checks page_is_locked() before even rendering
    # itself as clickable (so this shouldn't normally be reachable while
    # locked), but this catches it regardless of whether a call site forgot,
    # rather than depending on every one of them getting it right.
    if is_read_only():
        log_event(f"control blocked (read-only mode): {call}")
        st.toast("Read-only mode is on -- turn it off on the Spotify page to control playback.", icon="🔒")
        return False
    try:
        action(**kwargs)
    except urllib.error.HTTPError as error:
        if no_active_device(error):
            log_event(f"control failed: {call} -- no active device")
            st.toast("Nothing playing right now -- open Spotify on a device first.", icon="⚠️")
        else:
            log_event(f"control failed: {call} -- HTTP {error.code}")
            st.toast(f"Spotify couldn't do that right now (error {error.code}).", icon="⚠️")
        return False
    except (urllib.error.URLError, TimeoutError):
        log_event(f"control failed: {call} -- unreachable")
        st.toast("Couldn't reach Spotify right now.", icon="⚠️")
        return False
    log_event(f"control: {call}")
    if success:
        st.toast(success, icon="✅")
    elif rerun:
        st.rerun(scope=rerun_scope)
    return True


def page_is_locked(key_prefix: str) -> bool:
    # Call once per fragment run, before rendering any of that fragment's
    # controls -- render_transport_controls/render_seek_slider/etc. take the
    # result rather than each computing their own, so a page's worth of
    # controls agree on whether this particular render is trustworthy.
    #
    # Two ways in: the user's own Read-only mode toggle (persisted, not just
    # session state -- survives a restart, which is exactly the situation it
    # exists for), or the same auto-detected "this render followed a gap
    # since the last confirmed tick" signal _on_seek uses for the seek
    # slider specifically (see its docstring for the full reasoning) --
    # generalized here to cover every other control too (Play/Pause/Next/
    # Previous, Like, volume, shuffle). None of those have their own proven
    # vulnerability the way the slider's persisted-value-plus-callback design
    # did, but they can all act on the same live Spotify stream, so the same
    # "don't trust a render that just woke up from a gap" caution applies --
    # simplest to enforce by not rendering them as interactive at all for a
    # short cooldown after such a gap, same as the slider does.
    if is_read_only():
        return True
    now = time.time()
    last_tick_at = st.session_state.get(f"{key_prefix}_last_tick_at")
    gap = now - last_tick_at if last_tick_at is not None else None
    st.session_state[f"{key_prefix}_last_tick_at"] = now
    locked_until = st.session_state.get(f"{key_prefix}_locked_until", 0)
    if gap is not None and gap > _RESUME_GAP_THRESHOLD_S:
        locked_until = max(locked_until, now + _RECENT_POSITION_WINDOW_S)
        st.session_state[f"{key_prefix}_locked_until"] = locked_until
    return now < locked_until


def render_transport_controls(
    playback: dict, key_prefix: str, icons_only: bool = False, locked: bool = False
) -> None:
    if locked:
        st.caption("▶ Playing" if playback.get("is_playing") else "⏸ Paused")
        return

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
# the tab was backgrounded (switched away to another app, or just left in a
# background tab -- confirmed 2026-09-21: browsers throttle a backgrounded
# tab's timers to roughly once a minute, "intensive throttling", which lines
# up with repeated skips landing on an almost exact 60s cadence with no
# interaction at all). Coming back from a gap like that, the browser's next
# reported slider value can be an echo of wherever it was frozen before the
# gap -- the same "stale echo read as a real seek" failure guarded against
# below, just stale by longer than _RECENT_POSITION_WINDOW_S covers.
_RESUME_GAP_THRESHOLD_S = 2.5


def _on_seek(key: str) -> None:
    position_ms = _to_ms(st.session_state[key])
    now = time.time()

    # Two ways a resume gap gets caught, both needed:
    #
    # 1. A guard armed by an EARLIER call this same wake-up (below, or by a
    #    previous render) still active -- covers the 2nd+ stale echo in a
    #    burst of several arriving close together.
    # 2. Checking the gap since the slider's own last confirmed tick
    #    *directly*, right here -- covers the FIRST stale echo of a new
    #    wake-up, which can arrive and be processed before render_seek_slider
    #    gets a chance to run and notice the gap itself (Streamlit runs a
    #    widget's callback before the rest of that rerun's script body, so
    #    waiting for the render to notice and arm the guard is always one
    #    callback too late for whichever message discovers the gap first).
    #    This was the actual gap in the first version of this guard: bursts
    #    got caught, but an isolated single echo after a fresh ~60s
    #    throttled wake-up did not (confirmed from two live skips this
    #    session with no render in between to have armed anything).
    #
    # Either way, arm/extend the guard so anything else in this same wake-up
    # is covered too, regardless of which message happens to notice first.
    last_render_at = st.session_state.get(f"{key}_last_render_at")
    gap = now - last_render_at if last_render_at is not None else None
    guarded = now < st.session_state.get(f"{key}_resume_guard_until", 0)
    if guarded or (gap is not None and gap > _RESUME_GAP_THRESHOLD_S):
        st.session_state[f"{key}_resume_guard_until"] = max(
            st.session_state.get(f"{key}_resume_guard_until", 0), now + _RECENT_POSITION_WINDOW_S
        )
        reason = "post-resume guard" if guarded else f"{gap:.0f}s since last tick"
        log_event(f"seek ignored ({reason}): {key} reported {position_ms // 1000}s")
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


def _format_elapsed(ms: float, duration_ms: float) -> str:
    fmt = "%H:%M:%S" if duration_ms >= 3_600_000 else "%M:%S"
    return _to_time(ms).strftime(fmt)


def render_seek_slider(playback: dict, key: str, locked: bool = False) -> None:
    duration_ms = (playback.get("item") or {}).get("duration_ms") or 0
    if not duration_ms:
        return
    # Written before the widget exists on this run, which is what lets the
    # timer move it -- the widget's own state would otherwise win.
    placed_ms = min(_displayed_progress_ms(playback, key), duration_ms)

    if locked:
        # A plain progress bar and caption, not st.slider -- while locked
        # there's no interactive widget here at all, not just a disabled-
        # looking one, so there's nothing left for a stale echo to even be
        # read against (see page_is_locked).
        st.progress(placed_ms / duration_ms)
        st.caption(f"{_format_elapsed(placed_ms, duration_ms)} / {_format_elapsed(duration_ms, duration_ms)}")
        return

    now = time.time()
    # The slider's own "last confirmed tick" clock -- _on_seek reads this
    # directly to catch a stale echo the moment it arrives, rather than
    # waiting for this render to notice the same gap (see _on_seek).
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
