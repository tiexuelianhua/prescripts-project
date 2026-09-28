# Logic for the Activities page: food and things to do around a saved area or
# the computer's current location. No Streamlit rendering here, same split
# as the other data files.
#
# Both sources are OpenStreetMap's, free and keyless: Nominatim turns a typed
# station or area into coordinates, and Overpass finds places around them.
# Google's equivalents need a billing account. OSM's data is credited in the
# README and Home's credits, as its licence asks. Both services ask for a
# User-Agent naming the app, light use, and (Nominatim) at most one request a
# second -- lookups here only happen on an explicit search, and are cached.
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

from prescripts.common import SCRIPTS_DIR

ACTIVITIES_DIR = SCRIPTS_DIR.parent / "Activities"
SETTINGS_PATH = ACTIVITIES_DIR / "settings.json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_HEADERS = {"User-Agent": "The Prescripts (personal dashboard app)"}

# Walking distances offered, in metres. Coarse steps rather than a free
# slider, since each distance is its own (cached) lookup.
RADII = [400, 800, 1200, 1600, 2000, 3000]
DEFAULT_RADIUS = 800

# Each category: its label and the OSM tags that put a place in it, as
# (key, allowed values). A place needs every listed tag to match; the first
# category that fits wins. Kept to places worth walking to -- e.g. only
# Shinto and Buddhist places of worship, since the plain tag also covers
# small churches and the offices of religious groups.
CATEGORIES = {
    "food": {
        "convenience": ("Convenience stores", [("shop", ["convenience"])]),
        "supermarket": ("Supermarkets", [("shop", ["supermarket"])]),
        "restaurant": ("Restaurants", [("amenity", ["restaurant", "food_court"])]),
        "cafe": ("Cafés", [("amenity", ["cafe"])]),
        "fast_food": ("Fast food", [("amenity", ["fast_food"])]),
    },
    "things": {
        "park": ("Parks and gardens", [("leisure", ["park", "garden"])]),
        "shrine_temple": ("Shrines and temples", [("amenity", ["place_of_worship"]), ("religion", ["shinto", "buddhist"])]),
        "museum": ("Museums and galleries", [("tourism", ["museum", "gallery"])]),
        "viewpoint": ("Viewpoints", [("tourism", ["viewpoint"])]),
        "cinema_theatre": ("Cinemas and theatres", [("amenity", ["cinema", "theatre"])]),
    },
}


def load_settings() -> dict:
    # {"area": name shown, "lat", "lon", "radius"}; no area until one is set.
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"radius": DEFAULT_RADIUS}


