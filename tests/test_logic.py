# The rules underneath the pages, tested directly rather than through the UI:
# flashcard scheduling and typed answers, what counts toward a meal total,
# lyrics timing, and the play history that fills Spotify's gaps. Same setup
# as test_app.py -- each test runs in a temp copy of the code (conftest.py).
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
        from japanese_data import MINIMUM_EASE, add_card, load_deck, next_schedule, review_card, today_jst

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
        from japanese_data import add_card, load_deck, regrade, review_card, today_jst

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
        from japanese_data import due_cards, today_jst

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
        from japanese_data import normalize_kana, romaji_to_kana

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
        from japanese_data import answer_steps, check_step

        vocab = {"kind": "vocab", "front": "勉強", "reading": "べんきょう", "meaning": "to study; diligence (work)"}
        assert answer_steps(vocab) == ["reading", "meaning"]
        assert check_step(vocab, "reading", "benkyou")
        assert check_step(vocab, "reading", "ベンキョウ")
        assert not check_step(vocab, "reading", "benkyo")
        assert check_step(vocab, "meaning", "Study")
        assert check_step(vocab, "meaning", "study, diligence")
        assert not check_step(vocab, "meaning", "study, school")  # every part typed has to be on the card
        assert not check_step(vocab, "meaning", "   ")

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


def test_excluded_entries_never_count(app_copy):
    # Excluded rows (ticked, or given a reason) drop out of every total, and
    # a receipts.csv from before the excluded column existed still reads.
    _check(app_copy, """
        from datetime import date
        import pandas as pd
        from meal_receipts_data import (
            append_entry, counted_total, day_folder_for, load_entries, week_bounds, week_total_so_far,
            with_excluded_column,
        )

        rows = pd.DataFrame({
            "timestamp": ["2026-09-07 12:00:00"] * 4,
            "store": ["Lawson"] * 4,
            "item": ["Onigiri"] * 4,
            "cost_yen": [100, 200, 300, 400],
            "excluded": [False, True, None, None],  # None = a row added with the table's "+"
            "excluded_reason": [None, None, "Paid with cash", "  "],
        })
        normalized = with_excluded_column(rows)
        assert list(normalized["excluded"]) == [False, True, True, False]  # a reason implies excluded
        assert list(normalized["excluded_reason"].fillna("-")) == ["-", "-", "Paid with cash", "-"]  # blank = no reason
        assert counted_total(rows) == 500
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
        log(date(2026, 9, 10), 5000, excluded_reason="Covered by friend/coworker")
        log(date(2026, 9, 11), 400)  # after "today"
        assert week_total_so_far(date(2026, 9, 10)) == 100 + 150 + 300
    """)


def test_editing_a_date_moves_the_entry(app_copy):
    # The 2026-09-19 bug: a row whose date was edited stayed in the old
    # day's file. It now moves into the new day's, in time order.
    _check(app_copy, """
        from datetime import date
        import pandas as pd
        from meal_receipts_data import append_entry, day_folder_for, load_entries, relocate_edited_entries

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
        from meal_receipts_data import allowance_for_days, budget_settings

        assert budget_settings({}) == (0, "daily")
        assert budget_settings({"daily_budget": 1200}) == (1200, "daily")  # pre-2026-09-21 settings.json
        assert budget_settings({"daily_budget": 1200, "budget_amount": 7000, "budget_period": "weekly"}) == (7000, "weekly")
        assert allowance_for_days(1000, "daily", 30) == 30000
        assert allowance_for_days(7000, "weekly", 3) == 3000
    """)


def test_synced_lyrics(app_copy):
    _check(app_copy, """
        from lyrics_data import current_line_index, parse_synced

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
        import play_history
        from play_history import _iso, merge_with_api, record_observation

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
