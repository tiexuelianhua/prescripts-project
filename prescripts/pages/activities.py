# Activities page: food and things to do within walking distance of a saved area
# (a station or neighbourhood, typed once and remembered) or, for one visit,
# the computer's current location. Places come from OpenStreetMap -- see
# data/activities.py for the lookups and why they're OSM's. Things to do
# show a photo where Wikimedia Commons has one.
import html
import urllib.error
from datetime import date

import streamlit as st

from prescripts.common import inject_body_fade_in, render_page_title, show_logo
from prescripts.data.activities import (
    CATEGORIES,
    OTHER,
    RADII,
    fetch_named,
    fetch_places,
    find_area,
    hidden_places,
    hide_place,
    load_settings,
    map_embed,
    map_link,
    matches_wish,
    parse_places,
    parse_wish,
    place_photos,
    place_spot,
    save_settings,
    search_link,
    unhide_place,
    without_hidden,
)
from prescripts.data.events import (
    AHEAD_DAYS,
    FETCH_ERRORS as EVENT_FETCH_ERRORS,
    GROUPS,
    add_my_event,
    big_sight_events,
    dates_search,
    format_dates,
    matches,
    news,
    remove_my_event,
    today_jst,
    upcoming,
    web_search,
)

PAGE_TITLE = "Activities"
# Results shown at first, and added by each "Show more": a busy area like
# Shibuya has hundreds of places within a 10-minute walk, and the nearest
# few are usually what's wanted.
PAGE_SIZE = 5
KINDS = {"food": "Food", "things": "Things to do"}
CATEGORY_ICONS = {
    "convenience": "🏪", "supermarket": "🛒", "restaurant": "🍽️", "cafe": "☕", "fast_food": "🍔",
    "park": "🌳", "shrine_temple": "⛩️", "museum": "🏛️", "viewpoint": "🌄", "cinema_theatre": "🎭",
    "nightlife": "🍸", "shopping": "🛍️", "games_sports": "🎳", "bath": "♨️", "zoo_theme_park": "🎡",
    OTHER: "📌",
}
# How a place's own OSM type reads in its row, where it says more than the
# category does (food rows show their cuisine instead). Others read as the
# tag itself, e.g. "sports centre".
TYPE_LABELS = {
    "karaoke_box": "karaoke", "amusement_arcade": "arcade", "bowling_alley": "bowling",
    "escape_game": "escape room", "fitness_centre": "gym", "second_hand": "second-hand shop",
    "video_games": "video games", "anime": "anime and manga", "place_of_worship": "",
    "department_store": "department store", "public_bath": "",
}
FETCH_ERRORS = (urllib.error.URLError, TimeoutError, ValueError, KeyError)
GROUP_ICONS = {"festival": "🏮", "market": "🧺", "anime_games": "🎮", "art": "🎨", "music": "🎵", "convention": "🏢"}
# Web searches for the kinds of event no free source lists.
QUICK_SEARCHES = {
    "Anime pop-up shops this week": "アニメ ポップアップストア 東京 今週",
    "Collab cafés on now": "コラボカフェ 東京 開催中",
    "Art exhibitions this month": "東京 展覧会 今月",
    "Gigs this weekend": "東京 ライブ 今週末",
}

is_first_load = "_activities_title_played" not in st.session_state
inject_body_fade_in("main_body")

header_logo, header_title = st.columns([1, 4], vertical_alignment="center")
with header_logo:
    show_logo(width=120)
with header_title:
    render_page_title(PAGE_TITLE, is_first_load)

if is_first_load:
    st.session_state["_activities_title_played"] = True

