# The rules underneath the pages, tested directly rather than through the UI:
# flashcard scheduling, typed answers and the typo check, what counts toward
# a meal total, weather parsing, lyrics timing, the play history that fills
# Spotify's gaps and the guards on its controls, and which places the
# Activities page shows. Same setup
# as test_app.py -- each test runs in a temp copy of the code (conftest.py).
import sys

import pytest

from conftest import run_in


def _check(app_copy, code):
    result = run_in(app_copy, code)
    assert result.returncode == 0, result.stdout + result.stderr


def test_flashcard_schedule(app_copy):
    # Good: 1 day, then 3, then interval x ease. Again: back to today, ease
    # down (never below the floor), counted as a lapse. Easy is always at
    # least a day past Good.
    _check(app_copy, """
        from datetime import timedelta
        from prescripts.data.japanese.deck import (
            MINIMUM_EASE,
            add_card,
            load_deck,
            next_schedule,
            review_card,
            today_jst,
        )

        deck = load_deck()
        card = add_card(deck, "vocab", "勉強", "べんきょう", "study")
        today = today_jst()
        assert card["due"] == today.isoformat()  # new cards are due straight away

        for expected_interval in (1, 3, 8):  # 3 x 2.5 = 7.5, rounds to 8
            review_card(deck, card["id"], "good")
            assert card["interval"] == expected_interval, card
            assert card["due"] == (today + timedelta(days=expected_interval)).isoformat(), card
        assert card["reps"] == 3 and card["ease"] == 2.5

        review_card(deck, card["id"], "again")
        assert (card["interval"], card["reps"], card["lapses"], card["ease"]) == (0, 0, 1, 2.3), card
        assert card["due"] == today.isoformat()
        assert deck["reviews"][today.isoformat()] == 4

        assert next_schedule({"interval": 0, "ease": MINIMUM_EASE, "reps": 0}, "again") == (0, MINIMUM_EASE)
        hard, hard_ease = next_schedule({"interval": 0, "ease": 2.5, "reps": 0}, "hard")
        assert (hard, round(hard_ease, 2)) == (1, 2.35)
        for reps, interval in ((0, 0), (1, 1), (2, 3), (5, 40)):
            state = {"interval": interval, "ease": 2.5, "reps": reps}
            good, _ = next_schedule(state, "good")
            easy, easy_ease = next_schedule(state, "easy")
            assert easy > good and round(easy_ease, 2) == 2.65, (reps, good, easy)
    """)


def test_regrade_replaces_the_last_review(app_copy):
    # A typed answer marked wrong over a typo can be regraded: the "Again"
    # is undone, not stacked under the new grade.
    _check(app_copy, """
        from prescripts.data.japanese.deck import add_card, load_deck, regrade, review_card, today_jst

        deck = load_deck()
        card = add_card(deck, "kanji", "学", "", "study", onyomi="ガク", kunyomi="まな.ぶ")
        snapshot = dict(card)
        review_card(deck, card["id"], "again")
        regrade(deck, snapshot, "good")
        card = deck["cards"][0]
        assert (card["interval"], card["reps"], card["lapses"]) == (1, 1, 0), card
        assert deck["reviews"][today_jst().isoformat()] == 1
    """)


def test_due_card_order(app_copy):
    # Overdue first, then never-reviewed, then cards missed earlier today.
    # Shuffling keeps the misses at the back and is stable for one seed.
    _check(app_copy, """
        from datetime import timedelta
        from prescripts.data.japanese.deck import due_cards, today_jst

        today = today_jst()
        def card(front, due, last_reviewed=None):
            return {"id": front, "kind": "vocab", "front": front, "due": due.isoformat(), "last_reviewed": last_reviewed}

        deck = {"cards": [
            card("missed", today, f"{today.isoformat()}T09:00:00+09:00"),
            card("tomorrow", today + timedelta(days=1)),
            card("new", today),
            card("overdue", today - timedelta(days=2), "2026-01-01T09:00:00+09:00"),
        ]}
        assert [c["front"] for c in due_cards(deck)] == ["overdue", "new", "missed"]
        assert due_cards(deck, ["kanji"]) == []

        shuffled = [c["front"] for c in due_cards(deck, shuffle_seed="abc")]
        assert shuffled[-1] == "missed" and sorted(shuffled) == ["missed", "new", "overdue"], shuffled
        assert [c["front"] for c in due_cards(deck, shuffle_seed="abc")] == shuffled
    """)


def test_romaji_and_kana(app_copy):
    _check(app_copy, """
        from prescripts.data.japanese.answers import normalize_kana, romaji_to_kana

        cases = {
            "konnichiha": "こんにちは",   # nn before a vowel: the second n starts the next syllable
            "konnnichiha": "こんにちは",  # the IME's spelling works too
            "shinnen": "しんねん",
            "onna": "おんな",
            "kitte": "きって",            # doubled consonant -> small tsu
            "kyou": "きょう",
            "sensei": "せんせい",         # lone n before a consonant
            "hon": "ほん",                # lone n at the end
            "Tokyo": "ときょ",            # case doesn't matter
            "ko-hi-": "こーひー",
        }
        for romaji, kana in cases.items():
            assert romaji_to_kana(romaji) == kana, (romaji, romaji_to_kana(romaji))

        # Katakana, spaces and long-vowel marks all compare equal.
        assert normalize_kana("コーヒー") == normalize_kana("こおひい") == normalize_kana(romaji_to_kana("ko-hi-"))
        assert normalize_kana("ガク　セイ") == "がくせい"
    """)


def test_typed_answers(app_copy):
    _check(app_copy, """
        from prescripts.data.japanese.answers import answer_steps, check_step

        vocab = {"kind": "vocab", "front": "勉強", "reading": "べんきょう", "meaning": "to study; diligence (work)"}
        assert answer_steps(vocab) == ["reading", "meaning"]
        assert check_step(vocab, "reading", "benkyou")
        assert check_step(vocab, "reading", "ベンキョウ")
        assert not check_step(vocab, "reading", "benkyo")
        assert check_step(vocab, "meaning", "Study")
        assert check_step(vocab, "meaning", "study, diligence")
        assert not check_step(vocab, "meaning", "study, school")  # every part typed has to be on the card
        assert not check_step(vocab, "meaning", "   ")
        assert check_step(vocab, "meaning", "studying?")  # other forms of the word
        assert not check_step(vocab, "meaning", "work")    # a bracketed note isn't a meaning on its own

        # Near enough counts: punctuation, filler words, typos, "and" lists.
        genki = {"kind": "vocab", "front": "元気", "reading": "げんき", "meaning": "healthy; lively"}
        for typed in ("Healthy.", "be healthy", "health", "helthy", "lively and healthy"):
            assert check_step(genki, "meaning", typed), typed
        assert not check_step(genki, "meaning", "happy")
        assert not check_step({"kind": "vocab", "meaning": "big"}, "meaning", "bag")  # short words stay exact

        # Quoted and bracketed alternatives count; a qualifier can be kept or left out.
        un = {"kind": "vocab", "meaning": 'casual word for "yes" (yeah, uh-huh)'}
        assert all(check_step(un, "meaning", typed) for typed in ("yes", "yeah", "uh-huh"))
        assert not check_step(un, "meaning", "no")
        kou = {"kind": "vocab", "meaning": "(things are) this way"}
        assert check_step(kou, "meaning", "this way") and check_step(kou, "meaning", "things are this way")
        assert not check_step(kou, "meaning", "that way")

        kana_only = {"kind": "vocab", "front": "これ", "reading": "これ", "meaning": "this"}
        assert answer_steps(kana_only) == ["meaning"]

        kanji = {"kind": "kanji", "front": "学", "reading": "", "meaning": "study, learning",
                 "onyomi": "ガク", "kunyomi": "まな.ぶ"}
        assert answer_steps(kanji) == ["meaning", "onyomi", "kunyomi"]
        assert check_step(kanji, "onyomi", "gaku")
        assert check_step(kanji, "kunyomi", "manabu")  # whole word
        assert check_step(kanji, "kunyomi", "まな")     # or just the stem
        assert not check_step(kanji, "kunyomi", "gaku")

        no_kunyomi = dict(kanji, kunyomi="")
        assert answer_steps(no_kunyomi) == ["meaning", "onyomi"]
    """)


