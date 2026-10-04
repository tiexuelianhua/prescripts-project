# Data/business logic for the Budget page (was Meal Receipts) -- CSV I/O, settings, and
# summary computations, deliberately with no Streamlit *rendering* calls (
# st.cache_data is fine, it's just a caching decorator with no UI output).
# That separation means other pages (e.g. an Overview page wanting today's
# total) can import and call these directly without accidentally triggering
# pages/meal_receipts.py's own UI as a side effect of the import.
import calendar
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from prescripts.common import JST, SCRIPTS_DIR

MEAL_RECEIPTS_DIR = SCRIPTS_DIR.parent / "Meal Receipts"
SETTINGS_PATH = MEAL_RECEIPTS_DIR / "settings.json"
# "excluded": logged for the record but left out of every total/budget --
# e.g. paid in cash, or covered by a friend/coworker. Added 2026-09-23;
# receipts.csv files from before then don't have the column at all, which
# load_entries() reads as "not excluded" rather than rewriting them up front.
# "excluded_reason" (why it's excluded) was added the same day, same
# handling: missing column = no reason given. Since 2026-10-02 it's shown
# as "Notes": any note on any receipt, which no longer excludes it by
# itself (rows excluded through a reason before then were saved with
# excluded ticked, so they stay excluded). The column keeps its name, so
# no file needs rewriting.
# "category" (Food, Transport, ...) came on 2026-10-02, when the page grew
# from meals into a general Budget page. Same handling again: a row with no
# category is Food, since everything logged before then was a meal.
CSV_COLUMNS = ["timestamp", "store", "item", "cost_yen", "excluded", "excluded_reason", "category"]
DEFAULT_CATEGORY = "Food"
# Offered on a new install. Can be added to (type one into the picker) and
# renamed; the list in use is kept in settings.json, see categories().
DEFAULT_CATEGORIES = ["Food", "Transport", "Shopping", "Other"]
# Offered first in the Notes pickers; any other note typed is kept too and
# offered from then on (see known_exclusion_reasons()).
DEFAULT_EXCLUSION_REASONS = ["Paid with cash", "Covered by friend/coworker"]
JAPANESE_MONTHS = [
    "1月", "2月", "3月", "4月", "5月", "6月",
    "7月", "8月", "9月", "10月", "11月", "12月",
]


def get_today_folder() -> Path:
    # The .ps1 scripts (and their error logging) stay the source of truth on
    # Windows. Mac/Linux have no PowerShell, so there the same Year/Month/Day
    # folder is made directly -- what the scripts do in -Silent mode.
    if sys.platform != "win32":
        folder = day_folder_for(datetime.now(JST).date())
        folder.mkdir(parents=True, exist_ok=True)
        return folder
    # PowerShell's redirected-stdout encoding doesn't match Python's default
    # decoder, which mangles the kanji month name (e.g. "9月" -> "9?") unless
    # both sides are forced to UTF-8.
    script_path = SCRIPTS_DIR / "addDay_cV.ps1"
    command = f"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; & '{script_path}' -Silent"
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        encoding="utf-8",
        check=True,
        # Without this, Windows pops a real console window for PowerShell
        # every time this runs -- and this is called on every rerun of the
        # Meal Receipts page (pages/meal_receipts.py's module-level call), so
        # that's most widget interactions on that page. capture_output above
        # already redirects stdout/stderr through pipes regardless, so this
        # doesn't change what the call returns, only whether a window shows.
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    folder = result.stdout.strip().splitlines()[-1]
    return Path(folder)


def day_folder_for(date) -> Path:
    # Mirrors addYear_cV.ps1/addMonth_cV.ps1/addDay_cV.ps1's Year/Japanese-month/
    # Day layout, but read-only -- doesn't create anything, since editing only
    # makes sense for a day that already has entries.
    month_name = f"{JAPANESE_MONTHS[date.month - 1]}-{date.year}"
    return MEAL_RECEIPTS_DIR / str(date.year) / month_name / date.strftime("%d-%m-%Y")


