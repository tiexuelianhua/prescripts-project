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
import uuid
from datetime import date, datetime, timedelta

import pandas as pd

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
    # {"cards": [...], "reviews": {"YYYY-MM-DD": count}}. "reviews" only
    # feeds the "reviewed today" counts; the schedule itself is on each card.
    if CARDS_PATH.exists():
        with open(CARDS_PATH, encoding="utf-8") as file:
            deck = json.load(file)
    else:
        deck = {}
    deck.setdefault("cards", [])
    deck.setdefault("reviews", {})
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


def add_card(deck: dict, kind: str, front: str, reading: str, meaning: str) -> dict:
    # New cards are due straight away: they're things the user already
    # knows, so the first review just confirms it and starts the schedule.
    card = {
        "id": uuid.uuid4().hex,
        "kind": kind,
        "front": front.strip(),
        "reading": reading.strip() if kind == "vocab" else "",
        "meaning": meaning.strip(),
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
    # A blanked-out front or meaning is ignored (a card needs both); a
    # blanked-out reading is allowed, e.g. for a word written in kana only.
    for card in deck["cards"]:
        if card["id"] == card_id:
            for name in ("front", "reading", "meaning"):
                if name not in fields:
                    continue
                value = "" if pd.isna(fields[name]) else str(fields[name]).strip()
                if value or name == "reading":
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
    # easy
    if reps == 0:
        return 4, ease + 0.15
    return max(interval + 1, round(interval * ease * 1.3)), ease + 0.15


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


def due_cards(deck: dict, kinds: list[str] | None = None) -> list[dict]:
    # Overdue first (oldest due date), then least recently reviewed -- never-
    # reviewed cards before anything answered "Again" earlier today.
    today = today_jst().isoformat()
    kinds = kinds or KINDS
    due = [card for card in deck["cards"] if card["kind"] in kinds and card["due"] <= today]
    return sorted(due, key=lambda card: (card["due"], card["last_reviewed"] or ""))


def format_interval(days: int) -> str:
    if days == 0:
        return "today"
    if days < 30:
        return f"{days}d"
    if days < 365:
        return f"{days / 30:.1f}mo".replace(".0mo", "mo")
    return f"{days / 365:.1f}y".replace(".0y", "y")


def search_cards(deck: dict, query: str, kinds: list[str] | None = None) -> list[dict]:
    # Matches the written form, the reading, or the meaning (case-insensitive
    # for the English side). Empty query = every card of those kinds.
    kinds = kinds or KINDS
    query = query.strip().lower()
    return [
        card
        for card in deck["cards"]
        if card["kind"] in kinds
        and (
            not query
            or query in card["front"].lower()
            or query in card["reading"].lower()
            or query in card["meaning"].lower()
        )
    ]


def practice_summary() -> dict:
    # For the Overview tile.
    deck = load_deck()
    today = today_jst().isoformat()
    return {
        "total": {kind: sum(card["kind"] == kind for card in deck["cards"]) for kind in KINDS},
        "due": {kind: len(due_cards(deck, [kind])) for kind in KINDS},
        "reviewed_today": deck["reviews"].get(today, 0),
    }
