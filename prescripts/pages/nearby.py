# Nearby page: food and things to do within walking distance of a saved area
# (a station or neighbourhood, typed once and remembered) or, for one visit,
# the computer's current location. Places come from OpenStreetMap -- see
# data/nearby.py for the lookups and why they're OSM's.
import html
import urllib.error

import streamlit as st

from prescripts.common import inject_body_fade_in, render_page_title, show_logo
from prescripts.data.nearby import (
    CATEGORIES,
    RADII,
    fetch_places,
    find_area,
    load_settings,
    map_embed,
    map_link,
    parse_places,
    place_spot,
    save_settings,
)

PAGE_TITLE = "Nearby"
# Results shown at first, and added by each "Show more": a busy area like
# Shibuya has hundreds of places within a 10-minute walk, and the nearest
# few are usually what's wanted.
PAGE_SIZE = 5
KINDS = {"food": "Food", "things": "Things to do"}
CATEGORY_ICONS = {
    "convenience": "🏪", "supermarket": "🛒", "restaurant": "🍽️", "cafe": "☕", "fast_food": "🍔",
    "park": "🌳", "shrine_temple": "⛩️", "museum": "🏛️", "viewpoint": "🌄", "cinema_theatre": "🎭",
}
FETCH_ERRORS = (urllib.error.URLError, TimeoutError, ValueError, KeyError)

is_first_load = "_nearby_title_played" not in st.session_state
inject_body_fade_in("main_body")

header_logo, header_title = st.columns([1, 4], vertical_alignment="center")
with header_logo:
    show_logo(width=120)
with header_title:
    render_page_title(PAGE_TITLE, is_first_load)

if is_first_load:
    st.session_state["_nearby_title_played"] = True

# Place names in the system's Japanese font rather than the app's pixel font,
# which drops strokes from dense kanji -- the same reason the Japanese page's
# flashcards use it. The rest of each row stays in the pixel font.
st.markdown(
    '<style>.place-name { font-family: "Yu Gothic UI", "Yu Gothic", "Meiryo", "Hiragino Sans", sans-serif; }'
    "</style>",
    unsafe_allow_html=True,
)


def format_distance(metres: float) -> str:
    return f"{metres / 1000:.1f} km" if metres >= 1000 else f"{round(metres / 10) * 10:.0f} m"


def _plain(text: str) -> str:
    # Place names are other people's text, shown inside a little HTML: keep
    # a "<" or "&" in one from reading as markup, and a "*" or "[" as
    # Markdown formatting.
    # Quotes are left alone: they're only special inside attributes, and an
    # escaped one (&#x27;) would show as-is once Markdown gets to its "#".
    text = html.escape(text, quote=False)
    for character in "\\*_[]`":
        text = text.replace(character, "\\" + character)
    return text


def read_location_reply() -> None:
    # The browser's answer to "Use my location" arrives in the hidden
    # nearby_geo box (see request_location): "ok:lat,lon,accuracy|stamp" or
    # "error:reason|stamp". The stamp makes every answer a new value.
    reply = st.session_state.get("nearby_geo", "")
    if not reply or reply == st.session_state.get("_nearby_geo_handled"):
        return
    st.session_state["_nearby_geo_handled"] = reply
    st.session_state.pop("_nearby_locating", None)
    status, _, rest = reply.partition(":")
    detail = rest.split("|")[0]
    if status == "ok":
        lat, lon, accuracy = (float(part) for part in detail.split(","))
        st.session_state["_nearby_here"] = {"lat": lat, "lon": lon, "accuracy": accuracy}
        st.session_state.pop("_nearby_geo_error", None)
    else:
        # The browser's error codes: 1 = permission refused, 2 = position
        # unavailable, 3 = timed out.
        st.session_state["_nearby_geo_error"] = {
            "1": "Location access was refused, so this uses your saved area.",
            "2": "This computer couldn't work out where it is, so this uses your saved area.",
            "3": "Finding your location took too long, so this uses your saved area.",
        }.get(detail, "Your location isn't available here, so this uses your saved area.")


def request_location() -> None:
    # Streamlit has no way to ask the browser for its location, so a small
    # script does, then types the answer into a hidden box and presses Enter
    # -- which reruns the page with it (read_location_reply). Only sent on
    # the run right after the button, so it asks once per press.
    st.html(
        """<script>
        (() => {
            const input = document.querySelector(".st-key-nearby_geo input");
            if (!input) return;
            const send = text => {
                const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
                setValue.call(input, text + "|" + Date.now());
                input.dispatchEvent(new Event("input", {bubbles: true}));
                input.dispatchEvent(new KeyboardEvent("keydown", {
                    key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true,
                }));
            };
            if (!navigator.geolocation) { send("error:unsupported"); return; }
            navigator.geolocation.getCurrentPosition(
                position => send(`ok:${position.coords.latitude},${position.coords.longitude},${position.coords.accuracy}`),
                error => send(`error:${error.code}`),
                {timeout: 15000, maximumAge: 60000},
            );
        })();
        </script>""",
        unsafe_allow_javascript=True,
    )


