# Spelling check for hand-typed cards. Run when a card is added: compares
# what was typed against Jisho (vocab) and KANJIDIC (kanji readings) and
# returns any mismatches -- likely typos -- each as {"field", "message",
# "fix"}, "fix" being the corrected value for that whole field (or None when
# there's no single obvious correction). An empty list means everything
# checked out; blanks are never flagged, since every reading is optional.
from prescripts.data.japanese.answers import display_readings, normalize_kana, split_readings, typed_as_kana
from prescripts.data.japanese.lookups import KANJI_PATTERN, jisho_results, kanji_lookup


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
    entries = jisho_results(front)
    forms = [form for entry in entries for form in entry.get("japanese", [])]
    if KANJI_PATTERN.search(front):
        known = list(dict.fromkeys(form["reading"] for form in forms if form.get("word") == front and form.get("reading")))
        if not known:
            return [{"field": "front", "message": f"Jisho has no word written {front}. A typo?", "fix": None}]
        if reading and typed_as_kana(reading) not in {normalize_kana(k) for k in known}:
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
            if typed_as_kana(typed.replace(".", "").replace("-", "")) in accepted:
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
