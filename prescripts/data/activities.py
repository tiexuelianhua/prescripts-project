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
import time
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
    body = urllib.parse.urlencode({"data": query}).encode()
    try:
        return _get_json(OVERPASS_URL, data=body, timeout=40)["elements"]
    except urllib.error.HTTPError as error:
        # 429/504: the server's busy -- it runs only two lookups at a time
        # per address. One more try after a short wait usually gets through.
        if error.code not in (429, 504):
            raise
        time.sleep(3)
        return _get_json(OVERPASS_URL, data=body, timeout=40)["elements"]


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
            "religion": tags.get("religion", ""),
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


# "What do you feel like?": plain keyword matching, no language model.
# Words naming a kind of place pick its category (and, for shrines and
# temples, the religion: temples are Buddhist, shrines Shinto). Longest
# phrases are checked first, so "fast food" wins over "food".
_PLACE_WORDS = {
    "convenience store": ("food", "convenience", None), "konbini": ("food", "convenience", None),
    "コンビニ": ("food", "convenience", None), "supermarket": ("food", "supermarket", None),
    "groceries": ("food", "supermarket", None), "grocery": ("food", "supermarket", None),
    "スーパー": ("food", "supermarket", None), "restaurant": ("food", "restaurant", None),
    "cafe": ("food", "cafe", None), "café": ("food", "cafe", None), "coffee": ("food", "cafe", None),
    "カフェ": ("food", "cafe", None), "fast food": ("food", "fast_food", None),
    "eat": ("food", None, None), "food": ("food", None, None), "hungry": ("food", None, None),
    "meal": ("food", None, None), "lunch": ("food", None, None), "dinner": ("food", None, None),
    "park": ("things", "park", None), "garden": ("things", "park", None), "公園": ("things", "park", None),
    "shrine": ("things", "shrine_temple", "shinto"), "jinja": ("things", "shrine_temple", "shinto"),
    "神社": ("things", "shrine_temple", "shinto"), "temple": ("things", "shrine_temple", "buddhist"),
    "寺": ("things", "shrine_temple", "buddhist"), "museum": ("things", "museum", None),
    "gallery": ("things", "museum", None), "art": ("things", "museum", None),
    "exhibition": ("things", "museum", None), "美術館": ("things", "museum", None),
    "博物館": ("things", "museum", None), "view": ("things", "viewpoint", None),
    "viewpoint": ("things", "viewpoint", None), "scenery": ("things", "viewpoint", None),
    "cinema": ("things", "cinema_theatre", None), "movie": ("things", "cinema_theatre", None),
    "film": ("things", "cinema_theatre", None), "theatre": ("things", "cinema_theatre", None),
    "theater": ("things", "cinema_theatre", None), "映画": ("things", "cinema_theatre", None),
}
# Ignored: they say how, not what ("go to a", "I want some").
_FILLER = {
    "a", "an", "the", "some", "any", "go", "going", "to", "see", "visit", "want", "wanna", "i", "i'd",
    "get", "grab", "find", "for", "at", "in", "on", "me", "like", "feel", "something", "somewhere",
    "place", "places", "near", "nearby", "around", "here", "have", "let's", "lets", "with", "and", "or",
    "of", "maybe", "please", "good", "nice", "quiet", "fancy",
}
# A few foods whose Japanese name is more likely in a place's name than the
# English one is in its cuisine tag.
_ALSO_MEANS = {
    "ramen": ["ラーメン", "拉麺", "らーめん"], "sushi": ["寿司", "鮨", "すし"], "curry": ["カレー"],
    "udon": ["うどん"], "soba": ["そば", "蕎麦"], "tonkatsu": ["とんかつ"], "yakiniku": ["焼肉"],
    "izakaya": ["居酒屋"], "gyudon": ["牛丼"], "tempura": ["天ぷら", "天麩羅"], "okonomiyaki": ["お好み焼"],
}


def parse_wish(text: str) -> dict:
    # {"kind": "food"/"things"/None, "category": ... or None, "religion":
    # ... or None, "terms": [words to find in a place's cuisine or name]}.
    rest = f" {text.casefold().strip()} "
    wish = {"kind": None, "category": None, "religion": None, "terms": []}
    for phrase in sorted(_PLACE_WORDS, key=len, reverse=True):
        # Whole words for English (plurals too); anywhere for Japanese.
        pattern = re.escape(phrase) if re.search(r"[^\x00-\x7f]", phrase) else rf"\b{re.escape(phrase)}(e?s)?\b"
        if re.search(pattern, rest):
            kind, category, religion = _PLACE_WORDS[phrase]
            if wish["kind"] is None or (category and wish["category"] is None):
                wish.update(kind=kind, category=category or wish["category"], religion=religion or wish["religion"])
            rest = re.sub(pattern, " ", rest)
    wish["terms"] = [word for word in re.split(r"[\s,.!?、。]+", rest) if word and word not in _FILLER]
    return wish


def matches_wish(place: dict, wish: dict) -> bool:
    if wish["category"] and place["category"] != wish["category"]:
        return False
    if wish["religion"] and place["religion"] != wish["religion"]:
        return False
    text = f"{place['name']} {place['name_en']} {place['cuisine']}".casefold()
    return all(any(form in text for form in [term, *_ALSO_MEANS.get(term, [])]) for term in wish["terms"])


def search_link(text: str, lat: float, lon: float) -> str:
    # Google Maps' own search for the phrase around the spot, for when
    # OpenStreetMap has nothing -- a plain link, no API or key.
    return f"https://www.google.com/maps/search/{urllib.parse.quote(text.strip())}/@{lat},{lon},16z"


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
