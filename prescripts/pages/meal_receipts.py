# Streamlit interface for the Budget page (Meal Receipts until it took other
# spending too): logging receipts by category and viewing daily/monthly
# totals. This file, the data folder and the scripts keep the old name.
# Reuses addDay_cV.ps1 to create/locate today's folder, so folder-creation logic
# and its error logging stay in one place.
# Made by: Claude (cV)

import html
import time
from datetime import datetime

import pandas as pd
import streamlit as st

from prescripts.budget_widgets import category_colors, render_budget_bars
from prescripts.common import (
    JST,
    inject_body_fade_in,
    keep_typed_selectbox_text,
    render_page_title,
    show_logo,
    theme_colors,
    typewriter,
)
from prescripts.data.activities import is_konbini
from prescripts.data.meal_receipts import (
    BAG_ITEM,
    PERIODS,
    TAX_ITEM,
    TRANSIT_FEE_ITEM,
    append_entry,
    bag_price,
    budget_category,
    budget_for,
    budget_status,
    carried_over,
    categories,
    day_folder_for,
    get_today_folder,
    item_choice_label,
    item_choices,
    known_exclusion_reasons,
    known_stations,
    known_values,
    last_entry_for_item,
    load_entries,
    load_settings,
    meals,
    month_comparison,
    month_excluded_by_reason,
    month_summary,
    monthly_history,
    relocate_edited_entries,
    rename_value,
    route,
    save_budget,
    save_entries,
    save_settings,
    signed_yen,
    split_item_choice,
    split_route,
    totals_by_category,
    transport_category,
)

TEXT_COLOR, ACCENT_COLOR = theme_colors()
PAGE_TITLE = "Budget"


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
category_names = categories(settings)
# Food: where the form starts, 8% tax and "Log meal". Transport: From/To
# stations in place of a store, no bag or tax. Both follow a rename.
budgeted = budget_category(settings)
transport = transport_category(settings)
colors = category_colors(category_names, budgeted, ACCENT_COLOR)
today_jst = datetime.now(JST).date()

