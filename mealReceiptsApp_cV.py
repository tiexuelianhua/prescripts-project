# Streamlit interface for logging meal receipts and viewing daily/monthly totals.
# Reuses addDay_cV.ps1 to create/locate today's folder, so folder-creation logic
# and its error logging stay in one place.
# Made by: Claude (cV)

import json
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from prescripts_common import JST, LOGO_PATH, SCRIPTS_DIR, theme_colors, typewriter

MEAL_RECEIPTS_DIR = SCRIPTS_DIR.parent / "Meal Receipts"
SETTINGS_PATH = MEAL_RECEIPTS_DIR / "settings.json"
CSV_COLUMNS = ["timestamp", "store", "item", "cost_yen"]
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
        return pd.read_csv(csv_path)
    return pd.DataFrame(columns=CSV_COLUMNS)


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
        combined = pd.concat([load_entries(target_csv), rows], ignore_index=True)
        combined = combined.sort_values("timestamp").reset_index(drop=True)
        save_entries(target_csv, combined)
    return entries[entry_dates == viewed_date]


def append_entry(csv_path: Path, timestamp: str, store: str, item: str, cost_yen: int) -> None:
    entry = pd.DataFrame([{
        "timestamp": timestamp,
        "store": store,
        "item": item,
        "cost_yen": cost_yen,
    }])
    header = not csv_path.exists()
    entry.to_csv(csv_path, mode="a", header=header, index=False, encoding="utf-8")


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
            df = pd.read_csv(csv_path)
            rows.append({"day": day_dir.name, "total_yen": df["cost_yen"].sum()})
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


def last_price_for_item(item: str) -> int | None:
    # Timestamps are "YYYY-MM-DD HH:MM:SS" strings, which sort correctly as
    # plain text -- no need to parse them as datetimes to find the latest.
    matches = all_entries()
    matches = matches[matches["item"] == item]
    if matches.empty:
        return None
    return int(matches.sort_values("timestamp").iloc[-1]["cost_yen"])


TEXT_COLOR, ACCENT_COLOR = theme_colors()

