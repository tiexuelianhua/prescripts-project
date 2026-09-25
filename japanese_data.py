# Data/business logic for the Japanese page -- the user's own vocab and kanji
# flashcards and their spaced-repetition (SRS) schedule. No Streamlit
# rendering calls here, same split as meal_receipts_data.py/weather_data.py,
# so the Overview page can import this for its "Japanese practice" tile
# without running japanese_page.py's UI.
#
# Cards are words/kanji the user already knows, entered by hand:
# - vocab: front = the word as written (kanji), back = reading (hiragana) + meaning
# - kanji: front = the kanji,                   back = meaning
#
# Everything lives in one JSON file outside the repo (like Meal Receipts'
# CSVs and Spotify's settings) -- it's personal data, not code.
import json
import os
import random
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from prescripts_common import JST, SCRIPTS_DIR

JAPANESE_DIR = SCRIPTS_DIR.parent / "Japanese"
CARDS_PATH = JAPANESE_DIR / "cards.json"

KINDS = ["vocab", "kanji"]
KIND_LABELS = {"vocab": "Vocab", "kanji": "Kanji"}

# SRS grades, SM-2 style (the algorithm Anki grew out of), simplified to what
# a personal deck needs. Each card keeps an interval (days until it's due
# again) and an ease (how fast that interval grows on each "Good").
GRADES = ["again", "hard", "good", "easy"]
GRADE_LABELS = {"again": "Again", "hard": "Hard", "good": "Good", "easy": "Easy"}
STARTING_EASE = 2.5
MINIMUM_EASE = 1.3


def today_jst() -> date:
    return datetime.now(JST).date()


def load_deck() -> dict:
    # {"cards": [...], "reviews": {"YYYY-MM-DD": count}, "settings": {...}}.
    # "reviews" only feeds the "reviewed today" counts; the schedule itself
    # is on each card. "settings" holds page preferences (typed answers,
    # shuffled reviews) so they survive a restart.
    if CARDS_PATH.exists():
        with open(CARDS_PATH, encoding="utf-8") as file:
            deck = json.load(file)
    else:
        deck = {}
    deck.setdefault("cards", [])
    deck.setdefault("reviews", {})
    deck.setdefault("settings", {})
    # Kanji readings were added after the first cards were made -- older
    # cards just have them blank.
    for card in deck["cards"]:
        card.setdefault("onyomi", "")
        card.setdefault("kunyomi", "")
    return deck


def save_deck(deck: dict) -> None:
    # Written to a temp file and swapped in, so a crash mid-write can't leave
    # a half-written cards.json behind (the whole deck is one file).
    JAPANESE_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = CARDS_PATH.with_suffix(".json.tmp")
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(deck, file, ensure_ascii=False, indent=2)
    os.replace(temp_path, CARDS_PATH)


def find_duplicate(deck: dict, kind: str, front: str, exclude_id: str | None = None) -> dict | None:
    front = front.strip()
    for card in deck["cards"]:
        if card["kind"] == kind and card["front"] == front and card["id"] != exclude_id:
            return card
    return None


def add_card(
    deck: dict, kind: str, front: str, reading: str, meaning: str, onyomi: str = "", kunyomi: str = ""
) -> dict:
    # New cards are due straight away: they're things the user already
    # knows, so the first review just confirms it and starts the schedule.
    # `reading` is for vocab; kanji have their on'yomi / kun'yomi instead
    # (each a 、-separated list, kun'yomi okurigana marked with a dot as
    # KANJIDIC does: まな.ぶ).
    card = {
        "id": uuid.uuid4().hex,
        "kind": kind,
        "front": front.strip(),
        "reading": reading.strip() if kind == "vocab" else "",
        "meaning": meaning.strip(),
        "onyomi": onyomi.strip() if kind == "kanji" else "",
        "kunyomi": kunyomi.strip() if kind == "kanji" else "",
        "added": today_jst().isoformat(),
        "due": today_jst().isoformat(),
        "interval": 0,
        "ease": STARTING_EASE,
        "reps": 0,
        "lapses": 0,
        "last_reviewed": None,
    }
    deck["cards"].append(card)
    return card


