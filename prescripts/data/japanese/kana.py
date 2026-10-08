# Hiragana and katakana for total beginners: a drill on the Japanese page,
# outside the SRS reviews. Each set can be switched on by itself, so they
# can be learned a row at a time. Public version only -- the author's copy
# (the private look) doesn't show it.
#
# Set settings live in the deck's settings under "kana".
import random

from prescripts.data.japanese.answers import normalize_kana, romaji_to_kana

# The hiragana, set by set: (kana, accepted romaji, first one shown as the
# answer). Katakana are the same sounds, converted below. Exceptions (し ち
# つ ふ) don't follow their row's consonant, so they're a set of their own.
_HIRAGANA_SETS = {
    "あ": [("あ", "a"), ("い", "i"), ("う", "u"), ("え", "e"), ("お", "o")],
    "か": [("か", "ka"), ("き", "ki"), ("く", "ku"), ("け", "ke"), ("こ", "ko")],
    "さ": [("さ", "sa"), ("す", "su"), ("せ", "se"), ("そ", "so")],
    "た": [("た", "ta"), ("て", "te"), ("と", "to")],
    "な": [("な", "na"), ("に", "ni"), ("ぬ", "nu"), ("ね", "ne"), ("の", "no")],
    "は": [("は", "ha"), ("ひ", "hi"), ("へ", "he"), ("ほ", "ho")],
    "ま": [("ま", "ma"), ("み", "mi"), ("む", "mu"), ("め", "me"), ("も", "mo")],
    "や": [("や", "ya"), ("ゆ", "yu"), ("よ", "yo")],
    "ら": [("ら", "ra"), ("り", "ri"), ("る", "ru"), ("れ", "re"), ("ろ", "ro")],
    "わ": [("わ", "wa"), ("を", "wo o"), ("ん", "n nn")],
    "Exceptions": [("し", "shi si"), ("ち", "chi ti"), ("つ", "tsu tu"), ("ふ", "fu hu")],
    "が": [("が", "ga"), ("ぎ", "gi"), ("ぐ", "gu"), ("げ", "ge"), ("ご", "go")],
    "ざ": [("ざ", "za"), ("じ", "ji zi"), ("ず", "zu"), ("ぜ", "ze"), ("ぞ", "zo")],
    "だ": [("だ", "da"), ("ぢ", "ji di"), ("づ", "zu du"), ("で", "de"), ("ど", "do")],
    "ば": [("ば", "ba"), ("び", "bi"), ("ぶ", "bu"), ("べ", "be"), ("ぼ", "bo")],
    "ぱ": [("ぱ", "pa"), ("ぴ", "pi"), ("ぷ", "pu"), ("ぺ", "pe"), ("ぽ", "po")],
    "Combinations": [
        (consonant_kana + small, consonant_romaji + vowel)
        for consonant_kana, consonant_romaji in (
            ("き", "ky"), ("し", "sh"), ("ち", "ch"), ("に", "ny"), ("ひ", "hy"), ("み", "my"), ("り", "ry"),
            ("ぎ", "gy"), ("じ", "j"), ("び", "by"), ("ぴ", "py"),
        )
        for small, vowel in (("ゃ", "a"), ("ゅ", "u"), ("ょ", "o"))
    ],
}
KANA_SETS = list(_HIRAGANA_SETS)
SCRIPTS = {"hiragana": "Hiragana", "katakana": "Katakana"}
# A beginner's start: the first two rows of hiragana.
DEFAULT_SETTINGS = {"on": True, "scripts": ["hiragana"], "sets": ["あ", "か"]}


def _katakana(hiragana: str) -> str:
    return "".join(chr(ord(char) + 0x60) for char in hiragana)


def kana_settings(deck: dict) -> dict:
    return {**DEFAULT_SETTINGS, **deck["settings"].get("kana", {})}


def kana_pool(scripts: list[str], sets: list[str]) -> list[dict]:
    # Every kana switched on: {"kana", "romaji" (the answer shown), "accepted"}.
    pool = []
    for script in scripts:
        for set_name in sets:
            for hiragana, romaji in _HIRAGANA_SETS.get(set_name, []):
                accepted = romaji.split()
                pool.append({
                    "kana": hiragana if script == "hiragana" else _katakana(hiragana),
                    "romaji": accepted[0],
                    "accepted": accepted,
                })
    return pool


def next_kana(pool: list[dict], previous: str | None = None) -> dict | None:
    # Random, but never the same one twice in a row (when there's a choice).
    choices = [item for item in pool if item["kana"] != previous] or pool
    return random.choice(choices) if choices else None


def check_kana(item: dict, typed: str) -> bool:
    # The romaji listed for it, or anything that spells the same kana
    # (sya for しゃ, typing the kana itself).
    typed = typed.strip().lower()
    if not typed:
        return False
    if typed in item["accepted"]:
        return True
    return normalize_kana(romaji_to_kana(typed)) == normalize_kana(item["kana"])
