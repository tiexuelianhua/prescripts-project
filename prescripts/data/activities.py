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
#
# Photos for things to do come from Wikimedia Commons (see place_photos),
# also free and keyless, for places whose OSM entry links Wikidata,
# Wikipedia or a Commons file.
import difflib
import hashlib
import html
import json
import math
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

from prescripts.common import SCRIPTS_DIR

ACTIVITIES_DIR = SCRIPTS_DIR.parent / "Activities"
SETTINGS_PATH = ACTIVITIES_DIR / "settings.json"
CACHE_DIR = ACTIVITIES_DIR / "cache"
_CACHE_FRESH_S = 24 * 3600
_CACHE_KEEP_S = 30 * 24 * 3600
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Wikimedia also asks for a way to reach whoever runs the app: the repo.
_HEADERS = {"User-Agent": "The Prescripts (personal dashboard app; https://github.com/tiexuelianhua/prescripts-project)"}
WIKIDATA_URL = "https://www.wikidata.org/w/api.php"
COMMONS_URL = "https://commons.wikimedia.org/w/api.php"
PHOTOS_PATH = CACHE_DIR / "photos.json"
PHOTO_WIDTH = 240

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
        "nightlife": ("Nightlife", [("amenity", ["bar", "pub", "nightclub", "karaoke_box"])]),
        "shopping": ("Shopping and hobbies", [("shop", [
            "anime", "games", "video_games", "books", "music", "toys", "model", "hobby", "electronics",
            "second_hand", "mall", "department_store",
        ])]),
        "games_sports": ("Games and sports", [("leisure", [
            "amusement_arcade", "bowling_alley", "escape_game", "sports_centre", "fitness_centre",
        ])]),
        "bath": ("Baths and onsen", [("amenity", ["public_bath"])]),
        "zoo_theme_park": ("Zoos, aquariums and theme parks", [("tourism", ["zoo", "aquarium", "theme_park"])]),
    },
}
# Anything else a search turns up (see fetch_named): shown with its own type.
OTHER = "other"
_TYPE_KEYS = ["shop", "amenity", "leisure", "tourism", "craft", "office", "historic"]


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
    return _overpass(overpass_query(kind, lat, lon, radius))


def _overpass(query: str) -> list[dict]:
    # Answers are also saved to disk, so a restart doesn't mean waiting on
    # Overpass again. A saved answer under a day old is used as is; an older
    # one only when Overpass can't be reached, since slightly old places beat
    # none. Answers saved over a month ago are deleted.
    path = CACHE_DIR / (hashlib.sha1(query.encode()).hexdigest() + ".json")
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        saved = None
    if saved and time.time() - saved["saved_at"] < _CACHE_FRESH_S:
        return saved["elements"]
    try:
        elements = _overpass_fetch(query)
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
        if saved:
            return saved["elements"]
        raise
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"saved_at": time.time(), "elements": elements}, ensure_ascii=False), encoding="utf-8")
    for old in CACHE_DIR.glob("*.json"):
        if time.time() - old.stat().st_mtime > _CACHE_KEEP_S:
            old.unlink(missing_ok=True)
    return elements


