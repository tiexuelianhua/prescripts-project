# Shared constants and helpers for every Prescripts page -- the logo path,
# JST clock, color/typewriter helpers, and the page registry all live here so
# every page (present and future) stays visually and behaviorally consistent
# without each one redefining its own copy.

import json
import re
import time
from datetime import timedelta, timezone
from pathlib import Path

import streamlit as st

# The repo's own folder (this file is in prescripts/ inside it). Every page's
# data lives in folders beside it, e.g. SCRIPTS_DIR.parent / "Meal Receipts".
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))

# Two looks. The public one (what the repo ships) uses the forget-me-not
# logo in static/ and its periwinkle. The original author's own copy uses
# The Index logo and a sky blue instead -- that logo is kept outside the
# repo, so its presence is what picks the private look. desktop_app.py makes
# the same check to swap .streamlit/config.toml's colors to match.
PRIVATE_LOGO_PATH = SCRIPTS_DIR.parent / "Images" / "The_Index_Logo.webp"
PRIVATE_LOOK = PRIVATE_LOGO_PATH.exists()
LOGO_PATH = PRIVATE_LOGO_PATH if PRIVATE_LOOK else SCRIPTS_DIR / "static" / "forget_me_not.png"

# Buttons/links/input borders. Must match primaryColor in
# .streamlit/config.toml (public) and desktop_app.py's _PRIVATE_DARK_PALETTE.
# The public periwinkle is sampled from the forget-me-not's petals; light
# mode gets a deeper shade of it, since the petal color itself is too faint
# to read on white. The private sky blue was measured from
# prescript.neocities.org's style.css; the private look is dark-only, so it
# has no light-mode shade.
ACCENT_COLOR = "#96c4ec" if PRIVATE_LOOK else "#7578b2"
ACCENT_COLOR_LIGHT = "#6b6ead"

# Every non-home page in the app, in one place -- app.py's st.navigation()
# and the Home page's tile grid / search both read this, so adding a page
# means adding one entry here rather than touching multiple files.
# "url_path" is each page's address (e.g. 127.0.0.1:8501/weather). Spotify's
# keeps its original "spotify_page": it's the redirect address every user
# registers in their own Spotify developer app (REDIRECT_URI in
# data/spotify.py), so changing it would break every existing setup.
PAGES = [
    {
        "title": "Overview",
        "icon": "🎛️",
        "path": "prescripts/pages/overview.py",
        "url_path": "overview",
        "keywords": ["overview", "summary", "today", "control center", "dashboard"],
    },
    {
        # Called Meal Receipts until it took other spending too. The file,
        # address and settings key keep that name, so bookmarks and saved
        # page switches still work.
        "title": "Budget",
        "icon": "🧾",
        "path": "prescripts/pages/meal_receipts.py",
        "url_path": "meal_receipts",
        "keywords": [
            "budget", "meal", "meals", "receipt", "receipts", "food", "spending", "money", "expenses",
            "transport", "suica", "pasmo", "shopping",
        ],
    },
    {
        "title": "Weather",
        "icon": "🌤️",
        "path": "prescripts/pages/weather.py",
        "url_path": "weather",
        "keywords": ["weather", "forecast", "typhoon", "rain", "temperature", "advisory"],
    },
    {
        "title": "Activities",
        "icon": "📍",
        "path": "prescripts/pages/activities.py",
        "url_path": "activities",
        "keywords": [
            "activities", "activity", "nearby", "near me", "near here", "around here", "places", "things to do", "restaurant",
            "restaurants", "cafe", "convenience store", "konbini", "park", "shrine", "temple", "museum",
        ],
    },
    {
        "title": "Spotify",
        "icon": "🎧",
        "path": "prescripts/pages/spotify.py",
        "url_path": "spotify_page",
        "keywords": ["spotify", "music", "playlist", "song", "playback"],
    },
    {
        "title": "Japanese",
        "icon": "🈁",
        "path": "prescripts/pages/japanese.py",
        "url_path": "japanese",
        "keywords": ["japanese", "vocab", "vocabulary", "kanji", "flashcard", "flashcards", "srs", "study", "日本語"],
    },
    {
        "title": "Settings",
        "icon": "⚙️",
        "path": "prescripts/pages/settings.py",
        "url_path": "settings",
        "keywords": ["settings", "preferences", "options", "customise", "customize", "hide", "show", "pages", "widgets"],
        # Can't be switched off: it's where things are switched back on.
        "always_on": True,
    },
]
# Pages a new install of the public version starts with switched off, until
# turned on in Settings. Spotify needs each person to register a Spotify
# developer app of their own before it does anything. The author's own copy
# (the private look) starts with everything on.
OFF_BY_DEFAULT = set() if PRIVATE_LOOK else {"spotify_page"}
# Hiragana, katakana and kanji: text a reader with no Japanese can't read.
JAPANESE_TEXT = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")
# After something that only comes in Japanese, when English only is on.
IN_JAPANESE = "<small>(in Japanese)</small>"


