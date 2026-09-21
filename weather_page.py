# Weather page: a 7-day forecast plus any currently active advisories, both
# from the Japan Meteorological Agency's public "bosai" data feeds
# (https://www.jma.go.jp/bosai/) -- plain, keyless JSON, unlike the
# commercial routing/places APIs flagged elsewhere in the Beyond-phase
# backlog as needing a billing account.
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import streamlit as st

from prescripts_common import (
    JST,
    LOGO_PATH,
    SCRIPTS_DIR,
    inject_body_fade_in,
    render_page_title,
    theme_colors,
)

WEATHER_DIR = SCRIPTS_DIR.parent / "Weather"
SETTINGS_PATH = WEATHER_DIR / "settings.json"
WEATHER_CODES_PATH = SCRIPTS_DIR / "weather_codes.json"
DEFAULT_OFFICE_CODE = "130000"
DEFAULT_OFFICE_NAME = "Tokyo"

AREA_URL = "https://www.jma.go.jp/bosai/common/const/area.json"
FORECAST_URL = "https://www.jma.go.jp/bosai/forecast/data/forecast/{code}.json"
WARNING_URL = "https://www.jma.go.jp/bosai/warning/data/warning/{code}.json"
# AMeDAS: JMA's live observation network, updated every 10 minutes -- actual
# measured readings (not a forecast), for a "right now" section distinct
# from the forecast-only ones elsewhere on this page.
AMEDAS_LATEST_URL = "https://www.jma.go.jp/bosai/amedas/data/latest_time.txt"
AMEDAS_MAP_URL = "https://www.jma.go.jp/bosai/amedas/data/map/{timestamp}.json"
# MyMemory: free, keyless machine translation (a few thousand words/day
# anonymous, plenty for one person's occasional advisory headline) -- JMA's
# own advisory text has no English version at all, unlike its forecast
# codes, which already ship an "en" field in weather_codes.json.
TRANSLATE_URL = "https://api.mymemory.translated.net/get?q={text}&langpair=ja|en"

# JMA's own weather-code table (100=clear, 200=cloudy, 300=rain, 400=snow, at
# the hundreds level) mapped to a plain emoji -- SVG icons exist too, but
# they'd mean hosting/downloading JMA's image assets for what a single
# character already conveys at a glance in this app's minimal style.
CATEGORY_EMOJI = {"100": "☀️", "200": "☁️", "300": "🌧️", "400": "❄️"}


def _fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.read().decode("utf-8").strip()


@st.cache_data(ttl=60 * 60 * 24)
def offices() -> dict[str, str]:
    # Prefecture-level forecast offices (~58 of them) -- one selectbox entry
    # each, keyed by English name since JMA's own names in this file are
    # Japanese-only.
    data = _fetch_json(AREA_URL)
    return {code: office["enName"] for code, office in data["offices"].items()}


@st.cache_data(ttl=60 * 30)
def weekly_forecast(office_code: str) -> dict:
    return _fetch_json(FORECAST_URL.format(code=office_code))


@st.cache_data(ttl=60 * 10)
def active_warnings(office_code: str) -> dict:
    return _fetch_json(WARNING_URL.format(code=office_code))


@st.cache_data(ttl=60 * 10)
def translate_to_english(japanese_text: str) -> str | None:
    # Cached on the source text itself (same 10-minute ttl as the warnings
    # feed it's called from) so a headline is translated once per change,
    # not on every rerun a widget interaction triggers -- MyMemory's free
    # tier is generous for one person but there's no reason to spend it on
    # re-translating the same sentence every time a field is touched.
    url = TRANSLATE_URL.format(text=urllib.parse.quote(japanese_text))
    result = _fetch_json(url)
    translated = result.get("responseData", {}).get("translatedText")
    return translated or None


@st.cache_data(ttl=60 * 10)
def current_conditions(station_code: str) -> dict | None:
    latest = datetime.fromisoformat(_fetch_text(AMEDAS_LATEST_URL))
    timestamp = latest.strftime("%Y%m%d%H%M%S")
    stations = _fetch_json(AMEDAS_MAP_URL.format(timestamp=timestamp))
    return stations.get(station_code)


@st.cache_data(ttl=None)
def weather_codes() -> dict:
    return json.loads(WEATHER_CODES_PATH.read_text(encoding="utf-8"))


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return {"office_code": DEFAULT_OFFICE_CODE, "office_name": DEFAULT_OFFICE_NAME}


def save_settings(settings: dict) -> None:
    WEATHER_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


