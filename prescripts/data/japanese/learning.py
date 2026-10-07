# Learning mode: new cards are studied at their own pace (everything shown,
# nothing graded) before they join the reviews, and each card is linked to
# the rest of the deck -- a kanji to the vocab that uses it, with which of
# its readings each word uses (on'yomi or kun'yomi), and a word to its
# kanji. Readings stick through words already known, not through
# memorising lists.
from prescripts.data.japanese.answers import normalize_kana, split_readings
from prescripts.data.japanese.lookups import KANJI_PATTERN

# Shown beside a kanji in Learn. Rules of thumb, not rules: plenty of words
# break them (e.g. 場所 ばしょ is kun + on).
RULES_OF_THUMB = (
    "On'yomi (written in katakana) is usually the reading in words of two or more kanji, like 学校. "
    "Kun'yomi (hiragana) is usually the reading when the kanji stands alone or has kana after it, like 食べる."
)

# Sounds that change when a reading joins a word: the first one voiced
# (rendaku, か → が in 手紙 てがみ), or a final つ/く/ち/き cut short to っ
# before another kanji (学 がく → がっ in 学校).
_VOICED = dict(zip("かきくけこさしすせそたちつてとはひふへほ", "がぎぐげござじずぜぞだぢづでどばびぶべぼ"))
_HALF_VOICED = dict(zip("はひふへほ", "ぱぴぷぺぽ"))
_CUT_SHORT = set("つくちき")


def _variants(reading: str) -> list[tuple[str, bool]]:
    # Ways one reading can turn up in a word: (kana, changed). A kun'yomi's
    # okurigana (after the dot) and KANJIDIC's affix dashes are dropped.
    stem = normalize_kana(reading.split(".")[0].strip("-"))
    if not stem:
        return []
    variants = [(stem, False)]
    for table in (_VOICED, _HALF_VOICED):
        if stem[0] in table:
            variants.append((table[stem[0]] + stem[1:], True))
    if len(stem) > 1 and stem[-1] in _CUT_SHORT:
        variants += [(form[:-1] + "っ", True) for form, _ in list(variants)]
    return variants


def reading_in_word(kanji_card: dict, word: str, word_reading: str) -> dict | None:
    # Which of a kanji's readings a word uses: {"kind": "on"/"kun",
    # "reading", "sure"}, or None if none of them fit. Only a best guess:
    # "sure" is False when the reading had to change to fit, or when an
    # on'yomi and a kun'yomi both fit (the rules of thumb pick then).
    position = word.find(kanji_card["front"])
    reading = normalize_kana(word_reading or "")
    if position < 0 or not reading:
        return None
    candidates = []
    for kind, field in (("on", "onyomi"), ("kun", "kunyomi")):
        for listed in split_readings(kanji_card.get(field, "")):
            for form, changed in _variants(listed):
                if position == 0:
                    fits = reading.startswith(form)
                elif position == len(word) - 1:
                    fits = reading.endswith(form)
                else:
                    fits = form in reading[1:]
                if fits:
                    candidates.append({"kind": kind, "reading": listed, "length": len(form), "changed": changed})
    if not candidates:
        return None
    longest = max(candidate["length"] for candidate in candidates)
    best = [candidate for candidate in candidates if candidate["length"] == longest]
    kinds = {candidate["kind"] for candidate in best}
    if len(kinds) > 1:
        # Both fit: a word of kanji only, two or more, leans on'yomi.
        kanji_only = len(KANJI_PATTERN.findall(word)) == len(word) > 1
        choice = next(candidate for candidate in best if candidate["kind"] == ("on" if kanji_only else "kun"))
        return {"kind": choice["kind"], "reading": choice["reading"], "sure": False}
    choice = min(best, key=lambda candidate: candidate["changed"])
    return {"kind": choice["kind"], "reading": choice["reading"], "sure": not choice["changed"]}


def words_using(deck: dict, kanji_card: dict) -> list[dict]:
    # The deck's vocab written with this kanji, each with the reading it
    # uses there: {"card", "uses"} (uses as from reading_in_word).
    return [
        {"card": card, "uses": reading_in_word(kanji_card, card["front"], card["reading"] or card["front"])}
        for card in deck["cards"]
        if card["kind"] == "vocab" and kanji_card["front"] in card["front"]
    ]


def kanji_in(deck: dict, word_card: dict) -> list[dict]:
    # The deck's kanji cards for the kanji in a word, in the word's order.
    kanji_cards = {card["front"]: card for card in deck["cards"] if card["kind"] == "kanji"}
    return [kanji_cards[char] for char in dict.fromkeys(KANJI_PATTERN.findall(word_card["front"])) if char in kanji_cards]
