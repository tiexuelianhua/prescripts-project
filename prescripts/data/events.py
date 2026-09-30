# Logic for the Activities page's Events section: what's coming up around
# greater Tokyo. No Streamlit rendering here, same split as the other data
# files.
#
# Free event data for Tokyo is patchy (researched 2026-09), so this puts
# together what there is:
# - Tokyo Big Sight's own list of exhibitions (Tokyo's open data, CC BY),
#   kept to the ones open to the public -- most are trade-only.
# - A yearly list of well-known festivals and markets (yearly_events.json),
#   written by hand. Their dates move a little each year, so each says when
#   it usually is and links a search for this year's dates.
# - The user's own events, for pop-ups, gigs and exhibitions spotted
#   elsewhere, since nothing free lists those.
# - Headlines from Anime!Anime!'s news feed that name a collab or pop-up,
#   or words the user watches for (a series, a character).
import csv
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
from datetime import date, datetime, timedelta
from pathlib import Path

from prescripts.common import JST
from prescripts.data.activities import _HEADERS, ACTIVITIES_DIR, CACHE_DIR

BIG_SIGHT_URL = "https://www.opendata.metro.tokyo.lg.jp/tokyobigsight/tokyobigsighteventinformation.csv"
NEWS_URL = "https://animeanime.jp/rss/index.rdf"
YEARLY_PATH = Path(__file__).with_name("yearly_events.json")
MY_EVENTS_PATH = ACTIVITIES_DIR / "events.json"
# How far ahead the list looks.
AHEAD_DAYS = 60
FETCH_ERRORS = (urllib.error.URLError, TimeoutError, ValueError, KeyError, ElementTree.ParseError)

GROUPS = {
    "festival": "Festivals",
    "market": "Markets",
    "anime_games": "Anime and games",
    "art": "Art",
    "music": "Music",
    "convention": "Conventions",
}
# A Big Sight event's group, from words in its name or description. The
# first that fits wins; anything else is a convention.
_GROUP_WORDS = [
    ("anime_games", r"コミック|comic|同人|例大祭|アニメ|anime|ゲーム|game|ホビー|hobby|模型|フィギュア|figure|コスプレ"
                    r"|cosplay|vtuber|ボカロ|アミューズメント|doll|ドール"),
    ("art", r"アート|art|デザイン|design|文学|写真|photo|クリエイター|creator|ハンドメイド|handmade|作品"),
    ("music", r"音楽|music|ライブ|live|コンサート|concert|フェス(?!タ)|fes(?!ta)|dj"),
    ("market", r"マーケット|market|蚤の市|フリマ|骨董|antique"),
]
# Headlines worth showing without any watched words.
_NEWS_WORDS = r"ポップアップ|pop ?up|コラボカフェ|コラボ|カフェ|ストア|展示|原画展|イベント"


def today_jst() -> date:
    return datetime.now(JST).date()


def _fetch(url: str, timeout: float = 30) -> bytes:
    request = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _cached(name: str, fresh_s: float, fetch) -> str:
    # The same rules as the place lookups: a saved answer is used as is
    # while fresh, and an older one only when the source can't be reached.
    path = CACHE_DIR / f"{name}.txt"
    if path.exists() and time.time() - path.stat().st_mtime < fresh_s:
        return path.read_text(encoding="utf-8")
    try:
        text = fetch()
    except FETCH_ERRORS:
        if path.exists():
            return path.read_text(encoding="utf-8")
        raise
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def _decode(raw: bytes) -> str:
    # The Big Sight file has been Shift_JIS; UTF-8 is tried first in case
    # that ever changes.
    for encoding in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp932", errors="replace")


def group_of(text: str) -> str:
    for group, pattern in _GROUP_WORDS:
        if re.search(pattern, text, re.IGNORECASE):
            return group
    return "convention"


def _parse_day(text: str) -> date | None:
    try:
        year, month, day = (int(part) for part in text.strip().split("/"))
        return date(year, month, day)
    except ValueError:
        return None


def parse_big_sight(text: str) -> list[dict]:
    # Rows open to the public (来場対象者 says 一般), as events. Trade-only
    # (商談) ones are left out: they turn visitors away at the door.
    events = []
    for row in csv.DictReader(io.StringIO(text)):
        audience = row.get("来場対象者", "")
        start, end = _parse_day(row.get("会期(開始)", "")), _parse_day(row.get("会期(終了)", ""))
        name = " ".join(row.get("展示会名", "").split())
        if "一般" not in audience or not start or not name:
            continue
        hall = row.get("利用施設", "").strip()
        events.append({
            "name": name,
            "start": start.isoformat(),
            "end": (end or start).isoformat(),
            # 有明GYM-EX is its own building next door; the rest are halls.
            "place": hall if "GYM-EX" in hall else f"Tokyo Big Sight ({hall})" if hall else "Tokyo Big Sight",
            "group": group_of(f"{name} {row.get('内容', '')}"),
            "hours": " ".join(row.get("開催時間 開催時間が毎日異なる場合", "").split()),
            "link": row.get("URL", "").strip(),
            "source": "Big Sight",
        })
    return events


