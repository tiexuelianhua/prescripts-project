# Overview page: an at-a-glance summary tile per other page, "control
# center"-style. Imports each page's *data* module directly (never the page
# script itself, which would run that page's whole UI as a side effect of
# import) so every tile stays as fresh as the real page, reusing the exact
# same st.cache_data calls.
#
# Adding a tile for a future page = import its data module, write one more
# render_..._tile() function below, and add it to TILES. No registry beyond
# that list -- with only a handful of pages, a heavier plugin mechanism
# would be solving a problem this doesn't have yet.
import time
import urllib.error

import streamlit as st

from meal_receipts_data import today_summary as meal_receipts_today_summary
from prescripts_common import LOGO_PATH, inject_body_fade_in, render_page_title, theme_colors
from spotify_data import (
    current_playback as spotify_current_playback,
    describe_item as spotify_describe_item,
    is_configured as spotify_is_configured,
    is_connected as spotify_is_connected,
)
from spotify_log import log_event, log_slow
from spotify_widgets import inject_seek_slider_styles, page_is_locked, render_seek_slider, render_transport_controls
from weather_data import (
    CATEGORY_EMOJI,
    format_condition,
    key_events_headline,
    load_settings as weather_load_settings,
    today_conditions,
    translate_to_english,
    weather_codes,
)

run_started = time.time()
TEXT_COLOR, ACCENT_COLOR = theme_colors()
PAGE_TITLE = "Overview"

is_first_load = "_overview_title_played" not in st.session_state
inject_body_fade_in("main_body")

header_logo, header_title = st.columns([1, 4], vertical_alignment="center")
with header_logo:
    st.image(str(LOGO_PATH), width=120)
with header_title:
    render_page_title(PAGE_TITLE, is_first_load)

if is_first_load:
    st.session_state["_overview_title_played"] = True

inject_seek_slider_styles("overview_spotify_seek")


def render_meal_receipts_tile() -> None:
    st.subheader("🧾 Meal Receipts")
    data = meal_receipts_today_summary()
    # st.metric only reads a leading "-" to decide the arrow/color for a
    # string delta, so the sign has to be the very first character.
    if data["budget_period"] == "weekly" and data["budget_amount"] > 0:
        week_total = data["week_total_yen"]
        diff = week_total - data["budget_amount"]
        diff_str = f"-¥{abs(diff):,.0f}" if diff < 0 else f"¥{diff:,.0f}"
        st.metric(
            "This week's total",
            f"¥{week_total:,.0f}",
            delta=f"{diff_str} vs ¥{data['budget_amount']:,.0f} allowance",
            delta_color="inverse",
        )
        st.progress(min(week_total / data["budget_amount"], 1.0))
        st.caption(f"Today so far: ¥{data['total_yen']:,.0f}")
    elif data["budget_amount"] > 0:
        diff = data["total_yen"] - data["budget_amount"]
        diff_str = f"-¥{abs(diff):,.0f}" if diff < 0 else f"¥{diff:,.0f}"
        st.metric(
            "Today's total",
            f"¥{data['total_yen']:,.0f}",
            delta=f"{diff_str} vs ¥{data['budget_amount']:,.0f} budget",
            delta_color="inverse",
        )
        st.progress(min(data["total_yen"] / data["budget_amount"], 1.0))
    else:
        st.metric("Today's total", f"¥{data['total_yen']:,.0f}")
    st.page_link("mealReceiptsApp_cV.py", label="Open Meal Receipts", icon="🧾")


def render_weather_tile() -> None:
    settings = weather_load_settings()
    office_code = settings["office_code"]
    office_name = settings["office_name"]
    st.subheader(f"🌤️ Weather -- {office_name}")

    try:
        today = today_conditions(office_code)
        today_failed = False
    except (urllib.error.URLError, TimeoutError):
        today = None
        today_failed = True

    if today_failed:
        st.error("Couldn't reach JMA's forecast feed right now.")
    else:
        codes = weather_codes()
        info = codes.get(today["weather_code"], {"en": "Unknown", "category": "200"})
        condition_columns = st.columns([1, 3])
        with condition_columns[0]:
            st.markdown(f"### {CATEGORY_EMOJI.get(info['category'], '')}")
        with condition_columns[1]:
            st.markdown(f"**{format_condition(info['en'])}**")
            if today["temp"] is not None:
                st.caption(f"🌡️ {today['temp']}°C right now")
            if today["pop"] is not None:
                st.caption(f"☔ {today['pop']}% chance of rain")

    # Independent of today_conditions() above -- own endpoint, own failure
    # mode, same as the full Weather page keeps them separate.
    try:
        headline = key_events_headline(office_code)
        events_failed = False
    except (urllib.error.URLError, TimeoutError):
        headline = None
        events_failed = True

    if events_failed:
        st.error("Couldn't reach JMA's warnings feed right now.")
    elif headline:
        try:
            translated = translate_to_english(headline)
        except (urllib.error.URLError, TimeoutError):
            translated = None
        st.warning(translated or headline)

    st.page_link("weather_page.py", label="Open Weather", icon="🌤️")


