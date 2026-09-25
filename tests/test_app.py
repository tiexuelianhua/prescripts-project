# Run with:  .venv\Scripts\python -m pytest
# Everything runs against a temp copy of the code with its own empty data
# folders -- see conftest.py -- so the real data is never touched.
import shutil
import subprocess
import textwrap

import pytest

from conftest import run_in

# Loads app.py, switches to each page in turn, and prints any page whose run
# raised an error. Pages that fetch live data (Weather, lyrics, word
# lookups) need an internet connection to show it, but already cope without
# one, so they still load either way.
_RUN_EVERY_PAGE = """
    from streamlit.testing.v1 import AppTest
    from prescripts_common import PAGES, SCRIPTS_DIR

    failures = []
    for path in ["home_page.py", *[page["path"] for page in PAGES]]:
        at = AppTest.from_file(str(SCRIPTS_DIR / "app.py"), default_timeout=120)
        at.run()
        if path != "home_page.py":
            at.switch_page(path)
            at.run()
        for error in at.exception:
            failures.append(f"{path}: {str(error.value).splitlines()[0]}")
    print("\\n".join(failures) or "all pages OK")
    sys.exit(1 if failures else 0)
"""


def test_every_page_loads(app_copy):
    # A fresh copy has no private logo beside it, so this is the public look
    # -- what anyone installing from the README gets.
    result = run_in(app_copy, _RUN_EVERY_PAGE)
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_page_loads_in_private_look(app_copy):
    # The private look switches on when Images/The_Index_Logo.webp exists
    # beside the code; any real image will do for that.
    images = app_copy.parent / "Images"
    images.mkdir()
    shutil.copy(app_copy / "static" / "forget_me_not.png", images / "The_Index_Logo.webp")
    result = run_in(app_copy, "assert prescripts_common.PRIVATE_LOOK\n" + textwrap.dedent(_RUN_EVERY_PAGE))
    assert result.returncode == 0, result.stdout + result.stderr