def load_entries(csv_path: Path) -> pd.DataFrame:
    if csv_path.exists():
        try:
            return with_default_columns(pd.read_csv(csv_path))
        except pd.errors.EmptyDataError:
            pass
    return with_default_columns(pd.DataFrame(columns=CSV_COLUMNS))


def with_default_columns(entries: pd.DataFrame) -> pd.DataFrame:
    # Also covers rows added through the Entries table's "+" button, which
    # leave the checkbox as None rather than False.
    entries = entries.copy()
    if "excluded" not in entries.columns:
        entries["excluded"] = False
    if "excluded_reason" not in entries.columns:
        entries["excluded_reason"] = None
    reason = entries["excluded_reason"].astype("string").str.strip()
    has_reason = reason.notna() & (reason != "")
    entries["excluded_reason"] = reason.where(has_reason, None).astype(object)
    entries["excluded"] = entries["excluded"].fillna(False).astype(bool)
    # A day whose stores were all left blank reads in as a column of numbers
    # (all NaN), and the Entries table then won't take a store typed in.
    if "store" in entries.columns:
        entries["store"] = entries["store"].astype(object).where(entries["store"].notna(), None)
    if "category" not in entries.columns:
        entries["category"] = None
    category = entries["category"].astype("string").str.strip()
    entries["category"] = category.where(category.notna() & (category != ""), DEFAULT_CATEGORY).astype(object)
    return entries


def counted_total(entries: pd.DataFrame, category: str | None = None) -> int:
    # The one place "what counts toward a total" is decided -- every day/
    # week/month total goes through here, so excluded entries drop out of
    # all of them alike. With a category, only that category's rows count.
    if entries.empty:
        return 0
    entries = with_default_columns(entries)
    counted = ~entries["excluded"]
    if category is not None:
        counted &= entries["category"] == category
    return int(entries.loc[counted, "cost_yen"].fillna(0).sum())


def totals_by_category(entries: pd.DataFrame) -> dict[str, int]:
    # Counted total per category, largest first; categories with nothing
    # counted are left out.
    if entries.empty:
        return {}
    entries = with_default_columns(entries)
    counted = entries[~entries["excluded"]]
    totals = counted["cost_yen"].fillna(0).groupby(counted["category"]).sum().astype(int)
    return {name: int(yen) for name, yen in totals.sort_values(ascending=False).items() if yen}


def categories(settings: dict) -> list[str]:
    # The categories offered: the saved list (the defaults until one's added
    # or renamed), then any others found in receipts, e.g. typed into the
    # Entries table's file by hand.
    saved = settings.get("categories", DEFAULT_CATEGORIES)
    used = set(with_default_columns(all_entries())["category"].dropna().unique())
    return saved + sorted(used - set(saved))


def budget_category(settings: dict) -> str:
    # The food category: where the form starts, what the 8% tax and "Log
    # meal" are for, and whose budget the pre-categories settings held. A
    # setting so renaming Food (e.g. to "Meals") keeps all that on it.
    return settings.get("budget_category", DEFAULT_CATEGORY)


def transport_category(settings: dict) -> str:
    # The category logged with From/To stations instead of a store, and with
    # no bag or tax. A setting for the same reason as budget_category.
    return settings.get("transport_category", "Transport")


# A transport receipt's stations are kept in its store column, joined by
# this, so the Entries table and meal lines show the route with no new
# columns. Either station can be left out.
ROUTE_SEPARATOR = " → "


def route(from_station: str | None, to_station: str | None) -> str | None:
    stations = [name.strip() for name in (from_station, to_station) if name and name.strip()]
    return ROUTE_SEPARATOR.join(stations) if len(stations) == 2 else (stations[0] if stations else None)


