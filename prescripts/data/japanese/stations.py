# Train stations from the Budget page's fares, as vocab cards for reading
# station names in kanji: each station logged (From/To) becomes a card in
# Learn -- 北千住 (きたせんじゅ), "Kita-Senju (station)". Names, readings and
# English names come from OpenStreetMap (via Nominatim, as the Activities
# page uses), whose stations carry all three. Jisho has few station names.
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

from prescripts.data.activities import _HEADERS, NOMINATIM_URL
from prescripts.data.japanese.deck import add_card
from prescripts.data.meal_receipts import known_stations, load_settings, transport_category

STATION_POS = "Station"
# At most this many lookups each time the Japanese page opens (Nominatim
# asks for one request a second at most); the rest wait for next time.
LOOKUPS_PER_VISIT = 8


def _search(query: str) -> list[dict]:
    url = NOMINATIM_URL + "?" + urllib.parse.urlencode({
        "q": query, "format": "jsonv2", "namedetails": 1, "countrycodes": "jp", "limit": 20,
    })
    request = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=15) as response:
        results = json.load(response)
    time.sleep(1.1)
    return [result for result in results if result.get("category") == "railway" and result.get("type") in ("station", "halt")]


@st.cache_data(ttl=30 * 24 * 3600, show_spinner=False)
def station_lookup(typed: str) -> dict | None:
    # A station as typed on Budget ("北千住", "Kita-Senju", "Shinjuku
    # Station", "渋谷駅"): {"front", "reading", "name_en"}, or None if
    # OpenStreetMap has no such station with a Japanese name.
    name = typed.strip()
    for suffix in ("駅", " station", " Station", " STATION"):
        name = name.removesuffix(suffix)
    stations = _search(name) or _search(f"{name} station")
    details = [result.get("namedetails") or {} for result in stations]
    # The first with a reading: several stations share a name (one per
    # line), and most of them carry it.
    best = next((names for names in details if names.get("name:ja-Hira")), details[0] if details else None)
    if not best or not best.get("name"):
        return None
    return {"front": best["name"], "reading": best.get("name:ja-Hira", ""), "name_en": best.get("name:en", "")}


def new_stations(deck: dict) -> list[str]:
    # Stations in Budget's fares not looked up yet. Each is only ever tried
    # once (found or not), so a deleted station card doesn't come back.
    done = set(deck["settings"].get("stations_done", []))
    return [name for name in known_stations(transport_category(load_settings())) if name not in done]


def add_station_cards(deck: dict, names: list[str]) -> int:
    # Looks the stations up and adds a card in Learn for each one found that
    # isn't in the deck already. Returns how many cards were added. Stops
    # quietly if OpenStreetMap can't be reached, to try again next time.
    done = deck["settings"].setdefault("stations_done", [])
    not_found = deck["settings"].setdefault("stations_not_found", [])
    added = 0
    for name in names[:LOOKUPS_PER_VISIT]:
        try:
            station = station_lookup(name)
        except (urllib.error.URLError, TimeoutError, ValueError):
            break
        done.append(name)
        if station is None:
            not_found.append(name)
            continue
        if any(card["kind"] == "vocab" and card["front"] == station["front"] for card in deck["cards"]):
            continue
        meaning = f"{station['name_en'] or name} (station)"
        add_card(deck, "vocab", station["front"], station["reading"], meaning, pos=STATION_POS, learning=True)
        added += 1
    return added
