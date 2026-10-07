# The Japanese page's flashcard deck and its spaced-repetition (SRS)
# schedule: loading and saving cards, grading reviews, and picking what's due.
#
# Cards are words/kanji the user already knows, entered by hand:
# - vocab: front = the word as written (kanji), back = reading (hiragana) + meaning,
#          plus its part of speech ("pos", e.g. "Godan verb, Transitive")
# - kanji: front = the kanji,                   back = meaning
#
# Everything lives in one JSON file outside the repo (like Meal Receipts'
# CSVs and Spotify's settings) -- it's personal data, not code.
import json
import os
import random
import uuid
from datetime import date, datetime, timedelta

import pandas as pd

from prescripts.common import JST, SCRIPTS_DIR

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
    # Kanji readings and parts of speech were added after the first cards
    # were made -- older cards just have them blank.
    for card in deck["cards"]:
        card.setdefault("onyomi", "")
        card.setdefault("kunyomi", "")
        card.setdefault("pos", "")
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
    deck: dict, kind: str, front: str, reading: str, meaning: str, onyomi: str = "", kunyomi: str = "",
    pos: str = "",
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
        "pos": pos.strip() if kind == "vocab" else "",
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
            for name in ("front", "reading", "meaning", "onyomi", "kunyomi", "pos"):
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
    # Matches the written form, any reading, the meaning or the part of
    # speech (case-insensitive for the English side, so "verb" finds every
    # verb). Empty query = every card of those kinds.
    kinds = kinds or KINDS
    query = query.strip().lower()
    return [
        card
        for card in deck["cards"]
        if card["kind"] in kinds
        and (
            not query
            or any(query in card[field].lower() for field in ("front", "reading", "meaning", "onyomi", "kunyomi", "pos"))
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
