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


def switch_every_page_on(app_copy):
    # For tests that visit every page or tile: a new public install starts
    # with Spotify switched off (OFF_BY_DEFAULT in common.py).
    (app_copy.parent / "app_settings.json").write_text('{"pages": {"spotify_page": true}}', encoding="utf-8")


def test_every_page_loads(app_copy):
    # A fresh copy has no private logo beside it, so this is the public look
    # -- what anyone installing from the README gets.
    switch_every_page_on(app_copy)
    result = run_in(app_copy, _RUN_EVERY_PAGE)
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_page_loads_in_private_look(app_copy):
    # The private look switches on when Images/The_Index_Logo.webp exists
    # beside the code; any real image will do for that.
    switch_every_page_on(app_copy)
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
        next(button for button in at.button if button.label == "Log meal").click()
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
        assert at.checkbox(key="add_entry_bag").value is True
        assert at.number_input(key="add_entry_bag_yen").value == 5  # Lawson's last bag
        at.number_input(key="add_entry_bag_yen").set_value(6)  # costs more this time
        at.number_input(key="add_entry_tax").set_value(12)
        next(button for button in at.button if button.label == "Log meal").click()
        at.run()
        assert not at.exception and not at.warning, (at.exception, at.warning)
        entries = load_entries(get_today_folder() / "receipts.csv")
        assert list(zip(entries["item"], entries["cost_yen"], entries["store"])) == [
            ("Onigiri", 150, "Lawson"), (BAG_ITEM, 6, "Lawson"), (TAX_ITEM, 12, "Lawson"),
        ], entries
        # The form clears, bag box included.
        assert at.checkbox(key="add_entry_bag").value is False and at.number_input(key="add_entry_tax").value == 0
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_setting_todays_budget(app_copy):
    # "Set today's budget" makes today's whole budget that amount, carried
    # over included, and says so; "Start fresh" goes back to the plain budget.
    result = run_in(app_copy, """
        from datetime import datetime, timedelta
        from streamlit.testing.v1 import AppTest
        from prescripts.common import JST, SCRIPTS_DIR
        from prescripts.data.meal_receipts import MEAL_RECEIPTS_DIR, save_settings

        MEAL_RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
        week_ago = (datetime.now(JST).date() - timedelta(days=7)).isoformat()
        save_settings({"budget_amount": 1000, "budget_period": "daily", "carry_over": True, "carry_over_since": week_ago})

        at = AppTest.from_file(str(SCRIPTS_DIR / "prescripts/pages/meal_receipts.py"), default_timeout=60)
        at.run()
        def budget_line(text):
            return any(text in block.value for block in at.markdown if "budget-line" in block.value)
        assert at.number_input(key="meal_set_today_budget_Food").value == 8000  # 7 unspent days + today
        at.number_input(key="meal_set_today_budget_Food").set_value(2000)
        next(button for button in at.sidebar.button if button.label == "Set").click()
        at.run()
        assert not at.exception, at.exception
        assert any("Today's budget set to ¥2,000" in caption.value for caption in at.sidebar.caption)
        assert budget_line("¥0 / ¥2,000") and budget_line("+¥1,000 carried over")
        next(button for button in at.sidebar.button if button.label == "Start fresh from today").click()
        at.run()
        assert budget_line("¥0 / ¥1,000")
        assert at.number_input(key="meal_set_today_budget_Food").value == 1000  # follows the fresh start
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_logging_a_meal(app_copy):
    # Items gather into one meal with a running total and can be taken out
    # again; tax starts at 0, and "Use 8%" fills in 8% of the items; "Log meal"
    # saves every row at one time and store, and Entries shows them as one
    # meal with its total.
    result = run_in(app_copy, """
        from datetime import date
        from streamlit.testing.v1 import AppTest
        from prescripts.common import SCRIPTS_DIR
        from prescripts.data.meal_receipts import TAX_ITEM, append_entry, day_folder_for, get_today_folder, load_entries

        folder = day_folder_for(date(2026, 8, 1))
        folder.mkdir(parents=True)
        for item, yen in (("Onigiri", 150), ("Karaage", 250), ("Tea", 100)):
            append_entry(folder / "receipts.csv", "2026-08-01 12:00:00", "Olympic", item, yen)

        at = AppTest.from_file(str(SCRIPTS_DIR / "prescripts/pages/meal_receipts.py"), default_timeout=60)
        at.run()
        def add(item):
            at.selectbox(key="add_entry_item").set_value(item)
            at.run()
            next(button for button in at.button if button.label == "+ Add item").click()
            at.run()
        def total():
            return next(block.value for block in at.markdown if "Total:" in block.value)
        for item in ("Onigiri", "Karaage", "Tea"):
            add(item)
        assert at.selectbox(key="add_entry_item").value is None  # cleared for the next item
        assert at.selectbox(key="add_entry_store").value == "Olympic"
        assert at.number_input(key="add_entry_tax").value == 0  # prices usually include tax
        assert "¥500" in total() and "3 items" in total(), total()

        removes = [button for button in at.button if (button.key or "").startswith("meal_remove_")]
        removes[-1].click()  # take the tea out
        at.run()
        assert "¥400" in total() and "2 items" in total(), total()
        next(button for button in at.button if button.label == "Use 8%").click()
        at.run()
        assert at.number_input(key="add_entry_tax").value == 32 and "¥432" in total(), total()
        at.number_input(key="add_entry_tax").set_value(30)  # the receipt's own tax line
        at.run()
        add("Tea")
        assert at.number_input(key="add_entry_tax").value == 30, "typed tax was overwritten"
        next(button for button in at.button if button.label == "Log meal").click()
        at.run()
        assert not at.exception, at.exception

        entries = load_entries(get_today_folder() / "receipts.csv")
        assert list(zip(entries["item"], entries["cost_yen"])) == [
            ("Onigiri", 150), ("Karaage", 250), ("Tea", 100), (TAX_ITEM, 30)], entries
        assert entries["timestamp"].nunique() == 1 and set(entries["store"]) == {"Olympic"}
        assert [line for line in at.markdown if "<details>" in line.value and "Olympic · ¥530 · 3 items" in line.value]
        assert at.number_input(key="add_entry_tax").value == 0 and not at.selectbox(key="add_entry_store").value
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_logging_other_spending(app_copy):
    # A Suica top-up logged as Transport: From/To stations instead of a
    # store (filled in from the last top-up), no bag or tax, and each
    # category's budget shown as its own line, over its own period.
    result = run_in(app_copy, """
        from datetime import date
        from streamlit.testing.v1 import AppTest
        from prescripts.common import SCRIPTS_DIR
        from prescripts.data.meal_receipts import MEAL_RECEIPTS_DIR, append_entry, day_folder_for, get_today_folder, load_entries, save_settings

        folder = day_folder_for(date(2026, 8, 1))
        folder.mkdir(parents=True)
        append_entry(folder / "receipts.csv", "2026-08-01 08:00:00", "Lawson", "Onigiri", 150)
        append_entry(folder / "receipts.csv", "2026-08-01 09:00:00", "Shinjuku → Shibuya", "Suica top-up", 3000,
                     category="Transport")
        MEAL_RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
        save_settings({"budget_amount": 1000, "budget_period": "daily",
                       "budgets": {"Transport": {"amount": 10000, "period": "monthly"}}})

        at = AppTest.from_file(str(SCRIPTS_DIR / "prescripts/pages/meal_receipts.py"), default_timeout=60)
        at.run()
        assert at.selectbox(key="add_entry_category").value == "Food"
        assert at.selectbox(key="add_entry_item").options == ["Onigiri"]
        at.selectbox(key="add_entry_category").set_value("Transport")
        at.run()
        assert at.selectbox(key="add_entry_item").options == ["Suica top-up"]
        assert not [box for box in at.selectbox if box.key == "add_entry_store"]
        assert not [box for box in at.checkbox if box.key == "add_entry_bag"]
        assert not [box for box in at.number_input if box.key == "add_entry_tax"]
        at.selectbox(key="add_entry_item").set_value("Suica top-up")
        at.run()
        assert (at.selectbox(key="add_entry_from").value, at.selectbox(key="add_entry_to").value) == ("Shinjuku", "Shibuya")
        assert at.number_input(key="add_entry_cost").value == 3000
        at.selectbox(key="add_entry_to").set_value(None)  # just topped up at Shinjuku
        at.run()
        next(button for button in at.button if button.label == "Log receipt").click()
        at.run()
        assert not at.exception and not at.warning, (at.exception, at.warning)

        entries = load_entries(get_today_folder() / "receipts.csv")
        assert list(zip(entries["item"], entries["store"], entries["category"])) == [
            ("Suica top-up", "Shinjuku", "Transport")], entries
        assert at.selectbox(key="add_entry_category").value == "Food"  # back to Food for the next one
        [bars] = [block.value for block in at.markdown if "budget-line" in block.value]
        assert "Food · today" in bars and "¥0 / ¥1,000" in bars, bars
        assert "Transport · this month" in bars and "¥3,000 / ¥10,000" in bars and "¥7,000 left" in bars, bars
        assert any("Today: ¥3,000" in block.value for block in at.markdown)

        # A fare needs no item: left blank, it's a transit fee.
        at.selectbox(key="add_entry_category").set_value("Transport")
        at.run()
        at.number_input(key="add_entry_cost").set_value(178)
        at.run()
        next(button for button in at.button if button.label == "Log receipt").click()
        at.run()
        assert not at.exception and not at.warning, (at.exception, at.warning)
        entries = load_entries(get_today_folder() / "receipts.csv")
        assert list(zip(entries["item"], entries["cost_yen"]))[-1] == ("Transit fee", 178), entries
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_logging_a_whole_day_at_once(app_copy):
    # One basket can mix categories: each line keeps the category and store
    # or stations it was added with, and ⇄ swaps From and To for the trip
    # back. A day with no store anywhere still takes one typed in Entries.
    result = run_in(app_copy, """
        from datetime import date
        from streamlit.testing.v1 import AppTest
        from prescripts.common import SCRIPTS_DIR
        from prescripts.data.meal_receipts import append_entry, day_folder_for, get_today_folder, load_entries

        folder = day_folder_for(date(2026, 8, 1))
        folder.mkdir(parents=True)
        append_entry(folder / "receipts.csv", "2026-08-01 08:00:00", "Lawson", "Onigiri", 150)
        append_entry(folder / "receipts.csv", "2026-08-01 09:00:00", "Shinjuku → Shibuya", "Transit fee", 178,
                     category="Transport")

        at = AppTest.from_file(str(SCRIPTS_DIR / "prescripts/pages/meal_receipts.py"), default_timeout=60)
        at.run()
        def add():
            next(button for button in at.button if button.label == "+ Add item").click()
            at.run()
        at.selectbox(key="add_entry_item").set_value("Onigiri")
        at.run()
        add()
        at.selectbox(key="add_entry_category").set_value("Transport")
        at.run()
        at.selectbox(key="add_entry_item").set_value("Transit fee")
        at.run()
        assert (at.selectbox(key="add_entry_from").value, at.selectbox(key="add_entry_to").value) == ("Shinjuku", "Shibuya")
        add()
        at.button(key="add_entry_swap").click()
        at.run()
        assert (at.selectbox(key="add_entry_from").value, at.selectbox(key="add_entry_to").value) == ("Shibuya", "Shinjuku")
        at.number_input(key="add_entry_cost").set_value(178)  # no item: a transit fee
        at.run()
        next(button for button in at.button if button.label == "Log all").click()
        at.run()
        assert not at.exception and not at.warning, (at.exception, at.warning)

        entries = load_entries(get_today_folder() / "receipts.csv")
        assert list(zip(entries["item"], entries["category"], entries["store"])) == [
            ("Onigiri", "Food", "Lawson"),
            ("Transit fee", "Transport", "Shinjuku → Shibuya"),
            ("Transit fee", "Transport", "Shibuya → Shinjuku"),
        ], entries

        blank = day_folder_for(date(2026, 8, 2))
        blank.mkdir(parents=True)
        append_entry(blank / "receipts.csv", "2026-08-02 09:00:00", None, "Transit fee", 178, category="Transport")
        assert load_entries(blank / "receipts.csv")["store"].dtype == object
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
        next(button for button in at.button if button.label == "Log meal").click()
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
        import prescripts.data.events as events
        events.big_sight_events = lambda: []
        events.news = lambda words: []

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

        # Overview's tile: one of the places, a place to go with its photo,
        # an event, and "Another" picks a different place.
        things = [{"type": "node", "id": 7, "lat": 35.6590, "lon": 139.7020,
                   "tags": {"leisure": "park", "name": "代々木公園", "wikidata": "Q1"}}]
        activities.saved_or_fetch_places = lambda kind, lat, lon, radius: things
        photo = {"url": "https://thumb/park.jpg", "page": "https://page", "credit": "Someone · CC0"}
        activities.place_photos = lambda places: {place["id"]: photo for place in places if place["id"] == "node/7"}
        at.switch_page("prescripts/pages/overview.py")
        at.run()
        assert not at.exception, at.exception
        thing = next(block.value for block in at.markdown if "代々木公園" in block.value)
        assert "overview-photo" in thing and "thumb/park.jpg" in thing and "Someone · CC0" in thing, thing
        assert any("overview-event-name" in block.value for block in at.markdown)  # the monthly antique market at least
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


def test_activities_events(app_copy):
    # Events show soonest first with Conventions off at first; an event added
    # with the form shows and can be removed; and with Big Sight's list
    # unreachable the rest still show, with a note. Stand-ins replace the
    # network lookups.
    result = run_in(app_copy, """
        import urllib.error
        from datetime import date, timedelta
        from streamlit.testing.v1 import AppTest
        import prescripts.data.events as events
        from prescripts.common import SCRIPTS_DIR

        today = events.today_jst()
        def day(offset):
            return (today + timedelta(days=offset)).isoformat()
        sample = [
            {"name": "COMIC CITY", "start": day(5), "end": day(5), "place": "Tokyo Big Sight (西1-4)",
             "group": "anime_games", "hours": "10:30-15:00", "link": "https://example.com", "source": "Big Sight"},
            {"name": "Career fair", "start": day(2), "end": day(3), "place": "Tokyo Big Sight (南1-4)",
             "group": "convention", "hours": "", "link": "", "source": "Big Sight"},
        ]
        events.big_sight_events = lambda: sample
        events.news = lambda words: [{"title": "「ハローキティ」コラボカフェ", "link": "https://example.com/n", "date": "2026-09-30"}]
        events.yearly_events = lambda: []

        at = AppTest.from_file(str(SCRIPTS_DIR / "app.py"), default_timeout=60)
        at.run()
        at.switch_page("prescripts/pages/activities.py")
        at.run()
        assert not at.exception, at.exception
        def shown():
            return [block.value for block in at.markdown if "event-name" in block.value]
        assert len(shown()) == 1 and "COMIC CITY" in shown()[0] and "10:30-15:00" in shown()[0], shown()
        assert any("ハローキティ" in block.value for block in at.markdown)

        at.text_input(key="activities_event_name").input("Chiikawa pop-up")
        at.date_input(key="activities_event_start").set_value(today + timedelta(days=1))
        at.text_input(key="activities_event_place").input("Shibuya PARCO")
        at.selectbox(key="activities_event_group").set_value("anime_games")
        next(button for button in at.button if button.label == "Add event").click()
        at.run()
        assert not at.exception, at.exception
        assert len(shown()) == 2 and "Chiikawa pop-up" in shown()[0] and "Shibuya PARCO" in shown()[0], shown()
        [mine] = events.my_events()
        at.button(key=f"activities_event_remove_{mine['id']}").click()
        at.run()
        assert len(shown()) == 1 and events.my_events() == []

        def unreachable():
            raise urllib.error.URLError("down")
        events.big_sight_events = unreachable
        at.run()
        assert not at.exception, at.exception
        assert shown() == [] and any("couldn't be reached" in caption.value for caption in at.caption)
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_overview_translates_last(app_copy):
    # The Weather tile's warning shows in Japanese at first and is swapped for
    # English only after every tile has drawn, so the translation service
    # doesn't hold the others up. Stand-ins replace the network lookups.
    switch_every_page_on(app_copy)
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


def test_overview_tiles_with_no_data_yet(app_copy):
    # A fresh install: every tile says what's missing rather than failing,
    # and a set budget with nothing logged reads as ¥0 of it.
    switch_every_page_on(app_copy)
    result = run_in(app_copy, """
        import json
        from streamlit.testing.v1 import AppTest
        from prescripts.common import SCRIPTS_DIR
        from prescripts.data.meal_receipts import SETTINGS_PATH, get_today_folder

        get_today_folder()  # makes the Meal Receipts folders, as opening the app does
        SETTINGS_PATH.write_text(json.dumps({"budget_amount": 1500, "budget_period": "daily"}), encoding="utf-8")

        at = AppTest.from_file(str(SCRIPTS_DIR / "app.py"), default_timeout=120)
        at.run()
        at.switch_page("prescripts/pages/overview.py")
        at.run()
        assert not at.exception, at.exception
        captions = [caption.value for caption in at.caption]
        for expected in ("No flashcards yet.", "No area saved yet -- pick one on the Activities page.",
                         "Not connected yet -- connect your account on the Spotify page."):
            assert expected in captions, (expected, captions)
        budget = [block.value for block in at.markdown if "budget-line" in block.value]
        assert budget and "Food · today" in budget[0] and "¥0 of ¥1,500" in budget[0], budget
        assert any("Spent today: ¥0" in block.value for block in at.markdown)
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_home_button_goes_home(app_copy):
    # Every page but Home has the Home button (Ctrl+Shift+H presses it too).
    switch_every_page_on(app_copy)
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


def test_overview_button_goes_to_overview(app_copy):
    # Every page but Overview has the Overview button (Ctrl+Shift+O presses
    # it); on Home it's there but hidden, just for the shortcut.
    switch_every_page_on(app_copy)
    result = run_in(app_copy, """
        from streamlit.testing.v1 import AppTest
        from prescripts.common import PAGES, SCRIPTS_DIR

        def on_overview(at):
            return any(header.value.startswith("🧾") for header in at.subheader)  # the Budget tile

        at = AppTest.from_file(str(SCRIPTS_DIR / "app.py"), default_timeout=120)
        for path in ["prescripts/pages/home.py", *[page["path"] for page in PAGES]]:
            at.switch_page(path)
            at.run()
            if path.endswith("overview.py"):
                assert not [b for b in at.button if b.key == "go_overview"], "Overview shouldn't have its own button"
                continue
            at.button(key="go_overview").click()
            at.run()
            assert not at.exception, (path, at.exception)
            assert on_overview(at), path + " didn't go to Overview"
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_switching_pages_and_tiles(app_copy):
    # A new public install starts with Spotify off; Settings switches a page
    # off everywhere (sidebar, Home's commands, its tile) without touching its
    # data, a tile off on its own, and Overview off takes its button too.
    result = run_in(app_copy, """
        from streamlit.testing.v1 import AppTest
        from prescripts.common import SCRIPTS_DIR, load_app_settings, page_shown, shown_pages, tile_shown
        from prescripts.data.home import route_command

        assert not page_shown("spotify_page") and page_shown("japanese") and page_shown("settings")
        assert route_command("spotify", shown_pages()).get("page", {}).get("title") != "Spotify"

        at = AppTest.from_file(str(SCRIPTS_DIR / "app.py"), default_timeout=120)
        at.run()
        at.switch_page("prescripts/pages/settings.py")
        at.run()
        assert not at.exception, at.exception
        at.toggle(key="settings_pages_japanese").set_value(False)
        at.run()
        at.toggle(key="settings_tiles_activities").set_value(False)
        at.run()
        assert not page_shown("japanese") and not tile_shown("japanese")
        assert page_shown("activities") and not tile_shown("activities")
        assert at.toggle(key="settings_tiles_japanese").disabled  # its page is off
        assert route_command("japanese", shown_pages()).get("page", {}).get("title") != "Japanese"

        at.switch_page("prescripts/pages/overview.py")
        at.run()
        assert not at.exception, at.exception
        tiles = [header.value for header in at.subheader]
        assert any(tile.startswith("🧾") for tile in tiles), tiles
        assert not any(tile.startswith(("🈁", "📍", "🎵")) for tile in tiles), tiles
        try:
            at.switch_page("prescripts/pages/japanese.py")
            raise AssertionError("a hidden page should have left the navigation")
        except ValueError:
            pass

        at.switch_page("prescripts/pages/settings.py")
        at.run()
        at.toggle(key="settings_pages_japanese").set_value(True)
        at.toggle(key="settings_pages_overview").set_value(False)
        at.run()
        assert load_app_settings()["pages"] == {"japanese": True, "overview": False}
        assert not [button for button in at.button if button.key == "go_overview"]
        at.switch_page("prescripts/pages/japanese.py")  # back in the navigation
        at.run()
        assert not at.exception, at.exception
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_home_commands(app_copy):
    result = run_in(app_copy, """
        from prescripts.data.home import route_command
        from prescripts.common import PAGES

        def goes_to(query):
            route = route_command(query, PAGES)
            return route["page"]["title"] if route["action"] == "page" else route["action"]

        assert goes_to("Go to Meal Receipts") == "Budget"  # its old name still finds it
        assert goes_to("open the japanese page please") == "Japanese"
        assert goes_to("take me to weather") == "Weather"
        assert goes_to("what's the weather like") == "Weather"
        assert goes_to("wea") == "Weather"  # partial typing still works
        assert goes_to("spotify") == "Spotify"
        assert goes_to("日本語") == "Japanese"
        assert goes_to("activities") == "Activities"
        assert goes_to("nearby") == "Activities"
        # "near me" is more specific than Budget's "food".
        assert goes_to("food near me") == "Activities"

        both = route_command("japanese food", PAGES)
        assert both["action"] == "choose", both
        assert {page["title"] for page in both["pages"]} == {"Japanese", "Budget"}

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
            "Budget": "meal_receipts",  # kept from when it was Meal Receipts
            "Weather": "weather",
            "Activities": "activities",
            "Spotify": "spotify_page",
            "Japanese": "japanese",
            "Settings": "settings",
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