def test_new_store_and_item_are_suggested_straight_away(app_copy):
    # The Store/Item suggestions are cached; adding an entry must refresh
    # them, not leave a new store/item missing for a minute.
    result = run_in(app_copy, """
        from meal_receipts_data import append_entry, day_folder_for, known_values
        from datetime import date

        assert known_values("store") == [] and known_values("item") == []
        folder = day_folder_for(date(2026, 8, 1))
        folder.mkdir(parents=True)
        append_entry(folder / "receipts.csv", "2026-08-01 12:00:00", "Lawson", "Onigiri", 150)
        assert known_values("store") == ["Lawson"], known_values("store")
        assert known_values("item") == ["Onigiri"], known_values("item")
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_home_credits_only_the_quote_showing(app_copy):
    # The corner note names the one quote on screen (built-in or added), and
    # nothing when the prompt isn't a quote. Added quotes live outside the
    # code, and their typed-in text can't break the note's HTML.
    result = run_in(app_copy, """
        from streamlit.testing.v1 import AppTest
        from home_data import QUOTES_PATH, add_quote, load_quotes, remove_quote
        from prescripts_common import SCRIPTS_DIR

        assert QUOTES_PATH.parent == SCRIPTS_DIR.parent  # beside the code, not in it
        add_quote("Stay a while.", "A <Book> & More", "Someone", "")

        def corner_note(prompt):
            at = AppTest.from_file(str(SCRIPTS_DIR / "app.py"), default_timeout=60)
            at.session_state["_home_prompt"] = prompt
            at.run()
            assert not at.exception, at.exception
            note = next(m.value for m in at.markdown if "<details" in m.value)
            # A blank line inside it ends the HTML block, and Markdown shows
            # the rest as a code block instead of the note.
            assert "\\n\\n" not in "\\n".join(line.strip() for line in note.strip().splitlines()), note
            return note

        hero = corner_note("Hero on a plastic horse, riding like it's real.")
        assert 'This line is from "Hero" by Mili.' in hero, hero
        assert "Children of the City" not in hero and "TIAN TIAN" not in hero, hero

        assert "This line is from" not in corner_note("What's on your mind?")

        added = corner_note("Stay a while.")
        assert 'This line is from "A &lt;Book&gt; &amp; More" by Someone.' in added, added

        remove_quote(0)
        assert load_quotes() == []
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_month_comparisons(app_copy):
    # This month is compared with last month up to the same day, excluded
    # entries never count, and the history starts at the first month with
    # receipts. "Today" is fixed so the numbers are exact.
    result = run_in(app_copy, """
        from datetime import date
        from meal_receipts_data import append_entry, day_folder_for, month_comparison, monthly_history, signed_yen

        assert (signed_yen(175), signed_yen(-10400), signed_yen(0)) == ("+¥175", "-¥10,400", "+¥0")

        def log(day, yen, excluded=False):
            folder = day_folder_for(day)
            folder.mkdir(parents=True, exist_ok=True)
            append_entry(folder / "receipts.csv", f"{day} 12:00:00", "Lawson", "Onigiri", yen, excluded=excluded)

        for d in range(1, 32):  # August: 1,000/day to the 10th, then 500/day
            log(date(2026, 8, d), 1000 if d <= 10 else 500)
        log(date(2026, 8, 5), 5000, excluded=True)
        for d in range(1, 11):  # September so far (today = the 10th): 800/day
            log(date(2026, 9, d), 800)

        today = date(2026, 9, 10)
        c = month_comparison(today)
        assert (c["this_month_so_far"], c["last_month_same_point"], c["days_so_far"]) == (8000, 10000, 10), c
        assert c["has_last_month"]

        h = monthly_history(today, budget_amount=1000, budget_period="daily")
        assert list(h["month"]) == ["2026年8月", "2026年9月 (so far)"], list(h["month"])  # empty months before August dropped
        assert list(h["total_yen"]) == [20500, 8000], list(h["total_yen"])
        assert list(h["per_day_yen"]) == [661, 800], list(h["per_day_yen"])
        assert list(h["allowance_yen"]) == [31000, 10000], list(h["allowance_yen"])

        weekly = monthly_history(today, budget_amount=7000, budget_period="weekly")
        assert list(weekly["allowance_yen"]) == [31000, 10000]  # 7,000 a week = 1,000 a day

        # Compared on the 30th of a 30-day month: last month counts only up
        # to its 30th, not its 31st.
        c = month_comparison(date(2026, 9, 30))
        assert c["last_month_same_point"] == 20500 - 500, c
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_home_commands(app_copy):
    result = run_in(app_copy, """
        from home_data import route_command
        from prescripts_common import PAGES

        def goes_to(query):
            route = route_command(query, PAGES)
            return route["page"]["title"] if route["action"] == "page" else route["action"]

        assert goes_to("Go to Meal Receipts") == "Meal Receipts"
        assert goes_to("open the japanese page please") == "Japanese"
        assert goes_to("take me to weather") == "Weather"
        assert goes_to("what's the weather like") == "Weather"
        assert goes_to("wea") == "Weather"  # partial typing still works
        assert goes_to("spotify") == "Spotify"
        assert goes_to("日本語") == "Japanese"

        both = route_command("japanese food", PAGES)
        assert both["action"] == "choose", both
        assert {page["title"] for page in both["pages"]} == {"Japanese", "Meal Receipts"}

        search = route_command("how tall is Mount Fuji", PAGES)
        assert search["action"] == "search", search
        assert search["links"] == [("Search Google for it", "https://www.google.com/search?q=how+tall+is+Mount+Fuji")]

        cat = route_command("猫", PAGES)
        assert cat["links"][0] == ("Look it up on Jisho", "https://jisho.org/search/%E7%8C%AB"), cat
    """)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("script", ["addYear_cV.ps1", "addMonth_cV.ps1", "addDay_cV.ps1"])
def test_folder_scripts_write_beside_the_code(app_copy, script):
    # The PowerShell scripts find Meal Receipts relative to themselves, so a
    # copy of the code writes into its own Meal Receipts -- not a fixed path.
    shutil.which("powershell") or pytest.skip("PowerShell is Windows-only")
    (app_copy.parent / "Meal Receipts" / "Error Logs").mkdir(parents=True)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; & '{app_copy / script}' -Silent"],
        capture_output=True, text=True, encoding="utf-8",
    )
    created = result.stdout.strip()
    assert created.startswith(str(app_copy.parent / "Meal Receipts")), result.stdout + result.stderr