def split_route(store) -> tuple[str | None, str | None]:
    # (from, to) back out of a route; a single name counts as where it's from.
    if not isinstance(store, str) or not store.strip():
        return None, None
    from_station, separator, to_station = store.partition(ROUTE_SEPARATOR)
    return from_station.strip() or None, (to_station.strip() or None) if separator else None


def known_stations(category: str) -> list[str]:
    # Every station in past routes of this category, for the From/To boxes.
    stations = set()
    for store in known_values("store", category=category):
        stations.update(name for name in split_route(store) if name)
    return sorted(stations)


def meals(entries: pd.DataFrame) -> list[dict]:
    # A day's rows gathered into meals: rows logged together share their
    # time and store (a meal's items, bag and tax -- see the add form). In
    # the order logged, each {"time", "store", "rows", "total"}, "rows" a
    # DataFrame and "total" what counts toward totals.
    if entries.empty:
        return []
    entries = with_default_columns(entries)
    stores = entries["store"].where(entries["store"].notna(), "")
    found = []
    for (timestamp, store), rows in entries.groupby([entries["timestamp"], stores], sort=False):
        found.append({"time": str(timestamp), "store": store, "rows": rows, "total": counted_total(rows)})
    return found


def save_entries(csv_path: Path, entries: pd.DataFrame) -> None:
    # Normalized on the way out too, so a reason picked in the Entries table
    # is written with its implied excluded=True, not just read back that way.
    with_default_columns(entries).to_csv(csv_path, index=False, encoding="utf-8")
    # Every write goes through here, so this is the one place the cached
    # all_entries() scan is dropped -- a just-added store/item is suggested
    # straight away instead of after the cache's 60s ttl.
    all_entries.clear()


def relocate_edited_entries(entries: pd.DataFrame, viewed_date) -> pd.DataFrame:
    # Entries live one receipts.csv per day-folder, keyed by the *folder*
    # they're saved into -- not by their own timestamp text. So editing a
    # row's date in the table only rewrites that string in place unless the
    # row is actually moved to the folder matching its new date; otherwise
    # the edit silently has no visible effect (the row stays filed under the
    # old day, and the new day still shows nothing there).
    entry_dates = pd.to_datetime(entries["timestamp"]).dt.date
    moved = entries[entry_dates != viewed_date]
    for target_date, rows in moved.groupby(entry_dates[entry_dates != viewed_date]):
        target_csv = day_folder_for(target_date) / "receipts.csv"
        target_csv.parent.mkdir(parents=True, exist_ok=True)
        combined = pd.concat([load_entries(target_csv), with_default_columns(rows)], ignore_index=True)
        combined = combined.sort_values("timestamp").reset_index(drop=True)
        save_entries(target_csv, combined)
    return entries[entry_dates == viewed_date]


def append_entry(
    csv_path: Path,
    timestamp: str,
    store: str | None,
    item: str,
    cost_yen: int,
    excluded: bool = False,
    excluded_reason: str | None = None,
    category: str = DEFAULT_CATEGORY,
) -> None:
    # Rewrites the whole file rather than appending one line: a pre-"excluded"
    # receipts.csv has a 4-column header, and a 5-field row appended under
    # it would misalign.
    entry = pd.DataFrame([{
        "timestamp": timestamp,
        "store": store,
        "item": item,
        "cost_yen": cost_yen,
        "excluded": excluded,
        "excluded_reason": excluded_reason,
        "category": category,
    }])
    save_entries(csv_path, pd.concat([load_entries(csv_path), entry], ignore_index=True))