# Its own fragment so just this tile ticks every second (the position slider
# moves, a track change shows up) without re-running the other tiles.
@st.fragment(run_every=1)
@log_slow("Overview Spotify tile refresh")
def render_spotify_player() -> None:
    try:
        playback = spotify_current_playback()
    except (urllib.error.URLError, TimeoutError):
        st.error("Couldn't reach Spotify's player right now.")
        return

    if not playback or not playback.get("item"):
        st.caption("Nothing playing right now.")
        return

    # Read-only mode is set on the Spotify page but shared (persisted in
    # Spotify/settings.json) -- flipping it there also locks this tile.
    locked = page_is_locked("overview_spotify")

    track = spotify_describe_item(playback["item"])
    track_columns = st.columns([1, 3])
    with track_columns[0]:
        if track["image_url"]:
            st.image(track["image_url"], width=80)
    with track_columns[1]:
        st.markdown(f"**{track['name']}**")
        st.caption(track["artists"])
    render_seek_slider(playback, "overview_spotify_seek", locked=locked)
    render_transport_controls(playback, "overview_spotify", icons_only=True, locked=locked)


def render_spotify_tile() -> None:
    st.subheader("🎵 Spotify")
    if not spotify_is_configured() or not spotify_is_connected():
        st.caption("Not connected yet -- connect your account on the Spotify page.")
    else:
        render_spotify_player()
    st.page_link("spotify_page.py", label="Open Spotify", icon="🎵")


# Two columns, each tile placed in whichever is currently shorter -- so a
# short tile (Meal Receipts) gets the next one stacked under it instead of
# leaving a gap beside a tall one (Weather). Weights are rough relative
# heights, not measurements: Streamlit can't see rendered heights, and tiles
# vary (e.g. a weather warning adds a line), so this only has to be close.
# A new page's tile = one more (render function, weight, live) entry.
#
# "live" marks a tile showing something that moves in real time (the Spotify
# position slider). Those are filled in LAST: the page loads over the
# network (weather, etc.), and a live tile drawn early sits frozen at its
# starting value for however long the rest of the load takes, then visibly
# jumps once the next refresh lands. Drawn last, it's current the moment the
# load finishes. Each tile's spot is reserved (container) in layout order
# first, so filling them in a different order doesn't change where they show.
TILES = [
    (render_meal_receipts_tile, 3, False),
    (render_weather_tile, 4, False),
    (render_spotify_tile, 4, True),
]

# Each tile is outlined in the theme's accent blue (the same blue as the
# buttons' outlines) so the tiles read as separate widgets. Styled directly
# on the keyed container rather than via st.container(border=True), whose
# border color comes from the theme's generic borderColor instead.
#
# The tiles share edges, like cells of one grid: no gap between columns or
# between stacked tiles, and a -1px margin pulls each tile's border onto its
# neighbor's (bottom margin for stacked tiles, left margin for the right-hand
# column) so two 1px borders read as one line.
# Columns are already stretched to equal height by Streamlit; the last tile
# in each column grows to fill what's left, so both columns end on the same
# line instead of one sticking out past the other.
st.markdown(
    f"""
    <style>
    [class*="st-key-overview_tile_"] {{
        border: 1px solid {ACCENT_COLOR};
        border-radius: 0;
        margin: 0 0 -1px 0;
        /* The subheading brings its own top padding on top of this
           container's, so the bottom needs more than the top to make the
           gap under the last element match the gap above the title.
           (1.5rem still read slightly short.) */
        padding: 1rem 1rem 1.75rem;
    }}
    /* Tiles are as wide as their column, so a right margin can't pull the
       neighbor over; instead the right-hand column's tiles shift 1px left
       onto the left column's border. */
    [data-testid="stColumn"] + [data-testid="stColumn"] [class*="st-key-overview_tile_"] {{
        margin-left: -1px;
    }}
    [data-testid="stColumn"]:has([class*="st-key-overview_tile_"]) > [data-testid="stVerticalBlock"] {{
        gap: 0;
    }}
    [data-testid="stColumn"]:has([class*="st-key-overview_tile_"]) > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"]:last-child {{
        flex-grow: 1;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

with st.container(key="main_body"):
    columns = st.columns(2, gap=0)
    column_heights = [0, 0]
    placements = []
    for tile_number, (render_tile, weight, live) in enumerate(TILES):
        shorter = 0 if column_heights[0] <= column_heights[1] else 1
        column_heights[shorter] += weight
        spot = columns[shorter].container(key=f"overview_tile_{tile_number}")
        placements.append((render_tile, spot, live))

    # sorted() is stable, so non-live tiles keep their order among themselves.
    for render_tile, spot, _ in sorted(placements, key=lambda placement: placement[2]):
        with spot:
            render_tile()

if time.time() - run_started > 2.0:
    log_event(f"slow: Overview page full run took {time.time() - run_started:.2f}s")
