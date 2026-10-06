# Settings page: English only, which pages and Overview tiles are
# switched on, and updates (data/updates.py). Saved in
# app_settings.json beside the other app-wide settings (see page_shown and
# tile_shown in common.py, which every page list reads). Hiding only hides:
# a page's data stays where it is.
import urllib.error
from datetime import date

import streamlit as st

from prescripts.common import (
    PAGES,
    PRIVATE_LOOK,
    english_only,
    inject_body_fade_in,
    load_app_settings,
    page_shown,
    render_page_title,
    save_app_settings,
    show_logo,
    tile_shown,
)
from prescripts.data.updates import (
    CHANGES_SHOWN,
    PIP_PENDING,
    apply_update,
    check_for_update,
    in_desktop_window,
    local_version,
)

PAGE_TITLE = "Settings"
# One line on what each page is for, to help decide what to keep.
ABOUT = {
    "overview": "Every page's summary on one screen",
    "meal_receipts": "Log meals and other spending by category, against a budget",
    "weather": "The forecast and warnings, from Japan's weather agency",
    "activities": "Food, things to do and events nearby",
    "spotify_page": "Your Spotify, with lyrics. Needs a Spotify developer app of your own (see the README)",
    "japanese": "Flashcards for vocab and kanji, with word lookups",
}
# Pages with an Overview tile (Overview itself has none).
TILE_PAGES = ["meal_receipts", "weather", "japanese", "activities", "spotify_page"]

is_first_load = "_settings_title_played" not in st.session_state
inject_body_fade_in("main_body")

header_logo, header_title = st.columns([1, 4], vertical_alignment="center")
with header_logo:
    show_logo(width=120)
with header_title:
    render_page_title(PAGE_TITLE, is_first_load)

if is_first_load:
    st.session_state["_settings_title_played"] = True


def _switch(kind: str, url_path: str) -> None:
    # A toggle's callback: saved before the rerun draws anything, so the
    # sidebar and Overview already match when the page comes back.
    settings = load_app_settings()
    settings.setdefault(kind, {})[url_path] = st.session_state[f"settings_{kind}_{url_path}"]
    save_app_settings(settings)


settings = load_app_settings()
pages = {page["url_path"]: page for page in PAGES}

def _switch_english_only() -> None:
    settings = load_app_settings()
    settings["english_only"] = st.session_state["settings_english_only"]
    save_app_settings(settings)


def render_updates() -> None:
    # Public version only: the author's copy is where changes are made.
    st.subheader("Updates")
    local = local_version()
    if local is None:
        st.caption(
            "This copy was installed from the ZIP, so it can't update itself. To update, download the ZIP "
            "again (see \"Handy to know\" in the README), or reinstall with git to update from here."
        )
        return
    try:
        status = check_for_update(local["sha"])
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
        status = None
    version = f"Version {local['sha'][:7]}, from {date.fromisoformat(local['date']):%d %b %Y}."
    if status is None:
        st.caption(f"{version} Couldn't check for updates just now.")
    elif status["state"] == "up_to_date":
        st.caption(f"{version} This is the newest version.")
    elif status["state"] == "own_changes":
        st.caption(f"{version} This copy has changes of its own that aren't on GitHub, so it isn't updated from here.")
    else:
        changes = status["changes"]
        st.caption(version)
        st.info(f"A new version is ready, with {len(changes)} change{'s' if len(changes) != 1 else ''}:")
        lines = [f"- {title}" for title in changes[:CHANGES_SHOWN]]
        if len(changes) > CHANGES_SHOWN:
            lines.append(f"- and {len(changes) - CHANGES_SHOWN} more")
        st.markdown("\n".join(lines))
        desktop = in_desktop_window()
        if st.button("Update and restart" if desktop else "Update", key="settings_update"):
            with st.spinner("Updating..."):
                problem, needs_pip = apply_update(status["sha"])
            if problem:
                st.error(problem)
                return
            check_for_update.clear()
            if desktop:
                if needs_pip:
                    PIP_PENDING.touch()
                st.success("Updated. Restarting...")
                # The window closes and desktop_app.py starts it again (with
                # pip first when the packages changed). See _Api.restart.
                st.html("<script>window.pywebview.api.restart();</script>", unsafe_allow_javascript=True)
            else:
                st.success(
                    "Updated. Stop the app (Ctrl+C in PowerShell)"
                    + (", run install step 4 again, as the packages changed," if needs_pip else "")
                    + " and start it again to finish."
                )
            return
    if st.button("Check again", key="settings_check_updates"):
        check_for_update.clear()
        st.rerun()


with st.container(key="main_body"):
    # Not in the author's own copy, which keeps its Japanese.
    if not PRIVATE_LOOK:
        st.subheader("Language")
        st.session_state["settings_english_only"] = english_only(settings)
        st.toggle(
            "English only", key="settings_english_only", on_change=_switch_english_only,
            help="Puts Japanese text in English, or leaves it out. Things that only come in Japanese, like some "
            "event names and the collab news, are marked (in Japanese). The Japanese page starts off too, "
            "unless you've switched it on below.",
        )

    st.subheader("Pages")
    st.caption("Switch off what you don't use. Hiding a page keeps its data, "
               "so switching it back on brings everything back.")
    for page in PAGES:
        if page.get("always_on"):
            continue
        url_path = page["url_path"]
        # Always what's saved, set before the toggle's drawn (so no value=).
        st.session_state[f"settings_pages_{url_path}"] = page_shown(url_path, settings)
        st.toggle(
            f"{page['icon']} {page['title']}", key=f"settings_pages_{url_path}", help=ABOUT.get(url_path),
            on_change=_switch, args=("pages", url_path),
        )

    if page_shown("overview", settings):
        st.subheader("Overview tiles")
        st.caption("A hidden page's tile goes with it. A tile can also go on its own, keeping its page.")
        for url_path in TILE_PAGES:
            page = pages[url_path]
            st.session_state[f"settings_tiles_{url_path}"] = tile_shown(url_path, settings)
            st.toggle(
                f"{page['icon']} {page['title']}", key=f"settings_tiles_{url_path}",
                disabled=not page_shown(url_path, settings),
                on_change=_switch, args=("tiles", url_path),
            )

    if not PRIVATE_LOOK:
        render_updates()
