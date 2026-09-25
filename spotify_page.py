# Spotify page: currently playing + remote playback control (play/pause/
# skip/volume/shuffle on whichever device is already active elsewhere),
# lyrics, recently played (replay / add to queue), and playlists (embedded)
# -- via Spotify's plain Web API, not the Web Playback SDK (see spotify_data.py's
# module docstring for why).
import html
import time
import urllib.error

import streamlit as st

from lyrics_data import current_line_index, lyrics_status
from play_history import merge_with_api
from prescripts_common import inject_body_fade_in, render_page_title, show_logo, theme_colors
from spotify_data import (
    add_to_queue,
    authorize_url,
    current_playback,
    current_queue,
    describe_item,
    disconnect,
    exchange_code_for_tokens,
    is_configured,
    is_connected,
    is_read_only,
    is_saved,
    live_progress_ms,
    play_track,
    playlists,
    recently_played,
    save_item,
    saved_flags,
    set_read_only,
    set_shuffle,
    set_volume,
    skip_to_queued,
    unsave_item,
)
from spotify_log import log_event, log_slow
from spotify_widgets import (
    inject_seek_slider_styles,
    page_is_locked,
    render_seek_slider,
    render_transport_controls,
    run_control,
)

run_started = time.time()
TEXT_COLOR, ACCENT_COLOR = theme_colors()
PAGE_TITLE = "Spotify"
# Height (px) of the queue's scroll box, matching the Now playing block beside it
# (measured at about 330px).
QUEUE_BOX_HEIGHT = 330

is_first_load = "_spotify_title_played" not in st.session_state
inject_body_fade_in("main_body")

header_logo, header_title = st.columns([1, 4], vertical_alignment="center")
with header_logo:
    show_logo(width=120)
with header_title:
    render_page_title(PAGE_TITLE, is_first_load)

if is_first_load:
    st.session_state["_spotify_title_played"] = True

if not is_configured():
    st.error(
        "No Spotify app credentials found -- add \"client_id\" and "
        "\"client_secret\" to Spotify/settings.json (a sibling of the "
        "Meal Receipts/Weather data folders, outside this git repo)."
    )
    st.stop()

# Spotify redirects back here with ?code=... after the user approves on its
# own site -- caught before anything else renders, exchanged once, then the
# code is dropped from the URL (st.query_params.clear()) so refreshing the
# page or any later rerun doesn't try to reuse an already-spent code --
# cleared *before* attempting the exchange (not after) so a failed attempt
# doesn't leave the same dead code sitting in the URL for every later rerun
# to keep retrying uselessly (authorization codes are single-use).
auth_code = st.query_params.get("code")
if auth_code and not is_connected():
    st.query_params.clear()
    try:
        exchange_code_for_tokens(auth_code)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        st.error(f"Couldn't complete the Spotify connection (HTTP {error.code}): {detail}")
        st.stop()
    except (urllib.error.URLError, TimeoutError) as error:
        st.error(f"Couldn't reach Spotify to complete the connection: {error}")
        st.stop()
    st.rerun()