TEXT_COLOR, ACCENT_COLOR = theme_colors()
PAGE_TITLE = "Weather"

# Only the page title gets the typewriter treatment, and only once per
# session (own key -- session_state is shared across every page in this
# app, so reusing Meal Receipts' title key would make visiting one page
# silently skip the other's intro). Every other heading on this page (Key
# events, Today, 7-day outlook) stays plain: this page has a "Forecast
# area" selectbox that reruns the whole script on change, same as Meal
# Receipts' fields do -- animating more than one heading would either
# replay on every one of those reruns (the stutter fixed there earlier) or,
# if gated the same "first load only" way, just stack up several seconds of
# sequential typing before the page is usable at all.
is_first_load = "_weather_title_played" not in st.session_state
inject_body_fade_in("main_body")

header_logo, header_title = st.columns([1, 4], vertical_alignment="center")
with header_logo:
    st.image(str(LOGO_PATH), width=120)
with header_title:
    render_page_title(PAGE_TITLE, is_first_load)

if is_first_load:
    st.session_state["_weather_title_played"] = True

settings = load_settings()

with st.sidebar:
    st.header("Settings")
    try:
        office_choices = offices()
    except (urllib.error.URLError, TimeoutError):
        office_choices = {settings["office_code"]: settings["office_name"]}
        st.caption("Couldn't reach JMA to list other areas -- keeping the current one.")

    codes_sorted = sorted(office_choices, key=lambda code: office_choices[code])
    default_code = settings.get("office_code", DEFAULT_OFFICE_CODE)
    default_index = codes_sorted.index(default_code) if default_code in codes_sorted else 0
    chosen_code = st.selectbox(
        "Forecast area",
        options=codes_sorted,
        format_func=lambda code: office_choices[code],
        index=default_index,
        key="weather_office_code",
    )
    if chosen_code != settings.get("office_code"):
        settings = {"office_code": chosen_code, "office_name": office_choices[chosen_code]}
        save_settings(settings)