def test_grammar_points(app_copy):
    # A grammar point is reviewed with a word from the deck that it fits,
    # picked by part of speech, and makes the conjugated form from it. The
    # starter set adds only what isn't there yet.
    _check(app_copy, """
        from prescripts.data.japanese.deck import add_card, in_practice_set, load_deck, today_jst
        from prescripts.data.japanese.grammar import (
            STARTER_POINTS,
            add_grammar_point,
            add_starter_points,
            conjugate,
            pick_word,
            word_types,
        )

        assert word_types({"kind": "vocab", "pos": "Noun, No-adjective, Na-adjective"}) == {"noun", "na-adjective"}
        assert word_types({"kind": "vocab", "pos": "Station"}) == {"noun"}
        assert word_types({"kind": "vocab", "pos": "Pronoun"}) == {"noun"}
        assert word_types({"kind": "vocab", "pos": "Ichidan verb, Transitive"}) == set()
        assert word_types({"kind": "vocab", "pos": ""}) == set()
        assert word_types({"kind": "kanji", "pos": ""}) == set()

        deck = load_deck()
        eat = add_card(deck, "vocab", "食べる", "たべる", "to eat", pos="Ichidan verb")
        quiet = add_card(deck, "vocab", "静か", "しずか", "quiet", pos="Na-adjective")
        there = add_card(deck, "vocab", "そこ", "", "there", pos="Pronoun")
        new_word = add_card(deck, "vocab", "学校", "がっこう", "school", pos="Noun", learning=True)

        point = add_grammar_point(deck, "じゃなかった", "wasn't (casual)", ["noun", "na-adjective"])
        assert point["kind"] == "grammar" and point["front"] == "じゃなかった" and point["base"] == "word", point
        assert conjugate(point, quiet) == {"front": "静かじゃなかった", "reading": "しずかじゃなかった"}
        assert conjugate(point, there) == {"front": "そこじゃなかった", "reading": "そこじゃなかった"}

        # Only words it fits, never verbs; the same seed gives the same word;
        # words still in Learn only when nothing else fits.
        picks = {pick_word(deck, point, f"seed {n}")["front"] for n in range(40)}
        assert picks == {"静か", "そこ"}, picks
        assert pick_word(deck, point, "a")["id"] == pick_word(deck, point, "a")["id"]
        adjective_only = add_grammar_point(deck, "な", "(before a noun)", ["na-adjective"])
        assert {pick_word(deck, adjective_only, f"seed {n}")["front"] for n in range(20)} == {"静か"}
        deck["cards"] = [card for card in deck["cards"] if card["id"] not in (quiet["id"], there["id"])]
        assert pick_word(deck, point, "b")["front"] == "学校"
        assert pick_word(deck, adjective_only, "c") is None
        assert eat in deck["cards"]

        # Part-of-speech practice sets are for words, not grammar points.
        assert not in_practice_set(point, "Nouns", set(), today_jst())
        assert in_practice_set(point, "Every card", set(), today_jst())

        assert add_starter_points(deck) == len(STARTER_POINTS) - 1  # じゃなかった is already there
        assert add_starter_points(deck) == 0
        fronts = [card["front"] for card in deck["cards"] if card["kind"] == "grammar"]
        assert len(fronts) == len(set(fronts)), fronts
        assert {"だ", "です", "じゃない", "だった", "でした"} <= set(fronts), fronts
    """)


def test_typo_check_when_adding_a_card(app_copy):
    # Jisho and kanjiapi are faked, so this runs offline and doesn't depend on
    # what either site returns today.
    _check(app_copy, """
        import prescripts.data.japanese.spelling as spelling
        from prescripts.data.japanese.spelling import check_new_card

        jisho = {
            "勉強": [{"japanese": [{"word": "勉強", "reading": "べんきょう"}]}],
            "ありがとお": [{"japanese": [{"reading": "ありがとう"}]}, {"japanese": [{"reading": "ありがと"}]}],
            "これ": [{"japanese": [{"word": "此れ", "reading": "これ"}]}],
        }
        spelling.jisho_results = lambda query: jisho.get(query, [])
        spelling.kanji_lookup = lambda query: [{"front": "学", "meaning": "study", "on": "ガク", "kun": "まな.ぶ"}]

        assert check_new_card("vocab", "勉強", "benkyou", "", "") == []
        assert check_new_card("vocab", "勉強", "", "", "") == []  # blanks are never flagged
        [issue] = check_new_card("vocab", "勉強", "benkyo", "", "")
        assert (issue["field"], issue["fix"]) == ("reading", "べんきょう"), issue
        [issue] = check_new_card("vocab", "勉教", "", "", "")
        assert issue["field"] == "front" and issue["fix"] is None, issue

        # Kana-only: the word itself is checked, and ties go to Jisho's first result.
        assert check_new_card("vocab", "これ", "", "", "") == []
        [issue] = check_new_card("vocab", "ありがとお", "", "", "")
        assert issue["fix"] == "ありがとう", issue

        assert check_new_card("kanji", "学", "", "gaku", "manabu") == []
        assert check_new_card("kanji", "学", "", "", "まな") == []  # stem alone is fine
        [issue] = check_new_card("kanji", "学", "", "gyaku", "")
        assert (issue["field"], issue["fix"]) == ("onyomi", "ガク"), issue
    """)


def test_parts_of_speech(app_copy):
    # Jisho's names are shortened for a card, and an older card finds its
    # entry by what's written on it (kana words by their reading). Jisho is
    # faked, with its real answers for these words on 2026-10-07.
    _check(app_copy, """
        import prescripts.data.japanese.lookups as lookups
        from prescripts.data.japanese.lookups import part_of_speech_for, short_parts_of_speech

        assert short_parts_of_speech(["Noun", "Suru verb", "Transitive verb"]) == "Noun, Suru verb, Transitive"
        assert short_parts_of_speech(["Godan verb with 'ku' ending", "Transitive verb"]) == "Godan verb, Transitive"
        assert short_parts_of_speech(["Kuru verb - special class", "Intransitive verb"]) == "Irregular verb, Intransitive"
        assert short_parts_of_speech(["Suru verb - included"]) == "Irregular verb"
        assert short_parts_of_speech(["Na-adjective (keiyodoshi)", "Noun"]) == "Na-adjective, Noun"
        assert short_parts_of_speech(["Pre-noun adjectival (rentaishi)"]) == "Pre-noun adjectival"
        assert short_parts_of_speech(["Pronoun"]) == "Pronoun"
        assert short_parts_of_speech(["Noun", "Noun which may take the genitive case particle 'no'"]) == "Noun, No-adjective"
        assert short_parts_of_speech(["Expressions (phrases, clauses, etc.)"]) == "Expressions"
        assert short_parts_of_speech(["Wikipedia definition"]) == ""

        jisho = {
            "食べる": [{"japanese": [{"word": "食べる", "reading": "たべる"}],
                        "senses": [{"parts_of_speech": ["Ichidan verb", "Transitive verb"]}]}],
            "とても": [{"japanese": [{"word": "迚も", "reading": "とても"}],
                        "senses": [{"parts_of_speech": ["Adverb (fukushi)"]}]}],
            "ありがとう": [{"japanese": [{"word": "有難う", "reading": "ありがとう"}],
                          "senses": [{"parts_of_speech": []}, {"parts_of_speech": ["Interjection (kandoushi)"]}]}],
            "上手": [{"japanese": [{"word": "上手", "reading": "うわて"}], "senses": [{"parts_of_speech": ["Noun"]}]},
                     {"japanese": [{"word": "上手", "reading": "じょうず"}],
                      "senses": [{"parts_of_speech": ["Na-adjective (keiyodoshi)"]}]}],
        }
        lookups.jisho_results = lambda query: jisho.get(query, [])
        assert part_of_speech_for("食べる", "たべる") == "Ichidan verb, Transitive"
        assert part_of_speech_for("とても") == "Adverb"  # a kana word, written in kanji on Jisho
        assert part_of_speech_for("ありがとう") == "Interjection"  # its first sense has none
        assert part_of_speech_for("上手", "じょうず") == "Na-adjective"  # the entry with the card's reading
        assert part_of_speech_for("知らない言葉") == ""
    """)


