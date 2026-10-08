# Grammar points: a third kind of card, scheduled like vocab and kanji, but
# reviewed through the deck's own words. Each review pairs the point with a
# random word it fits (by part of speech) and shows the form they make
# together: 静か + じゃなかった -> 静かじゃなかった.
#
# A point is front = its ending (じゃなかった), meaning, plus:
# - "attaches": the word types it goes on (WORD_TYPES)
# - "base": the form of the word the ending goes on. Only "word" (the word
#   as written) for now -- nouns and na-adjectives need nothing more. Verb
#   and i-adjective forms (ます-stem, て-form, ...) would be new bases here,
#   with no change to the points already saved.
import random

from prescripts.data.japanese.deck import add_card

WORD_TYPES = {"noun": "Nouns", "na-adjective": "Na-adjectives"}
BASES = {"word": "The word as written"}

# Parts of speech on vocab cards (see lookups.py) that count as each word type.
_WORD_TYPE_LABELS = {
    "noun": {"noun", "pronoun", "station", "number"},
    "na-adjective": {"na-adjective"},
}

# State of being, the forms nouns and na-adjectives take: added in one go
# from Add cards. (ending, meaning)
STARTER_POINTS = [
    ("だ", "is (casual)"),
    ("です", "is (polite)"),
    ("じゃない", "isn't (casual)"),
    ("じゃありません", "isn't (polite)"),
    ("だった", "was (casual)"),
    ("でした", "was (polite)"),
    ("じゃなかった", "wasn't (casual)"),
    ("じゃありませんでした", "wasn't (polite)"),
]


# Where to read more about a point: Tae Kim's chapter on the starter set.
# Points added by hand have none. (link text, url)
_STATE_OF_BEING = ("Tae Kim, State of being", "https://guidetojapanese.org/learn/grammar/stateofbeing")


def read_more(point: dict) -> tuple[str, str] | None:
    return _STATE_OF_BEING if point["front"] in {ending for ending, _ in STARTER_POINTS} else None


def word_types(card: dict) -> set[str]:
    # "Noun, No-adjective, Na-adjective" -> {"noun", "na-adjective"}.
    if card["kind"] != "vocab":
        return set()
    labels = {label.strip().lower() for label in card.get("pos", "").split(",")}
    return {word_type for word_type, matches in _WORD_TYPE_LABELS.items() if labels & matches}


def add_grammar_point(
    deck: dict, ending: str, meaning: str, attaches: list[str], note: str = "", learning: bool = False
) -> dict:
    card = add_card(deck, "grammar", ending, "", meaning, note=note, learning=learning)
    card["attaches"] = [word_type for word_type in WORD_TYPES if word_type in attaches]
    card["base"] = "word"
    return card


def add_starter_points(deck: dict) -> int:
    # Skips any already in the deck (by ending). Returns how many it added.
    have = {card["front"] for card in deck["cards"] if card["kind"] == "grammar"}
    added = 0
    for ending, meaning in STARTER_POINTS:
        if ending not in have:
            add_grammar_point(deck, ending, meaning, list(WORD_TYPES))
            added += 1
    return added


def fitting_words(deck: dict, point: dict) -> list[dict]:
    # Words already known first; ones still in Learn only if nothing else fits.
    fits = [card for card in deck["cards"] if word_types(card) & set(point.get("attaches", []))]
    known = [card for card in fits if not card.get("learning")]
    return known or fits


def pick_word(deck: dict, point: dict, seed: str) -> dict | None:
    # The same seed always picks the same word, so the card on screen holds
    # still through Streamlit's reruns.
    words = sorted(fitting_words(deck, point), key=lambda card: card["id"])
    return random.Random(seed).choice(words) if words else None


def conjugate(point: dict, word: dict) -> dict:
    # The word with the point's ending on, written and read. A word written
    # in kana has no separate reading.
    reading = word["reading"] or word["front"]
    return {"front": word["front"] + point["front"], "reading": reading + point["front"]}


def typed_prompt(point: dict, word: dict) -> dict:
    # For typed answers: the point with the word it's paired with and the
    # form they make, which is what gets typed (see answers.check_step).
    form = conjugate(point, word)
    return dict(point, word=word, form_front=form["front"], form_reading=form["reading"])
