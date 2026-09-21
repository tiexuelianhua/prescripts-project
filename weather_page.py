# Weather page: a 7-day forecast plus any currently active advisories, both
# from the Japan Meteorological Agency's public "bosai" data feeds
# (https://www.jma.go.jp/bosai/) -- plain, keyless JSON, unlike the
# commercial routing/places APIs flagged elsewhere in the Beyond-phase
# backlog as needing a billing account.
import urllib.error
from datetime import datetime

import streamlit as st

from prescripts_common import JST, LOGO_PATH, inject_body_fade_in, render_page_title, theme_colors
from weather_data import (
    CATEGORY_EMOJI,
    DEFAULT_OFFICE_CODE,
    format_condition,
    key_events_headline,
    load_settings,
    offices,
    save_settings,
    today_conditions,
    translate_to_english,
    weather_codes,
    weekly_forecast,
)

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
    codes = weather_codes()

    try:
        today = today_conditions(office_code)
        today_fetch_failed = False
    except (urllib.error.URLError, TimeoutError):
        today = None
        today_fetch_failed = True

    if today_fetch_failed:
        st.error("Couldn't reach JMA's forecast feed right now.")
    else:
        st.subheader("Today")
        today_info = codes.get(today["weather_code"], {"en": "Unknown", "category": "200"})
        today_columns = st.columns([1, 3])
        with today_columns[0]:
            st.markdown(f"### {CATEGORY_EMOJI.get(today_info['category'], '')}")
        with today_columns[1]:
            st.markdown(f"**{format_condition(today_info['en'])}** for the rest of today")
            if today["pop"] is not None:
                st.caption(f"☔ {today['pop']}% chance of rain")
            if today["live_fetch_failed"]:
                st.caption("Couldn't reach JMA's live observation feed right now.")
            if today["temp"] is not None:
                st.caption(f"🌡️ {today['temp']}°C right now")
            if today["precip_last_hour"] is not None:
                st.caption(f"🌧️ {today['precip_last_hour']}mm of rain in the last hour")

    # Independent of the forecast fetch above (its own try/except) so it
    # still shows -- or reports its own failure -- even if that one failed.
    # Placed after "Today", same as Meal Receipts puts "Entries" after its
    # always-visible add-entry form rather than above it.
    try:
        headline = key_events_headline(office_code)
        warnings_fetch_failed = False
    except (urllib.error.URLError, TimeoutError):
        headline = None
        warnings_fetch_failed = True

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

    if not today_fetch_failed:
        try:
            forecast_reports = weekly_forecast(office_code)
        except (urllib.error.URLError, TimeoutError):
            forecast_reports = None

        if forecast_reports is not None:
            weekly_report = forecast_reports[1]
            condition_series = weekly_report["timeSeries"][0]
            temp_series = weekly_report["timeSeries"][1]
            # areas[0] is each report's primary/mainland district -- offices
            # split into several sub-areas (e.g. Tokyo's Izu/Ogasawara
            # islands) still get one clear forecast rather than a choice
            # buried deeper.
            condition_area = condition_series["areas"][0]
            temp_area = temp_series["areas"][0]

            # The *weekly* report starts tomorrow -- tomorrow's pop/temp
            # (which the weekly report leaves blank) come from the
            # *short-term* report instead, on a completely different time
            # grid (6-hour blocks, not one-value-per-day).
            short_report = forecast_reports[0]
            tomorrow_date = datetime.fromisoformat(condition_series["timeDefines"][0]).date()

            short_pop_series = short_report["timeSeries"][1]
            short_pop_area = short_pop_series["areas"][0]
            tomorrow_pops = [
                int(pop)
                for defined, pop in zip(short_pop_series["timeDefines"], short_pop_area["pops"])
                if datetime.fromisoformat(defined).date() == tomorrow_date and pop
            ]
            tomorrow_pop = str(max(tomorrow_pops)) if tomorrow_pops else ""

            # Only 1-2 point-in-time readings exist for tomorrow here (e.g.
            # "midnight" and "9 AM"), not a true day min/max the way every
            # other column gets -- so these are approximate ("~") rather
            # than presented as if they were as complete as days 2-7's
            # numbers.
            short_temp_series = short_report["timeSeries"][2]
            short_temp_area = short_temp_series["areas"][0]
            tomorrow_temps = [
                int(temp)
                for defined, temp in zip(short_temp_series["timeDefines"], short_temp_area["temps"])
                if datetime.fromisoformat(defined).date() == tomorrow_date and temp
            ]

            # Collapsible like "Key events" above -- but always expanded by
            # default, same as Meal Receipts' "This month" (a standing
            # summary, not something that's only sometimes worth seeing).
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

                        # "%-m"/"%-d" (no leading zero) is a glibc-only
                        # strftime extension -- doesn't exist on Windows'
                        # C runtime, so built manually instead of via
                        # strftime to stay portable.
                        st.markdown(f"**{day.strftime('%a')} {day.month}/{day.day}**")
                        st.markdown(f"### {CATEGORY_EMOJI.get(info['category'], '')}")
                        st.caption(format_condition(info["en"]))
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