def test_which_reading_a_word_uses(app_copy):
    # A kanji's reading in a word: on or kun, and whether that's a sure
    # thing or a best guess (the reading changed to fit, or both kinds fit).
    _check(app_copy, """
        from prescripts.data.japanese.learning import kanji_in, reading_in_word, words_using

        eat = {"front": "食", "onyomi": "ショク、ジキ", "kunyomi": "く.う、た.べる"}
        study = {"front": "学", "onyomi": "ガク", "kunyomi": "まな.ぶ"}
        school = {"front": "校", "onyomi": "コウ", "kunyomi": ""}
        hand = {"front": "手", "onyomi": "シュ", "kunyomi": "て、-て、て-"}
        paper = {"front": "紙", "onyomi": "シ", "kunyomi": "かみ"}

        def uses(kanji, word, reading):
            found = reading_in_word(kanji, word, reading)
            return found and (found["kind"], found["reading"], found["sure"])

        assert uses(eat, "食べる", "たべる") == ("kun", "た.べる", True)
        assert uses(eat, "食事", "しょくじ") == ("on", "ショク", True)
        assert uses(study, "学校", "がっこう") == ("on", "ガク", False)  # がく cut short to がっ
        assert uses(school, "学校", "がっこう") == ("on", "コウ", True)
        assert uses(paper, "手紙", "てがみ") == ("kun", "かみ", False)  # か voiced to が
        assert uses(hand, "手紙", "てがみ") == ("kun", "て", True)
        assert uses(study, "学生", "") is None  # no reading to go on
        assert uses(school, "食べる", "たべる") is None  # not in the word

        deck = {"cards": [
            {"kind": "vocab", "front": "食べる", "reading": "たべる"},
            {"kind": "vocab", "front": "学校", "reading": "がっこう"},
            {"kind": "kanji", "front": "学", "onyomi": "ガク", "kunyomi": "まな.ぶ"},
            {"kind": "kanji", "front": "校", "onyomi": "コウ", "kunyomi": ""},
        ]}
        assert [use["card"]["front"] for use in words_using(deck, study)] == ["学校"]
        assert [card["front"] for card in kanji_in(deck, deck["cards"][1])] == ["学", "校"]
    """)


def test_weather_parsing(app_copy):
    # JMA's feeds are faked with the fields the page reads. Only today's rain
    # chances count, and a live reading JMA flags as unreliable is left out.
    _check(app_copy, """
        from datetime import datetime, timedelta
        import prescripts.data.weather as weather
        from prescripts.common import JST

        today = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)
        forecast = [{"timeSeries": [
            {"areas": [{"weatherCodes": ["201", "300"]}]},
            {"timeDefines": [(today + timedelta(hours=h)).isoformat() for h in (12, 18)] + [tomorrow.isoformat()],
             "areas": [{"pops": ["30", "", "90"]}]},
            {"areas": [{"area": {"code": "44132"}}]},
        ]}]
        stations = {"44132": {"temp": [21.4, 0], "precipitation1h": [0.5, 1]}}

        def fake_fetch_json(url):
            if "forecast" in url:
                return forecast
            if "amedas/data/map/20260928113000" in url:
                return stations
            if "warning" in url:
                return {"headlineText": "  "}
            raise AssertionError(url)

        weather._fetch_json = fake_fetch_json
        weather._fetch_text = lambda url: "2026-09-28T11:30:00+09:00"

        now = weather.today_conditions("130000")
        assert now == {"weather_code": "201", "pop": 30, "temp": 21.4, "precip_last_hour": None,
                       "live_fetch_failed": False}, now
        assert weather.key_events_headline("130000") is None  # blank headline = no warnings

        assert weather.format_condition("RAIN,CLOUDY LATER") == "Rain, cloudy later"
        assert weather.CATEGORY_EMOJI[now["weather_code"][0] + "00"] == "☁️"
    """)


def test_quote_credit(app_copy):
    # The Home corner credit. Typed-in text is escaped, since it goes into HTML.
    _check(app_copy, """
        from prescripts.data.home import quote_credit

        assert quote_credit({"line": "Just a line"}) == ""
        assert quote_credit({"source": "Hero", "by": "Mili"}) == 'This line is from "Hero" by Mili.'
        assert quote_credit({"by": "Someone", "note": "paraphrased"}) == "This line is from a work by Someone (paraphrased)."
        assert quote_credit({"source": "<b>Tom & Jerry</b>"}) == 'This line is from "&lt;b&gt;Tom &amp; Jerry&lt;/b&gt;".'
        assert quote_credit({"source": "<i>Hero</i>"}, escape=False) == 'This line is from "<i>Hero</i>".'
    """)


def test_excluded_entries_never_count(app_copy):
    # Excluded rows drop out of every total, a note alone doesn't exclude a
    # row, and a receipts.csv from before the excluded column existed still
    # reads.
    _check(app_copy, """
        from datetime import date
        import pandas as pd
        from prescripts.data.meal_receipts import (
            append_entry, counted_total, day_folder_for, load_entries, week_bounds, week_total_so_far,
            with_default_columns,
        )

        rows = pd.DataFrame({
            "timestamp": ["2026-09-07 12:00:00"] * 4,
            "store": ["Lawson"] * 4,
            "item": ["Onigiri"] * 4,
            "cost_yen": [100, 200, 300, 400],
            "excluded": [False, True, None, None],  # None = a row added with the table's "+"
            "excluded_reason": [None, None, "Paid with cash", "  "],
        })
        normalized = with_default_columns(rows)
        assert list(normalized["excluded"]) == [False, True, False, False]  # a note is just a note
        assert list(normalized["excluded_reason"].fillna("-")) == ["-", "-", "Paid with cash", "-"]  # blank = no reason
        assert counted_total(rows) == 800
        assert counted_total(pd.DataFrame()) == 0

        old_day = day_folder_for(date(2026, 9, 8))
        old_day.mkdir(parents=True)
        (old_day / "receipts.csv").write_text(
            "timestamp,store,item,cost_yen\\n2026-09-08 12:00:00,Lawson,Onigiri,150\\n", encoding="utf-8"
        )
        assert counted_total(load_entries(old_day / "receipts.csv")) == 150
        append_entry(old_day / "receipts.csv", "2026-09-08 19:00:00", "Sukiya", "Gyudon", 600, excluded=True)
        assert list(load_entries(old_day / "receipts.csv")["cost_yen"]) == [150, 600]

        # Thursday 10 Sep: its week is Mon 7 - Sun 13, summed up to the 10th.
        assert week_bounds(date(2026, 9, 10)) == (date(2026, 9, 7), date(2026, 9, 13))
        def log(day, yen, **kw):
            folder = day_folder_for(day)
            folder.mkdir(parents=True, exist_ok=True)
            append_entry(folder / "receipts.csv", f"{day} 12:00:00", "Lawson", "Onigiri", yen, **kw)
        log(date(2026, 9, 6), 999)  # the Sunday before
        log(date(2026, 9, 7), 100)
        log(date(2026, 9, 10), 300)
        log(date(2026, 9, 10), 5000, excluded=True, excluded_reason="Covered by friend/coworker")
        log(date(2026, 9, 11), 400)  # after "today"
        assert week_total_so_far(date(2026, 9, 10)) == 100 + 150 + 300
    """)


def test_editing_a_date_moves_the_entry(app_copy):
    # The 2026-09-19 bug: a row whose date was edited stayed in the old
    # day's file. It now moves into the new day's, in time order.
    _check(app_copy, """
        from datetime import date
        import pandas as pd
        from prescripts.data.meal_receipts import append_entry, day_folder_for, load_entries, relocate_edited_entries

        target = day_folder_for(date(2026, 8, 2))
        target.mkdir(parents=True)
        append_entry(target / "receipts.csv", "2026-08-02 18:00:00", "FamilyMart", "Karaage", 250)

        viewed = pd.DataFrame({
            "timestamp": ["2026-08-01 12:00:00", "2026-08-02 09:00:00"],
            "store": ["Lawson", "7-Eleven"],
            "item": ["Onigiri", "Coffee"],
            "cost_yen": [150, 120],
        })
        kept = relocate_edited_entries(viewed, date(2026, 8, 1))
        assert list(kept["item"]) == ["Onigiri"]
        assert list(load_entries(target / "receipts.csv")["item"]) == ["Coffee", "Karaage"]
    """)