# Page config and the shared button style are handled once, in app.py, since
# this script now runs as one page of the multi-page app rather than its own
# entry point. Only the animation below is specific to this page.
st.markdown(
    f"""
    <style>
    /* Fades in everything below the typed "Logging to" line, so it doesn't
       pop in abruptly right after that animation finishes. Scoped to the
       "main_body" container (via its st-key-* class) so the typed lines
       above -- which already have their own reveal -- aren't double
       animated. */
    @keyframes fadeIn {{
        from {{ opacity: 0; }}
        to {{ opacity: 1; }}
    }}
    .st-key-main_body [data-testid="stElementContainer"] {{
        animation: fadeIn 0.4s ease-out;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

settings = load_settings()
excluded_stores = set(settings.get("excluded_stores", []))
excluded_items = set(settings.get("excluded_items", []))

with st.sidebar:
    st.header("Settings")
    daily_budget = st.number_input(
        "Daily budget (¥)", min_value=0, step=100, value=settings.get("daily_budget", 0)
    )
    if daily_budget != settings.get("daily_budget", 0):
        settings["daily_budget"] = daily_budget
        save_settings(settings)

    with st.expander("Manage suggestions"):
        # Hides a store/item name from the dropdown suggestions below without
        # touching any already-logged receipts -- useful for one-time store
        # names or typos that would otherwise clutter the autocomplete forever.
        # The exclusion list itself lives in settings.json, so removals are
        # reversible via the "Restore" pickers rather than a hard delete.
        st.caption("Hide a store/item from the dropdowns above. Past receipts aren't affected.")

        hide_stores = st.multiselect(
            "Hide store suggestions",
            options=known_values("store", exclude=excluded_stores),
            key="hide_stores",
        )
        if st.button("Hide selected stores", disabled=not hide_stores):
            settings["excluded_stores"] = sorted(excluded_stores | set(hide_stores))
            save_settings(settings)
            st.rerun()

        hide_items = st.multiselect(
            "Hide item suggestions",
            options=known_values("item", exclude=excluded_items),
            key="hide_items",
        )
        if st.button("Hide selected items", disabled=not hide_items):
            settings["excluded_items"] = sorted(excluded_items | set(hide_items))
            save_settings(settings)
            st.rerun()

        if excluded_stores or excluded_items:
            st.divider()

        if excluded_stores:
            restore_stores = st.multiselect(
                "Restore store suggestions", options=sorted(excluded_stores), key="restore_stores"
            )
            if st.button("Restore selected stores", disabled=not restore_stores):
                settings["excluded_stores"] = sorted(excluded_stores - set(restore_stores))
                save_settings(settings)
                st.rerun()

        if excluded_items:
            restore_items = st.multiselect(
                "Restore item suggestions", options=sorted(excluded_items), key="restore_items"
            )
            if st.button("Restore selected items", disabled=not restore_items):
                settings["excluded_items"] = sorted(excluded_items - set(restore_items))
                save_settings(settings)
                st.rerun()

header_logo, header_title = st.columns([1, 4], vertical_alignment="center")
with header_logo:
    st.image(str(LOGO_PATH), width=120)
with header_title:
    st.title("Meal Receipts")

today_folder = get_today_folder()
today_date = datetime.now(JST).date()

# Reserved here (top of the page) but not animated until after everything
# else below is built -- Streamlit streams each st.* call to the browser as
# it runs, so the form/table/chart all arrive immediately, and only this one
# element visibly finishes typing a moment later on each interaction,
# instead of the whole page waiting on it first.
logging_placeholder = st.empty()

with st.container(key="main_body"):
    # Streamlit raises StreamlitWidgetAlreadyInstantiatedError if you set
    # st.session_state[key] for a widget after that widget has already been
    # created in the *same* run -- so the reset requested on submit (below)
    # can't happen right there. Instead it just sets a flag, and the actual
    # reset happens here, at the very top of whatever run comes next, before
    # any of these widgets exist yet in that run.
    if st.session_state.get("_reset_add_entry_form"):
        st.session_state["add_entry_item"] = None
        st.session_state["_last_priced_item"] = None
        st.session_state["add_entry_day"] = today_date
        st.session_state["add_entry_store"] = None
        st.session_state["add_entry_cost"] = 0
        st.session_state["_reset_add_entry_form"] = False

    # Not an st.form: Item needs to live-react to selection (to suggest a
    # price below) and st.form batches every widget inside it, only reading
    # values on submit -- there'd be no way to react to "which item was just
    # picked" before submission if it were in one. Rather than have Item live
    # outside a form while Day/Store/Cost sit inside one (an inconsistent
    # mix), all four are plain widgets with a plain button, so the whole
    # section behaves the same way.
    #
    # Day is positioned before Item here purely for a more natural reading
    # order ("when" before "what") -- it doesn't participate in the price
    # suggestion below, so its position relative to Item is otherwise free.
    # The one real ordering constraint is Item before Cost: the suggestion
    # writes to Cost's session_state in between, and Cost has to be created
    # after that write to pick it up within the same run.
    entry_date = st.date_input(
        "Day", value=today_date, max_value=today_date, key="add_entry_day"
    )
    item = st.selectbox(
        "Item", options=known_values("item", exclude=excluded_items), index=None,
        accept_new_options=True, placeholder="Type or pick an item",
        key="add_entry_item",
    )
    if item and st.session_state.get("_last_priced_item") != item:
        last_price = last_price_for_item(item)
        if last_price is not None:
            st.session_state["add_entry_cost"] = last_price
        st.session_state["_last_priced_item"] = item

    col1, col2 = st.columns(2)
    store = col1.selectbox(
        "Store", options=known_values("store", exclude=excluded_stores), index=None,
        accept_new_options=True, placeholder="Type or pick a store",
        key="add_entry_store",
    )
    cost_yen = col2.number_input("Cost (¥)", min_value=0, step=1, key="add_entry_cost")
    st.caption("Click **Add entry** to submit")
    submitted = st.button("Add entry")
    if submitted:
        if not store or not item:
            st.warning("Store and item are required.")
        else:
            if entry_date == today_date:
                target_folder = today_folder
            else:
                # Past folders should normally already exist, but a day that
                # was never opened in the app yet (e.g. logging a forgotten
                # meal from a day the app wasn't run) won't -- the PowerShell
                # scripts only ever create *today's* chain, so this is
                # created directly instead.
                target_folder = day_folder_for(entry_date)
                target_folder.mkdir(parents=True, exist_ok=True)
            target_csv = target_folder / "receipts.csv"
            timestamp = datetime.combine(entry_date, datetime.now(JST).time())
            append_entry(target_csv, timestamp.strftime("%Y-%m-%d %H:%M:%S"), store, item, cost_yen)
            typewriter(f"[Logged {item} at {store} for ¥{cost_yen:,.0f}]")
            # No st.form here, so nothing clears itself automatically -- but
            # the actual field reset can't happen right here (Streamlit
            # forbids changing a widget's session_state after that widget's
            # already been instantiated in this run). This flag is picked up
            # at the top of the block on whatever run comes next instead.
            # Not forcing an immediate st.rerun() to apply it sooner: that
            # would interrupt this run before the "[Logged ...]" message
            # above ever painted, wiping it before it's seen.
            st.session_state["_reset_add_entry_form"] = True

    # A day-folder's receipts.csv can exist but be empty -- e.g. right after
    # relocate_edited_entries() above writes an edited-out day back with zero
    # rows left -- so today having logged entries is judged by row count, not
    # just file existence. Only affects the expander's *initial* state; once
    # a viewer un-collapses (or Streamlit remembers a prior collapse) it's
    # left alone on reruns.
    today_has_entries = not load_entries(today_folder / "receipts.csv").empty
    with st.expander("Entries", expanded=today_has_entries):
        selected_date = st.date_input(
            "Day", value=today_date, max_value=today_date, key="view_day"
        )
        selected_csv = day_folder_for(selected_date) / "receipts.csv"
        is_today = selected_date == today_date
        day_entries = load_entries(selected_csv)

        if day_entries.empty:
            st.write("No entries for this day.")
            day_total = 0
        else:
            edited_entries = st.data_editor(
                day_entries,
                num_rows="dynamic",
                width="stretch",
                key=f"editor_{selected_date}",
            )
            # Drops fully-blank rows left over from clicking the editor's "+"
            # add-row button without filling anything in, so they don't get
            # saved as-is.
            edited_entries = edited_entries.dropna(how="all")
            # Saving only on a click (rather than after every cell edit) means
            # you can make several changes to a row before committing any of
            # them to disk. The total/budget below still reflects the live
            # unsaved edit, since that's a harmless preview either way.
            if st.button("💾 Save changes", key=f"save_{selected_date}"):
                same_day_entries = relocate_edited_entries(edited_entries, selected_date)
                moved_count = len(edited_entries) - len(same_day_entries)
                save_entries(selected_csv, same_day_entries)
                all_entries.clear()
                if moved_count:
                    entry_word = "entry" if moved_count == 1 else "entries"
                    st.success(f"Saved. Moved {moved_count} {entry_word} to the day matching its edited date.")
                else:
                    st.success("Saved.")
                # A data_editor's own widget state (its accumulated cell
                # edits/added/deleted rows) persists across reruns under its
                # key regardless of what's passed as its value -- so without
                # clearing it here, a row just moved out to another day's
                # file would keep reappearing in this table (replayed from
                # that stale state) until some unrelated widget interaction
                # happened to reset it.
                del st.session_state[f"editor_{selected_date}"]
                st.rerun()
            else:
                st.caption("Edits above aren't saved until you click **Save changes**.")
            day_total = edited_entries["cost_yen"].sum() if not edited_entries.empty else 0

        # Showing "¥0 vs budget" for a past day with no logged entries at all
        # reads as if you tracked and spent nothing, rather than didn't log
        # that day -- so the total/budget metric only appears for today
        # (where ¥0 so far is meaningful) or a day that actually has entries.
        if is_today or not day_entries.empty:
            total_label = "Today's total" if is_today else f"Total for {selected_date.strftime('%d-%m-%Y')}"
            if daily_budget > 0:
                diff = day_total - daily_budget
                # st.metric only reads a leading "-" to decide the arrow/color
                # for a string delta, so the sign has to be the very first
                # character -- "¥-500" (sign after the yen mark) gets
                # misread as positive.
                diff_str = f"-¥{abs(diff):,.0f}" if diff < 0 else f"¥{diff:,.0f}"
                st.metric(
                    total_label,
                    f"¥{day_total:,.0f}",
                    delta=f"{diff_str} vs ¥{daily_budget:,.0f} budget",
                    delta_color="inverse",
                )
                st.progress(min(day_total / daily_budget, 1.0))
            else:
                st.metric(total_label, f"¥{day_total:,.0f}")

    with st.expander("This month", expanded=True):
        summary = month_summary(today_folder)
        if summary.empty:
            st.write("No entries logged yet this month.")
        else:
            st.metric("This month's total", f"¥{summary['total_yen'].sum():,.0f}")
            st.bar_chart(summary.set_index("day")["total_yen"])

    st.divider()
    st.caption(
        "Visual style (logo, color palette, layout) inspired by *Limbus Company* "
        "(Project Moon) and the fan site [prescript.neocities.org]"
        "(https://prescript.neocities.org/). Pixel font: "
        "[Galmuri](https://github.com/quiple/galmuri) by quiple, OFL-1.1 licensed."
    )

typewriter(
    f"[Logging to: {today_folder}]",
    markdown_wrap=":primary[{}]",
    placeholder=logging_placeholder,
)