def save_settings(settings: dict) -> None:
    ACTIVITIES_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_json(url: str, data: bytes | None = None, timeout: float = 30):
    request = urllib.request.Request(url, data=data, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


@st.cache_data(ttl=7 * 24 * 3600, show_spinner=False)
def find_area(query: str) -> list[dict]:
    # Up to five matches in Japan for a typed station or area, in Japanese
    # or English, each {"name", "lat", "lon"}. Names come back in English.
    url = NOMINATIM_URL + "?" + urllib.parse.urlencode(
        {"q": query.strip(), "format": "jsonv2", "limit": 5, "countrycodes": "jp", "accept-language": "en"}
    )
    return [
        {"name": result["display_name"], "lat": float(result["lat"]), "lon": float(result["lon"])}
        for result in _get_json(url, timeout=15)
    ]


def overpass_query(kind: str, lat: float, lon: float, radius: int) -> str:
    # One Overpass request for every category of a kind. `nwr` covers places
    # mapped as points and as outlines; "out center" gives outlines a point.
    around = f"(around:{radius},{lat},{lon})"
    parts = []
    for _label, rules in CATEGORIES[kind].values():
        filters = "".join(f'["{key}"~"^({"|".join(values)})$"]' for key, values in rules)
        parts.append(f"nwr{filters}{around};")
    return f"[out:json][timeout:25];({''.join(parts)});out center tags;"


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def fetch_places(kind: str, lat: float, lon: float, radius: int) -> list[dict]:
    # Raw Overpass elements. Cached for a day per spot and distance: places
    # rarely change, and Overpass is a shared service that can be slow.
    # Callers round lat/lon (see place_spot) so a location that wobbles by a
    # few metres still hits the cache.
    query = overpass_query(kind, lat, lon, radius)
    data = _get_json(OVERPASS_URL, data=urllib.parse.urlencode({"data": query}).encode(), timeout=40)
    return data["elements"]


def place_spot(lat: float, lon: float) -> tuple[float, float]:
    # Four decimal places is about 10 m: close enough for walking distances.
    return round(lat, 4), round(lon, 4)


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # Straight-line distance on the Earth's surface (haversine).
    radius_m = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi, d_lambda = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius_m * math.asin(math.sqrt(a))


# Convenience-store chains, by name or brand. OSM is edited by volunteers, so
# the odd branch is tagged a supermarket (seen with FamilyMart, Lawson Store
# 100 and 7-Eleven); a konbini chain's name overrides that.
_KONBINI_CHAINS = re.compile(
    r"ファミリーマート|familymart|ファミマ|セブン-?イレブン|7-eleven|ローソン|lawson|ミニストップ|ministop"
    r"|デイリーヤマザキ|daily yamazaki|newdays|セイコーマート|seicomart|ポプラ|poplar",
    re.IGNORECASE,
)
# Two entries with the same name this close are one place mapped twice
# (e.g. as a point and as its building's outline).
_SAME_PLACE_M = 30


def category_of(kind: str, tags: dict) -> str | None:
    for category, (_label, rules) in CATEGORIES[kind].items():
        if all(tags.get(key) in values for key, values in rules):
            if category == "supermarket" and _KONBINI_CHAINS.search(f"{tags.get('name', '')} {tags.get('brand', '')}"):
                return "convenience"
            return category
    return None


def parse_places(kind: str, elements: list[dict], lat: float, lon: float) -> list[dict]:
    # Named places of a known category, nearest first, each {"id", "name",
    # "name_en", "category", "cuisine", "hours", "distance", "lat", "lon"}
    # ("id" is OSM's own, e.g. "node/123").
    # Unnamed ones are dropped: "a restaurant" with no name can't be found.
    # A place mapped twice shows once, as its nearer entry.
    places = []
    for element in elements:
        tags = element.get("tags", {})
        name = tags.get("name")
        category = category_of(kind, tags)
        point = element if "lat" in element else element.get("center")
        if not name or not category or not point:
            continue
        english = tags.get("name:en", "")
        places.append({
            "id": f"{element.get('type', 'node')}/{element.get('id', '')}",
            "name": name,
            "name_en": english if english != name else "",
            "category": category,
            "cuisine": tags.get("cuisine", "").replace("_", " ").replace(";", ", "),
            "hours": tags.get("opening_hours", ""),
            "distance": distance_m(lat, lon, point["lat"], point["lon"]),
            "lat": point["lat"],
            "lon": point["lon"],
        })
    kept = []
    for place in sorted(places, key=lambda place: place["distance"]):
        if not any(
            other["name"].casefold() == place["name"].casefold()
            and distance_m(other["lat"], other["lon"], place["lat"], place["lon"]) < _SAME_PLACE_M
            for other in kept
        ):
            kept.append(place)
    return kept


def map_link(place: dict) -> str:
    # Opens the spot in Google Maps, for directions -- a plain link, no API
    # or key involved.
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(f"{place['lat']},{place['lon']}")


def map_embed(place: dict, span: float = 0.003) -> str:
    # OpenStreetMap's own embeddable map (free, no key), pinned on the place
    # and about 600 m across. Made for embedding, so light use like this
    # sits within OSM's tile usage policy.
    lat, lon = place["lat"], place["lon"]
    bbox = f"{lon - span},{lat - span},{lon + span},{lat + span}"
    return ("https://www.openstreetmap.org/export/embed.html?"
            + urllib.parse.urlencode({"bbox": bbox, "layer": "mapnik", "marker": f"{lat},{lon}"}))