def saved_or_fetch_places(kind: str, lat: float, lon: float, radius: int) -> list[dict]:
    # For Overview, which shouldn't wait on a slow lookup: the saved answer
    # whatever its age (places rarely change, and the Activities page keeps
    # it fresh), only asking Overpass when there's none yet.
    path = CACHE_DIR / (hashlib.sha1(overpass_query(kind, lat, lon, radius).encode()).hexdigest() + ".json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))["elements"]
    except (FileNotFoundError, ValueError, KeyError):
        return fetch_places(kind, lat, lon, radius)


def _overpass_fetch(query: str) -> list[dict]:
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


def is_konbini(name: str | None) -> bool:
    # Also used by Meal Receipts, to tick "+ 袋" for a konbini store.
    return bool(name) and _KONBINI_CHAINS.search(name) is not None


# Two entries with the same name this close are one place mapped twice
# (e.g. as a point and as its building's outline).
_SAME_PLACE_M = 30


def category_of(kind: str, tags: dict) -> str | None:
    # kind "any" (a search by name, see fetch_named) checks every kind, and
    # anything that fits none of them is OTHER rather than dropped.
    for each_kind in ["food", "things"] if kind == "any" else [kind]:
        for category, (_label, rules) in CATEGORIES[each_kind].items():
            if all(tags.get(key) in values for key, values in rules):
                if category == "supermarket" and _KONBINI_CHAINS.search(f"{tags.get('name', '')} {tags.get('brand', '')}"):
                    return "convenience"
                return category
    return OTHER if kind == "any" else None


def place_type(tags: dict) -> str:
    # The place's own OSM type, e.g. "anime", "bar", "karaoke_box".
    return next((tags[key] for key in _TYPE_KEYS if tags.get(key) not in (None, "", "yes")), "")


def parse_places(kind: str, elements: list[dict], lat: float, lon: float) -> list[dict]:
    # Named places of a known category, nearest first, each {"id", "name",
    # "name_en", "category", "type", "cuisine", "hours", "religion",
    # "distance", "lat", "lon", "photo_source"} ("id" is OSM's own, e.g.
    # "node/123"; for "photo_source" see photo_source).
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
            "type": place_type(tags),
            "cuisine": tags.get("cuisine", "").replace("_", " ").replace(";", ", "),
            "hours": tags.get("opening_hours", ""),
            "religion": tags.get("religion", ""),
            "distance": distance_m(lat, lon, point["lat"], point["lon"]),
            "lat": point["lat"],
            "lon": point["lon"],
            "photo_source": photo_source(tags) if category not in CATEGORIES["food"] else None,
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


# Places hidden with a row's ✕ -- joke or wrong entries (OSM is edited by
# anyone). Kept in settings as {"id", "name"}, the name only so the list of
# hidden places can say what each one was.
def hidden_places(settings: dict) -> list[dict]:
    return settings.get("hidden", [])


def without_hidden(places: list[dict], settings: dict) -> list[dict]:
    hidden = {entry["id"] for entry in hidden_places(settings)}
    return [place for place in places if place["id"] not in hidden]


def hide_place(settings: dict, place: dict) -> None:
    if all(entry["id"] != place["id"] for entry in hidden_places(settings)):
        settings["hidden"] = [*hidden_places(settings), {"id": place["id"], "name": place["name"]}]
        save_settings(settings)


def unhide_place(settings: dict, place_id: str) -> None:
    settings["hidden"] = [entry for entry in hidden_places(settings) if entry["id"] != place_id]
    save_settings(settings)


# "What do you feel like?": plain keyword matching, no language model.
# Words naming a kind of place pick its category -- and, where they're more
# specific than that, its OSM types ("karaoke" within Nightlife) or, for
# shrines and temples, the religion (temples Buddhist, shrines Shinto).
# Longest phrases are checked first, so "fast food" wins over "food".
_MERCH = {"anime", "games", "toys", "model", "hobby"}
_PLACE_WORDS = {
    # Food
    "convenience store": ("food", "convenience", None, None), "konbini": ("food", "convenience", None, None),
    "コンビニ": ("food", "convenience", None, None), "supermarket": ("food", "supermarket", None, None),
    "groceries": ("food", "supermarket", None, None), "grocery": ("food", "supermarket", None, None),
    "スーパー": ("food", "supermarket", None, None), "restaurant": ("food", "restaurant", None, None),
    "cafe": ("food", "cafe", None, None), "café": ("food", "cafe", None, None),
    "coffee": ("food", "cafe", None, None), "coffee shop": ("food", "cafe", None, None),
    "カフェ": ("food", "cafe", None, None), "fast food": ("food", "fast_food", None, None),
    "eat": ("food", None, None, None), "food": ("food", None, None, None), "hungry": ("food", None, None, None),
    "meal": ("food", None, None, None), "lunch": ("food", None, None, None), "dinner": ("food", None, None, None),
    # Sights
    "park": ("things", "park", None, None), "garden": ("things", "park", None, None),
    "公園": ("things", "park", None, None),
    "shrine": ("things", "shrine_temple", "shinto", None), "jinja": ("things", "shrine_temple", "shinto", None),
    "神社": ("things", "shrine_temple", "shinto", None), "temple": ("things", "shrine_temple", "buddhist", None),
    "寺": ("things", "shrine_temple", "buddhist", None),
    "museum": ("things", "museum", None, {"museum"}), "gallery": ("things", "museum", None, {"gallery"}),
    "art": ("things", "museum", None, None), "exhibition": ("things", "museum", None, None),
    "美術館": ("things", "museum", None, None), "博物館": ("things", "museum", None, {"museum"}),
    "view": ("things", "viewpoint", None, None), "viewpoint": ("things", "viewpoint", None, None),
    "scenery": ("things", "viewpoint", None, None),
    "cinema": ("things", "cinema_theatre", None, {"cinema"}), "movie": ("things", "cinema_theatre", None, {"cinema"}),
    "film": ("things", "cinema_theatre", None, {"cinema"}), "映画": ("things", "cinema_theatre", None, {"cinema"}),
    "theatre": ("things", "cinema_theatre", None, {"theatre"}),
    "theater": ("things", "cinema_theatre", None, {"theatre"}),
    # Nightlife
    "nightlife": ("things", "nightlife", None, None), "drink": ("things", "nightlife", None, None),
    "drinking": ("things", "nightlife", None, None),
    "bar": ("things", "nightlife", None, {"bar", "pub"}), "pub": ("things", "nightlife", None, {"pub", "bar"}),
    "バー": ("things", "nightlife", None, {"bar", "pub"}),
    "club": ("things", "nightlife", None, {"nightclub"}), "nightclub": ("things", "nightlife", None, {"nightclub"}),
    "clubbing": ("things", "nightlife", None, {"nightclub"}), "クラブ": ("things", "nightlife", None, {"nightclub"}),
    "karaoke": ("things", "nightlife", None, {"karaoke_box"}),
    "カラオケ": ("things", "nightlife", None, {"karaoke_box"}),
    # Shopping and hobbies
    "shopping": ("things", "shopping", None, None),
    "anime": ("things", "shopping", None, {"anime"}), "manga": ("things", "shopping", None, {"anime", "books"}),
    "merch": ("things", "shopping", None, _MERCH), "merchandise": ("things", "shopping", None, _MERCH),
    "figure": ("things", "shopping", None, _MERCH), "goods": ("things", "shopping", None, _MERCH),
    "games": ("things", "shopping", None, {"games", "video_games"}),
    "video game": ("things", "shopping", None, {"video_games", "games"}),
    "board game": ("things", "shopping", None, {"games"}),
    "book": ("things", "shopping", None, {"books"}), "bookstore": ("things", "shopping", None, {"books"}),
    "bookshop": ("things", "shopping", None, {"books"}), "本屋": ("things", "shopping", None, {"books"}),
    "record": ("things", "shopping", None, {"music"}), "music store": ("things", "shopping", None, {"music"}),
    "toy": ("things", "shopping", None, {"toys", "model", "hobby"}),
    "hobby": ("things", "shopping", None, {"hobby", "model", "toys"}),
    "electronics": ("things", "shopping", None, {"electronics"}), "家電": ("things", "shopping", None, {"electronics"}),
    "thrift": ("things", "shopping", None, {"second_hand"}), "second hand": ("things", "shopping", None, {"second_hand"}),
    "secondhand": ("things", "shopping", None, {"second_hand"}), "vintage": ("things", "shopping", None, {"second_hand"}),
    "mall": ("things", "shopping", None, {"mall", "department_store"}),
    "department store": ("things", "shopping", None, {"department_store", "mall"}),
    "デパート": ("things", "shopping", None, {"department_store", "mall"}),
    # Games and sports
    "arcade": ("things", "games_sports", None, {"amusement_arcade"}),
    "game center": ("things", "games_sports", None, {"amusement_arcade"}),
    "game centre": ("things", "games_sports", None, {"amusement_arcade"}),
    "ゲームセンター": ("things", "games_sports", None, {"amusement_arcade"}),
    "ゲーセン": ("things", "games_sports", None, {"amusement_arcade"}),
    "bowling": ("things", "games_sports", None, {"bowling_alley"}),
    "escape room": ("things", "games_sports", None, {"escape_game"}),
    "escape game": ("things", "games_sports", None, {"escape_game"}),
    "gym": ("things", "games_sports", None, {"fitness_centre", "sports_centre"}),
    "fitness": ("things", "games_sports", None, {"fitness_centre", "sports_centre"}),
    "workout": ("things", "games_sports", None, {"fitness_centre", "sports_centre"}),
    "sports": ("things", "games_sports", None, None),
    # Baths, zoos and theme parks
    "onsen": ("things", "bath", None, None), "sento": ("things", "bath", None, None),
    "bath": ("things", "bath", None, None), "spa": ("things", "bath", None, None),
    "温泉": ("things", "bath", None, None), "銭湯": ("things", "bath", None, None),
    "zoo": ("things", "zoo_theme_park", None, {"zoo"}), "動物園": ("things", "zoo_theme_park", None, {"zoo"}),
    "aquarium": ("things", "zoo_theme_park", None, {"aquarium"}),
    "水族館": ("things", "zoo_theme_park", None, {"aquarium"}),
    "theme park": ("things", "zoo_theme_park", None, {"theme_park"}),
    "amusement park": ("things", "zoo_theme_park", None, {"theme_park"}),
    "遊園地": ("things", "zoo_theme_park", None, {"theme_park"}),
}
# Ignored: they say how, not what ("go to a", "I want some").
_FILLER = {
    "a", "an", "the", "some", "any", "go", "going", "to", "see", "visit", "want", "wanna", "i", "i'd",
    "get", "grab", "find", "for", "at", "in", "on", "me", "like", "feel", "something", "somewhere",
    "place", "places", "near", "nearby", "around", "here", "have", "let's", "lets", "with", "and", "or",
    "of", "maybe", "please", "good", "nice", "quiet", "fancy", "shop", "shops", "store", "stores", "spot",
}
# A few foods whose Japanese name is more likely in a place's name than the
# English one is in its cuisine tag.
_ALSO_MEANS = {
    "ramen": ["ラーメン", "拉麺", "らーめん"], "sushi": ["寿司", "鮨", "すし"], "curry": ["カレー"],
    "udon": ["うどん"], "soba": ["そば", "蕎麦"], "tonkatsu": ["とんかつ"], "yakiniku": ["焼肉"],
    "izakaya": ["居酒屋"], "gyudon": ["牛丼"], "tempura": ["天ぷら", "天麩羅"], "okonomiyaki": ["お好み焼"],
}
# How alike two words must be to count as a typo of each other (difflib's
# ratio), for words long enough that this doesn't just match anything.
_CLOSE_ENOUGH = 0.85
_MIN_FUZZY_LENGTH = 5


def _forms(word: str) -> set[str]:
    # The word and its likely singular forms: "bars" and "bar" meet at "bar",
    # "galleries" and "gallery" at "gallery", while "barber" stays apart.
    forms = {word}
    if word.endswith("ies"):
        forms.add(word[:-3] + "y")
    if word.endswith("es"):
        forms.add(word[:-2])
    if word.endswith("s"):
        forms.add(word[:-1])
    return forms


def _is_japanese(text: str) -> bool:
    return re.search(r"[^\x00-\x7f]", text) is not None


def _close(a: str, b: str) -> bool:
    if _forms(a) & _forms(b):
        return True
    return (min(len(a), len(b)) >= _MIN_FUZZY_LENGTH
            and difflib.SequenceMatcher(None, a, b).ratio() >= _CLOSE_ENOUGH)


def _take_place_word(wish: dict, phrase: str) -> None:
    kind, category, religion, types = _PLACE_WORDS[phrase]
    if wish["kind"] is None or (category and wish["category"] is None):
        wish.update(kind=kind, category=category or wish["category"], religion=religion or wish["religion"])
    if types and wish["types"] is None and category == wish["category"]:
        wish["types"] = set(types)


def parse_wish(text: str) -> dict:
    # {"kind": "food"/"things"/None, "category": ... or None, "types": OSM
    # types or None, "religion": ... or None, "terms": [words to find in a
    # place's name, cuisine or type]}.
    rest = f" {text.casefold().strip()} "
    wish = {"kind": None, "category": None, "types": None, "religion": None, "terms": []}
    for phrase in sorted(_PLACE_WORDS, key=len, reverse=True):
        # Whole words for English (plurals too); anywhere for Japanese.
        pattern = re.escape(phrase) if _is_japanese(phrase) else rf"\b{re.escape(phrase)}(e?s)?\b"
        if re.search(pattern, rest):
            _take_place_word(wish, phrase)
            rest = re.sub(pattern, " ", rest)
    single_words = [phrase for phrase in _PLACE_WORDS if " " not in phrase and not _is_japanese(phrase)]
    for word in re.split(r"[\s,.!?、。]+", rest):
        if not word or word in _FILLER:
            continue
        # A near miss on a kind of place ("resturant") counts as that kind.
        typo_of = next((phrase for phrase in single_words if _close(word, phrase)), None)
        if typo_of:
            _take_place_word(wish, typo_of)
        else:
            wish["terms"].append(word)
    return wish


def _fold(text: str) -> str:
    # Lower case without accents, so "pokemon" finds "Pokémon". Only for
    # Latin text: decomposing Japanese would split ポ into ホ and its mark.
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def _term_found(term: str, place: dict) -> bool:
    names = f"{place['name']} {place['name_en']}"
    if _is_japanese(term) and not _is_japanese(_fold(term)):
        term = _fold(term)  # accented Latin, e.g. "café"
    if _is_japanese(term):
        return term in names
    if any(alias in names for alias in _ALSO_MEANS.get(term, [])):
        return True
    words = re.findall(r"[a-z0-9']+", _fold(f"{names} {place['cuisine']} {place.get('type', '')}").replace("_", " "))
    return any(_close(term, word) for word in words)


def matches_wish(place: dict, wish: dict) -> bool:
    if wish["category"] and place["category"] != wish["category"]:
        return False
    if wish.get("types") and place.get("type") not in wish["types"]:
        return False
    if wish["religion"] and place["religion"] != wish["religion"]:
        return False
    return all(_term_found(term, place) for term in wish["terms"])


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def fetch_named(term: str, lat: float, lon: float, radius: int) -> list[dict]:
    # For a word no category covers ("pokemon", "batting"): any named place
    # whose name has it in, or whose own type is it. Raw Overpass elements,
    # parsed with kind "any".
    safe = re.sub(r"[^\w\- ]", "", term)  # nothing that could break the query
    around = f"(around:{radius},{lat},{lon})"
    type_value = min(_forms(safe.casefold()), key=len).replace(" ", "_")
    parts = [f'nwr["name"~"{safe}",i]{around};', f'nwr["name:en"~"{safe}",i]{around};']
    parts += [f'nwr["{key}"="{type_value}"]["name"]{around};' for key in ("shop", "amenity", "leisure", "tourism")]
    return _overpass(f"[out:json][timeout:25];({''.join(parts)});out center tags;")


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


# Photos for things to do. Food places go without: OSM rarely links a
# restaurant to a photo, and a chain's links lead to its logo.
def _commons_file(value: str) -> str | None:
    # "File:Sensoji_2023.jpg", or a Commons page link to it, as the file's
    # name. Categories ("Category:Sensoji") and other websites don't count.
    value = urllib.parse.unquote(value.strip()).removeprefix("https://commons.wikimedia.org/wiki/")
    if not value.startswith("File:"):
        return None
    return value.removeprefix("File:").replace("_", " ")


def photo_source(tags: dict) -> str | None:
    # Where a place's photo can come from, best first, as one string: a
    # Commons file named on the place itself ("file:Name.jpg"), its Wikidata
    # item's image ("wikidata:Q123"), or its Wikipedia article's lead image
    # ("wikipedia:ja:浅草寺"). None when OSM links none of them.
    for key in ("wikimedia_commons", "image"):
        name = _commons_file(tags.get(key, ""))
        if name:
            return f"file:{name}"
    if re.fullmatch(r"Q\d+", tags.get("wikidata", "")):
        return f"wikidata:{tags['wikidata']}"
    if re.fullmatch(r"[a-z-]+:.+", tags.get("wikipedia", "")):
        return f"wikipedia:{tags['wikipedia']}"
    return None


def _in_batches(items: list, size: int = 50):
    # Wikimedia's APIs take up to 50 titles or ids at a time.
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _wikidata_images(ids: list[str]) -> dict[str, str]:
    # Wikidata item -> its image's file name (property P18), where it has one.
    found = {}
    for batch in _in_batches(ids):
        url = WIKIDATA_URL + "?" + urllib.parse.urlencode(
            {"action": "wbgetentities", "ids": "|".join(batch), "props": "claims", "format": "json"})
        for item_id, entity in _get_json(url, timeout=15).get("entities", {}).items():
            claims = entity.get("claims", {}).get("P18", [])
            value = claims[0].get("mainsnak", {}).get("datavalue", {}).get("value") if claims else None
            if isinstance(value, str):
                found[item_id] = value.replace("_", " ")
    return found


def _wikipedia_images(links: list[str]) -> dict[str, str]:
    # "ja:浅草寺" -> the article's lead image's file name. Only its freely
    # licensed one (page_image_free): some articles lead with a non-free
    # image that can't be shown elsewhere.
    by_language = {}
    for link in links:
        language, _, title = link.partition(":")
        by_language.setdefault(language, []).append(title)
    found = {}
    for language, titles in by_language.items():
        for batch in _in_batches(titles):
            url = f"https://{language}.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
                "action": "query", "titles": "|".join(batch), "prop": "pageprops", "ppprop": "page_image_free",
                "redirects": 1, "format": "json", "formatversion": 2,
            })
            reply = _get_json(url, timeout=15).get("query", {})
            # A title can come back tidied or redirected: follow it home.
            renamed = {entry["to"]: entry["from"] for key in ("normalized", "redirects") for entry in reply.get(key, [])}
            for page in reply.get("pages", []):
                name = page.get("pageprops", {}).get("page_image_free")
                if name:
                    title = page["title"]
                    while title in renamed:
                        title = renamed[title]
                    found[f"{language}:{title}"] = name.replace("_", " ")
    return found