def test_budget_settings(app_copy):
    _check(app_copy, """
        from prescripts.data.meal_receipts import allowance_for_days, budget_settings

        assert budget_settings({}) == (0, "daily")
        assert budget_settings({"daily_budget": 1200}) == (1200, "daily")  # pre-2026-09-21 settings.json
        assert budget_settings({"daily_budget": 1200, "budget_amount": 7000, "budget_period": "weekly"}) == (7000, "weekly")
        assert allowance_for_days(1000, "daily", 30) == 30000
        assert allowance_for_days(7000, "weekly", 3) == 3000
    """)


def test_budget_carry_over(app_copy):
    # Leftovers and overspends add up from the day carry-over was switched
    # on (a day with nothing logged is ¥0 spent), and only for daily budgets.
    _check(app_copy, """
        from datetime import date
        from prescripts.data.meal_receipts import append_entry, carried_over, day_folder_for

        def log(day, yen, **kw):
            folder = day_folder_for(day)
            folder.mkdir(parents=True, exist_ok=True)
            append_entry(folder / "receipts.csv", f"{day} 12:00:00", "Lawson", "Onigiri", yen, **kw)
        log(date(2026, 9, 1), 5000)  # before carry-over was on: doesn't count
        log(date(2026, 9, 10), 800)   # 200 under
        log(date(2026, 9, 11), 1500)  # 500 over
        log(date(2026, 9, 11), 9000, excluded=True)
        log(date(2026, 9, 13), 99999)  # today's own spending isn't carried yet

        settings = {"budget_amount": 1000, "budget_period": "daily", "carry_over": True,
                    "carry_over_since": "2026-09-10"}
        today = date(2026, 9, 13)
        assert carried_over(settings, today) == 200 - 500 + 1000  # the 12th: nothing logged
        assert carried_over(dict(settings, carry_over=False), today) == 0
        assert carried_over(dict(settings, budget_period="weekly"), today) == 0
        assert carried_over(dict(settings, carry_over_since="2026-09-13"), today) == 0  # just started fresh

        # Today's budget set by hand is exactly that, whatever the daily
        # amount, and the next day carries on from what's left of it.
        set_today = dict(settings, carry_over_since="2026-09-10", carry_over_set=2000)
        assert 1000 + carried_over(set_today, date(2026, 9, 10)) == 2000
        assert 1500 + carried_over(dict(set_today, budget_amount=1500), date(2026, 9, 10)) == 2000
        assert 1000 + carried_over(set_today, date(2026, 9, 11)) == 1000 + (2000 - 800)
    """)


def test_spending_categories(app_copy):
    # Rows from before categories count as Food. Totals split by category,
    # suggestions follow one, and the budget and its carry-over only count
    # its own category. Renaming Food reaches the old rows and the budget.
    _check(app_copy, """
        from datetime import date
        from prescripts.data.meal_receipts import (
            append_entry, budget_category, carried_over, categories, counted_total, day_folder_for, known_values,
            load_entries, rename_value, totals_by_category, week_total_so_far,
        )

        old_day = day_folder_for(date(2026, 9, 8))
        old_day.mkdir(parents=True)
        (old_day / "receipts.csv").write_text(
            "timestamp,store,item,cost_yen\\n2026-09-08 12:00:00,Lawson,Onigiri,150\\n", encoding="utf-8"
        )
        old = load_entries(old_day / "receipts.csv")
        assert list(old["category"]) == ["Food"], old

        day = day_folder_for(date(2026, 9, 9))
        day.mkdir(parents=True)
        csv = day / "receipts.csv"
        append_entry(csv, "2026-09-09 08:00:00", "Lawson", "Onigiri", 200)
        append_entry(csv, "2026-09-09 09:00:00", "JR East", "Suica top-up", 3000, category="Transport")
        append_entry(csv, "2026-09-09 18:00:00", "Uniqlo", "T-shirt", 1500, category="Shopping")
        append_entry(csv, "2026-09-09 19:00:00", "JR East", "Suica top-up", 1000, category="Transport", excluded=True)
        entries = load_entries(csv)
        assert counted_total(entries) == 4700
        assert counted_total(entries, "Transport") == 3000
        assert totals_by_category(entries) == {"Transport": 3000, "Shopping": 1500, "Food": 200}
        assert known_values("store", category="Transport") == ["JR East"]
        assert known_values("item", category="Food") == ["Onigiri"]
        assert week_total_so_far(date(2026, 9, 9), "Food") == 350  # Mon 7th to the 9th

        settings = {"budget_amount": 1000, "budget_period": "daily", "carry_over": True,
                    "carry_over_since": "2026-09-08"}
        assert carried_over(settings, date(2026, 9, 10)) == (1000 - 150) + (1000 - 200)

        assert categories({}) == ["Food", "Transport", "Shopping", "Other"]
        append_entry(csv, "2026-09-09 20:00:00", None, "Gift", 500, category="Presents")
        assert categories({}) == ["Food", "Transport", "Shopping", "Other", "Presents"]

        assert rename_value("category", "Food", "Meals") == 2  # the old row too
        assert set(load_entries(old_day / "receipts.csv")["category"]) == {"Meals"}
        assert budget_category({}) == "Food" and budget_category({"budget_category": "Meals"}) == "Meals"
    """)


def test_budget_per_category(app_copy):
    # Food's budget is read from the old top-level settings until it's next
    # saved; each category has its own amount, period and carry-over; and a
    # transport receipt's stations go in and out of its store column.
    _check(app_copy, """
        from datetime import date
        from prescripts.data.meal_receipts import (
            append_entry, budget_for, budget_status, carried_over, day_folder_for, route, save_budget, split_route,
        )

        old = {"budget_amount": 1000, "budget_period": "daily", "carry_over": True, "carry_over_since": "2026-09-07"}
        assert budget_for(old, "Food") == {"amount": 1000, "period": "daily", "carry_over": True,
                                           "carry_over_since": "2026-09-07"}
        assert budget_for(old, "Transport") == {"amount": 0, "period": "daily", "carry_over": False}
        settings = dict(old)
        save_budget(settings, "Food", budget_for(settings, "Food"))
        assert "budget_amount" not in settings and settings["budgets"]["Food"]["amount"] == 1000
        save_budget(settings, "Transport", {"amount": 6000, "period": "weekly", "carry_over": False})
        save_budget(settings, "Shopping", {"amount": 10000, "period": "monthly", "carry_over": False})
        save_budget(settings, "Other", {"amount": 500, "period": "daily", "carry_over": True,
                                        "carry_over_since": "2026-09-08"})

        def log(day, item, yen, category="Food"):
            folder = day_folder_for(day)
            folder.mkdir(parents=True, exist_ok=True)
            append_entry(folder / "receipts.csv", f"{day} 12:00:00", None, item, yen, category=category)
        log(date(2026, 9, 1), "T-shirt", 2000, "Shopping")
        log(date(2026, 9, 7), "Onigiri", 800)
        log(date(2026, 9, 8), "Suica top-up", 3000, "Transport")
        log(date(2026, 9, 9), "Onigiri", 300)
        log(date(2026, 9, 9), "Socks", 700, "Shopping")
        log(date(2026, 9, 9), "Stamps", 100, "Other")

        today = date(2026, 9, 9)  # a Wednesday
        # Food carries its own leftovers (200 + 1,000 on the 8th), not Transport's spending.
        assert carried_over(settings, today) == carried_over(settings, today, "Food") == 1200
        assert carried_over(settings, today, "Other") == 500
        status = {line["category"]: line for line in budget_status(settings, today, today)}
        assert [status[name]["period"] for name in ("Food", "Transport", "Shopping", "Other")] == [
            "daily", "weekly", "monthly", "daily"]
        assert (status["Food"]["spent"], status["Food"]["budget"], status["Food"]["carried"]) == (300, 2200, 1200)
        assert (status["Transport"]["spent"], status["Transport"]["budget"]) == (3000, 6000)  # Mon 7th to the 9th
        assert (status["Shopping"]["spent"], status["Shopping"]["budget"]) == (2700, 10000)
        # Another day: the plain amount, nothing carried.
        past = {line["category"]: line for line in budget_status(settings, date(2026, 9, 7), today)}
        assert (past["Food"]["spent"], past["Food"]["budget"], past["Food"]["carried"]) == (800, 1000, 0)

        assert route("Shinjuku", "Shibuya") == "Shinjuku → Shibuya"
        assert route(" ", "Shibuya") == "Shibuya" and route(None, None) is None
        assert split_route("Shinjuku → Shibuya") == ("Shinjuku", "Shibuya")
        assert split_route("Shinjuku") == ("Shinjuku", None) and split_route(float("nan")) == (None, None)
    """)