# App-wide preferences that don't belong to any one page (currently just the
# zoom level), kept outside the repo like every page's own settings.
APP_SETTINGS_PATH = SCRIPTS_DIR.parent / "app_settings.json"

# Zoom steps offered by the page zoom controls (see render_top_bar).
ZOOM_LEVELS = [0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75]


def balanced_columns(heights: list[float]) -> list[int]:
    # Which of two columns (0 or 1) each tile goes in, so the columns end as
    # close to level as possible. Every split is tried -- a handful of tiles
    # is only a few dozen -- rather than filling whichever column is shorter
    # so far, which can't look ahead and once left one tile stretched with
    # ~250px of nothing. Tiles keep their order within each column, the
    # first always goes left, and among equally even splits the earliest
    # found wins, so the layout is stable from one visit to the next.
    if not heights:
        return []
    best = None
    for split in range(2 ** (len(heights) - 1)):
        columns = [0] + [(split >> index) & 1 for index in range(len(heights) - 1)]
        totals = [0.0, 0.0]
        for column, height in zip(columns, heights):
            totals[column] += height
        gap = abs(totals[0] - totals[1])
        if best is None or gap < best[0]:
            best = (gap, columns)
    return best[1]


def show_logo(width: int) -> None:
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


def page_shown(url_path: str, settings: dict | None = None) -> bool:
    # Whether a page is switched on (Settings page). Hidden pages leave the
    # sidebar, Home's commands and Overview, but keep all their data.
    page = next((page for page in PAGES if page["url_path"] == url_path), {})
    if page.get("always_on"):
        return True
    settings = load_app_settings() if settings is None else settings
    # With English only on, the Japanese page starts off too.
    default = url_path not in OFF_BY_DEFAULT and not (url_path == "japanese" and english_only(settings))
    return settings.get("pages", {}).get(url_path, default)


def english_only(settings: dict | None = None) -> bool:
    # The Settings switch for friends who don't read Japanese: Japanese
    # text is dropped or put in English, and what only comes in Japanese
    # is tagged. Public version only, on to start; the author's copy (the
    # private look) has no switch and is never English only.
    if PRIVATE_LOOK:
        return False
    settings = load_app_settings() if settings is None else settings
    return settings.get("english_only", True)


def has_japanese(text) -> bool:
    return isinstance(text, str) and bool(JAPANESE_TEXT.search(text))


def place_name(name: str, name_en: str, english: bool) -> tuple[str, bool]:
    # A place or event's name as shown: "Japanese · English" normally; with
    # English only, the English name when there is one. The flag says it's
    # left in Japanese, for an (in Japanese) tag where one's wanted.
    if not english:
        return (f"{name} · {name_en}" if name_en else name), False
    return (name_en, False) if name_en else (name, has_japanese(name))


def shown_pages(settings: dict | None = None) -> list[dict]:
    settings = load_app_settings() if settings is None else settings
    return [page for page in PAGES if page_shown(page["url_path"], settings)]