with st.container(key="main_body"):
    office_code = settings["office_code"]
    office_name = settings["office_name"]

    try:
        forecast_reports = weekly_forecast(office_code)
    except (urllib.error.URLError, TimeoutError):
        st.error("Couldn't reach JMA's forecast feed right now.")
        forecast_reports = None

    if forecast_reports is not None:
        weekly_report = forecast_reports[1]
        condition_series = weekly_report["timeSeries"][0]
        temp_series = weekly_report["timeSeries"][1]
        # areas[0] is each report's primary/mainland district -- offices
        # split into several sub-areas (e.g. Tokyo's Izu/Ogasawara islands)
        # still get one clear forecast rather than a choice buried deeper.
        condition_area = condition_series["areas"][0]
        temp_area = temp_series["areas"][0]
        codes = weather_codes()

        # The *weekly* report starts tomorrow -- today's own conditions,
        # and tomorrow's pop/temp (which the weekly report leaves blank),
        # both come from this *short-term* report instead, on a completely
        # different time grid (today's remaining hours + tomorrow in
        # 6-hour blocks, not one-value-per-day). Same area (areas[0])
        # throughout for consistency.
        short_report = forecast_reports[0]
        today_date = datetime.now(JST).date()
        tomorrow_date = datetime.fromisoformat(condition_series["timeDefines"][0]).date()

        short_condition_area = short_report["timeSeries"][0]["areas"][0]
        short_pop_series = short_report["timeSeries"][1]
        short_pop_area = short_pop_series["areas"][0]

        def _pops_for(target_date):
            return [
                int(pop)
                for defined, pop in zip(short_pop_series["timeDefines"], short_pop_area["pops"])
                if datetime.fromisoformat(defined).date() == target_date and pop
            ]

        today_pops = _pops_for(today_date)
        tomorrow_pops = _pops_for(tomorrow_date)
        tomorrow_pop = str(max(tomorrow_pops)) if tomorrow_pops else ""

        # Only 1-2 point-in-time readings exist for tomorrow here (e.g.
        # "midnight" and "9 AM"), not a true day min/max the way every
        # other column gets -- so these are approximate ("~") rather than
        # presented as if they were as complete as days 2-7's numbers.
        short_temp_series = short_report["timeSeries"][2]
        short_temp_area = short_temp_series["areas"][0]
        station_code = short_temp_area["area"]["code"]
        tomorrow_temps = [
            int(temp)
            for defined, temp in zip(short_temp_series["timeDefines"], short_temp_area["temps"])
            if datetime.fromisoformat(defined).date() == tomorrow_date and temp
        ]

        st.subheader("Today")
        today_code = short_condition_area["weatherCodes"][0]
        today_info = codes.get(today_code, {"en": "Unknown", "category": "200"})
        today_columns = st.columns([1, 3])
        with today_columns[0]:
            st.markdown(f"### {CATEGORY_EMOJI.get(today_info['category'], '')}")
        with today_columns[1]:
            st.markdown(f"**{today_info['en'].capitalize()}** for the rest of today")
            if today_pops:
                st.caption(f"☔ {max(today_pops)}% chance of rain")
            try:
                live = current_conditions(station_code)
            except (urllib.error.URLError, TimeoutError):
                live = None
                st.caption("Couldn't reach JMA's live observation feed right now.")
            if live:
                temp_val, temp_flag = live.get("temp", [None, None])
                if temp_val is not None and temp_flag == 0:
                    st.caption(f"🌡️ {temp_val}°C right now")
                precip_val, precip_flag = live.get("precipitation1h", [None, None])
                if precip_val is not None and precip_flag == 0 and precip_val > 0:
                    st.caption(f"🌧️ {precip_val}mm of rain in the last hour")

    # Independent of the forecast fetch above (its own try/except) so it
    # still shows -- or reports its own failure -- even if that one failed.
    # Placed after "Today", same as Meal Receipts puts "Entries" after its
    # always-visible add-entry form rather than above it.
    try:
        warning_data = active_warnings(office_code)
        warnings_fetch_failed = False
    except (urllib.error.URLError, TimeoutError):
        warning_data = None
        warnings_fetch_failed = True

    headline = (warning_data or {}).get("headlineText", "").strip()
    # Collapsible like Meal Receipts' "Entries"/"This month" sections --
    # expanded when there's actually something to see (an active advisory,
    # or a fetch error worth noticing), collapsed when it's just "all
    # clear" and not worth the space.
    with st.expander(f"Key events -- {office_name}", expanded=bool(headline) or warnings_fetch_failed):
        if warnings_fetch_failed:
            st.error("Couldn't reach JMA's warnings feed right now.")
        elif headline:
            try:
                translated = translate_to_english(headline)
            except (urllib.error.URLError, TimeoutError):
                translated = None
            st.warning(translated or headline)
            if translated:
                st.caption(headline)
            else:
                st.caption("(English translation unavailable right now -- showing the original)")
        else:
            st.caption(f"No advisories currently in effect for {office_name}.")

    if forecast_reports is not None:
        # Collapsible like "Key events" above -- but always expanded by
        # default, same as Meal Receipts' "This month" (a standing summary,
        # not something that's only sometimes worth seeing).
        with st.expander("7-day outlook", expanded=True):
            day_columns = st.columns(len(condition_series["timeDefines"]))
            for i, column in enumerate(day_columns):
                with column:
                    day = datetime.fromisoformat(condition_series["timeDefines"][i])
                    weather_code = condition_area["weatherCodes"][i]
                    info = codes.get(weather_code, {"en": "Unknown", "category": "200"})
                    is_tomorrow = i == 0
                    pop = condition_area["pops"][i] or (tomorrow_pop if is_tomorrow else "")
                    if is_tomorrow and tomorrow_temps:
                        temp_min, temp_max = str(min(tomorrow_temps)), str(max(tomorrow_temps))
                        approx = "~"
                    else:
                        temp_min, temp_max = temp_area["tempsMin"][i], temp_area["tempsMax"][i]
                        approx = ""

                    # "%-m"/"%-d" (no leading zero) is a glibc-only strftime
                    # extension -- doesn't exist on Windows' C runtime, so
                    # built manually instead of via strftime to stay
                    # portable.
                    st.markdown(f"**{day.strftime('%a')} {day.month}/{day.day}**")
                    st.markdown(f"### {CATEGORY_EMOJI.get(info['category'], '')}")
                    st.caption(info["en"].capitalize())
                    if pop:
                        st.caption(f"☔ {pop}%")
                    if temp_min and temp_max:
                        st.caption(f"{approx}{temp_min}–{temp_max}°C")

            st.caption(f"Source: JMA, as of {weekly_report['reportDatetime']}")
            st.caption(
                "~ = tomorrow's temperature is from JMA's short-term forecast "
                "(only a couple of readings so far), not the full-day range "
                "the other days get once JMA's weekly numbers cover them."
            )