def test_area_japanese_name(app_copy):
    # An area saved before Japanese names were kept is looked up once: the
    # match nearest where it was saved, and the answer (even none) is kept.
    _check(app_copy, """
        import prescripts.data.activities as activities

        calls = []
        def fake_find_area(query):
            calls.append(query)
            return [{"name": "Asakusa, Hokkaido", "name_ja": "浅草（北海道）", "lat": 43.0, "lon": 141.0},
                    {"name": "Asakusa, Taito", "name_ja": "浅草", "lat": 35.7120, "lon": 139.7960}]
        activities.find_area = fake_find_area

        settings = {"area": "Asakusa", "lat": 35.7118, "lon": 139.7966, "radius": 1000}
        assert activities.area_name_ja(settings) == "浅草"
        assert activities.load_settings()["area_ja"] == "浅草"
        assert activities.area_name_ja(settings) == "浅草" and calls == ["Asakusa"]  # not looked up again

        far = {"area": "Nowhere", "lat": 26.2, "lon": 127.7}
        assert activities.area_name_ja(far) == "" and far["area_ja"] == ""
        assert activities.area_name_ja({}) == ""
    """)


def test_english_only(app_copy):
    # English only (Settings) shows a name in English where there is one,
    # says when one's left in Japanese, and writes months out in English.
    # The public look starts with it on; the author's copy never has it.
    _check(app_copy, """
        from datetime import date
        from prescripts.common import english_only, has_japanese, place_name
        from prescripts.data.meal_receipts import append_entry, day_folder_for, monthly_history

        assert english_only({}) and not english_only({"english_only": False})
        assert place_name("浅草寺", "Senso-ji", english=False) == ("浅草寺 · Senso-ji", False)
        assert place_name("浅草寺", "Senso-ji", english=True) == ("Senso-ji", False)
        assert place_name("コミックマーケット", "", english=True) == ("コミックマーケット", True)
        assert place_name("Blue Note Tokyo", "", english=True) == ("Blue Note Tokyo", False)
        assert has_japanese("ラーメン") and not has_japanese("Ramen") and not has_japanese(None)

        for day in (date(2026, 8, 3), date(2026, 9, 3)):
            folder = day_folder_for(day)
            folder.mkdir(parents=True)
            append_entry(folder / "receipts.csv", f"{day} 12:00:00", None, "Onigiri", 150)
        today = date(2026, 9, 10)
        assert list(monthly_history(today, english=True)["month"]) == ["Aug 2026", "Sep 2026 (so far)"]
        assert list(monthly_history(today)["month"]) == ["2026年8月", "2026年9月 (so far)"]
    """)


def test_meals_group_rows(app_copy):
    # Rows logged together (same time and store) are one meal, in the order
    # logged, a blank store included; excluded rows don't count in its total.
    _check(app_copy, """
        import pandas as pd
        from prescripts.data.meal_receipts import meals

        entries = pd.DataFrame({
            "timestamp": ["2026-09-30 08:00:00", "2026-09-30 08:00:00", "2026-09-30 12:30:00", "2026-09-30 12:30:00"],
            "store": ["Lawson", "Lawson", None, None],
            "item": ["Onigiri", "Tax", "Ramen", "Beer"],
            "cost_yen": [150, 12, 900, 500],
            "excluded": [False, False, False, True],
        })
        found = meals(entries)
        assert [(meal["time"][11:16], meal["store"], meal["total"], len(meal["rows"])) for meal in found] == [
            ("08:00", "Lawson", 162, 2), ("12:30", "", 900, 2)], found
        assert meals(entries.iloc[0:0]) == []
    """)


def test_synced_lyrics(app_copy):
    _check(app_copy, """
        from prescripts.data.lyrics import current_line_index, parse_synced

        lines = parse_synced("[00:12.00][00:45.50] chorus\\n[00:30.00] verse\\nno timestamp here\\n")
        assert lines == [(12000, "chorus"), (30000, "verse"), (45500, "chorus")], lines
        assert parse_synced(None) == []
        assert current_line_index(lines, 5000) is None  # before the first line
        assert current_line_index(lines, 12000) == 0
        assert current_line_index(lines, 44999) == 1
        assert current_line_index(lines, 999999) == 2
    """)


def test_play_history_fills_spotify_gaps(app_copy):
    # A play the app watched is added to Spotify's list unless Spotify already
    # has it (same track, end times close). Stopping early shows where.
    _check(app_copy, """
        import prescripts.data.play_history as play_history
        from prescripts.data.play_history import _iso, merge_with_api, record_observation

        def seen(uri, name, at, progress_s, duration_s=200):
            record_observation({"fetched_at": at, "progress_ms": progress_s * 1000, "item": {
                "uri": uri, "name": name, "type": "track", "duration_ms": duration_s * 1000,
                "artists": [{"name": "Mili"}],
            }})

        def api_item(uri, ended_at):
            return {"track": {"uri": uri, "name": uri, "artists": [], "type": "track"}, "played_at": _iso(ended_at)}

        start = 1_790_000_000
        seen("spotify:track:A", "A", start, 50)
        seen("spotify:track:A", "A", start + 5, 55)
        seen("spotify:track:B", "B", start + 10, 0)   # A ends: skipped at 0:55
        seen("spotify:track:B", "B", start + 12, 2)
        seen("spotify:track:B", "B", start + 14, 180)
        seen("spotify:track:B", "B", start + 16, 1)   # jumped back: a replay, so B's first play ends
        seen("spotify:track:C", "C", start + 100, 30)  # 84s since B was seen: that play is dropped

        plays = play_history._load()
        assert [(p["name"], p["listened_s"]) for p in plays] == [("A", 55), ("B", 180)], plays

        merged = merge_with_api([api_item("spotify:track:X", start - 60)])
        assert [m["track"]["uri"] for m in merged] == ["spotify:track:B", "spotify:track:A", "spotify:track:X"]
        assert [m.get("skipped_at") for m in merged] == ["3:00", "0:55", None]

        # Spotify listing A itself (ended a few seconds later than we saw) -> not doubled.
        merged = merge_with_api([api_item("spotify:track:A", start + 9), api_item("spotify:track:X", start - 60)])
        assert [m["track"]["uri"] for m in merged] == ["spotify:track:B", "spotify:track:A", "spotify:track:X"], merged
        assert merged[1]["played_at"] == _iso(start + 9)  # Spotify's copy, not ours
    """)