def rename_value(column: str, old_value: str, new_value: str) -> int:
    # Unlike the "hide" exclusion list in settings.json, this edits every
    # past receipts.csv in place -- for fixing an actual typo at the source
    # (so it stops showing up under the wrong name in month summaries too),
    # not just tidying the autocomplete going forward.
    renamed = 0
    for csv_file in MEAL_RECEIPTS_DIR.glob("*/*/*/receipts.csv"):
        try:
            # Filled in first, so renaming Food reaches rows from before
            # the category column too.
            df = with_default_columns(pd.read_csv(csv_file))
        except pd.errors.EmptyDataError:
            continue
        matches = df[column] == old_value
        if matches.any():
            df.loc[matches, column] = new_value
            save_entries(csv_file, df)
            renamed += int(matches.sum())
    return renamed


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return {}


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def month_summary(day_folder: Path) -> pd.DataFrame:
    # One row per logged day: "day", "total_yen", and a column of yen per
    # category spent on that month (0 on days it wasn't), for the stacked chart.
    rows = []
    for day_dir in sorted(day_folder.parent.iterdir()):
        csv_path = day_dir / "receipts.csv"
        if csv_path.exists():
            entries = load_entries(csv_path)
            rows.append({"day": day_dir.name, "total_yen": counted_total(entries), **totals_by_category(entries)})
    summary = pd.DataFrame(rows)
    category_columns = [column for column in summary.columns if column not in ("day", "total_yen")]
    summary[category_columns] = summary[category_columns].fillna(0).astype(int)
    return summary


def month_excluded_by_reason(day_folder: Path) -> pd.Series:
    # Yen left out of the month's total, per reason -- "No reason given" for
    # entries excluded without one. Largest first.
    frames = [
        load_entries(day_dir / "receipts.csv")
        for day_dir in sorted(day_folder.parent.iterdir())
        if (day_dir / "receipts.csv").exists()
    ]
    if not frames:
        return pd.Series(dtype=int)
    entries = pd.concat(frames, ignore_index=True)
    excluded = entries[entries["excluded"]]
    reasons = excluded["excluded_reason"].fillna("No note")
    return excluded["cost_yen"].groupby(reasons).sum().astype(int).sort_values(ascending=False)


def known_exclusion_reasons() -> list[str]:
    used = with_default_columns(all_entries())["excluded_reason"].dropna().unique()
    return DEFAULT_EXCLUSION_REASONS + sorted(set(used) - set(DEFAULT_EXCLUSION_REASONS))


@st.cache_data(ttl=60)
def all_entries() -> pd.DataFrame:
    # Backs both the Store/Item autocomplete and the last-price lookup below --
    # scans every day's CSV, not just the current month, so history from
    # months ago still counts. Cached (one disk scan shared by both features)
    # since it reads every receipts.csv on disk. save_entries() clears it on
    # every write, so the 60s ttl only matters for files changed outside the
    # app.
    frames = []
    for csv_file in MEAL_RECEIPTS_DIR.glob("*/*/*/receipts.csv"):
        try:
            frames.append(pd.read_csv(csv_file))
        except pd.errors.EmptyDataError:
            continue
    return with_default_columns(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=CSV_COLUMNS))


def entries_in(category: str | None) -> pd.DataFrame:
    # Every receipt, or just one category's -- the store/item suggestions
    # follow the add form's category, so a train top-up doesn't offer
    # onigiri.
    entries = all_entries()
    return entries if category is None else entries[entries["category"] == category]


def known_values(column: str, exclude: set[str] | None = None, category: str | None = None) -> list[str]:
    values = set(entries_in(category)[column].dropna().unique())
    if exclude:
        values -= exclude
    return sorted(values)


# An item bought at more than one store is offered once per store in the Item
# picker ("Onigiri (Lawson)", "Onigiri (FamilyMart)"), so picking one fills in
# that store's own last price. Each of those choices is the item and store
# joined by this separator -- a character nobody types -- and only the item
# part is ever saved, so no "Onigiri (Lawson)" item gets created.
_ITEM_STORE_SEPARATOR = "\x1f"


