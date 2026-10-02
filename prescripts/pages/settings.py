# Settings page: which pages and Overview tiles are switched on. Saved in
# app_settings.json beside the other app-wide settings (see page_shown and
# tile_shown in common.py, which every page list reads). Hiding only hides:
# a page's data stays where it is.
import streamlit as st

from prescripts.common import (
    PAGES,
    inject_body_fade_in,
    load_app_settings,
    page_shown,
    render_page_title,
    save_app_settings,
    show_logo,
    tile_shown,
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

with st.container(key="main_body"):
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