def test_spotify_control_guards(app_copy):
    # The seek slider's value can come back from the browser seconds stale.
    # A stale echo (a second the slider was recently placed at) and anything
    # reported right after the page woke from a gap (a backgrounded tab) must
    # not become a real seek -- that skipped songs live, 2026-09-21. A fresh
    # position is a real seek. After a gap every control locks for a while.
    _check(app_copy, """
        import datetime
        import prescripts.spotify_widgets as widgets

        class FakeStreamlit:
            session_state = {}
            def toast(self, *args, **kwargs):
                pass
        class Clock:
            now = 1_790_000_000.0
            def time(self):
                return self.now
        widgets.st, widgets.time = FakeStreamlit(), Clock()
        clock, state = widgets.time, widgets.st.session_state
        seeks = []
        widgets.seek = lambda position_ms: seeks.append(position_ms)
        widgets.is_read_only = lambda: False
        widgets.log_event = lambda text: None

        def report(second):
            state["slider"] = datetime.time(0, second // 60, second % 60)
            widgets._on_seek("slider")

        state["slider_last_render_at"] = clock.now - 1
        state["slider_placed"] = [(30, clock.now - 2), (31, clock.now - 20)]
        report(30)
        assert seeks == []  # placed there 2s ago: an echo
        report(31)
        assert seeks == [31_000]  # placed there too long ago to be an echo
        report(90)
        assert seeks == [31_000, 90_000] and state["slider_seeked"] == (90_000, clock.now)

        # Woken after a minute: ignored, and so is the rest of that wake-up.
        state["slider_last_render_at"] = clock.now - 60
        report(120)
        state["slider_last_render_at"] = clock.now
        clock.now += 5
        report(150)
        assert seeks == [31_000, 90_000]
        clock.now += widgets._RECENT_POSITION_WINDOW_S
        state["slider_last_render_at"] = clock.now - 1
        report(150)
        assert seeks[-1] == 150_000  # the guard has run out

        # Every control: unlocked while ticking, locked for a while after a gap.
        assert widgets.page_is_locked("tile") is False
        clock.now += 1
        assert widgets.page_is_locked("tile") is False
        clock.now += 30
        assert widgets.page_is_locked("tile") is True
        ticks = []
        for _ in range(widgets._RECENT_POSITION_WINDOW_S + 1):  # ticking once a second again
            clock.now += 1
            ticks.append(widgets.page_is_locked("tile"))
        assert ticks[0] is True and ticks[-1] is False, ticks
        widgets.is_read_only = lambda: True
        assert widgets.page_is_locked("tile") is True
        assert widgets.run_control(widgets.seek, position_ms=1) is False and seeks[-1] == 150_000
    """)


def test_spotify_keys_file_problems(app_copy):
    # The keys file is made by hand from the README, so the Spotify page says
    # what's wrong with it instead of crashing or a vague "not found":
    # Notepad's hidden .txt, a typo in the JSON, a missing key. A file saved
    # from PowerShell (UTF-16, or UTF-8 with a BOM) still reads.
    _check(app_copy, """
        import json
        from prescripts.data.spotify import SETTINGS_PATH, SPOTIFY_DIR, is_configured, setup_problem

        assert setup_problem() is None and not is_configured()  # no file: the page just asks for keys
        SPOTIFY_DIR.mkdir()
        txt = SETTINGS_PATH.with_name("settings.json.txt")
        txt.write_text("{}", encoding="utf-8")
        assert "settings.json.txt" in setup_problem()
        txt.unlink()

        SETTINGS_PATH.write_text('{"client_id": "a" "client_secret": "b"}', encoding="utf-8")
        assert "couldn't be read" in setup_problem() and not is_configured()
        SETTINGS_PATH.write_text('{"client_id": "a"}', encoding="utf-8")
        assert "client_secret" in setup_problem()

        keys = json.dumps({"client_id": "a", "client_secret": "b"})
        for encoding in ("utf-8", "utf-8-sig", "utf-16"):
            SETTINGS_PATH.write_text(keys, encoding=encoding)
            assert setup_problem() is None and is_configured(), encoding
    """)


def test_updates(app_copy):
    # #42. What GitHub says (stood in for here) decides what Settings offers:
    # a newer tested version, nothing, or nothing because the copy has
    # commits of its own. Updating is a real git fast-forward from a stand-in
    # "GitHub" folder: refused while the code has edits of its own, and it
    # notices when requirements.txt changed, so pip runs on the restart.
    _check(app_copy, """
        import subprocess
        import urllib.error
        from pathlib import Path
        import prescripts.data.updates as updates

        assert updates.local_version() is None  # the test copy has no .git: a ZIP install
        origin = Path(updates.SCRIPTS_DIR).parent / "origin.git"
        git = lambda *args, cwd=updates.SCRIPTS_DIR: subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
            cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()
        git("init", "-q", "--bare", "-b", "main", str(origin))
        git("init", "-q", "-b", "main")
        git("add", "-A")
        git("commit", "-q", "-m", "First")
        git("remote", "add", "origin", str(origin))
        git("push", "-q", "origin", "main")
        first = updates.local_version()["sha"]

        # Someone else pushes two changes, one to the packages.
        other = origin.parent / "other"
        git("clone", "-q", str(origin), str(other), cwd=origin.parent)
        (other / "README.md").write_text("new readme", encoding="utf-8")
        git("commit", "-q", "-am", "Change the README", cwd=other)
        with open(other / "requirements.txt", "a", encoding="utf-8") as file:
            file.write("# new package\\n")
        git("commit", "-q", "-am", "Add a package\\n\\nWith a body that isn't shown.", cwd=other)
        git("push", "-q", "origin", "main", cwd=other)
        latest = git("rev-parse", "HEAD", cwd=other)

        replies = {}
        def fake_get(url):
            if "/compare/" in url:
                reply = replies["compare"]
                if reply == 404:
                    raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
                return reply
            return {"workflow_runs": [{"head_sha": latest}]}
        updates._get = fake_get
        commit = lambda title: {"commit": {"message": title}}
        replies["compare"] = {"status": "ahead", "commits": [commit("Change the README"), commit("Add a package\\n\\nbody")]}
        status = updates.check_for_update(first)
        assert status == {"state": "available", "sha": latest, "changes": ["Add a package", "Change the README"]}, status
        for reply, state in (({"status": "identical"}, "up_to_date"), ({"status": "behind"}, "up_to_date"),
                             ({"status": "diverged"}, "own_changes"), (404, "own_changes")):
            updates.check_for_update.clear()
            replies["compare"] = reply
            assert updates.check_for_update(first)["state"] == state, reply

        (updates.SCRIPTS_DIR / "README.md").write_text("my edit", encoding="utf-8")
        problem, _ = updates.apply_update(latest)
        assert "edits of its own" in problem and updates.local_version()["sha"] == first
        git("checkout", "--", "README.md")

        assert updates.apply_update(latest) == (None, True)
        assert updates.local_version()["sha"] == latest
        assert (updates.SCRIPTS_DIR / "README.md").read_text(encoding="utf-8") == "new readme"
    """)


@pytest.mark.skipif(sys.platform != "win32", reason="the desktop window is Windows-only")
def test_update_window(app_copy):
    # The window shown while an update installs packages: the page is filled
    # in (the font inlined, the look's colour), and line 2 only shows pip's
    # progress lines, cut to fit.
    _check(app_copy, """
        import desktop_app

        page = desktop_app._update_window_html()
        assert "__FONT__" not in page and "__ACCENT__" not in page
        assert "--accent: #7578b2" in page  # the public look
        assert "world.execute(me);" in page and "sustain++" in page and "by Mili" in page
        status = desktop_app._pip_status
        assert status("Collecting pandas==3.0.6\\n") == "Collecting pandas==3.0.6"
        long = status("Requirement already satisfied: pandas==3.0.6 in c:\\\\somewhere\\\\long")
        assert len(long) == desktop_app._STATUS_WIDTH and long.endswith("…")
        assert status("[notice] A new release of pip is available") is None
        assert status("") is None
    """)


