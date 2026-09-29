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
    from prescripts.common import PAGES, SCRIPTS_DIR

    failures = []
    for path in ["prescripts/pages/home.py", *[page["path"] for page in PAGES]]:
        at = AppTest.from_file(str(SCRIPTS_DIR / "app.py"), default_timeout=120)
        at.run()
        if path != "prescripts/pages/home.py":
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
        from prescripts.data.meal_receipts import append_entry, day_folder_for, known_values
        from datetime import date

        assert known_values("store") == [] and known_values("item") == []
        folder = day_folder_for(date(2026, 8, 1))
        folder.mkdir(parents=True)
        append_entry(folder / "receipts.csv", "2026-08-01 12:00:00", "Lawson", "Onigiri", 150)
        assert known_values("store") == ["Lawson"], known_values("store")
        assert known_values("item") == ["Onigiri"], known_values("item")
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_store_can_be_left_blank(app_copy):
    # For a store whose name can't be recalled -- the add form takes just an
    # item, and a blank store is never offered back as a "nan" store.
    # (AppTest can't type a brand-new option, so the item is logged once
    # directly first, then picked from the suggestions.)
    result = run_in(app_copy, """
        from datetime import date
        from streamlit.testing.v1 import AppTest
        from prescripts.data.meal_receipts import append_entry, day_folder_for, get_today_folder, known_values, load_entries
        from prescripts.common import SCRIPTS_DIR

        folder = day_folder_for(date(2026, 8, 1))
        folder.mkdir(parents=True)
        append_entry(folder / "receipts.csv", "2026-08-01 12:00:00", None, "Onigiri", 150)
        assert known_values("store") == [], known_values("store")

        at = AppTest.from_file(str(SCRIPTS_DIR / "prescripts/pages/meal_receipts.py"), default_timeout=60)
        at.run()
        at.selectbox(key="add_entry_item").set_value("Onigiri")
        at.run()
        assert at.selectbox(key="add_entry_store").value is None
        next(button for button in at.button if button.label == "Add entry").click()
        at.run()
        assert not at.exception and not at.warning, (at.exception, at.warning)
        entries = load_entries(get_today_folder() / "receipts.csv")
        assert list(entries["item"]) == ["Onigiri"] and entries["store"].isna().all(), entries
        assert known_values("store") == [], known_values("store")
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_konbini_bag_and_tax_get_rows_of_their_own(app_copy):
    # At a konbini the bag box ticks itself, at the bag's last price there;
    # the bag and the receipt's tax line are logged beside the item.
    result = run_in(app_copy, """
        from datetime import date
        from streamlit.testing.v1 import AppTest
        from prescripts.data.meal_receipts import BAG_ITEM, TAX_ITEM, append_entry, day_folder_for, get_today_folder, load_entries
        from prescripts.common import SCRIPTS_DIR

        folder = day_folder_for(date(2026, 8, 1))
        folder.mkdir(parents=True)
        append_entry(folder / "receipts.csv", "2026-08-01 12:00:00", "Lawson", "Onigiri", 150)
        append_entry(folder / "receipts.csv", "2026-08-01 12:00:00", "Lawson", BAG_ITEM, 5)
        append_entry(folder / "receipts.csv", "2026-08-01 18:00:00", "Olympic", "Bread", 200)

        at = AppTest.from_file(str(SCRIPTS_DIR / "prescripts/pages/meal_receipts.py"), default_timeout=60)
        at.run()
        at.selectbox(key="add_entry_item").set_value("Bread")
        at.run()
        assert at.checkbox(key="add_entry_bag").value is False  # Olympic isn't a konbini
        at.selectbox(key="add_entry_item").set_value("Onigiri")
        at.run()
        bag = at.checkbox(key="add_entry_bag")
        assert bag.value is True and "¥5" in bag.label, (bag.value, bag.label)
        at.number_input(key="add_entry_tax").set_value(12)
        next(button for button in at.button if button.label == "Add entry").click()
        at.run()
        assert not at.exception and not at.warning, (at.exception, at.warning)
        entries = load_entries(get_today_folder() / "receipts.csv")
        assert list(zip(entries["item"], entries["cost_yen"], entries["store"])) == [
            ("Onigiri", 150, "Lawson"), (BAG_ITEM, 5, "Lawson"), (TAX_ITEM, 12, "Lawson"),
        ], entries
        # The form clears, bag box included.
        assert at.checkbox(key="add_entry_bag").value is False and at.number_input(key="add_entry_tax").value == 0
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_meal_receipts_works_without_powershell(app_copy):
    # Mac/Linux have no PowerShell, so today's folder is made in Python
    # there. It must be the same folder the .ps1 scripts give, and the page
    # (and Overview's tile from it) must load without ever calling them.
    result = run_in(app_copy, """
        import types
        from streamlit.testing.v1 import AppTest
        import prescripts.data.meal_receipts as meal_receipts_data
        from prescripts.common import SCRIPTS_DIR

        # Pages share this already-imported module, so the patches below
        # reach them too.
        from_powershell = meal_receipts_data.get_today_folder()
        from_powershell.rmdir()
        meal_receipts_data.sys = types.SimpleNamespace(platform="linux")
        def no_powershell(*args, **kwargs):
            raise AssertionError("called PowerShell off Windows")
        meal_receipts_data.subprocess = types.SimpleNamespace(run=no_powershell)

        assert meal_receipts_data.get_today_folder() == from_powershell
        assert from_powershell.is_dir()
        for page in ["prescripts/pages/meal_receipts.py", "prescripts/pages/overview.py"]:
            at = AppTest.from_file(str(SCRIPTS_DIR / "app.py"), default_timeout=120)
            at.run()
            at.switch_page(page)
            at.run()
            assert not at.exception, (page, at.exception)
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_item_bought_at_two_stores_is_offered_per_store(app_copy):
    # The Item picker lists "Onigiri (Lawson)" and "Onigiri (FamilyMart)",
    # each filling in its own store's last price, and still saves the item
    # as plain "Onigiri" -- no new item named after the store.
    result = run_in(app_copy, """
        from datetime import date
        from streamlit.testing.v1 import AppTest
        from prescripts.common import SCRIPTS_DIR
        from prescripts.data.meal_receipts import (
            append_entry, day_folder_for, get_today_folder, item_choice_label, item_choices, load_entries,
        )

        folder = day_folder_for(date(2026, 8, 1))
        folder.mkdir(parents=True)
        append_entry(folder / "receipts.csv", "2026-08-01 08:00:00", "Lawson", "Onigiri", 150)
        append_entry(folder / "receipts.csv", "2026-08-01 12:00:00", "FamilyMart", "Onigiri", 160)
        append_entry(folder / "receipts.csv", "2026-08-01 13:00:00", "Lawson", "Tea", 100)

        choices = item_choices()
        labels = [item_choice_label(choice) for choice in choices]
        assert labels == ["Onigiri (FamilyMart)", "Onigiri (Lawson)", "Tea"], labels
        # A hidden store's variant goes, leaving the plain item.
        hidden = [item_choice_label(choice) for choice in item_choices(exclude_stores={"FamilyMart"})]
        assert hidden == ["Onigiri", "Tea"], hidden

        at = AppTest.from_file(str(SCRIPTS_DIR / "prescripts/pages/meal_receipts.py"), default_timeout=60)
        at.run()
        # Lawson's price, not the more recent FamilyMart one.
        at.selectbox(key="add_entry_item").set_value(choices[labels.index("Onigiri (Lawson)")])
        at.run()
        assert at.selectbox(key="add_entry_store").value == "Lawson"
        assert at.number_input(key="add_entry_cost").value == 150
        # Typing a choice out in full means that choice, not a new item.
        at.selectbox(key="add_entry_item").set_value("Onigiri (FamilyMart)")
        at.run()
        assert at.selectbox(key="add_entry_store").value == "FamilyMart"
        assert at.number_input(key="add_entry_cost").value == 160
        at.checkbox(key="add_entry_bag").uncheck()  # ticked for a konbini, but no bag this time
        at.run()
        next(button for button in at.button if button.label == "Add entry").click()
        at.run()
        assert not at.exception, at.exception
        entries = load_entries(get_today_folder() / "receipts.csv")
        assert list(entries["item"]) == ["Onigiri"] and list(entries["store"]) == ["FamilyMart"], entries
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_activities_page(app_copy):
    # Around a saved area: named places nearest first, and a plain message
    # (not an error screen) when OpenStreetMap can't be reached. The lookup
    # is swapped for a stand-in, so this never touches the network.
    result = run_in(app_copy, """
        import urllib.error
        from streamlit.testing.v1 import AppTest
        import prescripts.data.activities as activities
        from prescripts.common import SCRIPTS_DIR

        activities.save_settings({"area": "Shibuya Station", "lat": 35.658, "lon": 139.7016, "radius": 800})
        sample = [
            {"type": "node", "id": 1, "lat": 35.6590, "lon": 139.7016,
             "tags": {"amenity": "restaurant", "name": "すき家", "name:en": "Sukiya"}},
            {"type": "node", "id": 2, "lat": 35.6581, "lon": 139.7016, "tags": {"shop": "convenience", "name": "Lawson"}},
            {"type": "node", "id": 3, "lat": 35.6600, "lon": 139.7016,
             "tags": {"amenity": "restaurant", "name": "うなぎ 松川", "name:en": "Matsukawa's Eel & Rice"}},
        ]
        activities.fetch_places = lambda kind, lat, lon, radius: sample

        at = AppTest.from_file(str(SCRIPTS_DIR / "app.py"), default_timeout=60)
        at.run()
        at.switch_page("prescripts/pages/activities.py")
        at.run()
        assert not at.exception, at.exception
        shown = [block.value for block in at.markdown if "<b class='place-name'>" in block.value]
        assert "Lawson" in shown[0] and "すき家 · Sukiya" in shown[1], shown
        # Punctuation in names shows as typed (an apostrophe once came out as &#x27;).
        assert "Matsukawa's Eel &amp; Rice" in shown[2], shown
        assert any("3 within 800 m of Shibuya Station" in caption.value for caption in at.caption)

        # "Map" opens OpenStreetMap's map of that place under it; again closes it.
        at.button(key="activities_map_food_node/2").click()
        at.run()
        frames = at.get("iframe")
        assert len(frames) == 1 and "marker=35.6581" in frames[0].proto.src, frames
        at.button(key="activities_map_food_node/2").click()
        at.run()
        assert not at.get("iframe")

        # "What do you feel like?" narrows the list, says so when nothing
        # matches (with a Google Maps search instead), and clearing it goes back.
        at.text_input(key="activities_wish").input("lawson").run()
        shown = [block.value for block in at.markdown if "<b class='place-name'>" in block.value]
        assert len(shown) == 1 and "Lawson" in shown[0], shown
        at.text_input(key="activities_wish").input("spanish restaurant").run()
        assert any("Nothing matching" in caption.value for caption in at.caption)
        assert any("google.com/maps/search/spanish%20restaurant" in block.value for block in at.markdown)
        at.text_input(key="activities_wish").input("").run()
        assert any("3 within 800 m" in caption.value for caption in at.caption)

        # Overview's tile: one of the places, and "Another" picks a different one.
        at.switch_page("prescripts/pages/overview.py")
        at.run()
        assert not at.exception, at.exception
        def picked():
            return next(block.value for block in at.markdown if "overview-place-name" in block.value
                        and "<div" in block.value)
        first = picked()
        assert any(name in first for name in ("Lawson", "すき家", "うなぎ")), first
        at.button(key="overview_activities_another").click()
        at.run()
        assert picked() != first

        def unreachable(*args):
            raise urllib.error.URLError("down")
        activities.fetch_places = unreachable
        at.run()  # Overview first: a quiet note in the tile, no error screen
        assert not at.exception, at.exception
        assert any("Couldn't reach OpenStreetMap" in caption.value for caption in at.caption)
        at.switch_page("prescripts/pages/activities.py")
        at.run()
        assert not at.exception, at.exception
        assert any("Couldn't reach OpenStreetMap" in error.value for error in at.error)
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_overview_translates_last(app_copy):
    # The Weather tile's warning shows in Japanese at first and is swapped for
    # English only after every tile has drawn, so the translation service
    # doesn't hold the others up. Stand-ins replace the network lookups.
    result = run_in(app_copy, """
        from streamlit.testing.v1 import AppTest
        import prescripts.data.spotify as spotify
        import prescripts.data.weather as weather
        from prescripts.common import SCRIPTS_DIR

        calls = []
        weather.key_events_headline = lambda office: "大雨注意報"
        weather.translate_to_english = lambda text: calls.append("translate") or "Heavy rain advisory"
        is_configured = spotify.is_configured
        spotify.is_configured = lambda: calls.append("spotify") or is_configured()

        at = AppTest.from_file(str(SCRIPTS_DIR / "app.py"), default_timeout=120)
        at.run()
        at.switch_page("prescripts/pages/overview.py")
        at.run()
        assert not at.exception, at.exception
        assert any(w.value == "Heavy rain advisory" for w in at.warning), [w.value for w in at.warning]
        assert calls[-1] == "translate" and "spotify" in calls, calls  # the Spotify tile (drawn last) came first
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_home_credits_only_the_quote_showing(app_copy):
    # The corner note names the one quote on screen (built-in or added), and
    # nothing when the prompt isn't a quote. Added quotes live outside the
    # code, and their typed-in text can't break the note's HTML.
    result = run_in(app_copy, """
        from streamlit.testing.v1 import AppTest
        from prescripts.data.home import QUOTES_PATH, add_quote, load_quotes, remove_quote
        from prescripts.common import SCRIPTS_DIR

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
        from prescripts.data.meal_receipts import append_entry, day_folder_for, month_comparison, monthly_history, signed_yen

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


def test_home_button_goes_home(app_copy):
    # Every page but Home has the Home button (Ctrl+Shift+H presses it too).
    result = run_in(app_copy, """
        from streamlit.testing.v1 import AppTest
        from prescripts.common import PAGES, SCRIPTS_DIR

        at = AppTest.from_file(str(SCRIPTS_DIR / "app.py"), default_timeout=120)
        at.run()
        assert not [b for b in at.button if b.key == "go_home"], "Home shouldn't have a Home button"
        for page in PAGES:
            at.switch_page(page["path"])
            at.run()
            at.button(key="go_home").click()
            at.run()
            assert not at.exception, (page["path"], at.exception)
            assert not [b for b in at.button if b.key == "go_home"], page["path"] + " didn't go Home"
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_home_commands(app_copy):
    result = run_in(app_copy, """
        from prescripts.data.home import route_command
        from prescripts.common import PAGES

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
        assert goes_to("activities") == "Activities"
        assert goes_to("nearby") == "Activities"
        # "near me" is more specific than Meal Receipts' "food".
        assert goes_to("food near me") == "Activities"

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


def test_page_addresses_stay_the_same(app_copy):
    # A page's address mustn't change when its file moves or is renamed:
    # bookmarks would break, and Spotify only accepts the exact redirect
    # address registered in the user's own developer app.
    result = run_in(app_copy, """
        from prescripts.common import PAGES
        from prescripts.data.spotify import REDIRECT_URI

        addresses = {page["title"]: page["url_path"] for page in PAGES}
        assert addresses == {
            "Overview": "overview",
            "Meal Receipts": "meal_receipts",
            "Weather": "weather",
            "Activities": "activities",
            "Spotify": "spotify_page",
            "Japanese": "japanese",
        }, addresses
        assert REDIRECT_URI == "http://127.0.0.1:8501/" + addresses["Spotify"], REDIRECT_URI
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