def big_sight_events() -> list[dict]:
    # The list is updated every few weeks, so a day-old copy is fine.
    return parse_big_sight(_cached("big_sight", 24 * 3600, lambda: _decode(_fetch(BIG_SIGHT_URL))))


def yearly_events() -> list[dict]:
    return json.loads(YEARLY_PATH.read_text(encoding="utf-8"))


def _yearly_next(entry: dict, today: date) -> date | None:
    # When a yearly event next starts, or today if it's under way; None if
    # not within AHEAD_DAYS. Its "around" ranges (["MM-DD", "MM-DD"]) are
    # only a rough guide to when it usually is, wide enough to cover a few
    # years' dates -- used to order the list, never shown as its dates.
    last = today + timedelta(days=AHEAD_DAYS)
    starts = []
    for year in (today.year - 1, today.year, today.year + 1):
        for first, final in entry["around"]:
            start = date(year, *map(int, first.split("-")))
            end = date(year + (final < first), *map(int, final.split("-")))
            if end >= today and start <= last:
                starts.append(max(start, today))
    return min(starts, default=None)


def my_events() -> list[dict]:
    try:
        return json.loads(MY_EVENTS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_my_events(events: list[dict]) -> None:
    ACTIVITIES_DIR.mkdir(parents=True, exist_ok=True)
    MY_EVENTS_PATH.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")


def add_my_event(name: str, start: date, end: date, place: str, group: str, link: str) -> None:
    events = my_events()
    events.append({
        "id": f"{time.time_ns()}", "name": name.strip(), "start": start.isoformat(),
        "end": max(start, end).isoformat(), "place": place.strip(), "group": group, "link": link.strip(),
    })
    _save_my_events(events)


def remove_my_event(event_id: str) -> None:
    _save_my_events([event for event in my_events() if event.get("id") != event_id])


def upcoming(today: date, big_sight: list[dict] | None) -> list[dict]:
    # Everything on now or starting within AHEAD_DAYS, soonest first. Each
    # {"name", "name_en", "start", "end", "place", "group", "hours", "link", "source",
    # "usually", "id"}; "usually" is set (and "end" empty) for yearly ones,
    # whose dates are only approximate. big_sight is None if it couldn't be
    # fetched.
    last = today + timedelta(days=AHEAD_DAYS)
    found = []
    for event in (big_sight or []) + [{**event, "source": "Mine"} for event in my_events()]:
        start, end = date.fromisoformat(event["start"]), date.fromisoformat(event["end"])
        if end >= today and start <= last:
            found.append({"name_en": "", "hours": "", "link": "", "usually": "", "id": "", **event})
    for entry in yearly_events():
        start = _yearly_next(entry, today)
        if start:
            found.append({
                "name": entry["name"], "name_en": entry.get("name_en", ""), "start": start.isoformat(), "end": "", "place": entry["place"],
                "group": entry["group"], "hours": "", "link": "", "source": "Yearly",
                "usually": entry["usually"], "id": "",
            })
    return sorted(found, key=lambda event: (event["start"], event["name"]))


def format_dates(event: dict) -> str:
    # "Sat 3 Oct", "2–4 Oct" or "28 Nov – 2 Dec". A yearly event's dates are
    # only approximate, so it says when it usually is instead.
    if event["usually"]:
        return f"usually {event['usually']}"
    start, end = date.fromisoformat(event["start"]), date.fromisoformat(event["end"])
    if start == end:
        return f"{start:%a} {start.day} {start:%b}"
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day}–{end.day} {end:%b}"
    return f"{start.day} {start:%b} – {end.day} {end:%b}"


def matches(event: dict, text: str) -> bool:
    # Every word typed is in its name, place or group.
    haystack = f"{event['name']} {event['place']} {GROUPS.get(event['group'], '')}".casefold()
    return all(word in haystack for word in text.casefold().split())


def dates_search(event: dict, today: date) -> str:
    # A web search for this year's dates of a yearly event.
    return "https://www.google.com/search?" + urllib.parse.urlencode({"q": f"{event['name']} {today.year} 日程"})


def web_search(words: str) -> str:
    return "https://www.google.com/search?" + urllib.parse.urlencode({"q": words})


def parse_news(text: str) -> list[dict]:
    # An RSS 1.0 (RDF) or 2.0 feed's items, as {"title", "link", "date"}.
    items = []
    for item in ElementTree.fromstring(text).iter():
        if item.tag.split("}")[-1] != "item":
            continue
        fields = {child.tag.split("}")[-1]: (child.text or "").strip() for child in item}
        if fields.get("title"):
            items.append({"title": fields["title"], "link": fields.get("link", ""),
                          "date": (fields.get("date") or fields.get("pubDate") or "")[:10]})
    return items


def news(watch_words: list[str]) -> list[dict]:
    # Recent headlines naming a watched word, or, with none set, a collab or
    # pop-up. Refreshed every hour at most: it's a news site's own feed.
    items = parse_news(_cached("anime_news", 3600, lambda: _fetch(NEWS_URL, timeout=20).decode("utf-8")))
    words = [word.casefold() for word in watch_words if word.strip()]
    if words:
        return [item for item in items if any(word in item["title"].casefold() for word in words)]
    return [item for item in items if re.search(_NEWS_WORDS, item["title"], re.IGNORECASE)]
