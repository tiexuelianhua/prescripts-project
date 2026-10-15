# The Budget page's per-category bars, used by both the Budget page and its
# Overview tile (same idea as spotify_widgets.py): one coloured line per
# budget, full at the start of the period and emptying as money is spent
# (an emptying bar reads as loss, which nudges toward saving; #53).
import html

import streamlit as st

from prescripts.common import ACCENT_COLOR_LIGHT, OTHER_ACCENT_COLOR, OTHER_ACCENT_COLOR_LIGHT
from prescripts.data.meal_receipts import ALL_SPENDING

# Colours for categories besides the food one (which takes the other look's
# accent colour): soft enough to sit beside it in both light and dark mode. Shared
# with the This month chart, so a category is the same colour everywhere.
CATEGORY_COLORS = ["#e0a37a", "#7fbf9b", "#c99ad1", "#c4b86a", "#7fb3c9"]

# How far over a budget is. Readable on both the light and dark backgrounds.
OVER_COLOR = "#d9534f"

_PERIOD_WORDS = {
    True: {"daily": "today", "weekly": "this week", "monthly": "this month", "none": "today"},
    False: {"daily": "that day", "weekly": "that week", "monthly": "that month", "none": "that day"},
}


def category_colors(names: list[str], food: str, accent: str) -> dict[str, str]:
    # All spending the accent, Food the other look's accent (the private
    # look's blue in the public one, and the other way round); the rest in
    # turn, by their place in the list, so a category keeps its colour from
    # day to day.
    others = [name for name in names if name != food]
    colors = {name: CATEGORY_COLORS[index % len(CATEGORY_COLORS)] for index, name in enumerate(others)}
    colors[food] = OTHER_ACCENT_COLOR_LIGHT if accent == ACCENT_COLOR_LIGHT else OTHER_ACCENT_COLOR
    colors[ALL_SPENDING] = accent
    return colors


def render_budget_bars(
    status: list[dict], colors: dict[str, str], is_today: bool = True, compact: bool = False,
) -> None:
    # One line per budget: name and period, what's left of the budget, a bar
    # of what's left, and what's been spent. Over budget, the bar is empty and
    # the amount over shows in red. Compact (the Overview tile, half as wide)
    # moves the amounts under the bar, so nothing wraps.
    lines = []
    for budget in status:
        spent, allowed = budget["spent"], budget["budget"]
        left = allowed - spent
        share = max(left, 0) / allowed if allowed > 0 else 0.0
        if left >= 0:
            amounts, note = f"¥{left:,} left of ¥{allowed:,}", f"¥{spent:,} spent"
        else:
            amounts = f"<span style='color: {OVER_COLOR}'>¥{-left:,} over</span>"
            note = f"¥{spent:,} spent of ¥{allowed:,}"
        if compact:
            note = f"{amounts} · {note}"
        if budget["carried"]:
            note += f" · {'+' if budget['carried'] > 0 else '-'}¥{abs(budget['carried']):,} carried over"
        color = colors.get(budget["category"], CATEGORY_COLORS[0])
        amounts = "" if compact else f"<span>{amounts}</span>"
        lines.append(
            "<div class='budget-line'>"
            f"<div class='budget-line-head'><span>{html.escape(budget['category'])} · "
            f"{_PERIOD_WORDS[is_today][budget['period']]}</span>{amounts}</div>"
            f"<div class='budget-line-track'><div style='width: {share * 100:.1f}%; background: {color}'></div></div>"
            f"<div class='budget-line-note'>{note}</div></div>"
        )
    st.markdown(
        "<style>"
        ".budget-line { margin-bottom: 0.7rem; }"
        ".budget-line-head { display: flex; justify-content: space-between; gap: 1rem; white-space: nowrap; }"
        ".budget-line-track { height: 0.5rem; border-radius: 0.25rem; margin: 0.3rem 0 0.2rem;"
        " background: rgba(128, 128, 128, 0.25); overflow: hidden; }"
        ".budget-line-track > div { height: 100%; border-radius: 0.25rem; }"
        ".budget-line-note { font-size: 0.85rem; color: color-mix(in srgb, currentColor 70%, transparent); }"
        "</style>" + "".join(lines),
        unsafe_allow_html=True,
    )
