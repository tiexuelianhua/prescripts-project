# Streamlit interface for logging meal receipts and viewing daily/monthly totals.
# Reuses addDay_cV.ps1 to create/locate today's folder, so folder-creation logic
# and its error logging stay in one place.
# Made by: Claude (cV)

from datetime import datetime

import pandas as pd
import streamlit as st

from meal_receipts_data import (
    append_entry,
    budget_settings,
    counted_total,
    day_folder_for,
    get_today_folder,
    known_exclusion_reasons,
    known_values,
    last_entry_for_item,
    load_entries,
    load_settings,
    month_excluded_by_reason,
    month_summary,
    relocate_edited_entries,
    rename_value,
    save_entries,
    save_settings,
    week_bounds,
    week_total_so_far,
)
from prescripts_common import (
    JST,
    inject_body_fade_in,
    keep_typed_selectbox_text,
    render_page_title,
    show_logo,
    theme_colors,
    typewriter,
)


TEXT_COLOR, ACCENT_COLOR = theme_colors()
PAGE_TITLE = "Meal Receipts"

# Page config and the shared button style are handled once, in app.py, since
# this script now runs as one page of the multi-page app rather than its own
# entry point.
#
# Both this page's first-load animations (the title below, and the
# "Logging to" line further down) share this one flag -- they're not
# independent events, they're both "first time this session has opened this
# page," so a single check computed once, up top, drives both.
is_first_load = "_typewriter_intro_played" not in st.session_state
inject_body_fade_in("main_body")

# Rendered here, before the sidebar or anything else, since render_page_title
# blocks (via typewriter()'s time.sleep loop) on a session's first load --
# nothing else on the page is generated, let alone sent to the browser,
# until the title's done typing, for a genuinely sequential "title, then
# everything else" load.
header_logo, header_title = st.columns([1, 4], vertical_alignment="center")
with header_logo:
    show_logo(width=120)
with header_title:
    render_page_title(PAGE_TITLE, is_first_load)

settings = load_settings()
excluded_stores = set(settings.get("excluded_stores", []))
excluded_items = set(settings.get("excluded_items", []))

with st.sidebar:
    st.header("Settings")
    stored_amount, stored_period = budget_settings(settings)
    period_options = ["Daily", "Weekly"]
    budget_period_choice = st.selectbox(
        "Budget period", options=period_options,
        index=period_options.index(stored_period.capitalize())
        if stored_period.capitalize() in period_options else 0,
    )
    budget_period = budget_period_choice.lower()
    budget_label = "Daily budget (¥)" if budget_period == "daily" else "Weekly allowance (¥)"
    budget_amount = st.number_input(budget_label, min_value=0, step=100, value=stored_amount)
    if budget_amount != stored_amount or budget_period != stored_period:
        settings["budget_amount"] = budget_amount
        settings["budget_period"] = budget_period
        # Only ever read from here on (see budget_settings()) -- dropped
        # now that the new keys have taken over, rather than left stale.
        settings.pop("daily_budget", None)
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

        st.divider()
        st.caption(
            "Rename a store/item everywhere it appears in past receipts -- "
            "fixes a typo at the source, not just in the dropdowns above."
        )

        # Widgets below are reset via this flag rather than directly, since
        # Streamlit forbids writing a widget's session_state after that
        # widget's already been instantiated in the same run -- see the
        # matching "_reset_add_entry_form" pattern below for the add-entry
        # form. Run before the widgets it targets are created this run.
        if st.session_state.get("_reset_rename_item"):
            st.session_state["rename_item_old"] = None
            st.session_state["rename_item_new"] = ""
            st.session_state["_reset_rename_item"] = False
        if st.session_state.get("_reset_rename_store"):
            st.session_state["rename_store_old"] = None
            st.session_state["rename_store_new"] = ""
            st.session_state["_reset_rename_store"] = False

        # Full item/store lists here (no exclude=), unlike the hide pickers
        # above -- a mistyped name worth fixing might already be hidden.
        rename_item_old = st.selectbox(
            "Item to rename", options=known_values("item"), index=None, key="rename_item_old"
        )
        rename_item_new = st.text_input("Rename to", key="rename_item_new")
        if st.button(
            "Rename item",
            disabled=not (rename_item_old and rename_item_new.strip()),
        ):
            renamed = rename_value("item", rename_item_old, rename_item_new.strip())
            st.session_state["_reset_rename_item"] = True
            # st.toast(), not st.success(): a message shown right before
            # st.rerun() is otherwise discarded with the rest of this
            # interrupted run before ever reaching the browser -- toast is
            # the one message type Streamlit carries across that rerun.
            st.toast(f"Renamed {renamed} receipt(s): '{rename_item_old}' → '{rename_item_new.strip()}'.")
            st.rerun()

        rename_store_old = st.selectbox(
            "Store to rename", options=known_values("store"), index=None, key="rename_store_old"
        )
        rename_store_new = st.text_input("Rename to", key="rename_store_new")
        if st.button(
            "Rename store",
            disabled=not (rename_store_old and rename_store_new.strip()),
        ):
            renamed = rename_value("store", rename_store_old, rename_store_new.strip())
            st.session_state["_reset_rename_store"] = True
            st.toast(f"Renamed {renamed} receipt(s): '{rename_store_old}' → '{rename_store_new.strip()}'.")
            st.rerun()

