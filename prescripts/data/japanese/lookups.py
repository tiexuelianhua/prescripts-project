# Lookups for filling in new cards. Both keyless and free: Jisho's public word
# search (it takes kanji, kana, romaji or English) and kanjiapi.dev (KANJIDIC
# data) for single kanji, since Jisho's API has no kanji endpoint.
import json
import re
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

JISHO_URL = "https://jisho.org/api/v1/search/words?keyword={}"
KANJI_URL = "https://kanjiapi.dev/v1/kanji/{}"
KANJI_PATTERN = re.compile(r"[㐀-䶿一-鿿々]")


def _get_json(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": "The Prescripts (personal app)"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def jisho_results(query: str) -> list[dict]:
    # Jisho's raw entries for a search -- shared by the lookup below and the
    # spelling check (check_new_card), so the same word isn't fetched twice.
    return _get_json(JISHO_URL.format(urllib.parse.quote(query.strip())))["data"]


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def jisho_lookup(query: str, limit: int = 5) -> list[dict]:
    # Candidate vocab cards for `query`: {"front", "reading", "meaning",
    # "pos", "common"}. The meaning is the first sense's definitions -- a card
    # needs the gist, not the whole dictionary entry (it's editable anyway).
    results = jisho_results(query)
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
            "pos": entry_part_of_speech(entry),
            "common": bool(entry.get("is_common")),
        }
        if candidate not in candidates:
            candidates.append(candidate)
        if len(candidates) == limit:
            break
    return candidates


# Jisho's part-of-speech names, shortened for a card. Checked in this order,
# first match wins: "Pronoun" and "Pre-noun adjectival" both contain "noun".
_PART_OF_SPEECH_NAMES = [
    ("wikipedia definition", None),
    ("godan verb", "Godan verb"),
    ("ichidan verb", "Ichidan verb"),
    ("kuru verb", "Irregular verb"),
    ("suru verb - included", "Irregular verb"),  # する itself
    ("suru verb", "Suru verb"),
    ("intransitive verb", "Intransitive"),
    ("transitive verb", "Transitive"),
    ("auxiliary verb", "Auxiliary verb"),
    ("i-adjective", "I-adjective"),
    ("na-adjective", "Na-adjective"),
    ("genitive case particle", "No-adjective"),
    ("pre-noun adjectival", "Pre-noun adjectival"),
    ("pronoun", "Pronoun"),
    ("adverb", "Adverb"),
    ("noun", "Noun"),
    ("numeric", "Number"),
]


def short_parts_of_speech(names: list[str]) -> str:
    # ["Noun", "Suru verb", "Transitive verb"] -> "Noun, Suru verb,
    # Transitive". Anything not listed above keeps Jisho's own wording, up
    # to any bracketed romaji ("Expressions (phrases, clauses, etc.)").
    labels = []
    for name in names:
        lowered = name.lower()
        label = next((short for match, short in _PART_OF_SPEECH_NAMES if match in lowered), name.split(" (")[0])
        if label and label not in labels:
            labels.append(label)
    return ", ".join(labels)


def entry_part_of_speech(entry: dict) -> str:
    # From the first sense that has any (ありがとう's first sense has none).
    for sense in entry.get("senses") or []:
        if sense.get("parts_of_speech"):
            return short_parts_of_speech(sense["parts_of_speech"])
    return ""


def part_of_speech_for(front: str, reading: str = "") -> str:
    # For a card made before parts of speech: the Jisho entry written as
    # its front (or, for a kana word, read as it) and with its reading.
    for entry in jisho_results(front):
        for form in entry.get("japanese") or []:
            written, read = form.get("word"), form.get("reading")
            if (written == front and (not reading or read == reading)) or (not written and read == front)                     or (read == front and not reading):
                return entry_part_of_speech(entry)
    return ""


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
