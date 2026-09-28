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
import html
import random
import time
import urllib.error
from datetime import datetime

import streamlit as st

from prescripts.common import (
    JST,
    balanced_columns,
    inject_body_fade_in,
    render_page_title,
    show_logo,
    theme_colors,
)
from prescripts.data.activities import (
    CATEGORIES as ACTIVITIES_CATEGORIES,
    DEFAULT_RADIUS as ACTIVITIES_DEFAULT_RADIUS,
    fetch_places as activities_fetch_places,
    load_settings as activities_load_settings,
    map_link as activities_map_link,
    parse_places as activities_parse_places,
    place_spot as activities_place_spot,
)
from prescripts.data.japanese.answers import (
    display_readings as japanese_display_readings,
    has_distinct_reading as japanese_has_distinct_reading,
)
from prescripts.data.japanese.deck import (
    KIND_LABELS,
    card_by_id as japanese_card_by_id,
    practice_summary as japanese_practice_summary,
    random_card as japanese_random_card,
)
from prescripts.data.meal_receipts import today_summary as meal_receipts_today_summary
from prescripts.data.spotify import (
    current_playback as spotify_current_playback,
    describe_item as spotify_describe_item,
    is_configured as spotify_is_configured,
    is_connected as spotify_is_connected,
)
from prescripts.data.spotify_log import log_event, log_slow
from prescripts.data.weather import (
    CATEGORY_EMOJI,
    format_condition,
    key_events_headline,
    load_settings as weather_load_settings,
    today_conditions,
    translate_to_english,
    weather_codes,
)
from prescripts.spotify_widgets import (
    inject_seek_slider_styles,
    page_is_locked,
    render_seek_slider,
    render_transport_controls,
)

run_started = time.time()
# (placeholder, Japanese text) for translations deferred until every tile
# has loaded -- see the Weather tile and the end of this page.
pending_translations = []
TEXT_COLOR, ACCENT_COLOR = theme_colors()
PAGE_TITLE = "Overview"

is_first_load = "_overview_title_played" not in st.session_state
inject_body_fade_in("main_body")

header_logo, header_title, header_clock = st.columns([1, 3, 1.2], vertical_alignment="center")
with header_logo:
    show_logo(width=120)
with header_title:
    render_page_title(PAGE_TITLE, is_first_load)

if is_first_load:
    st.session_state["_overview_title_played"] = True