def render_location(settings: dict) -> dict | None:
    # Where to look from: this visit's own location if one was found, else
    # the saved area. Returns {"lat", "lon", "label"}, or None if neither.
    st.markdown("<style>.st-key-nearby_geo { display: none; }</style>", unsafe_allow_html=True)
    st.text_input("Location reply", key="nearby_geo", label_visibility="collapsed")
    read_location_reply()

    here = st.session_state.get("_nearby_here")
    search_column, locate_column = st.columns([3, 1], vertical_alignment="bottom")
    with search_column:
        query = st.text_input(
            "Area", placeholder="A station or area, e.g. 渋谷駅 or Takadanobaba", key="nearby_area_query"
        )
    with locate_column:
        if st.button("📍 My location", width="stretch", help="Look around where this computer is for this visit"):
            st.session_state["_nearby_locating"] = True
    if st.session_state.get("_nearby_locating"):
        st.caption("Finding your location…")
        request_location()

    if query.strip() and query != st.session_state.get("_nearby_saved_query"):
        try:
            with st.spinner("Looking up that area…"):
                matches = find_area(query)
        except FETCH_ERRORS:
            matches = None
            st.error("Couldn't reach OpenStreetMap's area search right now. Try again in a minute.")
        if matches == []:
            st.warning("No match in Japan for that. Try a station name, or the area in Japanese.")
        elif matches:
            choice = st.selectbox(
                "Matches", range(len(matches)), format_func=lambda index: matches[index]["name"],
                # Per search, so a pick from an earlier, longer list of
                # matches can't point past the end of this one.
                key=f"nearby_area_choice_{query}",
            )
            if st.button("Save as my area"):
                chosen = matches[choice]
                settings.update(area=chosen["name"].split(",")[0], lat=chosen["lat"], lon=chosen["lon"])
                save_settings(settings)
                st.session_state["_nearby_saved_query"] = query
                st.session_state.pop("_nearby_here", None)
                st.rerun()

    if st.session_state.get("_nearby_geo_error"):
        st.caption(st.session_state["_nearby_geo_error"])
    if here:
        label = f"your current location (to within about {format_distance(here['accuracy'])})"
        if st.button("Back to my saved area" if settings.get("area") else "Stop using my location"):
            st.session_state.pop("_nearby_here", None)
            st.rerun()
        return {"lat": here["lat"], "lon": here["lon"], "label": label}
    if settings.get("area"):
        return {"lat": settings["lat"], "lon": settings["lon"], "label": settings["area"]}
    return None


def _toggle_map(place_id: str) -> None:
    # One map open at a time, under its place: opening another closes the
    # last, and pressing the same one again closes it.
    current = st.session_state.get("_nearby_open_map")
    st.session_state["_nearby_open_map"] = None if current == place_id else place_id


def render_places(kind: str, origin: dict, radius: int) -> None:
    categories = CATEGORIES[kind]
    chosen = st.pills(
        "Show", list(categories), format_func=lambda category: categories[category][0],
        selection_mode="multi", default=list(categories), key=f"nearby_{kind}_categories",
        label_visibility="collapsed",
    )
    try:
        with st.spinner("Looking up places…"):
            elements = fetch_places(kind, *place_spot(origin["lat"], origin["lon"]), radius)
    except FETCH_ERRORS:
        # Usually the shared server being busy for a moment. A failed lookup
        # isn't cached, so trying again really asks again. (Public backup
        # servers were tried in 2026-09 and were slower or timed out.)
        st.error("Couldn't reach OpenStreetMap's place search right now. It's a shared service "
                 "and is sometimes busy for a moment.")
        st.button("Try again", key=f"nearby_{kind}_retry")
        return
    places = [place for place in parse_places(kind, elements, origin["lat"], origin["lon"])
              if place["category"] in chosen]
    st.caption(f"{len(places)} within {format_distance(radius)} of {origin['label']}, nearest first.")

    limit_key = f"_nearby_{kind}_limit"
    limit = st.session_state.get(limit_key, PAGE_SIZE)
    open_map = st.session_state.get("_nearby_open_map")
    for place in places[:limit]:
        name = _plain(place["name"]) + (f" · {_plain(place['name_en'])}" if place["name_en"] else "")
        details = [format_distance(place["distance"])]
        details += [_plain(detail) for detail in (place["cuisine"], place["hours"]) if detail]
        text_column, map_column = st.columns([6, 1], vertical_alignment="center")
        text_column.markdown(
            f"{CATEGORY_ICONS[place['category']]} <b class='place-name'>{name}</b>  \n"
            f"<small>{' · '.join(details)} · "
            f"<a href='{map_link(place)}' target='_blank'>Directions</a></small>",
            unsafe_allow_html=True,
        )
        is_open = open_map == place["id"]
        map_column.button(
            "Hide" if is_open else "Map", key=f"nearby_map_{kind}_{place['id']}", width="stretch",
            on_click=_toggle_map, args=(place["id"],),
        )
        if is_open:
            st.iframe(map_embed(place), height=320)
    if len(places) > limit and st.button("Show more", key=f"nearby_{kind}_more"):
        st.session_state[limit_key] = limit + PAGE_SIZE
        st.rerun()


settings = load_settings()

with st.container(key="main_body"):
    origin = render_location(settings)
    radius = st.select_slider(
        "Distance", RADII, value=settings.get("radius", 800) if settings.get("radius") in RADII else 800,
        format_func=lambda metres: f"{format_distance(metres)} (~{round(metres / 80)} min walk)",
        key="nearby_radius",
    )
    if radius != settings.get("radius"):
        settings["radius"] = radius
        save_settings(settings)

    if origin is None:
        st.info("Type a station or area above to see what's around it, or use your location.")
    else:
        kind = st.segmented_control(
            "Looking for", list(KINDS), format_func=KINDS.get, default="food", required=True, key="nearby_kind"
        )
        render_places(kind, origin, radius)

    st.caption(
        "Places © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors. "
        "Only as complete as its map: some places may be missing or out of date."
    )