def test_activities_places(app_copy):
    # What the Activities page makes of OpenStreetMap's answer: named places of a
    # known category only, nearest first, outlines placed at their centre,
    # and shrines/temples but not other places of worship.
    _check(app_copy, """
        from prescripts.data.activities import category_of, distance_m, overpass_query, parse_places

        assert abs(distance_m(35.0, 139.0, 35.001, 139.0) - 111.2) < 0.5  # a thousandth of a degree north

        here = (35.6580, 139.7016)
        elements = [
            {"type": "node", "id": 1, "lat": 35.6590, "lon": 139.7016,
             "tags": {"amenity": "restaurant", "name": "すき家", "name:en": "Sukiya", "cuisine": "beef_bowl;japanese"}},
            {"type": "node", "id": 2, "lat": 35.6581, "lon": 139.7016,
             "tags": {"shop": "convenience", "name": "Lawson", "name:en": "Lawson", "opening_hours": "24/7"}},
            {"type": "way", "id": 3, "center": {"lat": 35.6600, "lon": 139.7016},
             "tags": {"amenity": "cafe", "name": "Cafe Outline"}},
            {"type": "node", "id": 4, "lat": 35.6582, "lon": 139.7016, "tags": {"amenity": "restaurant"}},
            {"type": "node", "id": 5, "lat": 35.6582, "lon": 139.7016, "tags": {"amenity": "bank", "name": "A bank"}},
        ]
        places = parse_places("food", elements, *here)
        assert [p["name"] for p in places] == ["Lawson", "すき家", "Cafe Outline"], places
        assert places[0]["name_en"] == ""  # same as the name, so not repeated
        assert places[1]["name_en"] == "Sukiya" and places[1]["cuisine"] == "beef bowl, japanese"
        assert places[0]["hours"] == "24/7" and places[0]["category"] == "convenience"
        assert places[0]["id"] == "node/2" and places[2]["id"] == "way/3"
        assert category_of("food", {"shop": "supermarket"}) == "supermarket"
        # A konbini chain tagged as a supermarket (a mapping slip) still counts as a konbini.
        assert category_of("food", {"shop": "supermarket", "name": "ファミリーマート 渋谷店"}) == "convenience"
        assert category_of("food", {"shop": "supermarket", "name": "Lawson Store 100"}) == "convenience"

        # One shop mapped twice (point + building outline) shows once, as the nearer entry.
        twice = [
            {"type": "node", "id": 7, "lat": 35.6590, "lon": 139.7016, "tags": {"shop": "convenience", "name": "FamilyMart"}},
            {"type": "way", "id": 8, "center": {"lat": 35.6591, "lon": 139.7016},
             "tags": {"shop": "supermarket", "name": "FamilyMart"}},
            {"type": "node", "id": 9, "lat": 35.6620, "lon": 139.7016, "tags": {"shop": "convenience", "name": "FamilyMart"}},
        ]
        assert [p["id"] for p in parse_places("food", twice, *here)] == ["node/7", "node/9"]
        assert round(places[0]["distance"]) == 11

        assert category_of("things", {"amenity": "place_of_worship", "religion": "shinto"}) == "shrine_temple"
        assert category_of("things", {"amenity": "place_of_worship", "religion": "christian"}) is None
        assert category_of("things", {"leisure": "garden"}) == "park"

        query = overpass_query("things", 35.658, 139.7016, 800)
        assert '["religion"~"^(shinto|buddhist)$"]' in query and "(around:800,35.658,139.7016)" in query, query
    """)

def test_activities_wishes(app_copy):
    # "What do you feel like?": kinds of place pick the category (temples
    # and shrines apart), other words must appear in the cuisine or name.
    _check(app_copy, """
        from prescripts.data.activities import matches_wish, parse_wish

        def place(name, category, cuisine="", name_en="", religion=""):
            return {"name": name, "name_en": name_en, "category": category, "cuisine": cuisine, "religion": religion}

        spanish = place("バル・エスパーニャ", "restaurant", cuisine="spanish")
        ramen = place("一蘭 ラーメン", "restaurant", cuisine="")
        cafe = place("スターバックス", "cafe", cuisine="coffee shop", name_en="Starbucks")
        temple = place("増上寺", "shrine_temple", religion="buddhist")
        shrine = place("明治神宮", "shrine_temple", religion="shinto")
        everything = [spanish, ramen, cafe, temple, shrine]

        def found(text):
            wish = parse_wish(text)
            return [p["name"] for p in everything if matches_wish(p, wish)]

        wish = parse_wish("Go to a Spanish restaurant")
        assert (wish["kind"], wish["category"], wish["terms"]) == ("food", "restaurant", ["spanish"]), wish
        assert found("Go to a Spanish restaurant") == ["バル・エスパーニャ"]
        assert found("see a temple") == ["増上寺"]          # Buddhist only, not the shrine
        assert found("visit some shrines") == ["明治神宮"]
        assert found("ramen") == ["一蘭 ラーメン"]           # English word, Japanese name
        assert found("coffee") == ["スターバックス"]
        assert found("starbucks") == ["スターバックス"]      # by English name
        assert parse_wish("fast food")["category"] == "fast_food"  # longer phrase wins over "food"
        assert found("karaoke") == []
    """)


def test_activities_close_matches(app_copy):
    # Plurals and near-miss typos still match, but a word inside a longer
    # one doesn't ("bar" isn't "barber"); the new groups narrow by type.
    _check(app_copy, """
        from prescripts.data.activities import matches_wish, parse_wish

        def place(name, category, type_, name_en="", cuisine=""):
            return {"name": name, "name_en": name_en, "category": category, "type": type_,
                    "cuisine": cuisine, "religion": ""}

        bar = place("Bar Trench", "nightlife", "bar")
        club = place("WOMB", "nightlife", "nightclub")
        karaoke = place("カラオケ館", "nightlife", "karaoke_box")
        barber = place("Barber Shop Ken", "other", "hairdresser")
        animate = place("アニメイト", "shopping", "anime")
        books = place("Kinokuniya", "shopping", "books")
        arcade = place("GiGO", "games_sports", "amusement_arcade")
        everything = [bar, club, karaoke, barber, animate, books, arcade]

        def found(text):
            wish = parse_wish(text)
            return [p["name"] for p in everything if matches_wish(p, wish)]

        assert found("bar") == ["Bar Trench"] and found("bars") == ["Bar Trench"]
        assert found("clubs") == ["WOMB"]
        assert found("go clubbing") == ["WOMB"]
        assert found("karaoke") == ["カラオケ館"]
        assert found("anime merch") == ["アニメイト"]
        assert found("bookstores") == ["Kinokuniya"]
        assert found("game center") == ["GiGO"]
        # A near-miss typo of a kind of place still picks it.
        assert parse_wish("resturant")["category"] == "restaurant"
        # ...and of a name: "starbuks" finds Starbucks.
        cafe = place("スターバックス", "cafe", "cafe", name_en="Starbucks")
        assert matches_wish(cafe, parse_wish("starbuks"))
        # Accents don't matter: "pokemon" finds "Pokémon".
        center = place("ポケモンセンター", "shopping", "toys", name_en="Pokémon Center")
        assert matches_wish(center, parse_wish("pokemon")) and matches_wish(center, parse_wish("ポケモン"))
        # As a plain word, "bar" still doesn't match inside "Barber".
        plain = {"kind": None, "category": None, "types": None, "religion": None, "terms": ["bar"]}
        assert not matches_wish(barber, plain) and matches_wish(bar, plain)
    """)


def test_activities_hidden_places(app_copy):
    # A place hidden with ✕ drops out of every list until shown again, and
    # survives a restart (it's in the saved settings).
    _check(app_copy, """
        from prescripts.data.activities import hidden_places, hide_place, load_settings, unhide_place, without_hidden

        troll = {"id": "node/1", "name": "Definitely a real ramen shop"}
        real = {"id": "node/2", "name": "一蘭"}
        settings = load_settings()
        hide_place(settings, troll)
        hide_place(settings, troll)  # twice is still once
        assert hidden_places(load_settings()) == [troll]
        assert without_hidden([troll, real], load_settings()) == [real]
        unhide_place(settings, "node/1")
        assert without_hidden([troll, real], load_settings()) == [troll, real]
    """)


def test_activities_saved_answers(app_copy):
    # Overpass answers are kept on disk: used as is for a day, after that
    # only when Overpass can't be reached, and deleted after a month.
    _check(app_copy, """
        import json
        import os
        import time
        import urllib.error
        import prescripts.data.activities as activities

        calls = []
        def fetch(query):
            calls.append(query)
            if fetch.down:
                raise urllib.error.URLError("Overpass is down")
            return [{"id": len(calls)}]
        fetch.down = False
        activities._overpass_fetch = fetch

        assert activities._overpass("q") == [{"id": 1}]
        assert activities._overpass("q") == [{"id": 1}] and len(calls) == 1  # a restart wouldn't refetch

        [path] = activities.CACHE_DIR.glob("*.json")
        saved = json.loads(path.read_text(encoding="utf-8"))
        saved["saved_at"] -= 2 * 24 * 3600
        path.write_text(json.dumps(saved), encoding="utf-8")
        fetch.down = True
        assert activities._overpass("q") == [{"id": 1}] and len(calls) == 2  # old, but better than nothing
        fetch.down = False
        assert activities._overpass("q") == [{"id": 3}]  # old and reachable: fetched again

        fetch.down = True
        try:
            activities._overpass("never asked before")
            raise AssertionError("should have failed: nothing saved to fall back on")
        except urllib.error.URLError:
            pass

        month_ago = time.time() - 31 * 24 * 3600
        os.utime(path, (month_ago, month_ago))
        fetch.down = False
        activities._overpass("another")
        assert not path.exists()
    """)