# Own fragment so just the clock ticks every second, same reasoning as the
# Spotify tile below: everything else on the page is left untouched by its
# reruns.
@st.fragment(run_every=1)
def render_jst_clock() -> None:
    now = datetime.now(JST)
    japanese_date = f"{now.year}年{now.month}月{now.day}日"
    st.markdown(
        f"""
        <div style="text-align: right; font-variant-numeric: tabular-nums;">
            <div style="font-size: 1.4rem; font-weight: bold; color: {ACCENT_COLOR};">{now:%H:%M:%S}</div>
            <div style="font-size: 0.8rem; color: {TEXT_COLOR}; opacity: 0.7;">{japanese_date} JST</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


with header_clock:
    render_jst_clock()

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
    st.page_link("prescripts/pages/meal_receipts.py", label="Open Meal Receipts", icon="🧾")


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
        # Shown in the original Japanese for now; the English goes into the
        # same spot once every tile has loaded (see the end of this page), so
        # the translation service's lookup doesn't hold up the tiles below.
        spot = st.empty()
        spot.warning(headline)
        pending_translations.append((spot, headline))

    st.page_link("prescripts/pages/weather.py", label="Open Weather", icon="🌤️")


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
    st.page_link("prescripts/pages/spotify.py", label="Open Spotify", icon="🎵")


def render_japanese_tile() -> None:
    st.subheader("🈁 Japanese")
    data = japanese_practice_summary()
    if not sum(data["total"].values()):
        st.caption("No flashcards yet.")
    else:
        # A random card from the deck, just to look at: new one each time
        # Overview is opened, but kept while staying on the page, so a
        # Spotify button press (a full rerun) doesn't swap it out.
        just_arrived = st.session_state.get("_previous_page") != st.session_state.get("_current_page")
        card = None if just_arrived else japanese_card_by_id(st.session_state.get("overview_japanese_card"))
        if card is None:  # just arrived, or the shown card was deleted
            card = japanese_random_card()
            st.session_state["overview_japanese_card"] = card["id"]
        reading = ""
        if japanese_has_distinct_reading(card):
            reading = f'<div class="overview-word-reading">{html.escape(card["reading"])}</div>'
        # Kanji: on'yomi and kun'yomi on one line, where vocab has its reading.
        kanji_readings = " · ".join(
            japanese_display_readings(card[field]) for field in ("onyomi", "kunyomi") if card.get(field)
        )
        if kanji_readings:
            reading = f'<div class="overview-word-reading">{html.escape(kanji_readings)}</div>'
        st.markdown(
            f'<div class="overview-word"><div class="overview-word-front" lang="ja">{html.escape(card["front"])}</div>'
            f'{reading}<div class="overview-word-meaning">{html.escape(card["meaning"])}</div></div>',
            unsafe_allow_html=True,
        )
        due_total = sum(data["due"].values())
        st.metric("Due for review", due_total)
        st.caption(
            " · ".join(f"{KIND_LABELS[kind]}: {data['due'][kind]} due of {data['total'][kind]}" for kind in data["total"])
        )
        st.caption(f"Reviewed today: {data['reviewed_today']}")
    st.page_link("prescripts/pages/japanese.py", label="Open Japanese", icon="🈁")


def render_activities_tile() -> None:
    settings = activities_load_settings()
    area = settings.get("area")
    st.subheader(f"📍 Activities -- {area}" if area else "📍 Activities")
    if not area:
        st.caption("No area saved yet -- pick one on the Activities page.")
    else:
        # Food only: it's the quick lookup (things to do can take 15s+ when
        # OSM is busy, which would hold up the whole page), and cached a day.
        radius = settings.get("radius", ACTIVITIES_DEFAULT_RADIUS)
        try:
            elements = activities_fetch_places("food", *activities_place_spot(settings["lat"], settings["lon"]), radius)
            places = activities_parse_places("food", elements, settings["lat"], settings["lon"])
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
            places = None
            st.caption("Couldn't reach OpenStreetMap's place search right now.")
        if places == []:
            st.caption("No food places found within walking distance.")
        elif places:
            # A random pick, like the Japanese tile's word: new each time
            # Overview is opened, kept while staying here (a Spotify button
            # press reruns the page), or re-rolled with the button.
            just_arrived = st.session_state.get("_previous_page") != st.session_state.get("_current_page")
            chosen_id = None if just_arrived else st.session_state.get("overview_activities_place")
            place = next((place for place in places if place["id"] == chosen_id), None) or random.choice(places)
            st.session_state["overview_activities_place"] = place["id"]
            english = f" · {html.escape(place['name_en'])}" if place["name_en"] else ""
            details = [ACTIVITIES_CATEGORIES["food"][place["category"]][0].removesuffix("s"),
                       f"{place['distance']:.0f} m away" if place["distance"] < 1000
                       else f"{place['distance'] / 1000:.1f} km away"]
            details += [html.escape(detail) for detail in (place["cuisine"], place["hours"]) if detail]
            st.markdown(
                f'<div class="overview-place-name" lang="ja">{html.escape(place["name"])}{english}</div>'
                f"<small>{' · '.join(details)} · "
                f"<a href='{activities_map_link(place)}' target='_blank'>Map</a></small>",
                unsafe_allow_html=True,
            )
            if st.button("🎲 Another", key="overview_activities_another"):
                others = [other for other in places if other["id"] != place["id"]] or places
                st.session_state["overview_activities_place"] = random.choice(others)["id"]
                st.rerun()
    st.page_link("prescripts/pages/activities.py", label="Open Activities", icon="📍")


# Two columns, split so they end as level as possible (balanced_columns in
# common.py). Streamlit can't see rendered heights, so each tile has an
# estimate, in tens of pixels, measured in a browser with sample data
# (2026-09-28). Tiles whose height swings with what they show are estimated
# from that: Weather is ~250px taller with a warning, Spotify taller once
# connected, and Japanese and Activities short until they have cards / an
# area. So tiles can sit in different columns on different days -- chosen
# over a fixed layout, which left a big gap on one kind of day.
# A new page's tile = one more (render function, height, live) entry, the
# height a number or a function returning one.
#
# "live" marks a tile showing something that moves in real time (the Spotify
# position slider). Those are filled in LAST: the page loads over the
# network (weather, etc.), and a live tile drawn early sits frozen at its
# starting value for however long the rest of the load takes, then visibly
# jumps once the next refresh lands. Drawn last, it's current the moment the
# load finishes. Each tile's spot is reserved (container) in layout order
# first, so filling them in a different order doesn't change where they show.
def _weather_height() -> int:
    # The same cached warnings lookup the tile itself makes, so no extra cost.
    try:
        return 57 if key_events_headline(weather_load_settings()["office_code"]) else 32
    except (urllib.error.URLError, TimeoutError):
        return 38  # the tile shows an error box instead


def _japanese_height() -> int:
    return 45 if sum(japanese_practice_summary()["total"].values()) else 19


def _activities_height() -> int:
    return 28 if activities_load_settings().get("area") else 19


def _spotify_height() -> int:
    # Connected, it's usually showing a track with its slider and buttons;
    # asking Spotify what's playing first would slow every Overview load.
    return 30 if spotify_is_configured() and spotify_is_connected() else 19


TILES = [
    (render_meal_receipts_tile, 33, False),
    (render_weather_tile, _weather_height, False),
    (render_japanese_tile, _japanese_height, False),
    (render_activities_tile, _activities_height, False),
    (render_spotify_tile, _spotify_height, True),
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
    /* The Japanese tile's random word: the word in Windows' Japanese font,
       same as the Japanese page's flashcard front (the pixel font drops
       strokes from dense kanji), reading in the accent blue. */
    .overview-word {{
        text-align: center;
        margin: 0.5rem 0 1rem;
    }}
    .overview-word-front {{
        font-family: "Yu Gothic UI", "Yu Gothic", "Meiryo", sans-serif;
        font-size: 3rem;
        line-height: 1.2;
    }}
    .overview-word-reading {{
        color: {ACCENT_COLOR};
        font-size: 1.2rem;
        margin-top: 0.25rem;
    }}
    .overview-word-meaning {{
        margin-top: 0.25rem;
    }}
    /* The Activities tile's pick, in the same Japanese font for the same reason. */
    .overview-place-name {{
        font-family: "Yu Gothic UI", "Yu Gothic", "Meiryo", "Hiragino Sans", sans-serif;
        font-size: 1.3rem;
        font-weight: bold;
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
    heights = [height() if callable(height) else height for _render, height, _live in TILES]
    placements = []
    for tile_number, ((render_tile, _height, live), column) in enumerate(zip(TILES, balanced_columns(heights))):
        spot = columns[column].container(key=f"overview_tile_{tile_number}")
        placements.append((render_tile, spot, live))

    # sorted() is stable, so non-live tiles keep their order among themselves.
    for render_tile, spot, _ in sorted(placements, key=lambda placement: placement[2]):
        with spot:
            render_tile()

    # Last, once every tile is showing: English for the warning(s) the
    # Weather tile put up in Japanese. If it fails, the Japanese just stays.
    for spot, headline in pending_translations:
        try:
            translated = translate_to_english(headline)
        except (urllib.error.URLError, TimeoutError):
            translated = None
        if translated:
            spot.warning(translated)

if time.time() - run_started > 2.0:
    log_event(f"slow: Overview page full run took {time.time() - run_started:.2f}s")