def item_choices(
    exclude_items: set[str] | None = None, exclude_stores: set[str] | None = None, category: str | None = None,
) -> list[str]:
    entries = entries_in(category)
    choices = []
    for item in known_values("item", exclude=exclude_items, category=category):
        stores = entries.loc[entries["item"] == item, "store"]
        # A blank store counts as its own variant ("" here), shown as the
        # plain item name next to the named ones.
        variants = sorted({"" if pd.isna(store) else str(store) for store in stores} - (exclude_stores or set()))
        if len(variants) > 1:
            choices += [item + _ITEM_STORE_SEPARATOR + store for store in variants]
        else:
            choices.append(item)
    return choices


def split_item_choice(choice: str) -> tuple[str, str | None]:
    # (item, store) for a per-store choice, where a store of "" means "bought
    # with no store given"; (item, None) for a plain item, meaning "whichever
    # store it was last bought at".
    item, separator, store = choice.partition(_ITEM_STORE_SEPARATOR)
    return (item, store) if separator else (item, None)


def item_choice_label(choice: str) -> str:
    item, store = split_item_choice(choice)
    return f"{item} ({store})" if store else item


def last_entry_for_item(item: str, store: str | None = None, category: str | None = None) -> pd.Series | None:
    # Timestamps are "YYYY-MM-DD HH:MM:SS" strings, which sort correctly as
    # plain text -- no need to parse them as datetimes to find the latest.
    # Returns the whole row (not just cost) so the caller can also suggest
    # the store it was last bought from. With a store (see item_choices),
    # only purchases from that store count; "" means ones with no store.
    # With a category, only that category's purchases.
    matches = entries_in(category)
    matches = matches[matches["item"] == item]
    if store == "":
        matches = matches[matches["store"].isna()]
    elif store is not None:
        matches = matches[matches["store"] == store]
    if matches.empty:
        return None
    return matches.sort_values("timestamp").iloc[-1]


def daily_totals_for_month(year: int, month: int, category: str | None = None) -> dict[date, int]:
    # Counted total per logged day of one month, keyed by date (read from the
    # day folders' dd-mm-yyyy names). Days with no receipts.csv are absent.
    # With a category, only that category's spending.
    month_dir = day_folder_for(date(year, month, 1)).parent
    totals = {}
    if month_dir.exists():
        for day_dir in month_dir.iterdir():
            csv_path = day_dir / "receipts.csv"
            if not csv_path.exists():
                continue
            try:
                day = datetime.strptime(day_dir.name, "%d-%m-%Y").date()
            except ValueError:
                continue
            totals[day] = counted_total(load_entries(csv_path), category)
    return totals


def _previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def signed_yen(amount: float) -> str:
    # "+¥175" / "-¥10,400": the sign before the ¥, as it's read aloud. A plain
    # hyphen, not a minus sign -- st.metric picks a delta's colour from it.
    return f"{'-' if amount < 0 else '+'}¥{abs(amount):,.0f}"


def allowance_for_days(budget_amount: int, budget_period: str, days: int, month_days: int = 30) -> int:
    # What the budget allows over a number of days. A weekly budget is spread
    # evenly across its 7 days, and a monthly one across the month's days
    # (month_days), so a month's share is pro rata.
    per_day = {"daily": budget_amount, "weekly": budget_amount / 7}.get(budget_period, budget_amount / month_days)
    return round(per_day * days)


def month_comparison(today: date) -> dict:
    # This month so far against last month *up to the same day* (1-10 Sep vs
    # 1-10 Aug), so a comparison mid-month isn't against a whole month.
    this_month = daily_totals_for_month(today.year, today.month)
    last_year, last_month = _previous_month(today.year, today.month)
    last_month_totals = daily_totals_for_month(last_year, last_month)
    same_point = min(today.day, calendar.monthrange(last_year, last_month)[1])
    return {
        "this_month_so_far": sum(yen for day, yen in this_month.items() if day <= today),
        "last_month_same_point": sum(yen for day, yen in last_month_totals.items() if day.day <= same_point),
        "has_last_month": bool(last_month_totals),
        "days_so_far": today.day,
    }