def test_activities_photos(app_copy):
    # A thing to do's photo comes from the Commons file named on it, else its
    # Wikidata image, else its Wikipedia article's free lead image; food gets
    # none. Found photos (and "none found") are saved, so a list seen before
    # makes no lookups, and a failed lookup is tried again next time.
    _check(app_copy, """
        import urllib.error
        import prescripts.data.activities as activities

        source = activities.photo_source
        assert source({"image": "https://commons.wikimedia.org/wiki/File:Sensoji_2023.jpg",
                       "wikidata": "Q1"}) == "file:Sensoji 2023.jpg"
        assert source({"wikimedia_commons": "Category:Sensoji", "wikidata": "Q1"}) == "wikidata:Q1"
        assert source({"image": "https://example.com/a.jpg", "wikipedia": "ja:浅草寺"}) == "wikipedia:ja:浅草寺"
        assert source({"name": "Somewhere"}) is None

        tags = {"leisure": "park", "wikidata": "Q1"}
        elements = [
            {"type": "node", "id": 1, "lat": 35.0, "lon": 139.0, "tags": {**tags, "name": "Park"}},
            {"type": "node", "id": 2, "lat": 35.0, "lon": 139.0, "tags": {**tags, "name": "Garden", "wikidata": "Q2"}},
            {"type": "node", "id": 3, "lat": 35.0, "lon": 139.0,
             "tags": {"leisure": "park", "name": "Shrine park", "wikipedia": "ja:浅草神社"}},
        ]
        places = activities.parse_places("things", elements, 35.0, 139.0)
        food = activities.parse_places("food", [{"type": "node", "id": 9, "lat": 35.0, "lon": 139.0,
            "tags": {"amenity": "cafe", "name": "Café", "wikidata": "Q9"}}], 35.0, 139.0)
        assert food[0]["photo_source"] is None

        asked = []
        def get_json(url, data=None, timeout=30):
            asked.append(url)
            if get_json.down:
                raise urllib.error.URLError("Wikimedia is down")
            if "wikidata.org" in url:  # Q2 has no image
                return {"entities": {"Q1": {"claims": {"P18": [{"mainsnak": {"datavalue": {"value": "Park.jpg"}}}]}},
                                     "Q2": {"claims": {}}}}
            if "wikipedia.org" in url:
                return {"query": {"pages": [{"title": "浅草神社", "pageprops": {"page_image_free": "Shrine_gate.jpg"}}]}}
            return {"query": {"pages": [
                {"title": f"File:{name}", "imageinfo": [{"thumburl": f"https://thumb/{name}", "descriptionurl": "https://page",
                    "extmetadata": {"Artist": {"value": "<a href='x'>Someone</a>"}, "LicenseShortName": {"value": "CC0"}}}]}
                for name in ("Park.jpg", "Shrine gate.jpg")]}}
        get_json.down = True
        activities._get_json = get_json

        assert activities.place_photos(places) == {}  # unreachable: nothing to show, nothing saved
        get_json.down = False
        photos = activities.place_photos(places)
        assert photos == {
            "node/1": {"url": "https://thumb/Park.jpg", "page": "https://page", "credit": "Someone · CC0"},
            "node/3": {"url": "https://thumb/Shrine gate.jpg", "page": "https://page", "credit": "Someone · CC0"},
        }, photos
        asked.clear()
        assert activities.place_photos(places) == photos and asked == []  # all saved, Q2's "none" too
    """)


def test_events(app_copy):
    # Big Sight's list keeps public events only, grouped by their words; a
    # yearly event shows while it's usually on or coming up, over the new
    # year too; news keeps collab headlines, or the watched words; and a
    # saved copy stands in when a source can't be reached.
    _check(app_copy, """
        import os
        import time
        import urllib.error
        from datetime import date
        import prescripts.data.events as events

        header = "展示会名,会期(開始),会期(終了),利用施設,開催時間 開催時間が毎日異なる場合,来場対象者,内容,URL"
        csv_text = "\\n".join([
            header,
            "COMIC CITY 東京153,2026/11/29,2026/11/29,西1-4,10:30-15:00,一般,,https://example.com",
            "食品開発展,2026/10/14,2026/10/16,西1・2・4,10:00-17:00,商談,,",
            "文学フリマ東京43,2026/11/8,2026/11/8,南1-4,12:00-17:00,一般,,",
            "産業交流展,2026/11/11,2026/11/13,有明GYM-EX,10:00-17:00,商談/一般,,",
        ])
        parsed = events.parse_big_sight(csv_text)
        assert [(event["name"], event["group"]) for event in parsed] == [
            ("COMIC CITY 東京153", "anime_games"), ("文学フリマ東京43", "art"), ("産業交流展", "convention")], parsed
        assert parsed[0]["start"] == "2026-11-29" and parsed[0]["place"] == "Tokyo Big Sight (西1-4)"
        assert parsed[2]["place"] == "有明GYM-EX"  # its own building, not a hall

        boroichi = {"around": [["12-15", "12-16"], ["01-15", "01-16"]]}
        assert events._yearly_next(boroichi, date(2026, 11, 20)) == date(2026, 12, 15)
        assert events._yearly_next(boroichi, date(2026, 12, 20)) == date(2027, 1, 15)
        assert events._yearly_next(boroichi, date(2026, 9, 1)) is None  # over two months off
        film_festival = {"around": [["10-25", "11-06"]]}
        assert events._yearly_next(film_festival, date(2026, 11, 1)) == date(2026, 11, 1)  # on now
        new_year = {"around": [["12-30", "01-03"]]}
        assert events._yearly_next(new_year, date(2027, 1, 2)) == date(2027, 1, 2)  # began last year
        for entry in events.yearly_events():  # the shipped list is well-formed
            assert entry["group"] in events.GROUPS and entry["usually"] and entry["around"], entry
            for first, final in entry["around"]:
                date(2028, *map(int, first.split("-"))), date(2028, *map(int, final.split("-")))

        feed = '''<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
            xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
            <item><title>「ハローキティ」コラボカフェ開催</title><link>https://a</link><dc:date>2026-09-30T01:00:00Z</dc:date></item>
            <item><title>新作アニメの放送日決定</title><link>https://b</link><dc:date>2026-09-29T01:00:00Z</dc:date></item>
            <item><title>「鬼滅の刃」新グッズ</title><link>https://c</link><dc:date>2026-09-28T01:00:00Z</dc:date></item>
        </rdf:RDF>'''
        fetched = []
        def fetch(url, timeout=30):
            fetched.append(url)
            if fetch.down:
                raise urllib.error.URLError("down")
            return feed.encode()
        fetch.down = False
        events._fetch = fetch
        assert [item["link"] for item in events.news([])] == ["https://a"]
        assert [item["link"] for item in events.news(["鬼滅"])] == ["https://c"]
        assert events.news([])[0]["date"] == "2026-09-30" and len(fetched) == 1  # saved for an hour

        path = events.CACHE_DIR / "anime_news.txt"
        hours_ago = time.time() - 2 * 3600
        os.utime(path, (hours_ago, hours_ago))
        fetch.down = True
        assert [item["link"] for item in events.news([])] == ["https://a"]  # old copy, source down
        path.unlink()
        try:
            events.news([])
            raise AssertionError("should have failed: nothing saved to fall back on")
        except urllib.error.URLError:
            pass
    """)


def test_overview_columns_end_level(app_copy):
    # Every split is tried, so the columns end as close to level as they can.
    # Placing tiles one at a time into the shorter column once left the
    # Japanese tile stretched with ~250px of nothing under it.
    _check(app_copy, """
        from prescripts.common import balanced_columns

        # Meal, Weather (warning), Japanese, Activities (no area), Spotify (connected).
        heights = [33, 57, 45, 19, 30]
        columns = balanced_columns(heights)
        left = sum(h for h, c in zip(heights, columns) if c == 0)
        right = sum(heights) - left
        assert abs(left - right) == 4, (columns, left, right)  # one at a time gave 78 vs 106
        assert columns[0] == 0  # Meal Receipts always top left
        assert balanced_columns([]) == [] and balanced_columns([10]) == [0]
        assert balanced_columns([10, 10]) == [0, 1]
    """)