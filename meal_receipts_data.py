# Data/business logic for the Meal Receipts page -- CSV I/O, settings, and
# summary computations, deliberately with no Streamlit *rendering* calls (
# st.cache_data is fine, it's just a caching decorator with no UI output).
# That separation means other pages (e.g. an Overview page wanting today's
# total) can import and call these directly without accidentally triggering
# mealReceiptsApp_cV.py's own UI as a side effect of the import.
import json
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from prescripts_common import JST, SCRIPTS_DIR

MEAL_RECEIPTS_DIR = SCRIPTS_DIR.parent / "Meal Receipts"
SETTINGS_PATH = MEAL_RECEIPTS_DIR / "settings.json"
# "excluded": logged for the record but left out of every total/budget --
# e.g. paid in cash, or covered by a friend/coworker. Added 2026-09-23;
# receipts.csv files from before then don't have the column at all, which
# load_entries() reads as "not excluded" rather than rewriting them up front.
CSV_COLUMNS = ["timestamp", "store", "item", "cost_yen", "excluded"]
JAPANESE_MONTHS = [
    "1月", "2月", "3月", "4月", "5月", "6月",
    "7月", "8月", "9月", "10月", "11月", "12月",
]


def get_today_folder() -> Path:
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
        # Meal Receipts page (mealReceiptsApp_cV.py's module-level call), so
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
            return with_excluded_column(pd.read_csv(csv_path))
        except pd.errors.EmptyDataError:
            pass
    return with_excluded_column(pd.DataFrame(columns=CSV_COLUMNS))


def with_excluded_column(entries: pd.DataFrame) -> pd.DataFrame:
    # Also covers rows added through the Entries table's "+" button, which
    # leave the checkbox as None rather than False.
    entries = entries.copy()
    if "excluded" not in entries.columns:
        entries["excluded"] = False
    entries["excluded"] = entries["excluded"].fillna(False).astype(bool)
    return entries


def counted_total(entries: pd.DataFrame) -> int:
    # The one place "what counts toward a total" is decided -- every day/
    # week/month total goes through here, so excluded entries drop out of
    # all of them alike.
    if entries.empty:
        return 0
    entries = with_excluded_column(entries)
    return int(entries.loc[~entries["excluded"], "cost_yen"].fillna(0).sum())


def save_entries(csv_path: Path, entries: pd.DataFrame) -> None:
    entries.to_csv(csv_path, index=False, encoding="utf-8")


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
        combined = pd.concat([load_entries(target_csv), with_excluded_column(rows)], ignore_index=True)
        combined = combined.sort_values("timestamp").reset_index(drop=True)
        save_entries(target_csv, combined)
    return entries[entry_dates == viewed_date]


def append_entry(
    csv_path: Path, timestamp: str, store: str, item: str, cost_yen: int, excluded: bool = False
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
            df = pd.read_csv(csv_file)
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
    rows = []
    for day_dir in sorted(day_folder.parent.iterdir()):
        csv_path = day_dir / "receipts.csv"
        if csv_path.exists():
            rows.append({"day": day_dir.name, "total_yen": counted_total(load_entries(csv_path))})
    return pd.DataFrame(rows)


@st.cache_data(ttl=60)
def all_entries() -> pd.DataFrame:
    # Backs both the Store/Item autocomplete and the last-price lookup below --
    # scans every day's CSV, not just the current month, so history from
    # months ago still counts. Cached (one disk scan shared by both features)
    # since it reads every receipts.csv on disk; 60s ttl balances that against
    # a freshly-typed store/item not showing up for a minute.
    frames = []
    for csv_file in MEAL_RECEIPTS_DIR.glob("*/*/*/receipts.csv"):
        try:
            frames.append(pd.read_csv(csv_file))
        except pd.errors.EmptyDataError:
            continue
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=CSV_COLUMNS)


def known_values(column: str, exclude: set[str] | None = None) -> list[str]:
    values = set(all_entries()[column].dropna().unique())
    if exclude:
        values -= exclude
    return sorted(values)


def last_entry_for_item(item: str) -> pd.Series | None:
    # Timestamps are "YYYY-MM-DD HH:MM:SS" strings, which sort correctly as
    # plain text -- no need to parse them as datetimes to find the latest.
    # Returns the whole row (not just cost) so the caller can also suggest
    # the store it was last bought from.
    matches = all_entries()
    matches = matches[matches["item"] == item]
    if matches.empty:
        return None
    return matches.sort_values("timestamp").iloc[-1]


def budget_settings(settings: dict) -> tuple[int, str]:
    # "daily_budget" is the pre-2026-09-21 key -- a flat number, always
    # treated as a daily figure. Read as a fallback (never written back
    # under its own name) so an existing settings.json keeps working
    # untouched until the sidebar's budget control is actually touched
    # again, at which point it's resaved under the new keys.
    amount = settings.get("budget_amount", settings.get("daily_budget", 0))
    period = settings.get("budget_period", "daily")
    return amount, period


def week_bounds(reference_date: date) -> tuple[date, date]:
    # Monday-start (ISO convention) week containing reference_date.
    week_start = reference_date - timedelta(days=reference_date.weekday())
    return week_start, week_start + timedelta(days=6)


def week_total_so_far(reference_date: date) -> int:
    # Sum of counted (non-excluded) cost_yen from the Monday of reference_date's week through
    # reference_date itself (not through the week's end -- there's usually
    # no point reading ahead into days that haven't happened yet).
    week_start, _ = week_bounds(reference_date)
    total = 0
    day = week_start
    while day <= reference_date:
        total += counted_total(load_entries(day_folder_for(day) / "receipts.csv"))
        day += timedelta(days=1)
    return total


def today_summary() -> dict:
    # For pages other than this one (e.g. Overview) that just want today's
    # numbers without pulling in CSV/settings plumbing themselves.
    today_folder = get_today_folder()
    entries = load_entries(today_folder / "receipts.csv")
    settings = load_settings()
    budget_amount, budget_period = budget_settings(settings)
    result = {
        "total_yen": counted_total(entries),
        "budget_amount": budget_amount,
        "budget_period": budget_period,
        "has_entries": not entries.empty,
    }
    if budget_period == "weekly" and budget_amount > 0:
        today_date = datetime.now(JST).date()
        result["week_total_yen"] = week_total_so_far(today_date)
        result["week_start"], result["week_end"] = week_bounds(today_date)
    return result