def monthly_history(
    today: date, budget_amount: int = 0, budget_period: str = "daily", months: int = 6,
    budget_category: str | None = None,
) -> pd.DataFrame:
    # One row per month, oldest first, for the last `months` months up to and
    # including this one -- starting from the first of them with any receipts,
    # so months before logging began don't show as zeros. The current month
    # counts only the days so far, for its per-day average and allowance.
    # "budgeted_yen" is what the budget's category spent (everything, with no
    # category given): that, not the total, is what the allowance is for.
    rows = []
    year, month = today.year, today.month
    for _ in range(months):
        totals = daily_totals_for_month(year, month)
        budgeted = daily_totals_for_month(year, month, budget_category) if budget_category else totals
        is_current = (year, month) == (today.year, today.month)
        month_days = calendar.monthrange(year, month)[1]
        days = today.day if is_current else month_days
        total = sum(totals.values())
        rows.append({
            "month": f"{year}年{month}月" + (" (so far)" if is_current else ""),
            "total_yen": total,
            "per_day_yen": round(total / days),
            "budgeted_yen": sum(budgeted.values()),
            "allowance_yen": allowance_for_days(budget_amount, budget_period, days, month_days) if budget_amount > 0 else None,
            "has_entries": bool(totals),
        })
        year, month = _previous_month(year, month)
    rows.reverse()
    while rows and not rows[0]["has_entries"]:
        rows.pop(0)
    columns = ["month", "total_yen", "per_day_yen", "budgeted_yen", "allowance_yen", "has_entries"]
    return pd.DataFrame(rows, columns=columns).drop(columns="has_entries")


def budget_settings(settings: dict) -> tuple[int, str]:
    # "daily_budget" is the pre-2026-09-21 key -- a flat number, always
    # treated as a daily figure. Read as a fallback (never written back
    # under its own name) so an existing settings.json keeps working
    # untouched until the sidebar's budget control is actually touched
    # again, at which point it's resaved under the new keys.
    amount = settings.get("budget_amount", settings.get("daily_budget", 0))
    period = settings.get("budget_period", "daily")
    return amount, period


# Pre-2026-10-02 settings.json files keep Food's budget in these top-level
# keys. Read as Food's budget until it's next saved, which moves it into
# "budgets" (see budget_for / save_budget).
_OLD_BUDGET_KEYS = ("daily_budget", "budget_amount", "budget_period", "carry_over", "carry_over_since", "carry_over_set")
PERIODS = ["daily", "weekly", "monthly"]


def budget_for(settings: dict, category: str) -> dict:
    # A category's budget: {"amount", "period", "carry_over"}, plus
    # "carry_over_since" / "carry_over_set" while carry-over is in use. An
    # amount of 0 means no budget. Budgets are soft: going over just shows.
    saved = settings.get("budgets", {}).get(category)
    if saved is not None:
        return {"amount": 0, "period": "daily", "carry_over": False, **saved}
    if category == budget_category(settings):
        amount, period = budget_settings(settings)
        budget = {"amount": amount, "period": period, "carry_over": settings.get("carry_over", False)}
        for key in ("carry_over_since", "carry_over_set"):
            if key in settings:
                budget[key] = settings[key]
        return budget
    return {"amount": 0, "period": "daily", "carry_over": False}


def save_budget(settings: dict, category: str, budget: dict) -> None:
    # Into settings (the caller saves the file). Food's old top-level keys go
    # once it's saved here, so there's one place it lives.
    settings.setdefault("budgets", {})[category] = budget
    if category == budget_category(settings):
        for key in _OLD_BUDGET_KEYS:
            settings.pop(key, None)


