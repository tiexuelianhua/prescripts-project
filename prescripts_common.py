# Shared constants and helpers for every Prescripts page -- the logo path,
# JST clock, color/typewriter helpers, and the page registry all live here so
# every page (present and future) stays visually and behaviorally consistent
# without each one redefining its own copy.

import json
import time
from datetime import timedelta, timezone
from pathlib import Path

import streamlit as st

SCRIPTS_DIR = Path(__file__).resolve().parent
# Outside the repo, like every page's data -- so a fresh clone won't have it,
# and everything that shows it has to cope without (see show_logo).
LOGO_PATH = SCRIPTS_DIR.parent / "Images" / "The_Index_Logo.webp"
JST = timezone(timedelta(hours=9))

ACCENT_COLOR = "#96c4ec"  # buttons/links/input borders, measured from style.css

# Every non-home page in the app, in one place -- app.py's st.navigation()
# and the Home page's tile grid / search both read this, so adding a page
# means adding one entry here rather than touching multiple files.
PAGES = [
    {
        "title": "Overview",
        "icon": "🎛️",
        "path": "overview_page.py",
        "keywords": ["overview", "summary", "today", "control center", "dashboard"],
    },
    {
        "title": "Meal Receipts",
        "icon": "🧾",
        "path": "mealReceiptsApp_cV.py",
        "keywords": ["meal", "receipt", "receipts", "food", "budget"],
    },
    {
        "title": "Weather",
        "icon": "🌤️",
        "path": "weather_page.py",
        "keywords": ["weather", "forecast", "typhoon", "rain", "temperature", "advisory"],
    },
    {
        "title": "Spotify",
        "icon": "🎧",
        "path": "spotify_page.py",
        "keywords": ["spotify", "music", "playlist", "song", "playback"],
    },
    {
        "title": "Japanese",
        "icon": "🈁",
        "path": "japanese_page.py",
        "keywords": ["japanese", "vocab", "vocabulary", "kanji", "flashcard", "flashcards", "srs", "study", "日本語"],
    },
]


# App-wide preferences that don't belong to any one page (currently just the
# zoom level), kept outside the repo like every page's own settings.
APP_SETTINGS_PATH = SCRIPTS_DIR.parent / "app_settings.json"

# Zoom steps offered by the page zoom controls (see render_zoom_controls).
ZOOM_LEVELS = [0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75]


def show_logo(width: int) -> None:
    # st.image raises on a missing file, which took down every page on a
    # fresh clone -- so the logo is simply left out there instead.
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=width)