def tile_shown(url_path: str, settings: dict | None = None) -> bool:
    # A page's Overview tile: only while its page is on, and it can also be
    # switched off by itself, keeping the page.
    settings = load_app_settings() if settings is None else settings
    return page_shown(url_path, settings) and settings.get("tiles", {}).get(url_path, True)


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


def render_top_bar() -> None:
    # For every page but Home (called from app.py): a Home button (also
    # Ctrl+Shift+H) and small "−  100%  +" zoom buttons pinned in the top bar.
    # The zoom scales the page's content
    # with CSS zoom. One level shared by all pages, remembered across
    # restarts. The whole main column is zoomed (so it widens like real
    # browser zoom, rather than just bigger text in the same width); the
    # controls live inside it -- Streamlit has no other place to put
    # widgets -- so they're zoomed back by the inverse to stay put.
    zoom = load_app_settings().get("zoom", 1.0)
    # Arriving on Overview by its shortcut, the buttons wait hidden until
    # Overview fades them in (see pages/overview.py). Hidden here too, since
    # this bar is drawn before Overview's own styles arrive.
    arriving_hide = ".st-key-top_bar { opacity: 0; }" if "_overview_glitch_at" in st.session_state else ""
    st.markdown(
        f"""
        <style>
        [data-testid="stMainBlockContainer"] {{
            zoom: {zoom};
        }}
        /* Tables and charts size themselves from on-screen (zoomed) pixels,
           then get zoomed again -- too narrow when zoomed out, spilling out
           of their box when zoomed in. Undoing the zoom on just them keeps
           them the width of their slot, at their normal text size. */
        [data-testid="stElementContainer"]:has(> [data-testid="stFullScreenFrame"] :is([data-testid="stDataFrame"], [data-testid="stVegaLiteChart"])) {{
            zoom: {1 / zoom};
        }}
        /* Out of the page's flow, into the top bar beside Streamlit's own
           menu -- the wrapper otherwise leaves a gap above the page. */
        [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] > *:has(.st-key-top_bar) {{
            position: absolute;
        }}
        /* Just right of the sidebar, which is open or shut and can be
           dragged wider (--sidebar-right, kept by install_page_shortcuts),
           so its arrow is never under the buttons. On a window too narrow
           for both, the open sidebar covers the page anyway, so the bar
           waits hidden until it's shut. */
        .st-key-top_bar {{
            position: fixed;
            top: 0.55rem;
            left: calc(var(--sidebar-right, 0px) + 3.5rem);
            z-index: 999991;
            zoom: {1 / zoom};
            width: auto;
            gap: 0.25rem;
            align-items: center;
        }}
        .st-key-top_bar button {{
            min-height: 0;
            padding: 0 0.6rem;
            line-height: 1.6;
        }}
        [data-sidebar-crowds] .st-key-top_bar {{
            visibility: hidden;
        }}
        {arriving_hide}
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="top_bar", horizontal=True):
        if st.button("🏠", key="go_home", help="Home (Ctrl+Shift+H)"):
            st.switch_page("prescripts/pages/home.py")
        if st.session_state.get("_current_page") != "overview":
            render_overview_button()
        st.button("−", key="zoom_out", help="Zoom out", on_click=_step_zoom, args=(-1,), disabled=zoom <= ZOOM_LEVELS[0])
        st.button(f"{zoom:.0%}", key="zoom_reset", help="Reset zoom to 100%", on_click=_step_zoom, args=(0,))
        st.button("+", key="zoom_in", help="Zoom in", on_click=_step_zoom, args=(1,), disabled=zoom >= ZOOM_LEVELS[-1])
        # Inside the pinned bar, since anywhere in the page's own flow it
        # adds an empty row above the title.
        install_page_shortcuts()


# Seconds Home's arrival glitch (static/home_glitch.js) runs for, and how far
# into it a page's title starts typing: as the static clears.
GLITCH_SECONDS = 1.0
TYPE_AFTER_GLITCH_SECONDS = GLITCH_SECONDS * 0.85


def render_overview_button() -> None:
    # Not there at all while Overview is switched off, so Ctrl+Shift+O finds
    # no button and does nothing.
    if not page_shown("overview"):
        return
    if st.button("🎛️", key="go_overview", help="Overview (Ctrl+Shift+O)"):
        # The glitch started in the browser with this click; Overview times
        # its title and logo from it.
        st.session_state["_overview_glitch_at"] = time.time()
        st.switch_page("prescripts/pages/overview.py")


def wait_for_glitch(started_at: float) -> None:
    time.sleep(max(0.0, started_at + TYPE_AFTER_GLITCH_SECONDS - time.time()))


def install_page_shortcuts() -> None:
    # Ctrl+Shift+H presses the Home button and Ctrl+Shift+O the Overview one
    # -- Ctrl combos Windows doesn't use, and that a page may take over from
    # Chrome and Edge. A key does nothing on a page without its button (Home
    # on Home, Overview on Overview). Installed once per browser tab (the
    # flag), so reruns and page switches don't stack up listeners.
    #
    # Going to Overview, by key or button, plays Home's arrival glitch
    # (static/home_glitch.js) over the switch. Its canvas sits on the page
    # itself, outside Streamlit's elements, so it carries on while the next
    # page draws. Going Home needs nothing here: arriving there plays it.
    glitch_options = json.dumps({"accent": theme_colors()[1], "seconds": GLITCH_SECONDS})
    st.html(
        "<script>"
        + (SCRIPTS_DIR / "static" / "home_glitch.js").read_text(encoding="utf-8")
        + """
        if (!window._pageShortcutsInstalled) {
            window._pageShortcutsInstalled = true;
            const buttons = {h: ".st-key-go_home button", o: ".st-key-go_overview button"};
            document.addEventListener("keydown", event => {
                if (!event.ctrlKey || !event.shiftKey || event.altKey) return;
                const selector = buttons[event.key.toLowerCase()];
                const button = selector && document.querySelector(selector);
                if (!button) return;
                event.preventDefault();
                button.click();
            }, true);
            document.addEventListener("click", event => {
                if (event.target.closest(".st-key-go_overview button")) window.playHomeGlitch(GLITCH_OPTIONS);
            }, true);
            // A button's help tooltip stays open while the button has focus,
            // and a click leaves it focused, so the tooltip hung on screen
            // after a click until something else was clicked (the queue's
            // hearts showed it most). Mouse clicks let go of focus; keyboard
            // presses (detail 0) keep it, so Tab users still see the tooltip.
            document.addEventListener("click", event => {
                const button = event.target.closest(".stTooltipHoverTarget button");
                if (button && event.detail > 0) button.blur();
            });
            // The top bar sits right of the sidebar (see render_top_bar).
            // Its width changes as it opens, shuts or is dragged, and part
            // of opening is a slide the observer can't see, so its edge is
            // re-read every frame for a moment after. The check every second
            // picks up a sidebar Streamlit has drawn afresh.
            let followUntil = 0;
            const follow = () => {
                if (!watched) return;
                const right = Math.max(0, watched.getBoundingClientRect().right);
                const bar = document.querySelector(".st-key-top_bar");
                const room = window.innerWidth - right - 56 - 50;  // its gap, Streamlit's menu
                document.documentElement.style.setProperty("--sidebar-right", right + "px");
                document.documentElement.toggleAttribute("data-sidebar-crowds", right > 0 && !!bar && bar.offsetWidth > room);
                if (performance.now() < followUntil) requestAnimationFrame(follow);
            };
            const edge = new ResizeObserver(() => {
                const idle = performance.now() >= followUntil;
                followUntil = performance.now() + 800;
                if (idle) follow();
            });
            let watched = null;
            const watchSidebar = () => {
                const sidebar = document.querySelector('[data-testid="stSidebar"]');
                if (sidebar && sidebar !== watched) {
                    if (watched) edge.unobserve(watched);
                    edge.observe(sidebar);
                    watched = sidebar;
                }
            };
            watchSidebar();
            setInterval(watchSidebar, 1000);
            window.addEventListener("resize", follow);
        }
        </script>""".replace("GLITCH_OPTIONS", glitch_options),
        unsafe_allow_javascript=True,
    )


def theme_colors() -> tuple[str, str]:
    # st.context.theme only exposes "type" ("dark"/"light"), not resolved hex
    # values, so the two palettes below are kept in sync with
    # .streamlit/config.toml by hand. Defaults to the dark palette when type
    # is unset (system default), since dark is this app's primary intended
    # look.
    # The private look renders dark even in the "light" slot (see
    # desktop_app.py's _PRIVATE_DARK_PALETTE), so it always takes the dark
    # colors here too.
    is_light = not PRIVATE_LOOK and st.context.theme.get("type") == "light"
    text_color = "#162a3b" if is_light else "#f0f8ff"
    return text_color, ACCENT_COLOR_LIGHT if is_light else ACCENT_COLOR


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
        /* In a form the submit button comes straight after the input, so
           the hint, moved below it, landed on the button. Room for it. */
        [data-testid="stForm"] [data-testid="stTextInput"] {
            margin-bottom: 0.9rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def keep_typed_selectbox_text(*keys: str) -> None:
    # A selectbox that accepts new options treats typing as a *search*: the
    # text only becomes its value on Enter (or by picking from the list), and
    # clicking or tabbing away silently throws it away -- easy to lose a
    # typed store/item that way. This presses Enter on the user's behalf
    # first, whenever they leave one of these boxes (by clicking elsewhere, or
    # Tab) while its list is still open with something typed -- the same
    # thing Enter itself would have done. Clicks on the list's own options,
    # or on the same box, are left alone. Switching to another window keeps
    # the text aside instead and types it back in on return, to carry on
    # with -- if that's within a few minutes. Set aside any longer, it's
    # dropped: the desktop window doesn't always say when it's back, and
    # text kept overnight once turned up the next day in the middle of a
    # Japanese item name ("Tデニッシュacos").
    #
    # Listeners go on the document once per browser tab (the flag), keyed by
    # these widgets' st-key-* classes, so reruns and page switches don't
    # stack up duplicates.
    selectors = json.dumps([f".st-key-{key} input" for key in keys])
    st.html(
        f"""<script>
        window._keepTypedSelectors = new Set([...(window._keepTypedSelectors || []), ...{selectors}]);
        if (!window._keepTypedInstalled) {{
            window._keepTypedInstalled = true;
            const pending = (input = document.activeElement) => {{
                if (!input || input.tagName !== "INPUT" || !input.value.trim()) return null;
                if (input.getAttribute("aria-expanded") !== "true") return null;
                return [...window._keepTypedSelectors].some(s => input.matches(s)) ? input : null;
            }};
            const pressEnter = input => input.dispatchEvent(new KeyboardEvent("keydown", {{
                key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true,
            }}));
            document.addEventListener("pointerdown", event => {{
                const input = pending();
                if (!input) return;
                if (event.target.closest('[role="listbox"]')) return;
                if (input.closest(".stSelectbox").contains(event.target)) return;
                pressEnter(input);
            }}, true);
            document.addEventListener("keydown", event => {{
                if (event.key === "Tab") {{
                    const input = pending();
                    if (input) pressEnter(input);
                    return;
                }}
                // Enter in an empty box would pick the list's first option
                // (whatever item sorts first) -- unless the arrow keys were
                // used to go to one, which Enter should still pick.
                const box = event.target;
                if (!box.matches || ![...window._keepTypedSelectors].some(s => box.matches(s))) return;
                // Keys mid Japanese conversion (Space to convert, Enter to
                // confirm) belong to the keyboard, not the box.
                if (event.isComposing || event.keyCode === 229) return;
                if (event.key === "ArrowDown" || event.key === "ArrowUp") box._keepTypedArrowed = true;
                else if (event.key !== "Enter") box._keepTypedArrowed = false;
                else if (!box.value.trim() && !box._keepTypedArrowed && event.isTrusted) {{
                    event.preventDefault();
                    event.stopPropagation();
                }}
            }}, true);
            document.addEventListener("focusin", event => {{ event.target._keepTypedArrowed = false; }}, true);
            // Clicking into a box that already has something in it selects
            // all of it (as Tab already does), so what's typed replaces it
            // whole. Otherwise the box keeps the old text around the new
            // and swaps it for just the new part itself -- which, mid
            // Japanese conversion, garbled the text ("ふファミマ") or brought
            // the old store back.
            document.addEventListener("pointerdown", event => {{
                const box = event.target;
                if (!box.matches || ![...window._keepTypedSelectors].some(s => box.matches(s))) return;
                box._keepTypedSelectAll = document.activeElement !== box && !!box.value;
            }}, true);
            document.addEventListener("pointerup", event => {{
                const box = event.target;
                if (!box._keepTypedSelectAll) return;
                box._keepTypedSelectAll = false;
                if (box.selectionStart === box.selectionEnd) box.select();
            }}, true);
            // Runs before the box's own blur handling, which drops the text.
            document.addEventListener("focusout", event => {{
                const input = pending(event.target);
                if (!input) return;
                const next = event.relatedTarget;
                if (next && (next.closest('[role="listbox"]') || input.closest(".stSelectbox").contains(next))) return;
                if (next) {{
                    pressEnter(input);
                    return;
                }}
                // Nothing else took focus: most likely the window itself lost
                // it (another window, or Win+Space's language switcher
                // mid-word). Entering the text then would make it the box's
                // value, and the next key typed on return would start a new
                // search, wiping it. So it's kept aside and typed back in on
                // return instead (below). The app's window can still say it
                // has focus at this point, so that's checked a moment later;
                // if it really did keep focus, the text is entered after all.
                const selector = [...window._keepTypedSelectors].find(s => input.matches(s));
                window._keepTypedResume = {{ selector, text: input.value, at: Date.now() }};
                setTimeout(() => {{
                    if (!document.hasFocus() || window._keepTypedResume?.selector !== selector) return;
                    const resume = window._keepTypedResume;
                    window._keepTypedResume = null;
                    const box = document.querySelector(selector);
                    if (!box) return;
                    const elsewhere = document.activeElement;
                    retype(box, resume.text);
                    // Enter waits for the box to take the text in, or it
                    // picks the list's first option instead.
                    setTimeout(() => {{
                        pressEnter(box);
                        if (elsewhere && elsewhere !== document.body && elsewhere !== box) elsewhere.focus();
                        else box.blur();
                    }}, 100);
                }}, 100);
            }}, true);
            // Typed in fresh: cleared first so the box counts it as new
            // typing even over a value it already had.
            const retype = (box, text) => {{
                box.focus();
                box.select();
                document.execCommand("delete");
                document.execCommand("insertText", false, text);
            }};
            // Back in the window, the browser puts focus back on the box.
            // Only the text it had then is typed back in: not after five
            // minutes, and not over something typed in it since.
            window.addEventListener("focus", () => {{
                const resume = window._keepTypedResume;
                window._keepTypedResume = null;
                if (!resume || Date.now() - resume.at > 5 * 60 * 1000) return;
                const box = document.querySelector(resume.selector);
                if (!box) return;
                if (box.value && box.value !== resume.text) return;
                if (document.activeElement !== box && document.activeElement !== document.body) return;
                retype(box, resume.text);
            }});
        }}
        </script>""",
        unsafe_allow_javascript=True,
    )


def inject_body_fade_in(container_key: str, extra_css: str = "") -> None:
    # extra_css: any other rules the page needs, sent in the same element --
    # a style element of their own would add an empty row above the page.
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
        {extra_css}
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