today_folder = get_today_folder()
today_date = datetime.now(JST).date()
logging_text = f"[Logging to: {today_folder}]"

# Deferred to the bottom of the script -- reserved here at the top but not
# animated until after everything else below is built, so the form/table/
# chart all stream in immediately rather than waiting on it. Every later
# rerun (typing in a field, adding an entry, anything) instead paints the
# finished line right here, immediately: that used to be deferred to the
# bottom too, which left this line sitting visibly blank while the rest of
# the page rendered below it -- showing up as the line disappearing and
# reappearing on every interaction.
if is_first_load:
    logging_placeholder = st.empty()
else:
    st.markdown(f":primary[{logging_text}]")

with st.container(key="main_body"):
    # Streamlit raises StreamlitWidgetAlreadyInstantiatedError if you set
    # st.session_state[key] for a widget after that widget has already been
    # created in the *same* run -- so the reset requested on submit (below)
    # can't happen right there. Instead it just sets a flag, and the actual
    # reset happens here, at the very top of whatever run comes next, before
    # any of these widgets exist yet in that run.
    if st.session_state.get("_reset_add_entry_form"):
        st.session_state["add_entry_item"] = None
        st.session_state["_last_autofilled_item"] = None
        st.session_state["add_entry_day"] = today_date
        st.session_state["add_entry_store"] = None
        st.session_state["add_entry_cost"] = 0
        st.session_state["add_entry_excluded"] = False
        st.session_state["add_entry_excluded_reason"] = None
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
    # The one real ordering constraint is Item before Store/Cost: the
    # suggestion writes to their session_state in between, and both have to
    # be created after that write to pick it up within the same run.
    entry_date = st.date_input(
        "Day", value=today_date, max_value=today_date, key="add_entry_day"
    )
    # Typed text in these three survives clicking/tabbing away without Enter.
    keep_typed_selectbox_text("add_entry_item", "add_entry_store", "add_entry_excluded_reason")
    item = st.selectbox(
        "Item", options=known_values("item", exclude=excluded_items), index=None,
        accept_new_options=True, placeholder="Type or pick an item",
        key="add_entry_item",
    )
    if item and st.session_state.get("_last_autofilled_item") != item:
        last_entry = last_entry_for_item(item)
        if last_entry is not None:
            st.session_state["add_entry_cost"] = int(last_entry["cost_yen"])
            # Just a suggestion -- still an ordinary editable selectbox, so
            # it can be confirmed or changed before submitting.
            st.session_state["add_entry_store"] = str(last_entry["store"])
        st.session_state["_last_autofilled_item"] = item

    col1, col2 = st.columns(2)
    store = col1.selectbox(
        "Store", options=known_values("store", exclude=excluded_stores), index=None,
        accept_new_options=True, placeholder="Type or pick a store",
        key="add_entry_store",
    )
    cost_yen = col2.number_input("Cost (¥)", min_value=0, step=1, key="add_entry_cost")
    excluded = st.checkbox(
        "Don't count toward totals",
        help="Still logged, but left out of the day/week/month totals and budget -- "
        "e.g. paid in cash, or covered by a friend/coworker. Can be changed later "
        "from the **Excluded** column in Entries.",
        key="add_entry_excluded",
    )
    # Only asked once the box is ticked -- optional even then, since the
    # entry's still excluded without one (it just files under "No reason
    # given" in the month breakdown).
    excluded_reason = None
    if excluded:
        excluded_reason = st.selectbox(
            "Reason", options=known_exclusion_reasons(), index=None,
            accept_new_options=True, placeholder="Optional -- pick or type a reason",
            key="add_entry_excluded_reason",
        )
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
            append_entry(
                target_csv, timestamp.strftime("%Y-%m-%d %H:%M:%S"), store, item, cost_yen,
                excluded, excluded_reason,
            )
            # No st.form here, so nothing clears itself automatically -- but
            # the actual field reset can't happen right here (Streamlit
            # forbids changing a widget's session_state after that widget's
            # already been instantiated in this run). Both this flag and the
            # confirmation message below are instead picked up on the very
            # next run, forced immediately (st.rerun()) rather than waiting
            # on whatever the user happens to interact with next -- fields
            # should read as cleared the moment "Add entry" is clicked, not
            # one click later. Stashing the message for that next run (rather
            # than calling typewriter() right here) is what makes that safe:
            # this run ends at the rerun below without ever painting it, so
            # showing it here would just mean it's never seen at all.
            st.session_state["_reset_add_entry_form"] = True
            excluded_note = ""
            if excluded:
                excluded_note = f" (not counted: {excluded_reason})" if excluded_reason else " (not counted toward totals)"
            st.session_state["_add_entry_confirmation"] = (
                f"[Logged {item} at {store} for ¥{cost_yen:,.0f}{excluded_note}]"
            )
            st.rerun()
    else:
        # The message from a successful add on the run just before this one
        # (forced via that st.rerun() above) -- popped so it only ever
        # displays once, not on every later rerun too.
        pending_confirmation = st.session_state.pop("_add_entry_confirmation", None)
        if pending_confirmation:
            typewriter(pending_confirmation)

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
                # Editable like any other column, so entries logged before
                # this option existed (or before realizing a friend covered
                # it) can be excluded retroactively, then saved as usual.
                column_config={
                    "excluded": st.column_config.CheckboxColumn(
                        "Excluded",
                        help="Left out of totals/budget (e.g. paid in cash, covered by someone else)",
                        default=False,
                    ),
                    # A fixed dropdown (the table can't take free text for new
                    # options) -- a reason not listed yet can be typed once
                    # on the add form, and shows up here from then on.
                    # Picking one here also ticks Excluded on save.
                    "excluded_reason": st.column_config.SelectboxColumn(
                        "Reason",
                        options=known_exclusion_reasons(),
                    ),
                },
            )
            # Drops fully-blank rows left over from clicking the editor's "+"
            # add-row button without filling anything in, so they don't get
            # saved as-is. The Excluded checkbox is left out of that check,
            # since its default=False means it's never blank on a new row.
            edited_entries = edited_entries.dropna(
                how="all", subset=[c for c in edited_entries.columns if c not in ("excluded", "excluded_reason")]
            )
            # Saved as soon as anything in the table changes (the user asked
            # for edits to save by default, not wait on a button) -- except
            # while a row is missing its time, store, item or cost, e.g. one
            # just added with "+" and still being filled in: saving it then
            # would file it under no day at all (relocate_edited_entries
            # sorts rows into day-folders by their time).
            editor_changes = st.session_state.get(f"editor_{selected_date}", {})
            has_changes = any(editor_changes.get(part) for part in ("edited_rows", "added_rows", "deleted_rows"))
            # A time typed by hand can be in any everyday format ("2026-09-24
            # 13:00", no seconds) -- rewritten to the stored one so every row
            # in the file matches (pandas won't parse a mix of the two).
            parsed_times = pd.to_datetime(edited_entries["timestamp"], errors="coerce", format="mixed")
            edited_entries.loc[parsed_times.notna(), "timestamp"] = parsed_times[parsed_times.notna()].dt.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            incomplete = edited_entries[["store", "item", "cost_yen"]].isna().any(axis=1) | parsed_times.isna()
            if has_changes and incomplete.any():
                st.caption(
                    "A row is missing its time (e.g. 2026-09-24 13:00), store, item or cost "
                    "-- it'll save once those are filled in."
                )
            elif has_changes:
                same_day_entries = relocate_edited_entries(edited_entries, selected_date)
                moved_count = len(edited_entries) - len(same_day_entries)
                save_entries(selected_csv, same_day_entries)
                # st.toast(), not st.success(): a message shown right before
                # st.rerun() is otherwise discarded with the rest of this
                # interrupted run before ever reaching the browser -- toast is
                # the one message type Streamlit carries across that rerun.
                if moved_count:
                    entry_word = "entry" if moved_count == 1 else "entries"
                    st.toast(f"Saved. Moved {moved_count} {entry_word} to the day matching its edited date.")
                else:
                    st.toast("Saved.")
                # A data_editor's own widget state (its accumulated cell
                # edits/added/deleted rows) persists across reruns under its
                # key regardless of what's passed as its value -- so without
                # clearing it here, the saved edits would be replayed on top
                # of the saved file: added rows added twice, deletions
                # removing whichever rows slid into those positions, and a
                # row moved out to another day reappearing here.
                del st.session_state[f"editor_{selected_date}"]
                st.rerun()
            day_total = counted_total(edited_entries)

        # Showing "¥0 vs budget" for a past day with no logged entries at all
        # reads as if you tracked and spent nothing, rather than didn't log
        # that day -- so the total/budget metric only appears for today
        # (where ¥0 so far is meaningful) or a day that actually has entries.
        if is_today or not day_entries.empty:
            total_label = "Today's total" if is_today else f"Total for {selected_date.strftime('%d-%m-%Y')}"
            # A single day's total only gets compared against the budget
            # when that budget is itself daily -- comparing one day's spend
            # to a weekly allowance would be misleading (see the separate
            # "This week's total" metric below for that case instead).
            if budget_period == "daily" and budget_amount > 0:
                diff = day_total - budget_amount
                # st.metric only reads a leading "-" to decide the arrow/color
                # for a string delta, so the sign has to be the very first
                # character -- "¥-500" (sign after the yen mark) gets
                # misread as positive.
                diff_str = f"-¥{abs(diff):,.0f}" if diff < 0 else f"¥{diff:,.0f}"
                st.metric(
                    total_label,
                    f"¥{day_total:,.0f}",
                    delta=f"{diff_str} vs ¥{budget_amount:,.0f} budget",
                    delta_color="inverse",
                )
                st.progress(min(day_total / budget_amount, 1.0))
            else:
                st.metric(total_label, f"¥{day_total:,.0f}")

            if budget_period == "weekly" and budget_amount > 0 and is_today:
                week_start, week_end = week_bounds(today_date)
                week_total = week_total_so_far(today_date)
                diff = week_total - budget_amount
                diff_str = f"-¥{abs(diff):,.0f}" if diff < 0 else f"¥{diff:,.0f}"
                st.metric(
                    f"This week's total ({week_start.strftime('%d-%m')}–{week_end.strftime('%d-%m')})",
                    f"¥{week_total:,.0f}",
                    delta=f"{diff_str} vs ¥{budget_amount:,.0f} allowance",
                    delta_color="inverse",
                )
                st.progress(min(week_total / budget_amount, 1.0))

    with st.expander("This month", expanded=True):
        summary = month_summary(today_folder)
        if summary.empty:
            st.write("No entries logged yet this month.")
        else:
            st.metric("This month's total", f"¥{summary['total_yen'].sum():,.0f}")
            excluded_by_reason = month_excluded_by_reason(today_folder)
            if not excluded_by_reason.empty:
                breakdown = " · ".join(f"{reason} ¥{yen:,.0f}" for reason, yen in excluded_by_reason.items())
                st.caption(f"Not counted: ¥{excluded_by_reason.sum():,.0f} ({breakdown})")
            st.bar_chart(summary.set_index("day")["total_yen"])

# Streamlit reruns this whole script on every widget interaction (picking an
# item, typing a store, nudging the cost), and typewriter() blocks for
# speed_ms per character -- animating this line on every one of those runs
# turned every field edit into a multi-second stall. The top of the script
# already handled every run except this one by painting the line directly
# in place; this is only reached on the first load of a session.
if is_first_load:
    typewriter(logging_text, markdown_wrap=":primary[{}]", placeholder=logging_placeholder)
    st.session_state["_typewriter_intro_played"] = True