with st.sidebar:
    st.header("Settings")
    # Each category has its own budget, set one at a time here: an amount
    # (0 = none) for a day, week or month. Budgets are soft -- going over
    # just shows as over.
    st.subheader("Budgets")
    editing = st.selectbox(
        "Category", options=category_names, key="budget_editing",
        index=category_names.index(budgeted) if budgeted in category_names else 0,
    )
    # In its colour, like the form's Category box.
    st.markdown(
        f"<style>.st-key-budget_editing input, .st-key-budget_editing [data-baseweb='select'] div "
        f"{{ color: {colors.get(editing, ACCENT_COLOR)}; }}</style>",
        unsafe_allow_html=True,
    )
    budget = budget_for(settings, editing)
    # Keyed per category, so switching categories shows that one's own
    # saved values rather than the last one's.
    period = st.selectbox(
        "Period", options=PERIODS, format_func=str.capitalize, key=f"budget_period_{editing}",
        index=PERIODS.index(budget["period"]) if budget["period"] in PERIODS else 0,
    )
    amount = st.number_input(
        f"{period.capitalize()} {editing.lower()} budget (¥)", min_value=0, step=100,
        value=int(budget["amount"]), key=f"budget_amount_{editing}",
        help="0 for no budget. Its spending is still logged and counted in the totals.",
    )
    if amount != budget["amount"] or period != budget["period"]:
        budget.update(amount=int(amount), period=period)
        save_budget(settings, editing, budget)
        save_settings(settings)

    if period == "daily" and amount > 0:
        # Some room above the switch, so it doesn't sit tight under the
        # amount box.
        st.markdown("<style>.st-key-budget_carry_box { margin-top: 0.75rem; }</style>", unsafe_allow_html=True)
        # Off for a new category until switched on.
        carry_on = st.container(key="budget_carry_box").toggle(
            "Carry leftover budget over", value=budget["carry_over"], key=f"budget_carry_{editing}",
            help="What's left of each day's budget adds to the next day's, and going over takes it away. "
            "Keeps adding up until you start fresh. A day with nothing logged counts as ¥0 spent.",
        )
        if carry_on != budget["carry_over"]:
            budget["carry_over"] = carry_on
            if carry_on:
                budget["carry_over_since"] = today_jst.isoformat()
                budget.pop("carry_over_set", None)
            save_budget(settings, editing, budget)
            save_settings(settings)
        if carry_on:
            carry = carried_over(settings, today_jst, editing)
            is_set_today = budget["carry_over_since"] == today_jst.isoformat() and "carry_over_set" in budget
            if is_set_today:
                st.caption(f"Today's budget set to ¥{budget['carry_over_set']:,}. Carrying over from there.")
            else:
                st.caption(f"Carried over: {signed_yen(carry)} since {budget['carry_over_since']}")
            fresh = budget["carry_over_since"] == today_jst.isoformat() and "carry_over_set" not in budget
            if st.button("Start fresh from today", disabled=fresh):
                budget["carry_over_since"] = today_jst.isoformat()
                budget.pop("carry_over_set", None)
                save_budget(settings, editing, budget)
                save_settings(settings)
                st.rerun()
            # To fix a carried-over total that's come out wrong: today's whole
            # budget, carry-over included, becomes this.
            # Starts at today's budget as it stands, and follows it when that
            # changes (a fresh start, a new daily amount), rather than keeping
            # whatever was last typed.
            set_key = f"meal_set_today_budget_{editing}"
            if st.session_state.get(f"_meal_set_today_from_{editing}") != amount + carry:
                st.session_state[f"_meal_set_today_from_{editing}"] = amount + carry
                st.session_state.pop(set_key, None)
            set_column, button_column = st.columns([3, 2], vertical_alignment="bottom")
            set_amount = set_column.number_input(
                "Set today's budget (¥)", min_value=0, step=100, value=int(amount + carry), key=set_key,
                help="Replaces today's budget and anything carried over. Tomorrow carries on from what's left of it.",
            )
            if button_column.button("Set", width="stretch"):
                budget["carry_over_since"] = today_jst.isoformat()
                budget["carry_over_set"] = int(set_amount)
                save_budget(settings, editing, budget)
                save_settings(settings)
                st.rerun()
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
            "Rename a store, item or category everywhere it appears in past receipts -- "
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

        # Categories are renamed the same way, and in the saved list too. A
        # new category needs no button: typing one into the add form's
        # Category box adds it.
        if st.session_state.get("_reset_rename_category"):
            st.session_state["rename_category_old"] = None
            st.session_state["rename_category_new"] = ""
            st.session_state["_reset_rename_category"] = False
        rename_category_old = st.selectbox(
            "Category to rename", options=category_names, index=None, key="rename_category_old"
        )
        rename_category_new = st.text_input("Rename to", key="rename_category_new")
        if st.button(
            "Rename category",
            disabled=not (rename_category_old and rename_category_new.strip()),
        ):
            new_name = rename_category_new.strip()
            # Its budget goes with it. Read before the food category's name
            # changes below: Food's may still be in the old top-level keys.
            moved_budget = budget_for(settings, rename_category_old)
            renamed = rename_value("category", rename_category_old, new_name)
            # Renaming onto a category that already exists merges the two.
            settings["categories"] = list(dict.fromkeys(
                new_name if name == rename_category_old else name for name in category_names
            ))
            if budgeted == rename_category_old:
                settings["budget_category"] = new_name
            if transport == rename_category_old:
                settings["transport_category"] = new_name
            settings.get("budgets", {}).pop(rename_category_old, None)
            if moved_budget["amount"] > 0 and new_name not in settings.get("budgets", {}):
                save_budget(settings, new_name, moved_budget)
            save_settings(settings)
            st.session_state["_reset_rename_category"] = True
            st.toast(f"Renamed {renamed} receipt(s): '{rename_category_old}' → '{new_name}'.")
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
        st.session_state["add_entry_day"] = today_date
        st.session_state["add_entry_category"] = budgeted
        st.session_state["add_entry_store"] = None
        st.session_state["add_entry_from"] = None
        st.session_state["add_entry_to"] = None
        st.session_state["add_entry_excluded"] = False
        st.session_state["add_entry_excluded_reason"] = None
        st.session_state["add_entry_tax"] = 0
        st.session_state["add_entry_bag"] = False
        st.session_state["_bag_ticked_for_store"] = None
        st.session_state["_meal_basket"] = []
        st.session_state["_reset_add_item"] = True
        st.session_state["_reset_add_entry_form"] = False
    # Just the item and its cost, after "+ Add item" puts them in the meal.
    if st.session_state.get("_reset_add_item"):
        st.session_state["add_entry_item"] = None
        st.session_state["_last_autofilled_item"] = None
        st.session_state["add_entry_cost"] = 0
        st.session_state["_reset_add_item"] = False
    # A meal is logged whole: its items gather here until "Log meal" saves
    # them together. Each line keeps the category and store (or stations) it
    # was added with, so one go can log a whole day's spending: {"id",
    # "item", "cost", "category", "store"}.
    basket = st.session_state.setdefault("_meal_basket", [])

    # Not an st.form: Item needs to live-react to selection (to suggest a
    # price below) and st.form batches every widget inside it, only reading
    # values on submit -- there'd be no way to react to "which item was just
    # picked" before submission if it were in one. So the whole section is
    # plain widgets with plain buttons, and behaves the same way throughout.
    #
    # The meal's day, category and store come first, then its items one at a
    # time. The one real ordering constraint is Item before Store/Cost: the
    # suggestion writes to their session_state in between, and both have to
    # be created after that write to pick it up within the same run -- so
    # Store sits beside Day but is drawn after Item, via columns made up front.
    day_column, category_column, store_column = st.columns([2, 2, 3])
    entry_date = day_column.date_input(
        "Day", value=today_date, max_value=today_date, key="add_entry_day"
    )
    # Typed text in these survives clicking/tabbing away without Enter.
    keep_typed_selectbox_text(
        "add_entry_category", "add_entry_item", "add_entry_store", "add_entry_from", "add_entry_to",
        "add_entry_excluded_reason",
    )
    # A category typed that isn't listed yet is added when the receipt's
    # logged. Store and item suggestions only come from this category's
    # past receipts.
    category = category_column.selectbox(
        "Category", options=category_names, accept_new_options=True,
        index=category_names.index(budgeted) if budgeted in category_names else 0,
        key="add_entry_category",
        help="Type a new one to add it. Store and item suggestions follow the category.",
    )
    category = (category or "").strip() or budgeted
    # The chosen category in its own colour (Food's is the accent, like the
    # other boxes' hints) rather than plain white.
    st.markdown(
        f"<style>.st-key-add_entry_category input {{ color: {colors.get(category, ACCENT_COLOR)}; }}</style>",
        unsafe_allow_html=True,
    )
    # Transport takes From/To stations where the store goes, on a row of
    # their own (drawn after Item too, for the same reason as Store).
    is_transport = category == transport
    if is_transport:
        from_column, swap_column, to_column = st.columns([6, 1, 6], vertical_alignment="bottom")
    item_column, cost_column, add_column = st.columns([5, 2, 2], vertical_alignment="bottom")
    choices = item_choices(excluded_items, excluded_stores, category)
    item_choice = item_column.selectbox(
        "Item", options=choices, format_func=item_choice_label, index=None,
        accept_new_options=True,
        # Transport needs no item: left blank, it's logged as a transit fee.
        placeholder=f"{TRANSIT_FEE_ITEM} -- or type or pick another" if is_transport else "Type or pick an item",
        key="add_entry_item",
    )
    # A per-store choice typed out in full ("Onigiri (Lawson)") and entered
    # as new text still means that choice, not a new item with that name.
    if item_choice not in choices:
        item_choice = {item_choice_label(choice): choice for choice in choices}.get(item_choice, item_choice)
    item, choice_store = split_item_choice(item_choice) if item_choice else (None, None)
    if item and st.session_state.get("_last_autofilled_item") != item_choice:
        last_entry = last_entry_for_item(item, choice_store, category)
        if last_entry is not None:
            st.session_state["add_entry_cost"] = int(last_entry["cost_yen"])
            # Just a suggestion -- still an ordinary editable selectbox. Only
            # for this category's first item: after that the store is the
            # meal's. Left blank if the store was left blank last time too.
            last_store = last_entry["store"]
            if not any(line["category"] == category for line in basket):
                # Only the boxes on show: a food store mustn't turn up as a
                # station after switching to Transport.
                if is_transport:
                    st.session_state["add_entry_from"], st.session_state["add_entry_to"] = split_route(last_store)
                else:
                    st.session_state["add_entry_store"] = str(last_store) if pd.notna(last_store) else None
        st.session_state["_last_autofilled_item"] = item_choice

    if is_transport:
        # Both optional. Saved as the receipt's store, "From → To".
        stations = known_stations(category)
        from_station = from_column.selectbox(
            "From", options=stations, index=None, accept_new_options=True,
            placeholder="Optional -- type or pick a station", key="add_entry_from",
        )
        # For the trip back: From and To trade places.
        swap_column.button(
            "⇄", key="add_entry_swap", width="stretch", help="Swap From and To",
            on_click=lambda: st.session_state.update(
                add_entry_from=st.session_state.get("add_entry_to"),
                add_entry_to=st.session_state.get("add_entry_from"),
            ),
        )
        to_station = to_column.selectbox(
            "To", options=stations, index=None, accept_new_options=True,
            placeholder="Optional -- type or pick a station", key="add_entry_to",
        )
        store = route(from_station, to_station)
    else:
        store = store_column.selectbox(
            "Store", options=known_values("store", exclude=excluded_stores, category=category), index=None,
            accept_new_options=True, placeholder="Optional -- type or pick a store",
            # Optional, for a store whose name can't be recalled (or read) at
            # the time -- it can be filled in later from Entries.
            key="add_entry_store",
        )
    cost_yen = cost_column.number_input("Cost (¥)", min_value=0, step=1, key="add_entry_cost")
    if is_transport and not item and cost_yen:
        item = TRANSIT_FEE_ITEM
    # Never greyed out: a click can land before an item just typed has
    # registered, and a greyed-out button would swallow it.
    if add_column.button("+ Add item", width="stretch"):
        if item:
            basket.append({"id": time.time_ns(), "item": item, "cost": int(cost_yen),
                           "category": category, "store": store})
            st.session_state["_reset_add_item"] = True
            st.rerun()
        st.caption("Type or pick an item first.")

    for index, line in enumerate(basket):
        name_column, price_column, remove_column = st.columns([7, 2, 1], vertical_alignment="center")
        # Its category in its colour, then where from, so a mixed day reads
        # at a glance.
        line_color = colors.get(line["category"], ACCENT_COLOR)
        name_column.markdown(
            f"{html.escape(line['item'])} <small><span style='color: {line_color}'>{html.escape(line['category'])}</span>"
            + (f" · {html.escape(line['store'])}" if line["store"] else "") + "</small>",
            unsafe_allow_html=True,
        )
        price_column.write(f"¥{line['cost']:,}")
        remove_column.button("✕", key=f"meal_remove_{line['id']}", help="Take this item out of the meal",
                             on_click=basket.pop, args=(index,))

    # An item picked but not added yet still goes in when the meal's logged:
    # a single item needs no "+ Add item" first.
    pending = [{"item": item, "cost": int(cost_yen), "category": category, "store": store}] if item else []
    items = basket + pending
    subtotal = sum(line["cost"] for line in items)
    line_categories = {line["category"] for line in items} | {category}

    # A bag and the receipt's tax line each go in as a row of their own. The
    # bag box ticks itself whenever the store changes to a konbini (bags are
    # usual there) and can still be unticked.
    # Its price starts at what a bag last cost at this store, and can be
    # changed (one store's chain doesn't always charge the same) -- the
    # price logged is then what's offered there next time.
    if store != st.session_state.get("_bag_ticked_for_store"):
        st.session_state["add_entry_bag"] = is_konbini(store)
        st.session_state["add_entry_bag_yen"] = bag_price(store)
        st.session_state["_bag_ticked_for_store"] = store
    # Tax starts at 0, since most prices (konbini ones especially) already
    # include it. "Use 8%" fills in food's reduced rate on the items so far,
    # rounded down, for a receipt that adds tax on top; it can still be
    # typed over to match the receipt, as stores round differently. Every
    # other category gets the standard 10%.
    def tax_rate(line_category):
        return 0 if line_category == transport else 8 if line_category == budgeted else 10

    rates = sorted({tax_rate(name) for name in line_categories} - {0})
    rate_label = "/".join(f"{rate}%" for rate in rates)
    tax_on_items = sum(line["cost"] * tax_rate(line["category"]) for line in items) // 100
    # Fares and top-ups have neither, so Transport leaves both out.
    tax_yen, with_bag, bag_yen = 0, False, 0
    if not is_transport:
        # Tax at the left with its button, lined up under the items, and the
        # bag box on its own line below.
        tax_column, rate_column, _ = st.columns([3, 2, 4], vertical_alignment="bottom")
        # 8% on food and 10% on the rest when a basket mixes them; fares
        # have none.
        rate_column.button(
            f"Use {rate_label}", width="stretch", help=f"Fill in {rate_label} of the items so far",
            on_click=lambda amount: st.session_state.update(add_entry_tax=amount), args=(tax_on_items,),
        )
        tax_yen = tax_column.number_input(
            "Tax (¥)", min_value=0, step=1, key="add_entry_tax",
            help="Only when prices were before tax: the receipt's tax line. Logged as its own row.",
        )
        bag_column, bag_yen_column, _ = st.columns([3, 2, 4], vertical_alignment="center")
        with_bag = bag_column.checkbox(
            "+ 袋 bag", key="add_entry_bag",
            help="Logs the bag as its own row. Its price starts at what one last cost at this store.",
        )
        if with_bag:
            # Gone from session state while the box was unticked.
            st.session_state.setdefault("add_entry_bag_yen", bag_price(store))
            bag_yen = bag_yen_column.number_input(
                "Bag (¥)", min_value=0, step=1, key="add_entry_bag_yen", label_visibility="collapsed",
            )
    meal_total = subtotal + (bag_yen if with_bag else 0) + tax_yen
    item_word = "item" if len(items) == 1 else "items"
    st.markdown(f"**Total: ¥{meal_total:,}** <small>({len(items)} {item_word}"
                + (f", bag ¥{bag_yen:,}" if with_bag else "") + (f", tax ¥{tax_yen:,}" if tax_yen else "")
                + ")</small>", unsafe_allow_html=True)
    # Any note, e.g. why it isn't counted. Typed ones are offered from then
    # on, and can be changed later in Entries.
    excluded_reason = st.selectbox(
        "Notes", options=known_exclusion_reasons(), index=None,
        accept_new_options=True, placeholder="Optional -- pick or type a note",
        key="add_entry_excluded_reason",
    )
    excluded = st.checkbox(
        "Don't count toward totals",
        help="Still logged, but left out of the day/week/month totals and budget -- "
        "e.g. paid in cash, or covered by a friend/coworker. Can be changed later "
        "from the **Excluded** column in Entries.",
        key="add_entry_excluded",
    )
    if line_categories == {budgeted}:
        log_label = "Log meal"
    elif len(line_categories) == 1:
        log_label = "Log receipt"
    else:
        log_label = "Log all"
    log_clicked = st.button(log_label)
    if log_clicked and not items:
        st.warning("Add an item first.")
    elif log_clicked:
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
        # Every row shares the time and exclusion, and rows from one store
        # share it too: that's what groups them back into one meal under
        # Entries. The bag and tax go with the store the form is on.
        rows = [(line["item"], line["cost"], line["category"], line["store"]) for line in items]
        if with_bag:
            rows.append((BAG_ITEM, bag_yen, category, store))
        if tax_yen:
            rows.append((TAX_ITEM, tax_yen, category, store))
        for row_item, row_yen, row_category, row_store in rows:
            append_entry(
                target_csv, timestamp.strftime("%Y-%m-%d %H:%M:%S"), row_store, row_item, row_yen,
                excluded, excluded_reason, row_category,
            )
        # A newly typed category joins the saved list, so it's offered from
        # now on in the order it was added.
        new_categories = [name for name in dict.fromkeys(row[2] for row in rows) if name not in category_names]
        if new_categories:
            settings["categories"] = category_names + new_categories
            save_settings(settings)
        # No st.form here, so nothing clears itself automatically -- but the
        # actual field reset can't happen right here (Streamlit forbids
        # changing a widget's session_state after that widget's already been
        # instantiated in this run). Both this flag and the confirmation
        # message below are picked up on the very next run, forced
        # immediately with st.rerun(), so the form reads as cleared the
        # moment "Log meal" is clicked. The message is stashed for that run
        # because this one ends at the rerun without painting it.
        st.session_state["_reset_add_entry_form"] = True
        excluded_note = ""
        if excluded:
            excluded_note = " (not counted toward totals)"
        what = items[0]["item"] if len(items) == 1 else f"{len(items)} items"
        logged_categories = list(dict.fromkeys(line["category"] for line in items))
        category_note = "" if logged_categories == [budgeted] else f" ({', '.join(logged_categories)})"
        stores = {line["store"] for line in items}
        logged_store = next(iter(stores)) if len(stores) == 1 else None
        st.session_state["_add_entry_confirmation"] = (
            f"[Logged {what}{category_note}{f' at {logged_store}' if logged_store else ''} "
            f"for ¥{meal_total:,.0f}{excluded_note}]"
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
        else:
            # Each meal as one line with its total, opening to its items; the
            # table under it is where rows are changed.
            for meal in meals(day_entries):
                rows = meal["rows"]
                item_count = int((~rows["item"].isin([BAG_ITEM, TAX_ITEM])).sum())
                no_store = "No stations" if set(rows["category"]) == {transport} else "No store"
                summary = [meal["time"][11:16], html.escape(meal["store"] or no_store), f"¥{meal['total']:,}",
                           f"{item_count} item{'s' if item_count != 1 else ''}"]
                # Food is most of them, so only other categories are named,
                # each in its own colour.
                meal_categories = [name for name in rows["category"].unique() if name != budgeted]
                if meal_categories:
                    summary.insert(1, " / ".join(
                        f"<span style='color: {colors.get(name, ACCENT_COLOR)}'>{html.escape(name)}</span>"
                        for name in meal_categories
                    ))
                if rows["excluded"].all():
                    summary.append("not counted")
                lines = "".join(
                    f"<div>{html.escape(str(row.item) if pd.notna(row.item) else '')}"
                    f" · ¥{int(row.cost_yen) if pd.notna(row.cost_yen) else 0:,}"
                    + (" <small>(not counted)</small>" if row.excluded and not rows["excluded"].all() else "")
                    + (f" <small>· {html.escape(row.excluded_reason)}</small>" if pd.notna(row.excluded_reason) else "")
                    + "</div>"
                    for row in rows.itertuples()
                )
                st.markdown(f"<details><summary>{' · '.join(summary)}</summary>"
                            f"<div style='margin: 0.3rem 0 0.5rem 1.2rem'>{lines}</div></details>",
                            unsafe_allow_html=True)
            st.caption("Change, add or delete rows here. Changes save straight away.")
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
                    # Free text: a dropdown here can't take anything not
                    # already listed.
                    "excluded_reason": st.column_config.TextColumn("Notes"),
                    # Text even on a day with no store given yet.
                    "store": st.column_config.TextColumn("store"),
                    # Same: a new category is typed on the add form first.
                    "category": st.column_config.SelectboxColumn(
                        "Category", options=category_names, default=budgeted,
                    ),
                },
            )
            # Drops fully-blank rows left over from clicking the editor's "+"
            # add-row button without filling anything in, so they don't get
            # saved as-is. The Excluded checkbox and Category are left out of
            # that check, since their defaults mean they're never blank on a
            # new row.
            edited_entries = edited_entries.dropna(
                how="all",
                subset=[c for c in edited_entries.columns if c not in ("excluded", "excluded_reason", "category")],
            )
            # Saved as soon as anything in the table changes (the user asked
            # for edits to save by default, not wait on a button) -- except
            # while a row is missing its time, item or cost, e.g. one
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
            incomplete = edited_entries[["item", "cost_yen"]].isna().any(axis=1) | parsed_times.isna()
            if has_changes and incomplete.any():
                st.caption(
                    "A row is missing its time (e.g. 2026-09-24 13:00), item or cost "
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


        # Showing "¥0 of budget" for a past day with no logged entries at all
        # reads as if you tracked and spent nothing, rather than didn't log
        # that day -- so the budgets only appear for today (where ¥0 so far
        # is meaningful) or a day that actually has entries.
        if is_today or not day_entries.empty:
            # One coloured line per budget, each over its own period around
            # this day, then the day's whole spending split by category.
            status = budget_status(settings, selected_date, today_date)
            if status:
                render_budget_bars(status, colors, is_today)
            day_categories = totals_by_category(edited_entries) if not day_entries.empty else {}
            day_name = "Today" if is_today else selected_date.strftime("%d-%m-%Y")
            line = f"**{day_name}: ¥{sum(day_categories.values()):,}**"
            if len(day_categories) > 1:
                line += " (" + " · ".join(f"{html.escape(name)} ¥{yen:,}" for name, yen in day_categories.items()) + ")"
            st.markdown(line)
    with st.expander("This month", expanded=True):
        summary = month_summary(today_folder)
        if summary.empty:
            st.write("No entries logged yet this month.")
        else:
            # Compared with last month only up to the same day, so it's a fair
            # comparison mid-month. Spending less is the good direction, hence
            # "inverse" (a drop shows green).
            comparison = month_comparison(today_date)
            month_delta = None
            if comparison["has_last_month"]:
                difference = comparison["this_month_so_far"] - comparison["last_month_same_point"]
                month_delta = f"{signed_yen(difference)} vs this point last month"
            st.metric(
                "This month's total", f"¥{summary['total_yen'].sum():,.0f}",
                delta=month_delta, delta_color="inverse",
            )
            st.caption(
                f"About ¥{comparison['this_month_so_far'] / comparison['days_so_far']:,.0f} a day "
                f"over the {comparison['days_so_far']} days so far"
            )
            excluded_by_reason = month_excluded_by_reason(today_folder)
            if not excluded_by_reason.empty:
                breakdown = " · ".join(f"{reason} ¥{yen:,.0f}" for reason, yen in excluded_by_reason.items())
                st.caption(f"Not counted: ¥{excluded_by_reason.sum():,.0f} ({breakdown})")
            # Each day's bar split by category, Food first, the rest largest
            # first, each in the same colour as its budget line.
            month_categories = summary.drop(columns=["day", "total_yen"]).sum().sort_values(ascending=False)
            month_categories = month_categories[month_categories > 0]
            order = sorted(month_categories.index, key=lambda name: name != budgeted)
            if len(order) > 1:
                shares = " · ".join(f"{name} ¥{month_categories[name]:,.0f}" for name in order)
                st.caption(f"By category: {shares}")
                st.bar_chart(summary.set_index("day")[order], color=[colors.get(name, ACCENT_COLOR) for name in order],
                             y_label="")
            else:
                st.bar_chart(summary.set_index("day")["total_yen"], color=ACCENT_COLOR)

    # Secondary, so collapsed (the page's convention): the last six months
    # side by side. Only months from the first one with receipts are shown.
    with st.expander("Month by month"):
        # Food's budget for now; each category's comes with the month view
        # by category (step 3 of #25).
        food_budget = budget_for(settings, budgeted)
        budget_amount, budget_period = food_budget["amount"], food_budget["period"]
        history = monthly_history(today_date, budget_amount, budget_period, budget_category=budgeted)
        if len(history) < 2:
            st.write("Month-by-month comparisons appear once there's more than one month of receipts.")
        else:
            # Labels without "(so far)" -- the chart's slanted labels cut it off.
            chart = history.assign(month=history["month"].str.replace(" (so far)", "", regex=False))
            st.bar_chart(chart.set_index("month")["total_yen"], x_label="", y_label="Total (¥)", color=ACCENT_COLOR)
            table = pd.DataFrame({
                "Month": history["month"],
                "Total": history["total_yen"].map("¥{:,.0f}".format),
                "Per day": history["per_day_yen"].map("¥{:,.0f}".format),
            })
            if budget_amount > 0:
                # The allowance is for the budgeted category, so that's what
                # it's set against -- shown as its own column once anything
                # else has been spent.
                if (history["budgeted_yen"] != history["total_yen"]).any():
                    table[budgeted] = history["budgeted_yen"].map("¥{:,.0f}".format)
                table["Allowance"] = history["allowance_yen"].map("¥{:,.0f}".format)
                table["Difference"] = (history["budgeted_yen"] - history["allowance_yen"]).map(signed_yen)
            st.dataframe(table, hide_index=True, width="stretch")
            if budget_amount > 0:
                st.caption(
                    f"Allowance is your {budgeted.lower()} budget spread over each month's days"
                    + {"weekly": " (a weekly allowance counts as a seventh per day).",
                       "monthly": " (a monthly one is spread evenly over the month)."}.get(budget_period, ".")
                    + " Under budget shows as a minus."
                )

# Streamlit reruns this whole script on every widget interaction (picking an
# item, typing a store, nudging the cost), and typewriter() blocks for
# speed_ms per character -- animating this line on every one of those runs
# turned every field edit into a multi-second stall. The top of the script
# already handled every run except this one by painting the line directly
# in place; this is only reached on the first load of a session.
if is_first_load:
    typewriter(logging_text, markdown_wrap=":primary[{}]", placeholder=logging_placeholder)
    st.session_state["_typewriter_intro_played"] = True