def update_card(deck: dict, card_id: str, **fields) -> None:
    # A blanked-out front or meaning is ignored (a card needs both); blank
    # readings are allowed, e.g. a word written in kana only, or a kanji
    # with no kun'yomi.
    for card in deck["cards"]:
        if card["id"] == card_id:
            for name in ("front", "reading", "meaning", "onyomi", "kunyomi"):
                if name not in fields:
                    continue
                value = "" if pd.isna(fields[name]) else str(fields[name]).strip()
                if value or name not in ("front", "meaning"):
                    card[name] = value
            return


def delete_cards(deck: dict, card_ids: set[str]) -> None:
    deck["cards"] = [card for card in deck["cards"] if card["id"] not in card_ids]


def next_schedule(card: dict, grade: str) -> tuple[int, float]:
    # Returns (interval in days, ease) after answering `grade`. Interval 0 =
    # "again today": the card goes to the back of today's queue.
    interval, ease, reps = card["interval"], card["ease"], card["reps"]
    if grade == "again":
        return 0, max(MINIMUM_EASE, ease - 0.2)
    if grade == "hard":
        return max(1, round(interval * 1.2)), max(MINIMUM_EASE, ease - 0.15)
    if grade == "good":
        if reps == 0:
            return 1, ease
        if reps == 1:
            return 3, ease
        return max(interval + 1, round(interval * ease)), ease
    # easy -- always at least a day past what "Good" would give (on a
    # card's second review the formula alone could land on the same day).
    good_interval, _ = next_schedule(card, "good")
    if reps == 0:
        return max(4, good_interval + 1), ease + 0.15
    return max(good_interval + 1, round(interval * ease * 1.3)), ease + 0.15


def review_card(deck: dict, card_id: str, grade: str) -> None:
    today = today_jst()
    for card in deck["cards"]:
        if card["id"] == card_id:
            interval, ease = next_schedule(card, grade)
            card["interval"] = interval
            card["ease"] = round(ease, 2)
            if grade == "again":
                card["reps"] = 0
                card["lapses"] += 1
            else:
                card["reps"] += 1
            card["due"] = (today + timedelta(days=interval)).isoformat()
            # Full timestamp, not just the date: due_cards() sorts on it so
            # a card answered "Again" goes behind the others due today.
            card["last_reviewed"] = datetime.now(JST).isoformat(timespec="seconds")
            break
    deck["reviews"][today.isoformat()] = deck["reviews"].get(today.isoformat(), 0) + 1


def regrade(deck: dict, snapshot: dict, grade: str) -> None:
    # Undoes the last review of a card and answers it again with `grade` --
    # for a typed answer marked wrong over a typo. `snapshot` is a copy of
    # the card from before that review.
    today = today_jst().isoformat()
    for index, card in enumerate(deck["cards"]):
        if card["id"] == snapshot["id"]:
            deck["cards"][index] = dict(snapshot)
            deck["reviews"][today] = max(0, deck["reviews"].get(today, 0) - 1)
            review_card(deck, snapshot["id"], grade)
            return


def due_cards(deck: dict, kinds: list[str] | None = None, shuffle_seed: str | None = None) -> list[dict]:
    # Overdue first (oldest due date), then least recently reviewed -- never-
    # reviewed cards before anything answered "Again" earlier today.
    # With a shuffle_seed, cards not yet seen today come in a random order
    # instead -- the same order for the same seed, so the card on screen
    # doesn't change under Streamlit's reruns -- and anything answered
    # "Again" today still waits behind them, oldest miss first.
    today = today_jst().isoformat()
    kinds = kinds or KINDS
    due = [card for card in deck["cards"] if card["kind"] in kinds and card["due"] <= today]
    if shuffle_seed is None:
        return sorted(due, key=lambda card: (card["due"], card["last_reviewed"] or ""))

    def shuffled_key(card: dict) -> tuple:
        seen_today = (card["last_reviewed"] or "").startswith(today)
        if seen_today:
            return (1, card["last_reviewed"], 0.0)
        return (0, "", random.Random(f"{shuffle_seed}:{card['id']}").random())

    return sorted(due, key=shuffled_key)


def format_interval(days: int) -> str:
    if days == 0:
        return "today"
    if days < 30:
        return f"{days}d"
    if days < 365:
        return f"{days / 30:.1f}mo".replace(".0mo", "mo")
    return f"{days / 365:.1f}y".replace(".0y", "y")