# Place names in the system's Japanese font rather than the app's pixel font,
# which drops strokes from dense kanji -- the same reason the Japanese page's
# flashcards use it. The rest of each row stays in the pixel font.
# A photo sits at the left of its row, cropped to one size so rows line up.
st.markdown(
    '<style>.place-name { font-family: "Yu Gothic UI", "Yu Gothic", "Meiryo", "Hiragino Sans", sans-serif; }'
    ".place-photo { float: left; width: 6rem; height: 4.5rem; object-fit: cover; border-radius: 4px;"
    " margin: 0.2rem 0.8rem 0.2rem 0; }"
    ".place-row-end { clear: both; }"
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
    # activities_geo box (see request_location): "ok:lat,lon,accuracy|stamp" or
    # "error:reason|stamp". The stamp makes every answer a new value.
    reply = st.session_state.get("activities_geo", "")
    if not reply or reply == st.session_state.get("_activities_geo_handled"):
        return
    st.session_state["_activities_geo_handled"] = reply
    st.session_state.pop("_activities_locating", None)
    status, _, rest = reply.partition(":")
    detail = rest.split("|")[0]
    if status == "ok":
        lat, lon, accuracy = (float(part) for part in detail.split(","))
        st.session_state["_activities_here"] = {"lat": lat, "lon": lon, "accuracy": accuracy}
        st.session_state.pop("_activities_geo_error", None)
    else:
        # The browser's error codes: 1 = permission refused, 2 = position
        # unavailable, 3 = timed out.
        st.session_state["_activities_geo_error"] = {
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
            const input = document.querySelector(".st-key-activities_geo input");
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
    st.markdown("<style>.st-key-activities_geo { display: none; }</style>", unsafe_allow_html=True)
    st.text_input("Location reply", key="activities_geo", label_visibility="collapsed")
    read_location_reply()

    here = st.session_state.get("_activities_here")
    search_column, locate_column = st.columns([3, 1], vertical_alignment="bottom")
    with search_column:
        query = st.text_input(
            "Area", placeholder="A station or area, e.g. 渋谷駅 or Takadanobaba", key="activities_area_query"
        )
    with locate_column:
        if st.button("📍 My location", width="stretch", help="Look around where this computer is for this visit"):
            st.session_state["_activities_locating"] = True
    if st.session_state.get("_activities_locating"):
        st.caption("Finding your location…")
        request_location()

    if query.strip() and query != st.session_state.get("_activities_saved_query"):
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
                key=f"activities_area_choice_{query}",
            )
            if st.button("Save as my area"):
                chosen = matches[choice]
                settings.update(area=chosen["name"].split(",")[0], area_ja=chosen["name_ja"],
                                lat=chosen["lat"], lon=chosen["lon"])
                save_settings(settings)
                st.session_state["_activities_saved_query"] = query
                st.session_state.pop("_activities_here", None)
                st.rerun()

    if st.session_state.get("_activities_geo_error"):
        st.caption(st.session_state["_activities_geo_error"])
    # The box above is empty on a later visit, so this says where the page
    # is looking from.
    if here:
        label = f"your current location (to within about {format_distance(here['accuracy'])})"
        st.caption(f"📍 Looking around {label}.")
        if st.button("Back to my saved area" if settings.get("area") else "Stop using my location"):
            st.session_state.pop("_activities_here", None)
            st.rerun()
        return {"lat": here["lat"], "lon": here["lon"], "label": label}
    if settings.get("area"):
        st.caption(f"📍 Looking around your saved area, **{_plain(settings['area'])}**. "
                   "Search above to change it.")
        return {"lat": settings["lat"], "lon": settings["lon"], "label": settings["area"]}
    return None


def _toggle_map(place_id: str) -> None:
    # One map open at a time, under its place: opening another closes the
    # last, and pressing the same one again closes it.
    current = st.session_state.get("_activities_open_map")
    st.session_state["_activities_open_map"] = None if current == place_id else place_id


def _hide(place: dict) -> None:
    hide_place(settings, place)
    if st.session_state.get("_activities_open_map") == place["id"]:
        st.session_state["_activities_open_map"] = None


def load_places(kind: str, origin: dict, radius: int) -> list[dict] | None:
    # Every named place of that kind in range, or None (with a message and
    # a Try again button) if OpenStreetMap couldn't be reached.
    try:
        with st.spinner("Looking up places…"):
            elements = fetch_places(kind, *place_spot(origin["lat"], origin["lon"]), radius)
    except FETCH_ERRORS:
        # Usually the shared server being busy for a moment. A failed lookup
        # isn't cached, so trying again really asks again. (Public backup
        # servers were tried in 2026-09 and were slower or timed out.)
        st.error("Couldn't reach OpenStreetMap's place search right now. It's a shared service "
                 "and is sometimes busy for a moment.")
        st.button("Try again", key=f"activities_{kind}_retry")
        return None
    return without_hidden(parse_places(kind, elements, origin["lat"], origin["lon"]), settings)


def render_places(kind: str, origin: dict, radius: int) -> None:
    categories = CATEGORIES[kind]
    chosen = st.pills(
        "Show", list(categories), format_func=lambda category: categories[category][0],
        selection_mode="multi", default=list(categories), key=f"activities_{kind}_categories",
        label_visibility="collapsed",
    )
    places = load_places(kind, origin, radius)
    if places is None:
        return
    places = [place for place in places if place["category"] in chosen]
    st.caption(f"{len(places)} within {format_distance(radius)} of {origin['label']}, nearest first.")
    render_list(places, kind)


def render_wish(text: str, origin: dict, radius: int) -> None:
    # Places matching what was typed. With no kind of place named ("ramen",
    # "starbucks"), food is tried first, then things to do.
    wish = parse_wish(text)
    found = []
    for kind in [wish["kind"]] if wish["kind"] else ["food", "things"]:
        places = load_places(kind, origin, radius)
        if places is None:
            return
        found = [place for place in places if matches_wish(place, wish)]
        if found:
            break
    if not found and wish["terms"] and not wish["kind"]:
        # Nothing in any category: look for the word in any place's name or
        # own type ("pokemon", "batting"), whatever kind of place it is.
        term = max(wish["terms"], key=len)
        try:
            with st.spinner("Looking further…"):
                elements = fetch_named(term, *place_spot(origin["lat"], origin["lon"]), radius)
            found = [place for place in without_hidden(parse_places("any", elements, origin["lat"], origin["lon"]), settings)
                     if matches_wish(place, wish)]
        except FETCH_ERRORS:
            pass  # the "nothing matching" note below still offers Google Maps
    if not found:
        st.caption(f"Nothing matching that within {format_distance(radius)} of {origin['label']}. "
                   "A wider distance may help, or other words.")
        st.markdown(f"[Search Google Maps for it]({search_link(text, origin['lat'], origin['lon'])})")
        return
    st.caption(f"{len(found)} matching within {format_distance(radius)} of {origin['label']}, nearest first.")
    render_list(found, "wish")


def render_list(places: list[dict], list_key: str) -> None:
    limit_key = f"_activities_{list_key}_limit"
    limit = st.session_state.get(limit_key, PAGE_SIZE)
    open_map = st.session_state.get("_activities_open_map")
    # Only for the rows on show: each new one is a lookup, the first time.
    photos = place_photos(places[:limit])
    for place in places[:limit]:
        name = _plain(place["name"]) + (f" · {_plain(place['name_en'])}" if place["name_en"] else "")
        details = [format_distance(place["distance"])]
        if place["category"] == "shrine_temple":
            details.append({"shinto": "Shinto shrine", "buddhist": "Buddhist temple"}.get(place["religion"], ""))
        elif place["category"] not in CATEGORIES["food"]:
            kind_of_place = TYPE_LABELS.get(place["type"], place["type"].replace("_", " "))
            details.append(_plain(kind_of_place))
        details += [_plain(detail) for detail in (place["cuisine"], place["hours"]) if detail]
        details = [detail for detail in details if detail]
        text_column, map_column, hide_column = st.columns([11, 2, 1], vertical_alignment="center")
        photo = photos.get(place["id"])
        # The photo links to its Commons page, which has the full credit.
        picture = (f"<a href='{html.escape(photo['page'])}' target='_blank'>"
                   f"<img class='place-photo' src='{html.escape(photo['url'])}' alt=''></a>") if photo else ""
        credit = f"  \n<small>Photo: {_plain(photo['credit'] or 'Wikimedia Commons')}</small>" if photo else ""
        text_column.markdown(
            f"{picture}{CATEGORY_ICONS[place['category']]} <b class='place-name'>{name}</b>  \n"
            f"<small>{' · '.join(details)} · "
            f"<a href='{map_link(place)}' target='_blank'>Directions</a></small>{credit}"
            + ("<div class='place-row-end'></div>" if photo else ""),
            unsafe_allow_html=True,
        )
        is_open = open_map == place["id"]
        map_column.button(
            "Close" if is_open else "Map", key=f"activities_map_{list_key}_{place['id']}", width="stretch",
            on_click=_toggle_map, args=(place["id"],),
        )
        hide_column.button(
            "✕", key=f"activities_hide_{list_key}_{place['id']}", width="stretch",
            help="Hide this place (a joke or wrong entry). Undo under Hidden places.",
            on_click=_hide, args=(place,),
        )
        if is_open:
            st.iframe(map_embed(place), height=320)
    if len(places) > limit and st.button("Show more", key=f"activities_{list_key}_more"):
        st.session_state[limit_key] = limit + PAGE_SIZE
        st.rerun()


def _add_event() -> None:
    name = st.session_state.get("activities_event_name", "").strip()
    if not name:
        st.session_state["_activities_event_note"] = "Give the event a name first."
        return
    start = st.session_state["activities_event_start"]
    add_my_event(name, start, st.session_state.get("activities_event_end") or start,
                 st.session_state.get("activities_event_place", ""), st.session_state["activities_event_group"],
                 st.session_state.get("activities_event_link", ""))
    for key in ("activities_event_name", "activities_event_place", "activities_event_link"):
        st.session_state[key] = ""
    st.session_state["_activities_event_note"] = f"Added {name}."


def render_event_row(event: dict, today: date) -> None:
    name = _plain(event["name"]) + (f" · {_plain(event['name_en'])}" if event["name_en"] else "")
    details = [format_dates(event), _plain(event["place"])]
    if event["hours"]:
        details.append(_plain(event["hours"]))
    if event["link"].startswith(("https://", "http://")):
        details.append(f"<a href='{html.escape(event['link'])}' target='_blank'>Details</a>")
    if event["usually"]:
        details.append(f"<a href='{html.escape(dates_search(event, today))}' target='_blank'>This year's dates</a>")
    details = [detail for detail in details if detail]
    text_column, remove_column = st.columns([13, 1], vertical_alignment="center")
    text_column.markdown(
        f"{GROUP_ICONS.get(event['group'], '📅')} <b class='place-name event-name'>{name}</b>  \n"
        f"<small>{' · '.join(details)}</small>",
        unsafe_allow_html=True,
    )
    if event["source"] == "Mine":
        remove_column.button("✕", key=f"activities_event_remove_{event['id']}", width="stretch",
                             help="Remove this event", on_click=remove_my_event, args=(event["id"],))


def render_events() -> None:
    # Coming up around greater Tokyo. Not tied to the saved area, so shown
    # even before one is set.
    st.subheader("📅 Events")
    today = today_jst()
    try:
        with st.spinner("Looking up events…"):
            big_sight = big_sight_events()
    except EVENT_FETCH_ERRORS:
        big_sight = None
    chosen = st.pills(
        "Kinds of event", list(GROUPS), format_func=lambda group: f"{GROUP_ICONS[group]} {GROUPS[group]}",
        # Conventions start off: most of Big Sight's public days are career
        # and trade-style fairs, which would bury the rest.
        selection_mode="multi", default=[group for group in GROUPS if group != "convention"],
        key="activities_event_groups", label_visibility="collapsed",
    )
    search = st.text_input("Search events", placeholder="e.g. comic, Asakusa, fireworks", key="activities_event_search")
    events = [event for event in upcoming(today, big_sight)
              if event["group"] in chosen and (not search.strip() or matches(event, search))]
    note = f"{len(events)} in the next {AHEAD_DAYS // 30} months, soonest first."
    if big_sight is None:
        note += " Tokyo Big Sight's list couldn't be reached, so its events are missing for now."
    st.caption(note)

    limit_key = "_activities_events_limit"
    limit = st.session_state.get(limit_key, PAGE_SIZE)
    for event in events[:limit]:
        render_event_row(event, today)
    if len(events) > limit and st.button("Show more", key="activities_events_more"):
        st.session_state[limit_key] = limit + PAGE_SIZE
        st.rerun()

    with st.expander("Add an event"):
        st.caption("For pop-ups, gigs and exhibitions you spot elsewhere. Only kept on this computer.")
        st.text_input("Name", key="activities_event_name")
        start_column, end_column = st.columns(2)
        start_column.date_input("From", value=today, key="activities_event_start", format="YYYY/MM/DD")
        end_column.date_input("To", value=None, key="activities_event_end", format="YYYY/MM/DD",
                              help="Leave empty for a one-day event")
        st.text_input("Where", key="activities_event_place")
        st.selectbox("Kind", list(GROUPS), format_func=GROUPS.get, key="activities_event_group")
        st.text_input("Link (optional)", key="activities_event_link")
        st.button("Add event", on_click=_add_event)
        if st.session_state.get("_activities_event_note"):
            st.caption(st.session_state.pop("_activities_event_note"))

    with st.expander("Collab and pop-up news"):
        words = st.text_input(
            "Watch for", value=", ".join(settings.get("news_words", [])),
            placeholder="Series or characters, e.g. 鬼滅の刃, ハローキティ", key="activities_news_words",
            help="Leave empty to see every collab and pop-up headline",
        )
        watched = [word.strip() for word in words.replace("、", ",").split(",") if word.strip()]
        if watched != settings.get("news_words", []):
            settings["news_words"] = watched
            save_settings(settings)
        try:
            headlines = news(watched)[:10]
        except EVENT_FETCH_ERRORS:
            headlines = None
            st.caption("Couldn't reach the news feed right now.")
        if headlines == []:
            st.caption("Nothing in the latest headlines" + (" mentions those." if watched else "."))
        for item in headlines or []:
            st.markdown(f"<small>{_plain(item['date'])}</small> "
                        f"<a href='{html.escape(item['link'])}' target='_blank'>{_plain(item['title'])}</a>",
                        unsafe_allow_html=True)
        st.caption("Headlines from [Anime!Anime!](https://animeanime.jp). Nothing free lists pop-ups as such, "
                   "so these search the web instead: "
                   + " · ".join(f"[{label}]({web_search(query)})" for label, query in QUICK_SEARCHES.items()))


settings = load_settings()

with st.container(key="main_body"):
    origin = render_location(settings)
    radius = st.select_slider(
        "Distance", RADII, value=settings.get("radius", 800) if settings.get("radius") in RADII else 800,
        format_func=lambda metres: f"{format_distance(metres)} (~{round(metres / 80)} min walk)",
        key="activities_radius",
    )
    if radius != settings.get("radius"):
        settings["radius"] = radius
        save_settings(settings)

    if origin is None:
        st.info("Type a station or area above to see what's around it, or use your location.")
    else:
        # When something's typed here it takes over from browsing by kind;
        # clearing it brings the Food / Things to do choice back.
        wish = st.text_input(
            "What do you feel like?", placeholder="e.g. a Spanish restaurant, see a temple, ramen",
            key="activities_wish",
        )
        if wish.strip():
            render_wish(wish, origin, radius)
        else:
            kind = st.segmented_control(
                "Looking for", list(KINDS), format_func=KINDS.get, default="food", required=True,
                key="activities_kind",
            )
            render_places(kind, origin, radius)

    st.divider()
    render_events()

    if hidden_places(settings):
        with st.expander(f"Hidden places ({len(hidden_places(settings))})"):
            for entry in hidden_places(settings):
                name_column, undo_column = st.columns([3, 1], vertical_alignment="center")
                name_column.markdown(f"<span class='place-name'>{_plain(entry['name'])}</span>",
                                     unsafe_allow_html=True)
                undo_column.button("Show again", key=f"activities_unhide_{entry['id']}", width="stretch",
                                   on_click=unhide_place, args=(settings, entry["id"]))

    st.caption(
        "Places © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors. "
        "Photos from [Wikimedia Commons](https://commons.wikimedia.org), each credited under it. "
        "Big Sight's events: [Tokyo open data](https://portal.data.metro.tokyo.lg.jp/) (CC BY 4.0). "
        "Only as complete as its map: some places may be missing or out of date."
    )
