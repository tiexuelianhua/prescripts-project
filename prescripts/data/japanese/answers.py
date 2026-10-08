# Typed answers: a realkana-style review, where you type the answer and the
# app checks it. Vocab asks for the reading (kana, or romaji converted here)
# -- or the meaning, for kana-only words; kanji ask for the meaning and then
# each kind of reading (see answer_steps below).
import difflib
import re

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


# Words that don't change a meaning: "to study", "a friend", "be healthy".
FILLER_WORDS = {"to", "a", "an", "the", "be", "is", "are", "being"}


def _plain_meaning(text: str) -> str:
    # Lowercase, punctuation out, filler words dropped, so "Healthy." and
    # "be healthy" compare as the word.
    words = re.sub(r"[^\w\s]", " ", text.lower()).split()
    return " ".join(word for word in words if word not in FILLER_WORDS)


def meaning_parts(text: str) -> set[str]:
    # What a card accepts: "healthy; lively" -> {"healthy", "lively"}. Split
    # on the usual separators; a bracketed bit can be left out or kept
    # ("(things are) this way"); a bracketed list of alternatives counts on
    # its own, as does anything in quotes ('casual word for "yes" (yeah,
    # uh-huh)').
    parts = set()
    for segment in re.split(r"[;/]|,(?![^(]*\))", text):
        options = [re.sub(r"\(.*?\)", "", segment), segment]
        options += re.findall(r'"(.*?)"', segment)
        for inside in re.findall(r"\((.*?)\)", segment):
            if "," in inside:
                options += inside.split(",")
        parts.update(_plain_meaning(option) for option in options)
    parts.discard("")
    return parts


def typed_meaning_parts(typed: str) -> set[str]:
    # What was typed: several meanings can be listed with commas, semicolons,
    # slashes or "and" ("lively and healthy").
    parts = {_plain_meaning(part) for part in re.split(r"[,;/]|\band\b", typed)}
    parts.discard("")
    return parts


def meaning_close_enough(typed: str, accepted: set[str]) -> bool:
    # Exact after _plain_meaning, or a near miss on a longer word -- a typo
    # ("helthy"), a plural ("friends") or another form of it ("health",
    # "studying"). Short words have to match exactly: "big" and "bag" are
    # different answers.
    if typed in accepted:
        return True
    for option in accepted:
        if min(len(typed), len(option)) < 5:
            continue
        single_words = " " not in typed and " " not in option
        if single_words and (typed.startswith(option) or option.startswith(typed)):
            return True
        if difflib.SequenceMatcher(None, typed, option).ratio() >= 0.85:
            return True
    return False


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
    "form": "Put them together (kana or romaji)",
}


def answer_steps(card: dict) -> list[str]:
    # Every card asks for its meaning; readings come first where there are any.
    if card["kind"] == "vocab":
        return ["reading", "meaning"] if has_distinct_reading(card) else ["meaning"]
    if card["kind"] == "grammar":  # a point paired with a word: grammar.typed_prompt
        return ["form"]
    return ["meaning"] + [field for field in ("onyomi", "kunyomi") if split_readings(card.get(field, ""))]


def typed_as_kana(typed: str) -> str:
    if re.search(r"[a-zA-Z]", typed):
        typed = romaji_to_kana(typed)
    return normalize_kana(typed)


def check_step(card: dict, step: str, typed: str) -> bool:
    if not typed.strip():
        return False
    if step == "meaning":
        # Any of the card's meanings counts, loosely (see
        # meaning_close_enough); typing several ("study, learning") is fine
        # as long as each one is on the card.
        typed_parts = typed_meaning_parts(typed)
        accepted = meaning_parts(card["meaning"])
        return bool(typed_parts) and all(meaning_close_enough(part, accepted) for part in typed_parts)
    if step == "form" and typed.strip() == card["form_front"]:  # typed with an IME, kanji and all
        return True
    typed_kana = typed_as_kana(typed)
    if step == "form":
        return typed_kana == normalize_kana(card["form_reading"])
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