def search_cards(deck: dict, query: str, kinds: list[str] | None = None) -> list[dict]:
    # Matches the written form, any reading, or the meaning (case-insensitive
    # for the English side). Empty query = every card of those kinds.
    kinds = kinds or KINDS
    query = query.strip().lower()
    return [
        card
        for card in deck["cards"]
        if card["kind"] in kinds
        and (
            not query
            or any(query in card[field].lower() for field in ("front", "reading", "meaning", "onyomi", "kunyomi"))
        )
    ]


def card_by_id(card_id: str | None) -> dict | None:
    return next((card for card in load_deck()["cards"] if card["id"] == card_id), None)


def random_card() -> dict | None:
    # For the Overview tile's word display.
    cards = load_deck()["cards"]
    return random.choice(cards) if cards else None


def practice_summary() -> dict:
    # For the Overview tile.
    deck = load_deck()
    today = today_jst().isoformat()
    return {
        "total": {kind: sum(card["kind"] == kind for card in deck["cards"]) for kind in KINDS},
        "due": {kind: len(due_cards(deck, [kind])) for kind in KINDS},
        "reviewed_today": deck["reviews"].get(today, 0),
    }


# --- Lookups for filling in new cards --------------------------------------
# Both keyless and free: Jisho's public word search (it takes kanji, kana,
# romaji or English) and kanjiapi.dev (KANJIDIC data) for single kanji,
# since Jisho's API has no kanji endpoint.
JISHO_URL = "https://jisho.org/api/v1/search/words?keyword={}"
KANJI_URL = "https://kanjiapi.dev/v1/kanji/{}"
KANJI_PATTERN = re.compile(r"[㐀-䶿一-鿿々]")