def load_app_settings() -> dict:
    try:
        with open(APP_SETTINGS_PATH, encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_app_settings(settings: dict) -> None:
    with open(APP_SETTINGS_PATH, "w", encoding="utf-8") as file:
        json.dump(settings, file, indent=2)


def _step_zoom(step: int) -> None:
    # Button callback: runs before the rerun draws anything, so the page
    # comes back already at the new zoom.
    settings = load_app_settings()
    current = settings.get("zoom", 1.0)
    index = min(range(len(ZOOM_LEVELS)), key=lambda i: abs(ZOOM_LEVELS[i] - current))
    if step == 0:
        settings["zoom"] = 1.0
    else:
        settings["zoom"] = ZOOM_LEVELS[max(0, min(len(ZOOM_LEVELS) - 1, index + step))]
    save_app_settings(settings)


def render_zoom_controls() -> None:
    # Page zoom for every page but Home (called from app.py): small
    # "−  100%  +" buttons pinned in the top bar, scaling the page's content
    # with CSS zoom. One level shared by all pages, remembered across
    # restarts. The whole main column is zoomed (so it widens like real
    # browser zoom, rather than just bigger text in the same width); the
    # controls live inside it -- Streamlit has no other place to put
    # widgets -- so they're zoomed back by the inverse to stay put.
    zoom = load_app_settings().get("zoom", 1.0)
    st.markdown(
        f"""
        <style>
        [data-testid="stMainBlockContainer"] {{
            zoom: {zoom};
        }}
        /* Out of the page's flow, into the top bar beside Streamlit's own
           menu -- the wrapper otherwise leaves a gap above the page. */
        [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] > *:has(.st-key-zoom_controls) {{
            position: absolute;
        }}
        .st-key-zoom_controls {{
            position: fixed;
            top: 0.55rem;
            left: 3.5rem;
            z-index: 999991;
            zoom: {1 / zoom};
            width: auto;
            gap: 0.25rem;
            align-items: center;
        }}
        .st-key-zoom_controls button {{
            min-height: 0;
            padding: 0 0.6rem;
            line-height: 1.6;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="zoom_controls", horizontal=True):
        st.button("−", key="zoom_out", help="Zoom out", on_click=_step_zoom, args=(-1,), disabled=zoom <= ZOOM_LEVELS[0])
        st.button(f"{zoom:.0%}", key="zoom_reset", help="Reset zoom to 100%", on_click=_step_zoom, args=(0,))
        st.button("+", key="zoom_in", help="Zoom in", on_click=_step_zoom, args=(1,), disabled=zoom >= ZOOM_LEVELS[-1])


def theme_colors() -> tuple[str, str]:
    # st.context.theme only exposes "type" ("dark"/"light"), not resolved hex
    # values, so the two palettes below are kept in sync with
    # .streamlit/config.toml by hand. Defaults to the dark palette when type
    # is unset (system default), since dark is this app's primary intended
    # look.
    is_light = st.context.theme.get("type") == "light"
    text_color = "#162a3b" if is_light else "#f0f8ff"
    return text_color, ACCENT_COLOR


def inject_button_style() -> None:
    # Matches Images/Reference 1.png and prescript.neocities.org/style.css:
    # buttons there are outlined (transparent fill, accent border+text) and
    # turn to the body text color on hover, not Streamlit's default
    # solid-filled style. `stBaseButton-*` covers every button kind (regular,
    # form submit, download, link) across Streamlit versions via the prefix
    # match. Called once from app.py, which reruns on every navigation, so
    # every page picks this up without injecting it again itself.
    text_color, accent_color = theme_colors()
    st.markdown(
        f"""
        <style>
        [data-testid^="stBaseButton"] {{
            background-color: transparent;
            border: 2px solid {accent_color};
            color: {accent_color};
            font-family: inherit;
        }}
        [data-testid^="stBaseButton"]:hover,
        [data-testid^="stBaseButton"]:active,
        [data-testid^="stBaseButton"]:focus:not(:focus-visible) {{
            border-color: {text_color};
            color: {text_color};
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_toast_style() -> None:
    # st.toast() pops in and vanishes abruptly with no transition of its own
    # (verified in Streamlit's bundled frontend: [data-testid="stToast"]
    # carries no animation/transition). Faked here with one continuous
    # keyframe animation spanning its whole visible lifetime -- reveal fast,
    # hold, then fade out right before Streamlit unmounts it -- since a pure
    # CSS injection can't hook into the moment a React-managed node actually
    # gets removed. The 4s duration matches "short", the default (and only
    # one used anywhere in this app); a toast ever passed duration="long" or
    # an explicit number of seconds would need a separate animation timed to
    # match, or its fade-out tail won't line up with the real dismissal.
    st.markdown(
        """
        <style>
        @keyframes toastFade {
            0% { opacity: 0; transform: translateY(8px); }
            8% { opacity: 1; transform: translateY(0); }
            92% { opacity: 1; transform: translateY(0); }
            100% { opacity: 0; transform: translateY(8px); }
        }
        [data-testid="stToast"] {
            animation: toastFade 4s ease-in-out forwards;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_input_style() -> None:
    # Streamlit positions the "Press Enter to apply" hint under a text/number
    # input (data-testid="InputInstructions") absolutely, anchored to the
    # bottom of the *un*edited input's box -- assuming a normal font's line
    # height. Galmuri14 (this app's pixel font, see the module docstring)
    # renders noticeably taller, so the typed value's own glyphs reach down
    # into that same space and the hint overlaps it instead of sitting
    # below it (worst on narrow fields, like the sidebar's budget amount,
    # confirmed live via headless Chrome). Nudged below the input's border
    # instead -- verified this leaves a normal-looking gap above whatever
    # comes next, not just fixing the overlap by creating a new one.
    st.markdown(
        """
        <style>
        [data-testid="InputInstructions"] {
            bottom: -20px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_body_fade_in(container_key: str) -> None:
    # Fades in every element inside st.container(key=container_key) --
    # scoped there (not the whole page) so a page's title isn't
    # double-animated by this rule too. Always immediate: render_page_title()
    # below blocks on its own (the typewriter reveal runs before anything
    # else in the script, title included, ever gets sent to the browser),
    # so by the time this container's contents are generated the title's
    # already done -- no need to also delay this fade-in to line up with it.
    st.markdown(
        f"""
        <style>
        @keyframes fadeIn {{
            from {{ opacity: 0; }}
            to {{ opacity: 1; }}
        }}
        .st-key-{container_key} [data-testid="stElementContainer"] {{
            animation: fadeIn 0.4s ease-out;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_page_title(title: str, is_first_load: bool) -> None:
    # Every page but Home types its title in once per session, blocking
    # (via typewriter()'s own time.sleep loop) so nothing else on the page
    # is even generated -- let alone sent to the browser -- until the title
    # has finished, for a genuinely sequential "title, then everything
    # else" load rather than an approximation timed to match. Paints the
    # title instantly on every later rerun instead (callers compute
    # is_first_load themselves, typically `session_key not in
    # st.session_state` with a page-specific session_key: session_state is
    # shared across every page in this app, so reusing one key would make
    # visiting one page silently skip another's first-time reveal).
    if is_first_load:
        typewriter(title, markdown_wrap="# {}")
    else:
        st.markdown(f"# {title}")


def typewriter(
    text: str,
    speed_ms: int = 30,
    markdown_wrap: str | None = None,
    placeholder: "st.delta_generator.DeltaGenerator | None" = None,
) -> None:
    # Own implementation of the reveal-one-character-at-a-time effect used by
    # prescript.neocities.org for in-game "Prescript" messages -- same generic
    # progressive-reveal idea, written from scratch (not their code) to avoid
    # copying the site itself. Renders as a normal st.markdown element (via a
    # placeholder re-rendered each tick) rather than an iframe, so it inherits
    # the page's theme/font/layout exactly and doesn't introduce a separate
    # document with its own box model.
    #
    # Accepts an existing placeholder so a caller can reserve a spot early
    # (e.g. at the top of the page) but only actually run the animation later
    # in the script -- Streamlit streams each st.* call's output to the
    # browser as it happens, so everything written before this call reaches
    # the page immediately, and only this element visibly trails behind.
    placeholder = placeholder or st.empty()
    for i in range(1, len(text) + 1):
        chunk = text[:i]
        if markdown_wrap:
            chunk = markdown_wrap.format(chunk)
        placeholder.markdown(chunk)
        time.sleep(speed_ms / 1000)