def _plain_text(markup: str) -> str:
    # Commons gives authors as HTML (often a link to their user page).
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


def _commons_photos(names: list[str]) -> dict[str, dict]:
    # File name -> {"url": a thumbnail PHOTO_WIDTH wide, "page": its Commons
    # page, "credit": "author · licence"}, the credit its licence asks for.
    found = {}
    for batch in _in_batches(names):
        url = COMMONS_URL + "?" + urllib.parse.urlencode({
            "action": "query", "titles": "|".join(f"File:{name}" for name in batch), "prop": "imageinfo",
            "iiprop": "url|extmetadata", "iiurlwidth": PHOTO_WIDTH,
            "iiextmetadatafilter": "Artist|LicenseShortName", "format": "json", "formatversion": 2,
        })
        reply = _get_json(url, timeout=15).get("query", {})
        renamed = {entry["to"]: entry["from"] for entry in reply.get("normalized", [])}
        for page in reply.get("pages", []):
            info = (page.get("imageinfo") or [{}])[0]
            if not info.get("thumburl"):
                continue
            metadata = info.get("extmetadata", {})
            author = _plain_text(metadata.get("Artist", {}).get("value", ""))
            if len(author) > 60:
                author = author[:57].rstrip() + "…"
            licence = _plain_text(metadata.get("LicenseShortName", {}).get("value", ""))
            title = renamed.get(page["title"], page["title"])
            found[title.removeprefix("File:").replace("_", " ")] = {
                "url": info["thumburl"],
                "page": info.get("descriptionurl", ""),
                "credit": " · ".join(part for part in (author, licence) if part),
            }
    return found