def carried_over(settings: dict, today: date, category: str | None = None) -> int:
    # With carry-over on (daily budgets only), every day from when it was
    # switched on (or last started fresh) up to yesterday adds what it was
    # under budget, or takes away what it was over. Nothing resets it on its
    # own. A day with nothing logged counts as ¥0 spent. Uses today's budget
    # amount for every day, so changing the amount changes the past too.
    #
    # "carry_over_set" is a whole budget set by hand for the "since" day, to
    # fix a total that's come out wrong: that day's budget is exactly it,
    # and later days carry on from what's left of it.
    #
    # Each category carries its own (Food when none is given).
    category = category or budget_category(settings)
    budget = budget_for(settings, category)
    amount, since = budget["amount"], budget.get("carry_over_since")
    if not budget["carry_over"] or budget["period"] != "daily" or amount <= 0 or not since:
        return 0
    balance = budget["carry_over_set"] - amount if "carry_over_set" in budget else 0
    day = date.fromisoformat(since)
    while day < today:
        balance += amount - counted_total(load_entries(day_folder_for(day) / "receipts.csv"), category)
        day += timedelta(days=1)
    return balance


def budget_status(settings: dict, day: date, today: date) -> list[dict]:
    # Every category with a budget, in the categories' order, as spent so far
    # in its period around `day`: {"category", "period", "spent", "budget",
    # "carried"}. Carry-over only moves today's budget; another day is
    # judged against the plain amount.
    status = []
    for category in categories(settings):
        budget = budget_for(settings, category)
        if budget["amount"] <= 0:
            continue
        if budget["period"] == "weekly":
            spent = week_total_so_far(day, category)
        elif budget["period"] == "monthly":
            spent = sum(yen for logged, yen in daily_totals_for_month(day.year, day.month, category).items()
                        if logged <= day)
        else:
            spent = counted_total(load_entries(day_folder_for(day) / "receipts.csv"), category)
        carried = carried_over(settings, today, category) if day == today and budget["period"] == "daily" else 0
        status.append({"category": category, "period": budget["period"], "spent": spent,
                       "budget": budget["amount"] + carried, "carried": carried})
    return status


# Bags and tax are logged as rows of their own beside the item (see the add
# form), so a receipt's lines still add up to what was paid.
BAG_ITEM = "Bag (袋)"
TAX_ITEM = "Tax"
DEFAULT_BAG_YEN = 3
# What a transport receipt is logged as when no item is given.
TRANSIT_FEE_ITEM = "Transit fee"


def bag_price(store: str | None) -> int:
    # What a bag last cost at this store, else anywhere, else ¥3.
    last = last_entry_for_item(BAG_ITEM, store) if store else None
    if last is None:
        last = last_entry_for_item(BAG_ITEM)
    return int(last["cost_yen"]) if last is not None else DEFAULT_BAG_YEN


def week_bounds(reference_date: date) -> tuple[date, date]:
    # Monday-start (ISO convention) week containing reference_date.
    week_start = reference_date - timedelta(days=reference_date.weekday())
    return week_start, week_start + timedelta(days=6)


def week_total_so_far(reference_date: date, category: str | None = None) -> int:
    # Sum of counted (non-excluded) cost_yen from the Monday of reference_date's week through
    # reference_date itself (not through the week's end -- there's usually
    # no point reading ahead into days that haven't happened yet). With a
    # category, only that category's.
    week_start, _ = week_bounds(reference_date)
    total = 0
    day = week_start
    while day <= reference_date:
        total += counted_total(load_entries(day_folder_for(day) / "receipts.csv"), category)
        day += timedelta(days=1)
    return total


def today_summary() -> dict:
    # For pages other than this one (e.g. Overview) that just want today's
    # numbers without pulling in CSV/settings plumbing themselves: every
    # budget (see budget_status), what's been spent today and this month in
    # all, and the categories in order (for their colours).
    today_folder = get_today_folder()
    settings = load_settings()
    today = datetime.now(JST).date()
    return {
        "budgets": budget_status(settings, today, today),
        "today_yen": counted_total(load_entries(today_folder / "receipts.csv")),
        "month_yen": sum(daily_totals_for_month(today.year, today.month).values()),
        "categories": categories(settings),
        "budget_category": budget_category(settings),
    }