def _get_json(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": "The Prescripts (personal app)"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _jisho_results(query: str) -> list[dict]:
    # Jisho's raw entries for a search -- shared by the lookup below and the
    # spelling check (check_new_card), so the same word isn't fetched twice.
    return _get_json(JISHO_URL.format(urllib.parse.quote(query.strip())))["data"]


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def jisho_lookup(query: str, limit: int = 5) -> list[dict]:
    # Candidate vocab cards for `query`: {"front", "reading", "meaning",
    # "common"}. The meaning is the first sense's definitions -- a card
    # needs the gist, not the whole dictionary entry (it's editable anyway).
    results = _jisho_results(query)
    candidates = []
    for entry in results:
        forms = entry.get("japanese") or []
        senses = entry.get("senses") or []
        if not forms or not senses:
            continue
        form = forms[0]
        reading = form.get("reading", "")
        # Words usually written in kana (e.g. コーヒー, listed under 珈琲)
        # get the kana as the front, since that's how they'd be met.
        kana_usually = any("kana alone" in tag for tag in senses[0].get("tags", []))
        front = reading if kana_usually or not form.get("word") else form["word"]
        candidate = {
            "front": front,
            "reading": "" if front == reading else reading,
            "meaning": "; ".join(senses[0].get("english_definitions", [])[:3]),
            "common": bool(entry.get("is_common")),
        }
        if candidate not in candidates:
            candidates.append(candidate)
        if len(candidates) == limit:
            break
    return candidates


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def kanji_lookup(query: str, limit: int = 10) -> list[dict]:
    # One candidate per kanji in `query` (so pasting a word offers each of
    # its kanji): {"front", "meaning", "on", "kun"} -- the readings as
    # 、-separated lists, kun'yomi with KANJIDIC's okurigana dot (つよ.い).
    candidates = []
    for character in dict.fromkeys(KANJI_PATTERN.findall(query)):
        try:
            info = _get_json(KANJI_URL.format(urllib.parse.quote(character)))
        except urllib.error.HTTPError as error:
            if error.code == 404:  # not in KANJIDIC
                continue
            raise
        candidates.append(
            {
                "front": character,
                "meaning": ", ".join(info.get("meanings", [])[:3]),
                "on": "、".join(info.get("on_readings", [])),
                "kun": "、".join(info.get("kun_readings", [])),
            }
        )
        if len(candidates) == limit:
            break
    return candidates


# --- Typed answers ---------------------------------------------------------
# realkana-style review: type the answer and the app checks it. Vocab asks
# for the reading (kana, or romaji converted here) -- or the meaning, for
# kana-only words; kanji ask for the meaning and then each kind of reading
# (see answer_steps below).
ROMAJI = {
    "a": "あ", "i": "い", "u": "う", "e": "え", "o": "お",
    "ka": "か", "ki": "き", "ku": "く", "ke": "け", "ko": "こ",
    "ga": "が", "gi": "ぎ", "gu": "ぐ", "ge": "げ", "go": "ご",
    "sa": "さ", "shi": "し", "si": "し", "su": "す", "se": "せ", "so": "そ",
    "za": "ざ", "ji": "じ", "zi": "じ", "zu": "ず", "ze": "ぜ", "zo": "ぞ",
    "ta": "た", "chi": "ち", "ti": "ち", "tsu": "つ", "tu": "つ", "te": "て", "to": "と",
    "da": "だ", "di": "ぢ", "du": "づ", "de": "で", "do": "ど",
    "na": "な", "ni": "に", "nu": "ぬ", "ne": "ね", "no": "の",
    "ha": "は", "hi": "ひ", "fu": "ふ", "hu": "ふ", "he": "へ", "ho": "ほ",
    "ba": "ば", "bi": "び", "bu": "ぶ", "be": "べ", "bo": "ぼ",
    "pa": "ぱ", "pi": "ぴ", "pu": "ぷ", "pe": "ぺ", "po": "ぽ",
    "ma": "ま", "mi": "み", "mu": "む", "me": "め", "mo": "も",
    "ya": "や", "yu": "ゆ", "yo": "よ",
    "ra": "ら", "ri": "り", "ru": "る", "re": "れ", "ro": "ろ",
    "wa": "わ", "wo": "を", "n'": "ん",
    "sha": "しゃ", "shu": "しゅ", "sho": "しょ", "she": "しぇ",
    "sya": "しゃ", "syu": "しゅ", "syo": "しょ",
    "ja": "じゃ", "ju": "じゅ", "jo": "じょ", "je": "じぇ",
    "jya": "じゃ", "jyu": "じゅ", "jyo": "じょ",
    "zya": "じゃ", "zyu": "じゅ", "zyo": "じょ",
    "cha": "ちゃ", "chu": "ちゅ", "cho": "ちょ", "che": "ちぇ",
    "tya": "ちゃ", "tyu": "ちゅ", "tyo": "ちょ",
    "cya": "ちゃ", "cyu": "ちゅ", "cyo": "ちょ",
    "fa": "ふぁ", "fi": "ふぃ", "fe": "ふぇ", "fo": "ふぉ",
    "-": "ー",
}
for _consonant, _i_kana in {
    "k": "き", "g": "ぎ", "n": "に", "h": "ひ", "b": "び", "p": "ぴ", "m": "み", "r": "り",
}.items():
    for _vowel, _small in {"a": "ゃ", "u": "ゅ", "o": "ょ"}.items():
        ROMAJI[f"{_consonant}y{_vowel}"] = _i_kana + _small
for _vowel, _small in zip("aiueo", "ぁぃぅぇぉ"):
    ROMAJI[f"x{_vowel}"] = ROMAJI[f"l{_vowel}"] = _small
ROMAJI.update({"xtsu": "っ", "ltsu": "っ", "xtu": "っ", "ltu": "っ", "xya": "ゃ", "xyu": "ゅ", "xyo": "ょ"})

# The vowel each kana ends on, for spelling out a long-vowel mark (ー) --
# so "koohii" and "ko-hi-" both match コーヒー.
KANA_VOWEL = {}
for _romaji, _kana in ROMAJI.items():
    if _romaji[-1] in "aiueo":
        KANA_VOWEL[_kana[-1]] = ROMAJI[_romaji[-1]]


def romaji_to_kana(text: str) -> str:
    # Greedy longest match, plus the two rules a table can't hold: a doubled
    # consonant is a small っ (kka -> っか), and a lone n before a consonant
    # or at the end is ん. Anything unrecognised is kept as typed.
    text = text.lower()
    output = []
    i = 0
    while i < len(text):
        if i + 1 < len(text) and text[i] == text[i + 1] and text[i] in "bcdfghjkmpqrstvwz":
            output.append("っ")
            i += 1
            continue
        if text[i] == "n" and (i + 1 == len(text) or text[i + 1] not in "aiueoy'n"):
            output.append("ん")
            i += 1
            continue
        # "nn": ん on its own ("shinnen"), but when a vowel follows, the
        # second n starts the next syllable -- "konnichiha", "onna" -- the
        # way people write it, not the IME's "konnnichiha" (also accepted).
        if text[i : i + 2] == "nn":
            output.append("ん")
            i += 1 if i + 2 < len(text) and text[i + 2] in "aiueoy" else 2
            continue
        for size in (4, 3, 2, 1):
            chunk = text[i : i + size]
            if chunk in ROMAJI:
                output.append(ROMAJI[chunk])
                i += size
                break
        else:
            output.append(text[i])
            i += 1
    return "".join(output)


def normalize_kana(text: str) -> str:
    # Katakana -> hiragana, spaces dropped, ー spelled out as the vowel it
    # lengthens, so a reading typed any of those ways compares equal.
    text = text.replace(" ", "").replace("　", "")
    hiragana = "".join(chr(ord(char) - 0x60) if "ァ" <= char <= "ヶ" else char for char in text)
    spelled = []
    for char in hiragana:
        if char == "ー" and spelled:
            spelled.append(KANA_VOWEL.get(spelled[-1], "ー"))
        else:
            spelled.append(char)
    return "".join(spelled)


def meaning_parts(text: str) -> set[str]:
    # "to study; diligence (work)" -> {"study", "diligence"}: split on the
    # usual separators, lowercase, and drop a leading "to"/article and
    # anything in brackets, so the check is about the word, not punctuation.
    parts = set()
    for part in re.split(r"[,;/]", text.lower()):
        part = re.sub(r"\(.*?\)", "", part).strip()
        part = re.sub(r"^(to|a|an|the) ", "", part).strip()
        if part:
            parts.add(part)
    return parts


def has_distinct_reading(card: dict) -> bool:
    # False for kana-only words even if their reading was filled in (e.g.
    # これ / これ): the reading just repeats the front, so it's neither worth
    # showing again on the back nor asking for in typed mode.
    return (
        card["kind"] == "vocab"
        and bool(card["reading"])
        and normalize_kana(card["reading"]) != normalize_kana(card["front"])
    )


def split_readings(text: str) -> list[str]:
    # "キョウ、ゴウ" / "つよ.い, し.いる" -> one entry per reading.
    return [part for part in re.split(r"[、,;/\s]+", text or "") if part]


def display_readings(text: str) -> str:
    # For showing kun'yomi: KANJIDIC's dot before the okurigana becomes
    # brackets (つよ.い -> つよ(い)), and the list gets a readable separator.
    shown = []
    for reading in split_readings(text):
        stem, _, okurigana = reading.partition(".")
        shown.append(f"{stem}({okurigana})" if okurigana else stem)
    return "、".join(shown)


# The parts a typed answer is asked for, in order. Vocab: its reading (or
# its meaning, for kana-only words). Kanji: meaning, then on'yomi, then
# kun'yomi -- skipping a reading the card doesn't have.
STEP_LABELS = {
    "reading": "Reading (kana or romaji)",
    "meaning": "Meaning",
    "onyomi": "On'yomi (kana or romaji)",
    "kunyomi": "Kun'yomi (kana or romaji)",
}


def answer_steps(card: dict) -> list[str]:
    # Every card asks for its meaning; readings come first where there are any.
    if card["kind"] == "vocab":
        return ["reading", "meaning"] if has_distinct_reading(card) else ["meaning"]
    return ["meaning"] + [field for field in ("onyomi", "kunyomi") if split_readings(card.get(field, ""))]


def _typed_kana(typed: str) -> str:
    if re.search(r"[a-zA-Z]", typed):
        typed = romaji_to_kana(typed)
    return normalize_kana(typed)


def check_step(card: dict, step: str, typed: str) -> bool:
    if not typed.strip():
        return False
    if step == "meaning":
        # Any of the card's meanings counts; typing several ("study,
        # learning") is fine as long as each one is on the card.
        typed_parts = meaning_parts(typed)
        return bool(typed_parts) and typed_parts <= meaning_parts(card["meaning"])
    typed_kana = _typed_kana(typed)
    if step == "reading":
        return typed_kana == normalize_kana(card["reading"])
    # A reading: any one listed of that kind counts. Kun'yomi can be typed
    # whole (まなぶ) or as just the stem (まな); KANJIDIC's "-" marks
    # (prefix/suffix readings like -め) are ignored.
    accepted = set()
    for reading in split_readings(card[step]):
        reading = reading.replace("-", "")
        stem, _, okurigana = reading.partition(".")
        accepted.add(normalize_kana(stem + okurigana))
        accepted.add(normalize_kana(stem))
    return typed_kana in accepted


# --- Spelling check for hand-typed cards ------------------------------------
# Run when a card is added: compares what was typed against Jisho (vocab)
# and KANJIDIC (kanji readings) and returns any mismatches -- likely typos --
# each as {"field", "message", "fix"}, "fix" being the corrected value for
# that whole field (or None when there's no single obvious correction). An
# empty list means everything checked out; blanks are never flagged, since
# every reading is optional.
def _edit_distance(a: str, b: str) -> int:
    # Characters to add, drop or swap to turn a into b (Levenshtein).
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b)))
        previous = current
    return previous[-1]