def _load_photo_cache() -> dict:
    try:
        return json.loads(PHOTOS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def place_photos(places: list[dict]) -> dict[str, dict]:
    # Place id -> its photo (see _commons_photos), for those of the places
    # given that have one. Kept on disk by photo source for a month,
    # "none found" included, so a list already seen needs no lookups. If
    # Wikimedia can't be reached, what's saved is shown and the rest are
    # tried again next time.
    cache = _load_photo_cache()
    now = time.time()
    sources = {place["id"]: place["photo_source"] for place in places if place.get("photo_source")}
    missing = sorted({source for source in sources.values()
                      if now - cache.get(source, {}).get("saved_at", 0) > _CACHE_KEEP_S})
    if missing:
        try:
            files = {source: source.removeprefix("file:") for source in missing if source.startswith("file:")}
            wikidata = _wikidata_images([source.removeprefix("wikidata:") for source in missing
                                         if source.startswith("wikidata:")])
            files |= {f"wikidata:{item}": name for item, name in wikidata.items()}
            wikipedia = _wikipedia_images([source.removeprefix("wikipedia:") for source in missing
                                           if source.startswith("wikipedia:")])
            files |= {f"wikipedia:{link}": name for link, name in wikipedia.items()}
            photos = _commons_photos(sorted(set(files.values())))
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
            photos = None
        if photos is not None:
            for source in missing:
                cache[source] = {"saved_at": now, "photo": photos.get(files.get(source, ""))}
            cache = {source: entry for source, entry in cache.items() if now - entry["saved_at"] <= _CACHE_KEEP_S}
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            PHOTOS_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return {place_id: cache[source]["photo"] for place_id, source in sources.items()
            if cache.get(source, {}).get("photo")}
