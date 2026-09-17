# Streamlit interface for logging meal receipts and viewing daily/monthly totals.
# Reuses addDay_cV.ps1 to create/locate today's folder, so folder-creation logic
# and its error logging stay in one place.
# Made by: Claude (cV)

import json
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

SCRIPTS_DIR = Path(__file__).resolve().parent
LOGO_PATH = SCRIPTS_DIR.parent / "Images" / "The_Index_Logo.webp"
MEAL_RECEIPTS_DIR = SCRIPTS_DIR.parent / "Meal Receipts"
SETTINGS_PATH = MEAL_RECEIPTS_DIR / "settings.json"
JST = timezone(timedelta(hours=9))
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


def known_values(column: str) -> list[str]:
    return sorted(all_entries()[column].dropna().unique())


def last_price_for_item(item: str) -> int | None:
    # Timestamps are "YYYY-MM-DD HH:MM:SS" strings, which sort correctly as
    # plain text -- no need to parse them as datetimes to find the latest.
    matches = all_entries()
    matches = matches[matches["item"] == item]
    if matches.empty:
        return None
    return int(matches.sort_values("timestamp").iloc[-1]["cost_yen"])


def typewriter(
    text: str,
    speed_ms: int = 30,
    markdown_wrap: str | None = None,
    placeholder: "st.delta_generator.DeltaGenerator | None" = None,
) -> None:
    # Own implementation of the reveal-one-character-at-a-time effect used by
    # prescript.neocities.org for in-game "Prescript" messages -- same generic
    # progressive-reveal idea, written from scratch (not their code) to avoid
    # copying the site itself. Renders as a normal st.markdown element (via a
    # placeholder re-rendered each tick) rather than an iframe, so it inherits
    # the page's theme/font/layout exactly and doesn't introduce a separate
    # document with its own box model.
    #
    # Accepts an existing placeholder so a caller can reserve a spot early
    # (e.g. at the top of the page) but only actually run the animation later
    # in the script -- Streamlit streams each st.* call's output to the
    # browser as it happens, so everything written before this call reaches
    # the page immediately, and only this element visibly trails behind.
    placeholder = placeholder or st.empty()
    for i in range(1, len(text) + 1):
        chunk = text[:i]
        if markdown_wrap:
            chunk = markdown_wrap.format(chunk)
        placeholder.markdown(chunk)
        time.sleep(speed_ms / 1000)


st.set_page_config(page_title="Meal Receipts", page_icon=str(LOGO_PATH))

# st.context.theme only exposes "type" ("dark"/"light"), not resolved hex
# values, so the two palettes below are kept in sync with .streamlit/config.toml
# by hand. Defaults to the dark palette when type is unset (system default),
# since dark is this app's primary intended look.
IS_LIGHT_THEME = st.context.theme.get("type") == "light"
TEXT_COLOR = "#162a3b" if IS_LIGHT_THEME else "#f0f8ff"
ACCENT_COLOR = "#96c4ec"  # buttons/links/input borders, measured from style.css

# Matches Images/Reference 1.png and prescript.neocities.org/style.css: buttons
# there are outlined (transparent fill, accent border+text) and turn to the
# body text color on hover, not Streamlit's default solid-filled style.
# `stBaseButton-*` covers every button kind (regular, form submit, download,
# link) across Streamlit versions via the prefix match.
st.markdown(
    f"""
    <style>
    [data-testid^="stBaseButton"] {{
        background-color: transparent;
        border: 2px solid {ACCENT_COLOR};
        color: {ACCENT_COLOR};
        font-family: inherit;
    }}
    [data-testid^="stBaseButton"]:hover,
    [data-testid^="stBaseButton"]:active,
    [data-testid^="stBaseButton"]:focus:not(:focus-visible) {{
        border-color: {TEXT_COLOR};
        color: {TEXT_COLOR};
    }}
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
with st.sidebar:
    st.header("Settings")
    daily_budget = st.number_input(
        "Daily budget (¥)", min_value=0, step=100, value=settings.get("daily_budget", 0)
    )
    if daily_budget != settings.get("daily_budget", 0):
        settings["daily_budget"] = daily_budget
        save_settings(settings)

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
        "Item", options=known_values("item"), index=None,
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
        "Store", options=known_values("store"), index=None,
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

    with st.expander("Entries", expanded=True):
        selected_date = st.date_input(
            "Day", value=today_date, max_value=today_date, key="view_day"
        )
        selected_csv = day_folder_for(selected_date) / "receipts.csv"
        is_today = selected_date == today_date

        if not selected_csv.exists():
            st.write("No entries for this day.")
            day_total = 0
        else:
            day_entries = load_entries(selected_csv)
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
                save_entries(selected_csv, edited_entries)
                st.success("Saved.")
            else:
                st.caption("Edits above aren't saved until you click **Save changes**.")
            day_total = edited_entries["cost_yen"].sum() if not edited_entries.empty else 0

        # Showing "¥0 vs budget" for a past day with no logged entries at all
        # reads as if you tracked and spent nothing, rather than didn't log
        # that day -- so the total/budget metric only appears for today
        # (where ¥0 so far is meaningful) or a day that actually has entries.
        if is_today or selected_csv.exists():
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