with st.container(key="main_body"):
    if not is_connected():
        st.write("Connect your Spotify account to see what's playing and control it from here.")
        st.link_button("Connect to Spotify", authorize_url())
    else:
        with st.sidebar:
            st.header("Settings")
            read_only = st.toggle(
                "Read-only mode",
                value=is_read_only(),
                help=(
                    "Turns every control here and on the Overview tile into a plain display -- "
                    "no seek slider, buttons, volume, or shuffle -- so nothing here can ever send "
                    "a command to your Spotify playback. Useful if you're going to leave this open "
                    "and unattended for a while. Persists across restarts."
                ),
            )
            if read_only != is_read_only():
                set_read_only(read_only)
                st.rerun()
            if st.button("Disconnect Spotify"):
                disconnect()
                st.rerun()

        inject_seek_slider_styles("spotify_page_seek")
        # The icon-only heart buttons (beside the song title, and in the
        # queue / Recently played rows) and the queue's play buttons drop the app-wide outlined-button
        # look so they read as plain icons. They also sit in narrow columns,
        # where the default button padding is wider than the column and
        # clipped the heart, hence the zero side padding.
        st.markdown(
            """
            <style>
            .st-key-spotify_page_like button,
            .st-key-spotify_page_unlike button,
            [class*="st-key-queue_like_"] button,
            [class*="st-key-queue_play_"] button,
            [class*="st-key-recent_like_"] button {
                border: none;
                box-shadow: none;
                padding-left: 0;
                padding-right: 0;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        # Re-runs just this section every second: the position is
        # extrapolated locally between the (5s-cached) API fetches, so the
        # bar moves smoothly and a track change shows up on its own. Leaving
        # the page stops the timer -- nothing polls in the background.
        @st.fragment(run_every=1)
        @log_slow("Spotify page now_playing refresh")
        def now_playing() -> None:
            try:
                playback = current_playback()
            except (urllib.error.URLError, TimeoutError):
                st.error("Couldn't reach Spotify's player right now.")
                return

            if not playback or not playback.get("item"):
                st.caption("Nothing playing right now -- open Spotify on a device (phone, desktop app, etc.) first.")
                return

            # Once per fragment run, before anything below that could act on
            # playback -- see page_is_locked for what this covers and why.
            locked = page_is_locked("spotify_page")

            track = describe_item(playback["item"])
            item_uri = playback["item"].get("uri")

            # A song change is when the queue shrinks and Recently played
            # gains a row -- drop their caches right then so the open lists
            # pick it up on their next refresh instead of waiting out the TTL.
            if st.session_state.get("spotify_last_item_uri") != item_uri:
                if "spotify_last_item_uri" in st.session_state:
                    current_queue.clear()
                    recently_played.clear()
                    # For working out which plays Spotify counts toward
                    # Recently played: how long the previous track had been
                    # playing when it changed (as of the last refresh).
                    previous = st.session_state.get("spotify_last_track_info")
                    if previous:
                        log_event(
                            f'track changed: "{previous[0]}" left after ~{previous[1]}s of {previous[2]}s '
                            f'-> "{track["name"]}"'
                        )
                st.session_state["spotify_last_item_uri"] = item_uri
            st.session_state["spotify_last_track_info"] = (
                track["name"],
                round(live_progress_ms(playback) / 1000),
                round(track["duration_ms"] / 1000),
            )

            try:
                saved = is_saved(item_uri) if item_uri else False
                like_checked = True
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
                # Local files and anything else Spotify won't check just
                # don't get a Like button; not worth an error for.
                saved = False
                like_checked = False

            now_playing_columns = st.columns([1, 3])
            with now_playing_columns[0]:
                if track["image_url"]:
                    st.image(track["image_url"], width=100)
            with now_playing_columns[1]:
                # Same icon button as the queue / Recently played rows, at
                # the right end of the title line.
                title_column, like_column = st.columns([6, 1], vertical_alignment="center")
                with title_column:
                    st.markdown(f"**{track['name']}**")
                    st.caption(track["artists"])
                if like_checked and item_uri and saved is not None:
                    with like_column:
                        if locked:
                            st.caption("💚" if saved else "🤍")
                        elif saved:
                            if st.button("💚", key="spotify_page_unlike", help="Liked -- click to remove"):
                                run_control(unsave_item, uri=item_uri)
                        else:
                            if st.button("🤍", key="spotify_page_like", help="Add to Liked Songs"):
                                run_control(save_item, uri=item_uri)
                # Real elapsed/total time (00:00 .. track length) rather than
                # a bare percentage bar, and draggable to seek (unless locked).
                render_seek_slider(playback, "spotify_page_seek", locked=locked)

            if locked:
                st.caption("🔒 Read-only right now -- controls are hidden (see the sidebar).")

            render_transport_controls(playback, "spotify_page", locked=locked)

            device = playback.get("device") or {}
            current_volume = device.get("volume_percent")
            # Some Spotify Connect devices don't report a volume at all --
            # comparing a slider's int value against None would never be
            # equal, silently pushing "set volume to 0" on every single
            # rerun (any button click anywhere on the page), so the control
            # just doesn't render rather than guessing a default to push.
            if current_volume is not None:
                if locked:
                    st.caption(f"🔊 Volume: {current_volume}%")
                else:
                    volume = st.slider("Volume", min_value=0, max_value=100, value=current_volume)
                    if volume != current_volume:
                        run_control(set_volume, percent=volume)

            if locked:
                st.caption(f"🔀 Shuffle: {'On' if playback.get('shuffle_state') else 'Off'}")
            else:
                shuffle_on = st.toggle("Shuffle", value=bool(playback.get("shuffle_state")))
                if shuffle_on != bool(playback.get("shuffle_state")):
                    run_control(set_shuffle, state=shuffle_on)

            if saved is None:
                st.caption(
                    "Reconnect Spotify (Disconnect in the sidebar, then Connect) "
                    "to enable Liked Songs."
                )

        # Queue: shown beside Now playing, always (no expander), refreshing
        # itself every 3s -- it changes on song boundaries and when it's edited
        # from another device, not continuously. In a fixed-height scroll box
        # so a long queue scrolls instead of stretching the row.
        @st.fragment(run_every=3)
        @log_slow("Spotify page queue_view refresh")
        def queue_view() -> None:
            try:
                queue_items = current_queue()
            except (urllib.error.URLError, TimeoutError):
                st.error("Couldn't reach Spotify right now.")
                return
            except urllib.error.HTTPError as error:
                st.error(f"Spotify couldn't load the queue (error {error.code}).")
                return

            if not queue_items:
                st.caption("Nothing queued up.")
                return
            # Own tick cadence (run_every=3), so its own page_is_locked()
            # call -- shares "spotify_page" with now_playing, since a
            # background-tab gap affects every fragment on this page at once.
            locked = page_is_locked("spotify_page")
            shown = queue_items[:15]
            uris = tuple(queued["uri"] for queued in shown)
            try:
                flags = saved_flags(uris)
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
                flags = None  # no Like buttons, but the list still shows
            # None = token lacks the library scopes (see now_playing's
            # reconnect note); a length mismatch = Spotify returned
            # something unexpected. Either way, skip the buttons.
            can_like = not locked and flags is not None and len(flags) == len(shown)

            with st.container(height=QUEUE_BOX_HEIGHT):
                for position, queued in enumerate(shown, start=1):
                    described = describe_item(queued)
                    row_text, row_play, row_like = st.columns([4, 1, 1], vertical_alignment="center")
                    with row_text:
                        st.markdown(
                            f"**{position}. {html.escape(described['name'])}**<br>"
                            f'<span style="opacity:0.6;font-size:0.85em">{html.escape(described["artists"])}</span>',
                            unsafe_allow_html=True,
                        )
                    if not locked:
                        with row_play:
                            # Skips forward to this song rather than playing
                            # it on its own, so the rest of the queue survives
                            # -- see skip_to_queued. Same uri-in-key reasoning
                            # as the Like button below.
                            if st.button("▶", key=f"queue_play_{position}_{queued['uri']}", help="Play now (skips the songs ahead of it)"):
                                run_control(skip_to_queued, uri=queued["uri"], position=position)
                    if can_like:
                        with row_like:
                            # Key carries the uri as well as the position: if
                            # the queue shifts between render and click, the
                            # stale button just vanishes instead of liking
                            # whatever slid into that slot.
                            key = f"queue_like_{position}_{queued['uri']}"
                            if flags[position - 1]:
                                if st.button("💚", key=key, help="Liked -- click to remove"):
                                    run_control(unsave_item, rerun_scope="fragment", uri=queued["uri"])
                            else:
                                if st.button("🤍", key=key, help="Add to Liked Songs"):
                                    run_control(save_item, rerun_scope="fragment", uri=queued["uri"])
            if len(queue_items) > len(shown):
                st.caption(f"...and {len(queue_items) - len(shown)} more")

        now_playing_column, queue_column = st.columns([3, 2])
        with now_playing_column:
            st.subheader("Now playing")
            now_playing()
        with queue_column:
            st.subheader("Queue")
            queue_view()

        # Lyrics come from LRCLIB (Spotify's API has none), looked up on a
        # background thread -- see lyrics_data.py -- so this only ever polls.
        # Ticks every second like Now playing so the current line follows the
        # song; the expander lives inside the fragment (state survives the
        # refreshes) and nothing is looked up while it's collapsed.
        @st.fragment(run_every=1)
        @log_slow("Spotify page lyrics_view refresh")
        def lyrics_view() -> None:
            lyrics_expander = st.expander("Lyrics", on_change="rerun")
            if not lyrics_expander.open:
                return
            with lyrics_expander:
                try:
                    playback = current_playback()
                except (urllib.error.URLError, TimeoutError):
                    st.caption("Couldn't reach Spotify's player right now.")
                    return
                item = (playback or {}).get("item")
                # Episodes are spoken word; local files have no Spotify uri.
                if not item or item.get("type") == "episode" or not item.get("uri"):
                    st.caption("Nothing playing that has lyrics.")
                    return

                artists = item.get("artists") or [{}]
                status = lyrics_status(
                    item["uri"],
                    item["name"],
                    artists[0].get("name", ""),
                    (item.get("album") or {}).get("name", ""),
                    round((item.get("duration_ms") or 0) / 1000),
                )
                if status["state"] == "loading":
                    st.caption("Looking up lyrics...")
                    return
                if status["state"] == "failed":
                    st.caption("Couldn't reach the lyrics service right now -- it'll retry in a minute.")
                    return
                lyrics = status["lyrics"]
                if lyrics is None:
                    st.caption("No lyrics found for this track.")
                    return
                if lyrics["instrumental"] and not lyrics["plain"]:
                    st.caption("Instrumental.")
                    return

                synced = lyrics["synced"]
                if synced:
                    # A fixed window (2 before, the current line, 3 after -- padded at
                    # the ends) so the block doesn't change height as the song moves
                    # through it. One HTML block, not an element per line: separate
                    # elements get a gap between each.
                    current = current_line_index(synced, live_progress_ms(playback))
                    center = current if current is not None else -1
                    window_lines = []
                    for offset in range(-2, 4):
                        position = center + offset
                        words = html.escape(synced[position][1]) if 0 <= position < len(synced) else ""
                        if offset == 0 and current is not None:
                            style = f"font-size:1.3rem;line-height:1.7;color:{ACCENT_COLOR}"
                        else:
                            style = "line-height:1.7;opacity:0.55"
                        window_lines.append(f'<div style="{style}">{words or "&nbsp;"}</div>')
                    st.markdown("".join(window_lines), unsafe_allow_html=True)

                if lyrics["plain"]:
                    st.caption("Full lyrics")
                    with st.container(height=300):
                        # Escaped so lyrics can't be read as markup, and line
                        # breaks become <br>: a real blank line (between
                        # stanzas) would end the HTML block in markdown and
                        # let the rest be parsed as markup.
                        lyric_html = "<br>".join(html.escape(line) for line in lyrics["plain"].splitlines())
                        st.markdown(
                            f'<div style="line-height:1.6">{lyric_html}</div>',
                            unsafe_allow_html=True,
                        )
                st.caption("Lyrics from LRCLIB (community-maintained).")

        lyrics_view()

        # Own fragment for the same reason as the queue: refreshes itself
        # while open (a new row appears when a song finishes -- Now playing
        # also drops this cache the moment the song changes), and does no
        # work at all while collapsed.
        @st.fragment(run_every=5)
        @log_slow("Spotify page recent_view refresh")
        def recent_view() -> None:
            recent_expander = st.expander("Recently played", on_change="rerun")
            if recent_expander.open:
                with recent_expander:
                    try:
                        # Spotify's list omits some plays its own apps show
                        # (e.g. skipped tracks); the app fills those in from
                        # what it saw play. See play_history.py.
                        recent_items = merge_with_api(recently_played())
                        recent_failed = False
                    except (urllib.error.URLError, TimeoutError):
                        recent_items = []
                        recent_failed = True

                    if recent_failed:
                        st.error("Couldn't reach Spotify right now.")
                    elif not recent_items:
                        st.caption("No recent listening history yet.")
                    else:
                        # Own tick cadence (run_every=5), so its own
                        # page_is_locked() call -- see queue_view's note.
                        locked = page_is_locked("spotify_page")
                        # The same song can appear more than once in recent
                        # history -- ask about each uri once. Same fallbacks as
                        # the queue: no buttons if Spotify refuses (403 = needs
                        # the reconnect) or the check fails; the list still shows.
                        unique_uris = tuple(dict.fromkeys(played["track"]["uri"] for played in recent_items))
                        try:
                            recent_flags = saved_flags(unique_uris)
                        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
                            recent_flags = None
                        can_like_recent = not locked and recent_flags is not None and len(recent_flags) == len(unique_uris)
                        recent_saved = dict(zip(unique_uris, recent_flags)) if can_like_recent else {}

                        for index, played in enumerate(recent_items):
                            track = played["track"]
                            # Same defensive .get() as "Now playing" -- Spotify's
                            # recently-played endpoint has historically only
                            # returned tracks (never episodes, which lack
                            # "artists"), but not worth trusting that to hold given
                            # how much else has shifted under this API recently.
                            artists = ", ".join(artist["name"] for artist in track.get("artists", []))
                            # Buttons keyed by position, not track: the same song
                            # can appear twice in recent history.
                            row_text, row_play, row_queue, row_like = st.columns([6, 1, 1, 1], vertical_alignment="center")
                            with row_text:
                                label = f"**{track['name']}** -- {artists}"
                                if played.get("skipped_at"):
                                    label += f" *(skipped at {played['skipped_at']})*"
                                st.write(label)
                            if not locked:
                                with row_play:
                                    if st.button("▶", key=f"recent_play_{index}_{track['uri']}", help="Play again"):
                                        run_control(play_track, uri=track["uri"])
                                with row_queue:
                                    if st.button("＋", key=f"recent_queue_{index}_{track['uri']}", help="Add to queue"):
                                        run_control(add_to_queue, success=f"Queued {track['name']}", uri=track["uri"])
                            if can_like_recent:
                                with row_like:
                                    if recent_saved[track["uri"]]:
                                        if st.button("💚", key=f"recent_like_{index}_{track['uri']}", help="Liked -- click to remove"):
                                            run_control(unsave_item, rerun_scope="fragment", uri=track["uri"])
                                    else:
                                        if st.button("🤍", key=f"recent_like_{index}_{track['uri']}", help="Add to Liked Songs"):
                                            run_control(save_item, rerun_scope="fragment", uri=track["uri"])

                        # Only items filled in from the app's own record
                        # carry a skipped_at key (None when played through).
                        if any("skipped_at" in played for played in recent_items):
                            st.caption(
                                "Includes plays Spotify's list leaves out (like skipped songs), "
                                "filled in from what this app saw while it was open."
                            )

        recent_view()

        playlists_expander = st.expander("Playlists", on_change="rerun")
        if playlists_expander.open:
            with playlists_expander:
                try:
                    playlist_items = playlists()
                    playlists_failed = False
                except (urllib.error.URLError, TimeoutError):
                    playlist_items = []
                    playlists_failed = True

                if playlists_failed:
                    st.error("Couldn't reach Spotify right now.")
                elif not playlist_items:
                    st.caption("No playlists found.")
                else:
                    # One embed at a time, not one per playlist -- each embed is
                    # its own full iframe load, and 20 of them at once would
                    # crawl. The embed plays full tracks only if this browser is
                    # already logged in to Spotify (previews otherwise) -- that's
                    # Spotify's own rule, not something this page controls.
                    chosen = st.selectbox(
                        "Playlist",
                        playlist_items,
                        index=None,
                        format_func=lambda playlist: playlist["name"],
                        placeholder="Pick a playlist to view",
                    )
                    if chosen:
                        st.iframe(
                            f"https://open.spotify.com/embed/playlist/{chosen['id']}",
                            height=380,
                        )
                        st.markdown(f"[Open in Spotify]({chosen['external_urls']['spotify']})")

if time.time() - run_started > 2.0:
    log_event(f"slow: Spotify page full run took {time.time() - run_started:.2f}s")