def _closest(typed: str, known: list[str]) -> str:
    # The known reading/word fewest keystrokes away from what was typed;
    # ties go to whichever comes first in `known` (Jisho lists the most
    # common first), so ありがとお suggests ありがとう, not ありがと.
    typed_kana = normalize_kana(typed.replace(".", "").replace("-", ""))
    return min(
        known,
        key=lambda reading: _edit_distance(typed_kana, normalize_kana(reading.replace(".", "").replace("-", ""))),
    )


def check_new_card(kind: str, front: str, reading: str, onyomi: str, kunyomi: str) -> list[dict]:
    front = front.strip()
    if kind == "vocab":
        return _check_vocab(front, reading.strip())
    return _check_kanji(front, onyomi, kunyomi)


def _check_vocab(front: str, reading: str) -> list[dict]:
    entries = _jisho_results(front)
    forms = [form for entry in entries for form in entry.get("japanese", [])]
    if KANJI_PATTERN.search(front):
        known = list(dict.fromkeys(form["reading"] for form in forms if form.get("word") == front and form.get("reading")))
        if not known:
            return [{"field": "front", "message": f"Jisho has no word written {front}. A typo?", "fix": None}]
        if reading and _typed_kana(reading) not in {normalize_kana(k) for k in known}:
            return [
                {
                    "field": "reading",
                    "message": f"Jisho reads {front} as {'、'.join(known)} -- you typed {reading}.",
                    "fix": _closest(reading, known),
                }
            ]
        return []
    # Kana-only: the word itself is what might be misspelled.
    target = normalize_kana(front)
    if any(normalize_kana(form.get("reading", "")) == target or form.get("word") == front for form in forms):
        return []
    # Suggestions: Jisho's results within a couple of keystrokes of what was
    # typed (it also returns loosely related words), nearest first.
    readings = list(dict.fromkeys(form["reading"] for form in forms if form.get("reading")))
    distance = {reading: _edit_distance(target, normalize_kana(reading)) for reading in readings}
    nearby = sorted((r for r in readings if distance[r] <= max(2, len(target) // 3)), key=distance.get)[:3]
    message = f"Jisho has no word {front}."
    if nearby:
        message += f" Closest matches: {'、'.join(nearby)}."
    return [{"field": "front", "message": message, "fix": _closest(front, nearby) if nearby else None}]


def _check_kanji(front: str, onyomi: str, kunyomi: str) -> list[dict]:
    info = next((candidate for candidate in kanji_lookup(front) if candidate["front"] == front), None)
    if info is None:  # not a single kanji KANJIDIC knows -- nothing to check against
        return []
    issues = []
    for field, name, known_text in (("onyomi", "on'yomi", info["on"]), ("kunyomi", "kun'yomi", info["kun"])):
        known = split_readings(known_text)
        typed_readings = split_readings(onyomi if field == "onyomi" else kunyomi)
        if not known or not typed_readings:
            continue
        # Kun'yomi can be typed with or without the okurigana (つよい / つよ).
        accepted = set()
        for reading in known:
            stem, _, okurigana = reading.replace("-", "").partition(".")
            accepted |= {normalize_kana(stem + okurigana), normalize_kana(stem)}
        for typed in typed_readings:
            if _typed_kana(typed.replace(".", "").replace("-", "")) in accepted:
                continue
            # dict.fromkeys: a correction that duplicates a reading already
            # listed (キョウ、ギョウ -> キョウ) collapses into it.
            fixed = dict.fromkeys(_closest(typed, known) if other == typed else other for other in typed_readings)
            issues.append(
                {
                    "field": field,
                    "message": f"{typed} isn't a known {name} of {front}. Known: {display_readings(known_text)}.",
                    "fix": "、".join(fixed),
                }
            )
    return issues
