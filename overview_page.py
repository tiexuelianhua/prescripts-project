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
import urllib.error

import streamlit as st

from meal_receipts_data import today_summary as meal_receipts_today_summary
from prescripts_common import LOGO_PATH, inject_body_fade_in, render_page_title, theme_colors
from weather_data import (
    CATEGORY_EMOJI,
    format_condition,
    key_events_headline,
    load_settings as weather_load_settings,
    today_conditions,
    translate_to_english,
    weather_codes,
)

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


with st.container(key="main_body"):
    TILES = [render_meal_receipts_tile, render_weather_tile]
    tile_columns = st.columns(len(TILES))
    for render_tile, column in zip(TILES, tile_columns):
        with column:
            render_tile()
