# Data/business logic for the Weather page -- JMA's public "bosai" feeds,
# settings, and summary computations, deliberately with no Streamlit
# *rendering* calls (st.cache_data is fine, it's just a caching decorator
# with no UI output). That separation means other pages (e.g. an Overview
# page wanting today's conditions) can import and call these directly
# without accidentally triggering weather_page.py's own UI as a side effect
# of the import.
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

import streamlit as st

from prescripts_common import JST, SCRIPTS_DIR

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
# character already conveys at a glance in this app's minimal style. Lives
# here (not just in weather_page.py) so any other page rendering a weather
# tile shows the same icon for the same category.
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


def format_condition(en: str) -> str:
    # JMA's own English weather-code text is occasionally missing a space
    # after a comma (e.g. "RAIN,CLOUDY LATER" -- 13 of its 118 codes do
    # this) -- fixed here at display time, not in weather_codes.json
    # itself, so that file stays a faithful, unmodified copy of JMA's
    # source data. .capitalize() (not .title()) matches how every other
    # word in these all-caps strings should read: lowercase except the
    # first letter.
    return re.sub(r",(?!\s)", ", ", en).strip().capitalize()


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return {"office_code": DEFAULT_OFFICE_CODE, "office_name": DEFAULT_OFFICE_NAME}


def save_settings(settings: dict) -> None:
    WEATHER_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def today_conditions(office_code: str) -> dict:
    # Shared by this page's own "Today" section and any other page's
    # summary tile -- parses the short-term forecast (today's remaining
    # condition + rain chance) and the live AMeDAS observation (actual
    # temp/precipitation, not a forecast) for the office's primary
    # district/station (areas[0], same convention used throughout).
    forecast_reports = weekly_forecast(office_code)
    short_report = forecast_reports[0]
    short_condition_area = short_report["timeSeries"][0]["areas"][0]
    short_pop_series = short_report["timeSeries"][1]
    short_pop_area = short_pop_series["areas"][0]
    station_code = short_report["timeSeries"][2]["areas"][0]["area"]["code"]

    today_date = datetime.now(JST).date()
    today_pops = [
        int(pop)
        for defined, pop in zip(short_pop_series["timeDefines"], short_pop_area["pops"])
        if datetime.fromisoformat(defined).date() == today_date and pop
    ]

    temp = None
    precip_last_hour = None
    live_fetch_failed = False
    try:
        live = current_conditions(station_code)
    except (urllib.error.URLError, TimeoutError):
        live = None
        live_fetch_failed = True
    if live:
        temp_val, temp_flag = live.get("temp", [None, None])
        if temp_val is not None and temp_flag == 0:
            temp = temp_val
        precip_val, precip_flag = live.get("precipitation1h", [None, None])
        if precip_val is not None and precip_flag == 0 and precip_val > 0:
            precip_last_hour = precip_val

    return {
        "weather_code": short_condition_area["weatherCodes"][0],
        "pop": max(today_pops) if today_pops else None,
        "temp": temp,
        "precip_last_hour": precip_last_hour,
        "live_fetch_failed": live_fetch_failed,
    }


def key_events_headline(office_code: str) -> str | None:
    # Independent of today_conditions()/weekly_forecast() above -- its own
    # endpoint, its own failure mode -- so a caller can still show today's
    # conditions even if this one fails, and vice versa.
    warning_data = active_warnings(office_code)
    headline = (warning_data or {}).get("headlineText", "").strip()
    return headline or None
