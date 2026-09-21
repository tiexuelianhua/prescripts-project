# Spotify page: currently playing + remote playback control (play/pause/
# skip/volume/shuffle on whichever device is already active elsewhere),
# recently played (replay / add to queue), and playlists (embedded) -- via
# Spotify's plain Web API, not the Web Playback SDK (see spotify_data.py's
# module docstring for why).
import urllib.error

import streamlit as st

from prescripts_common import LOGO_PATH, inject_body_fade_in, render_page_title, theme_colors
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
    is_saved,
    play_track,
    playlists,
    recently_played,
    save_item,
    saved_flags,
    set_shuffle,
    set_volume,
    unsave_item,
)
from spotify_widgets import (
    inject_seek_slider_styles,
    render_seek_slider,
    render_transport_controls,
    run_control,
)

TEXT_COLOR, ACCENT_COLOR = theme_colors()
PAGE_TITLE = "Spotify"

is_first_load = "_spotify_title_played" not in st.session_state
inject_body_fade_in("main_body")

header_logo, header_title = st.columns([1, 4], vertical_alignment="center")
with header_logo:
    st.image(str(LOGO_PATH), width=120)
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
            if st.button("Disconnect Spotify"):
                disconnect()
                st.rerun()

        inject_seek_slider_styles("spotify_page_seek")

        st.subheader("Now playing")

        # Re-runs just this section every second: the position is
        # extrapolated locally between the (5s-cached) API fetches, so the
        # bar moves smoothly and a track change shows up on its own. Leaving
        # the page stops the timer -- nothing polls in the background.
        @st.fragment(run_every=1)
        def now_playing() -> None:
            try:
                playback = current_playback()
            except (urllib.error.URLError, TimeoutError):
                st.error("Couldn't reach Spotify's player right now.")
                return

            if not playback or not playback.get("item"):
                st.caption("Nothing playing right now -- open Spotify on a device (phone, desktop app, etc.) first.")
                return

            track = describe_item(playback["item"])
            item_uri = playback["item"].get("uri")

            # A song change is when the queue shrinks and Recently played
            # gains a row -- drop their caches right then so the open lists
            # pick it up on their next refresh instead of waiting out the TTL.
            if st.session_state.get("spotify_last_item_uri") != item_uri:
                if "spotify_last_item_uri" in st.session_state:
                    current_queue.clear()
                    recently_played.clear()
                st.session_state["spotify_last_item_uri"] = item_uri

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
                        if saved:
                            if st.button("💚", key="spotify_page_unlike", help="Liked -- click to remove"):
                                run_control(unsave_item, uri=item_uri)
                        else:
                            if st.button("🤍", key="spotify_page_like", help="Add to Liked Songs"):
                                run_control(save_item, uri=item_uri)
                # Real elapsed/total time (00:00 .. track length) rather than
                # a bare percentage bar, and draggable to seek.
                render_seek_slider(playback, "spotify_page_seek")

            render_transport_controls(playback, "spotify_page")

            device = playback.get("device") or {}
            current_volume = device.get("volume_percent")
            # Some Spotify Connect devices don't report a volume at all --
            # comparing a slider's int value against None would never be
            # equal, silently pushing "set volume to 0" on every single
            # rerun (any button click anywhere on the page), so the control
            # just doesn't render rather than guessing a default to push.
            if current_volume is not None:
                volume = st.slider("Volume", min_value=0, max_value=100, value=current_volume)
                if volume != current_volume:
                    run_control(set_volume, percent=volume)

            shuffle_on = st.toggle("Shuffle", value=bool(playback.get("shuffle_state")))
            if shuffle_on != bool(playback.get("shuffle_state")):
                run_control(set_shuffle, state=shuffle_on)

            if saved is None:
                st.caption(
                    "Reconnect Spotify (Disconnect in the sidebar, then Connect) "
                    "to enable Liked Songs."
                )

        now_playing()

        # Own fragment (3s, not 1s) -- the queue changes on song boundaries
        # and when it's edited from another device, not continuously. The
        # expander lives inside the fragment so its open/closed state
        # survives the refreshes, and its contents (two API calls) are only
        # fetched while it's actually open.
        @st.fragment(run_every=3)
        def queue_view() -> None:
            queue_expander = st.expander("Queue", on_change="rerun")
            if not queue_expander.open:
                return
            with queue_expander:
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
                shown = queue_items[:15]
                uris = tuple(queued["uri"] for queued in shown)
                try:
                    flags = saved_flags(uris)
                except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
                    flags = None  # no Like buttons, but the list still shows
                # None = token lacks the library scopes (see now_playing's
                # reconnect note); a length mismatch = Spotify returned
                # something unexpected. Either way, skip the buttons.
                can_like = flags is not None and len(flags) == len(shown)

                for position, queued in enumerate(shown, start=1):
                    described = describe_item(queued)
                    row_text, row_like = st.columns([7, 1], vertical_alignment="center")
                    with row_text:
                        st.write(f"{position}. **{described['name']}** -- {described['artists']}")
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
                    st.caption(f"+ {len(queue_items) - len(shown)} more")

        queue_view()

        # Own fragment for the same reason as the queue: refreshes itself
        # while open (a new row appears when a song finishes -- Now playing
        # also drops this cache the moment the song changes), and does no
        # work at all while collapsed.
        @st.fragment(run_every=5)
        def recent_view() -> None:
            recent_expander = st.expander("Recently played", on_change="rerun")
            if recent_expander.open:
                with recent_expander:
                    try:
                        recent_items = recently_played()
                        recent_failed = False
                    except (urllib.error.URLError, TimeoutError):
                        recent_items = []
                        recent_failed = True

                    if recent_failed:
                        st.error("Couldn't reach Spotify right now.")
                    elif not recent_items:
                        st.caption("No recent listening history yet.")
                    else:
                        # The same song can appear more than once in recent
                        # history -- ask about each uri once. Same fallbacks as
                        # the queue: no buttons if Spotify refuses (403 = needs
                        # the reconnect) or the check fails; the list still shows.
                        unique_uris = tuple(dict.fromkeys(played["track"]["uri"] for played in recent_items))
                        try:
                            recent_flags = saved_flags(unique_uris)
                        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
                            recent_flags = None
                        can_like_recent = recent_flags is not None and len(recent_flags) == len(unique_uris)
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
                                st.write(f"**{track['name']}** -- {artists}")
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
